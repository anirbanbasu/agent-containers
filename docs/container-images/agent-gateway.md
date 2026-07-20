---
icon: lucide/earth-lock
---

# The `agent-gateway` container image

`agent-gateway` is a small, disposable sibling container that owns egress
enforcement on behalf of a workload container such as
[`claude-code`](claude-code.md). Instead of a workload filtering its own
outbound traffic, it tunnels **all** of it — over SSH, using
[`sshuttle`](https://github.com/sshuttle/sshuttle) — to `agent-gateway`,
which is the only party with a real route to the internet and the only
party holding the allowlist rules. A compromise of the workload container
gives an attacker no path to the rules governing its own network access,
because those rules live in a different container entirely.

`agent-gateway` reuses the exact `iptables`/`ipset`/`dnsmasq` allowlist
mechanism `claude-code` uses for its own (optional) in-container allowlist —
same `CLAUDE_ALLOWED_EGRESS`/`egress-allowlist.txt` inputs, same deny-all
default — just applied to itself instead.

Use `agent-gateway` when you want a stronger isolation guarantee than the
in-container allowlist alone provides, whether as:

- a **sibling container** on the same Docker host as the workload
  (isolates a compromised workload from its own firewall rules, but not
  from a compromise of the shared host); or
- a **genuinely separate machine** — a small cloud VM, a home server,
  another site's Docker host (isolates the workload's egress policy even
  from a full compromise of the machine running it).

Same image, same enforcement mechanism, in both cases — only reachability
differs.

## Build

