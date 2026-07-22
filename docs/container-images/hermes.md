---
icon: lucide/send
---

# The `hermes` container

`hermes` packages [Hermes Agent](https://github.com/NousResearch/hermes-agent)
— Nous Research's self-improving, multi-provider agentic CLI — inside a
hardened container, with the same network-containment posture as
[`claude-code`](claude-code.md): read-only root filesystem, a minimal Linux
capability set, and outbound network access denied by default.

Like `claude-code`, two mechanisms control what the container can reach
over the network — an **in-container allowlist** (the default) or
**gateway-client mode**, tunnelling all traffic over SSH to a separate
[`agent-gateway`](agent-gateway.md) container. See
[Egress control](#egress-control) below; the mechanism and env vars are
identical to `claude-code`'s, since both consume the same shared
`AGENT_*`/`/etc/agent/*` contract.

## Build

The image's build context needs `agent-images/shared` supplied as a named
[Buildx build context](https://docs.docker.com/build/building/context/#additional-build-contexts):

```sh
docker build --build-context shared=agent-images/shared \
  -t hermes agent-images/hermes
```

## Run

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run:exec \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID --cap-add=CHOWN --cap-add=DAC_OVERRIDE \
  -v hermes-data:/opt/data \
  hermes
```

### Capabilities

| Flag | Purpose |
|---|---|
| `--cap-add=NET_ADMIN` `--cap-add=NET_RAW` | Same as `claude-code` — the entrypoint always installs a default-deny `iptables`/`ip6tables` policy, and domain-based allowlist matching needs `NET_RAW`. |
| `--cap-add=SETUID` `--cap-add=SETGID` | Upstream's own privilege-drop mechanism (`s6-setuidgid`, its equivalent of `gosu`), not a `claude`-style entrypoint drop — this image has none. |
| `--cap-add=CHOWN` | Upstream's first-boot hook (`stage2-hook.sh`) `chown`s the freshly-created `/opt/data` volume from root to the `hermes` user; needs `CAP_CHOWN` under `--cap-drop=ALL`. Neither `claude-code` nor `agent-gateway` need this. |
| `--cap-add=DAC_OVERRIDE` | Required for `s6-supervise`/`s6-rc` to open lock files for services (`main-hermes`, `dashboard`) that upstream's `02-reconcile-profiles` cont-init step registers dynamically, after the static service trees are already chowned. |

!!! note "`--tmpfs /run:exec`, not `--tmpfs /run`"
    Docker's default `--tmpfs /run` mounts `noexec`. Upstream's s6-overlay
    boot sequence execs a staged binary from `/run/s6/basedir/bin/init`, and
    fails with `Permission denied` (exit 126) without the `exec` mount
    option — so `hermes`, unlike `claude-code`, needs `/run` mounted
    executable.

### A hardening constraint: no UID/GID remap

Upstream supports remapping the `hermes` user to an arbitrary UID/GID at
boot via `HERMES_UID`/`HERMES_GID` (or `PUID`/`PGID`), which requires a
writable rootfs (`usermod`/`groupmod`) — incompatible with `--read-only`.
This image never sets those variables: the container always runs as the
image's baked-in UID 10000, and `--read-only` is kept. Unlike `claude-code`
(where the in-container UID is chosen at build time to match a host user),
`hermes`'s container-side UID is fixed.

### Persistent state

A named volume at `/opt/data` (upstream's `HERMES_HOME`) — analogous to
`claude-home`, but at the path upstream dictates. Config (`config.yaml`,
`auth.json`), skills, memories, session/cron state, and lazy-installed
optional-provider packages all persist there across container recreation.

### Provider / auth configuration

Hermes supports dozens of LLM and messaging-platform providers via env
vars or `hermes setup` (which writes into the persisted `config.yaml`/
`auth.json`):

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run:exec \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID --cap-add=CHOWN --cap-add=DAC_OVERRIDE \
  -v hermes-data:/opt/data \
  -e OPENROUTER_API_KEY=replace-with-your-key \
  hermes
```

See upstream's own `.env.example` and documentation for the full provider
list rather than duplicating it here.

Out of scope for this image: mounting `/var/run/docker.sock` (leave
`terminal.backend` at its `local` default — this container already is the
sandbox), and a `plugins.txt`-equivalent build-time skill seeding mechanism
(Hermes has its own skills/MCP ecosystem, unrelated to Claude Code's plugin
marketplaces).

## Egress control

### In-container allowlist

The default mode, identical in mechanism to
[`claude-code`'s](claude-code.md#in-container-allowlist):
`AGENT_ALLOWED_EGRESS` (or a mounted `/etc/agent/egress-allowlist.txt`,
which takes precedence) against the container's own `OUTPUT` chain,
defaulting to deny-all if neither is set.

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run:exec \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID --cap-add=CHOWN --cap-add=DAC_OVERRIDE \
  -v hermes-data:/opt/data \
  -e AGENT_ALLOWED_EGRESS=openrouter.ai,your-provider.example.com \
  hermes
```

Set `AGENT_ALLOWED_EGRESS=*` for unrestricted egress.

### Gateway-client mode

Setting `AGENT_GATEWAY_HOST` switches `hermes` from the in-container
allowlist to gateway-client mode — `sshuttle` tunnels all outbound traffic
to an [`agent-gateway`](agent-gateway.md) container, exactly as described in
[`claude-code`'s Gateway-client mode](claude-code.md#gateway-client-mode).
The same `AGENT_GATEWAY_PORT`/`AGENT_GATEWAY_USER`/
`AGENT_GATEWAY_BOOTSTRAP_ALLOW`/`AGENT_GATEWAY_ACCESS_HOSTNAME` variables
and `/etc/agent/gateway-key`/`/etc/agent/gateway-known-hosts` mounts apply
unchanged — see that page for the full configuration table and worked
examples (same-host sibling, genuinely remote gateway, Cloudflare Tunnel).