The image's build context needs `agent-images/shared` supplied as a named
[Buildx build context](https://docs.docker.com/build/building/context/#additional-build-contexts),
since `Dockerfile` pulls the shared egress-allowlist script from it:

```sh
docker build --build-context shared=agent-images/shared \
  -t agent-gateway agent-images/agent-gateway
```

## How to use

### 1. Generate a keypair for the tunnel account

The gateway authenticates the workload by SSH public key only — there is no
password login. Generate a keypair once per gateway deployment:

```sh
ssh-keygen -t ed25519 -f gateway-key -N "" -C "agent-gateway"
```

This produces `gateway-key` (private, mounted into the workload container)
and `gateway-key.pub` (public, mounted into the gateway container).

### 2. Run the gateway

=== "Same-host sibling"

    Reachable purely by Docker's own service-name DNS on an ordinary
    (non-`internal`) bridge network — no published port needed:

    ```sh
    docker network create claude-net
    docker run -d --name agent-gateway --network claude-net \
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW \
      --cap-add=SETUID --cap-add=SETGID --cap-add=SYS_CHROOT \
      -e CLAUDE_ALLOWED_EGRESS=github.com,pypi.org \
      -v ./gateway-key.pub:/etc/claude/gateway-key.pub:ro \
      -v agent-gateway-hostkey:/etc/ssh/keys \
      agent-gateway
    ```

=== "Remote host"

    Reachable over a published port — stands in for a genuinely remote
    deployment (swap the port mapping for real infrastructure at actual
    deploy time; add `--restart unless-stopped` for a persistent host):

    ```sh
    docker run -d --name agent-gateway --restart unless-stopped \
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW \
      --cap-add=SETUID --cap-add=SETGID --cap-add=SYS_CHROOT \
      -p 2222:2222 \
      -e CLAUDE_ALLOWED_EGRESS=github.com,pypi.org \
      -v ./gateway-key.pub:/etc/claude/gateway-key.pub:ro \
      -v agent-gateway-hostkey:/etc/ssh/keys \
      agent-gateway
    ```

`CLAUDE_ALLOWED_EGRESS` (or a mounted `/etc/claude/egress-allowlist.txt`,
which takes precedence if both are supplied) is the allowlist that actually
matters once a workload is tunnelling through this gateway — set it to the
real policy this gateway exists to enforce. Omitting both defaults to
deny-all. Set to `*` for unrestricted egress.

The `agent-gateway-hostkey` volume persists the gateway's SSH host key
across restarts at `/etc/ssh/keys` — regenerating it on every start would
break `StrictHostKeyChecking` on the workload side, since the pinned
`gateway-known-hosts` file (below) would no longer match.

### 3. Pin the gateway's host key

Before pointing a workload at the gateway, capture its host key so the
workload can verify it non-interactively (no interactive
trust-on-first-use prompt is possible from a container entrypoint):

```sh
# same-host sibling: scan by the container's Docker network alias, not by
# querying the host — the workload will connect using this same name
# (CLAUDE_GATEWAY_HOST=agent-gateway), so the pinned key must be keyed to it:
docker run --rm --network claude-net alpine:3 sh -c \
  "apk add --no-cache openssh-client >/dev/null && ssh-keyscan -p 2222 agent-gateway" \
  > gateway-known-hosts

# remote host, published port:
ssh-keyscan -p 2222 <gateway-public-ip-or-hostname> > gateway-known-hosts
```

!!! note "Scan from a container on the same network, not from the Docker host"
    On Docker Desktop (macOS/Windows), the host cannot route directly to a
    container's bridge-network IP — only to published ports — so
    `ssh-keyscan` has to run from another container on `claude-net`, as
    shown above. On native Linux this would also work by running
    `ssh-keyscan` directly against the bridge IP from the host, but scanning
    by the same hostname the workload will use is what actually matters:
    `known_hosts` entries are keyed by the exact host string used to
    connect, so scanning by IP when the workload connects by name (or vice
    versa) produces a pinned key that won't match.

### 4. Point a workload at the gateway

See [`claude-code`'s gateway-client mode](claude-code.md#gateway-client-mode)
for the full workload-side configuration
(`CLAUDE_GATEWAY_HOST`/`CLAUDE_GATEWAY_BOOTSTRAP_ALLOW`, the `gateway-key`
and `gateway-known-hosts` mounts) and worked examples for both topologies
above.

## Capabilities required

| Flag | Purpose |
|---|---|
| `--cap-drop=ALL` | Strips Docker's full default capability set. |
| `--cap-add=NET_ADMIN` `--cap-add=NET_RAW` | For the gateway's own `iptables`/`ipset`/`dnsmasq` allowlist setup — the same grant `claude-code`'s in-container allowlist needs, applied here to the gateway's own `OUTPUT` chain instead. |
| `--cap-add=SETUID` `--cap-add=SETGID` | Needed for `gosu` to install `authorized_keys` as the `tunnel` user (see below), and separately for `dnsmasq` itself to drop from root to its own service user — not for a `claude`-style entrypoint privilege drop, since this image has none. |
| `--cap-add=SYS_CHROOT` | `sshd`'s privilege-separation model `chroot`s its pre-authentication child into `/run/sshd`; without this capability every connection is reset before authentication even starts. |

`sshd` itself still runs as root throughout — for its own internal
privilege-separation/setuid-per-session machinery, which is standard for
`sshd` containers and not a regression — `PermitRootLogin no` is what keeps
the *login* surface non-root regardless.

!!! info "Why `authorized_keys` needs `gosu`, not a plain root copy"
    The entrypoint installs the mounted `gateway-key.pub` into
    `/home/tunnel/.ssh/authorized_keys` via `gosu tunnel install ...`, not a
    plain root copy. `sshd` re-reads that file as the `tunnel` user during
    authentication (not as root), so it has to be genuinely owned by
    `tunnel` — and root, stripped of `CAP_CHOWN`/`CAP_DAC_OVERRIDE` under
    `--cap-drop=ALL`, can't `chown` a file to another user or write into a
    directory it doesn't own. Switching to `tunnel` via `gosu` (which only
    needs `CAP_SETUID`/`CAP_SETGID`, already granted above) sidesteps both
    restrictions — the file is created by `tunnel`, into `tunnel`'s own
    directory, no ownership change required.

## Trust model

| Boundary | Mechanism |
|---|---|
| Workload → internet | No route except via the gateway, once the tunnel is up |
| Workload → gateway's firewall rules | No access — different container, no shared filesystem/namespace |
| Gateway → internet | Its own `iptables`/`ipset`/`dnsmasq` allowlist, deny-all by default |
| Gateway SSH account | Key-only, non-root login (`PermitRootLogin no`), single unprivileged `tunnel` user, `AllowTcpForwarding yes` and nothing else |
| Tunnel setup itself | `StrictHostKeyChecking=yes` against the pinned `gateway-known-hosts`, so the first connection can't be MITM'd |
| `tunnel` account if abused | Contained by this being a disposable, single-purpose container: no other secrets, no other volume mounts, no Docker socket, trivially rebuilt from the image |
| Enforcement surviving workload-host compromise | Only if the gateway runs on a separate machine — a same-host sibling container does not survive compromise of the shared Docker host/daemon |

!!! note "The `tunnel` account is a real shell account"
    `sshuttle` execs a small Python relay stub over the SSH session, so it
    needs a genuine remote shell — a `ForceCommand`-restricted, shell-less
    account (the usual way to harden an SSH tunnel account) is not
    compatible with it. The mitigation here is containment of the account,
    not restriction of it: `agent-gateway` holds nothing else worth
    reaching.

## Reachability

### Direct TCP

The default, shown in [Run the gateway](#2-run-the-gateway) above — a
Docker bridge address for a same-host sibling, or a published port/public
address for a remote host.

### Cloudflare Tunnel

An alternative for reaching the gateway with **no inbound port open at
all**: `cloudflared` runs as a sidecar inside `agent-gateway`, making an
outbound-only connection to Cloudflare's edge, and a Cloudflare Access "SSH"
application routes connections to the gateway's private origin
(`localhost:2222`) over that tunnel.

`cloudflared` is always present in both images but never invoked unless
these variables are set — the direct-TCP path above is completely
unaffected if you don't use this option.

!!! warning "One-time external setup required (not part of this repo)"
    This needs a Cloudflare account with a tunnel and an Access application
    already configured, done once via the Cloudflare dashboard or the
    `cloudflared` CLI:

    1. `cloudflared tunnel login`
    2. `cloudflared tunnel create agent-gateway` — note the generated tunnel token.
    3. In Zero Trust → Access → Tunnels, add a public hostname (e.g.
       `gateway.example.com`) with service type `SSH` pointing at
       `localhost:2222`.
    4. In Zero Trust → Access → Applications, create an application for that
       hostname with a policy permitting whatever identity will run
       `claude-code` (e.g. a service token for non-interactive use).
    5. Record the tunnel token (for the gateway) and the Access hostname
       (for the workload).

Run the gateway with the tunnel token instead of (or alongside) a published
port:

```sh
docker run -d --name agent-gateway \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW \
  --cap-add=SETUID --cap-add=SETGID --cap-add=SYS_CHROOT \
  -e CLAUDE_ALLOWED_EGRESS=github.com,pypi.org \
  -e CLOUDFLARE_TUNNEL_TOKEN=<token-from-setup-above> \
  -v ./gateway-key.pub:/etc/claude/gateway-key.pub:ro \
  -v agent-gateway-hostkey:/etc/ssh/keys \
  agent-gateway
```

Then, on the [`claude-code`](claude-code.md#gateway-client-mode) side, set
`CLAUDE_GATEWAY_ACCESS_HOSTNAME` to the Access hostname instead of relying
on `CLAUDE_GATEWAY_HOST` being directly reachable — see that page's
gateway-client mode section for the full workload-side example.

**Trade-offs:** no inbound port anywhere, and traffic to the edge is
genuine HTTPS/WebSocket rather than raw SSH-on-a-port, so it blends in with
ordinary web traffic and works even where the workload's own network only
permits HTTPS egress. In exchange, it adds a Cloudflare account/tunnel/Access
application as external infrastructure, and `cloudflared`'s own binary and
update cadence become part of the trust chain in both images. Prefer direct
TCP for simplicity when both sides can already open or reach a port; reach
for this specifically when the goal is "no inbound port at all" or "must
look like ordinary HTTPS."

### Bring your own tunnel or VPN

`sshuttle` and Cloudflare Tunnel are this project's *reference*
implementations of "get the workload's traffic to the gateway," not the
only correct way to satisfy the underlying contract — which is just: *the
workload has no route out except through a process it does not itself
control the firewall rules of.* An operator with an existing trusted network
boundary (a corporate VPN, a WireGuard mesh, a Cisco AnyConnect/OpenConnect
endpoint) can substitute that client for `sshuttle` inside `claude-code` and
point it at their own infrastructure instead of `agent-gateway`. Nothing
about filesystem or process containment changes; only the "how does egress
leave this container" mechanism does.
