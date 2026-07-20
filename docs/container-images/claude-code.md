---
icon: lucide/bot
---

# The `claude-code` container image

`claude-code` packages [Claude Code](https://claude.com/product/claude-code)
— the command-line coding agent — inside a hardened container: non-root
user, read-only root filesystem, a minimal Linux capability set, and
outbound network access denied by default. Use it any time you want Claude
Code to operate with real filesystem and shell access on a project without
extending that access, or Claude's own network reachability, to the rest of
the host.

Two mechanisms are available for controlling what the container can reach
over the network:

- an **in-container allowlist** (the default) — `iptables`/`ipset`/`dnsmasq`
  rules enforced inside `claude-code` itself; see
  [Egress control](#egress-control) below.
- **gateway-client mode** — `claude-code` tunnels all outbound traffic over
  SSH to a separate [`agent-gateway`](agent-gateway.md) container, which
  owns the allowlist instead. This is a stronger isolation guarantee: a
  compromised `claude-code` container has no access to the rules governing
  its own egress, since those rules live in a different container (or on a
  different machine entirely). See
  [Gateway-client mode](#gateway-client-mode) below.

Gateway-client mode is opt-in and additive — it changes nothing about the
default, standalone deployment described first.

## Build

The image's build context needs `agent-images/shared` supplied as a named
[Buildx build context](https://docs.docker.com/build/building/context/#additional-build-contexts),
since `Dockerfile` pulls the shared egress-allowlist script from it:

```sh
docker build --build-context shared=agent-images/shared \
  -t claude-code agent-images/claude-code
```

## Run

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v claude-home:/home/claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  claude-code
```

### Hardening flags

| Flag | Purpose |
|---|---|
| `--security-opt=no-new-privileges` | Blocks privilege escalation via setuid binaries. |
| `--read-only` | Makes the root filesystem immutable. |
| `--tmpfs /tmp` | Writable scratch space for `dnsmasq`'s runtime config/pid files and `iptables`' lock file. `/workspace` and `/home/claude` stay writable regardless — mounts are independent of the root filesystem's read-only flag. |
| `--tmpfs /run` | Writable scratch space for process-runtime files. |
| `--cap-drop=ALL` | Strips Docker's full default capability set. |
| `--cap-add=NET_ADMIN` `--cap-add=NET_RAW` | Required in every configuration (even with no allowlist set) — the entrypoint always installs a default-deny `iptables`/`ip6tables` policy. `NET_RAW` is additionally needed once a domain-based allowlist is in play, since matching rules against the resolved-IP `ipset` needs it. |
| `--cap-add=SETUID` `--cap-add=SETGID` | Needed for `gosu` to drop from root to the unprivileged `claude` user after entrypoint setup. |

### Persistent state

`/home/claude` is mounted from a named volume (`claude-home`) so plugins,
settings, Claude's own project memory, and any Python/Node package state
persist across container runs instead of being lost when the container is
removed. That volume is shared by every invocation of this image, and
Claude Code keys its per-project memory/session data off the working
directory's path — so if every project were mounted at the same
`/workspace` path, unrelated projects would collide inside that shared
volume. Mounting each project under its own `/workspace/<project_name>`
subdirectory (and setting `-w` to match) keeps them distinct.

Volumes created before this mount point widened from `/home/claude/.claude`
to `/home/claude` are migrated automatically on first run — see
`entrypoint.sh`.

!!! warning "Migrating a pre-existing volume"
    If you have such a pre-existing volume, do one plain run (no extra
    `-v`/`-e` overrides) first to let migration complete before combining
    it with the `settings.local-model.json` mount example below — mounting
    that file on the very first run against an unmigrated volume forces its
    parent directory to be created before migration can run, which skips
    migration and leaves the volume's old contents at the top level instead
    of nested under `.claude/`. This does not affect brand-new volumes or
    volumes already migrated under this version.

## Installing Python and Node packages at runtime

Claude can install packages at runtime without the rootfs needing to be
writable:

- **Python, project-scoped** — `uv venv .venv && uv pip install <package>`
  inside `/workspace/<project>` (or `uv add <package>` in a `uv`-managed
  project). Lives in the project's own directory, persists via the project
  bind mount, isolated per project.
- **Python, ad hoc** — `uv venv /tmp/<name>` (or `uv run --with <package>
  ...`). Lives on the `/tmp` tmpfs, isolated per task, wiped when the
  container exits.
- **Node, project-scoped** — `npm install <package>` inside
  `/workspace/<project>`, writing to that project's own `node_modules` —
  works the same way it always has.
- **Node, global** — `npm install -g <package>` installs under
  `/home/claude/.npm-global`, which is on `PATH` and persists via the
  `claude-home` volume.

`uv`'s own package cache and any Python interpreters it downloads to
satisfy a project's `requires-python` also live under `/home/claude` and
persist via the same volume — repeated installs of a previously-seen
package/interpreter version are instant, and different projects/tasks can
depend on conflicting versions of the same package without interfering with
each other, since environments (venvs, `node_modules`) are never shared —
only the cache is.

## Optional configuration

- **`plugins.txt`** — plugins to install at build time, one per line, as
  `<plugin>@<marketplace>`. The official Anthropic marketplace is
  preinstalled as `claude-plugins-official`.
- **`plugin-marketplaces.txt`** — additional plugin marketplaces to add
  before installing plugins from `plugins.txt`; see the comments in the
  file for accepted source formats.
- **`examples/settings.local-model.json`** — sample `settings.json` for
  pointing Claude Code at a custom/local model endpoint
  (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`).
- **`examples/egress-allowlist.txt`** — sample allowlist of hosts/IPs the
  container is allowed to reach outbound; defaults to deny-all if neither
  this file nor `CLAUDE_ALLOWED_EGRESS` is set, or set to `*` for
  unrestricted egress.

Model settings and the egress allowlist can each be supplied either by
mounting a file into the container or by setting environment variables
directly with `-e`.

=== "Mount the file"

    ```sh
    docker run -it --rm \
      --security-opt=no-new-privileges \
      --read-only \
      --tmpfs /tmp \
      --tmpfs /run \
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
      -v claude-home:/home/claude \
      -v "$PWD":"/workspace/$(basename "$PWD")" \
      -w "/workspace/$(basename "$PWD")" \
      -v "$PWD/agent-images/claude-code/examples/settings.local-model.json":/home/claude/.claude/settings.json:ro \
      claude-code
    ```

    Mounted `:ro` since this file is bind-mounted directly over whatever
    `settings.json` already exists in the `claude-home` volume — it shadows
    that file for the run rather than merging with it, and mounting
    read-write would mean any settings Claude Code writes back land on your
    host's checked-in `settings.local-model.json` instead of in the volume.
    If you want local-model settings to coexist with whatever else lives in
    the volume's `settings.json`, prefer the environment-variable form
    instead.

=== "Environment variables"

    ```sh
    docker run -it --rm \
      --security-opt=no-new-privileges \
      --read-only \
      --tmpfs /tmp \
      --tmpfs /run \
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
      -v claude-home:/home/claude \
      -v "$PWD":"/workspace/$(basename "$PWD")" \
      -w "/workspace/$(basename "$PWD")" \
      -e ANTHROPIC_BASE_URL=https://your-local-model.example.com \
      -e ANTHROPIC_AUTH_TOKEN=replace-with-your-token \
      -e ANTHROPIC_MODEL=your-local-model-name \
      claude-code
    ```

To keep the container fully static/offline (no background update checks),
set `DISABLE_AUTOUPDATER=1` as an environment variable or mount a file
containing this setting. Updates require outbound network access to the
marketplace source — relevant given the image's egress allowlist
(`api.anthropic.com` etc. would need to be reachable, or marketplace hosts
allowed too).

## Egress control

### In-container allowlist

The default mode. `entrypoint.sh` enforces `CLAUDE_ALLOWED_EGRESS` (or a
mounted `/etc/claude/egress-allowlist.txt`, which takes precedence if both
are supplied) against the container's own `OUTPUT` chain, defaulting to
deny-all if neither is set.

=== "Mount the file"

    ```sh
    docker run -it --rm \
      --security-opt=no-new-privileges \
      --read-only \
      --tmpfs /tmp \
      --tmpfs /run \
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
      -v claude-home:/home/claude \
      -v "$PWD":"/workspace/$(basename "$PWD")" \
      -w "/workspace/$(basename "$PWD")" \
      -v "$PWD/agent-images/claude-code/examples/egress-allowlist.txt":/etc/claude/egress-allowlist.txt \
      claude-code
    ```

=== "Environment variable"

    ```sh
    docker run -it --rm \
      --security-opt=no-new-privileges \
      --read-only \
      --tmpfs /tmp \
      --tmpfs /run \
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
      -v claude-home:/home/claude \
      -v "$PWD":"/workspace/$(basename "$PWD")" \
      -w "/workspace/$(basename "$PWD")" \
      -e CLAUDE_ALLOWED_EGRESS=api.anthropic.com,your-local-model.example.com \
      claude-code
    ```

Set `CLAUDE_ALLOWED_EGRESS=*` for unrestricted egress.

### Gateway-client mode

Setting `CLAUDE_GATEWAY_HOST` switches `claude-code` from the in-container
allowlist to gateway-client mode: instead of filtering its own traffic,
`claude-code` runs [`sshuttle`](https://github.com/sshuttle/sshuttle) to
tunnel **all** outbound traffic (including DNS) to an
[`agent-gateway`](agent-gateway.md) container, which enforces the allowlist
on the workload's behalf. `CLAUDE_ALLOWED_EGRESS`/`egress-allowlist.txt` are
ignored (with a logged warning) when `CLAUDE_GATEWAY_HOST` is set — the
allowlist that matters in this mode is the one configured on the gateway
itself.

!!! info "Why tunnel instead of filtering locally?"
    A compromised `claude-code` container running the in-container
    allowlist still holds `NET_ADMIN` and the `iptables` rules constraining
    its own egress — a sufficiently capable compromise could rewrite them.
    In gateway-client mode, those rules live in a separate container (or on
    a separate machine), which the workload has no access to.

#### Configuration

| Variable / mount | Purpose |
|---|---|
| `CLAUDE_GATEWAY_HOST` | Gateway's address (Docker network address, public IP/hostname). Enables gateway-client mode when set; unset falls back to the in-container allowlist. |
| `CLAUDE_GATEWAY_PORT` | Gateway's SSH port. Defaults to `2222`. |
| `CLAUDE_GATEWAY_USER` | SSH user on the gateway. Defaults to `tunnel`. |
| `CLAUDE_GATEWAY_BOOTSTRAP_ALLOW` | Comma-separated bare IPs/CIDRs (never a hostname) the entrypoint allows *before* the tunnel comes up — narrowly scoped to the gateway's own address, so egress isn't wide open during the brief window before `sshuttle` takes over. |
| `-v ./gateway-key:/etc/claude/gateway-key:ro` | SSH private key for the tunnel. |
| `-v ./gateway-known-hosts:/etc/claude/gateway-known-hosts:ro` | Pinned gateway host key, so `StrictHostKeyChecking=yes` works non-interactively on the first connection. |

No additional capabilities are required beyond the defaults above —
`sshuttle` uses the same `NET_ADMIN`/`NET_RAW` grant that the in-container
allowlist uses, just to install redirect rules instead of filter rules.

#### Example: same-host sibling gateway

```sh
docker network create claude-net
ssh-keygen -t ed25519 -f gateway-key -N "" -C "agent-gateway"

# Start the gateway first — see agent-gateway.md for the full walkthrough.
docker run -d --name agent-gateway --network claude-net \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW \
  --cap-add=SETUID --cap-add=SETGID --cap-add=SYS_CHROOT \
  -e CLAUDE_ALLOWED_EGRESS=github.com,pypi.org \
  -v ./gateway-key.pub:/etc/claude/gateway-key.pub:ro \
  -v agent-gateway-hostkey:/etc/ssh/keys \
  agent-gateway

# Scan from another container on claude-net, not from the Docker host — see
# agent-gateway.md's "Pin the gateway's host key" note for why.
docker run --rm --network claude-net alpine:3 sh -c \
  "apk add --no-cache openssh-client >/dev/null && ssh-keyscan -p 2222 agent-gateway" \
  > gateway-known-hosts
GW_IP=$(docker inspect agent-gateway --format '{{ (index .NetworkSettings.Networks "claude-net").IPAddress }}')

docker run -it --rm --network claude-net \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  --security-opt=no-new-privileges --read-only --tmpfs /tmp --tmpfs /run \
  -e CLAUDE_GATEWAY_HOST=agent-gateway \
  -e CLAUDE_GATEWAY_BOOTSTRAP_ALLOW="$GW_IP" \
  -v ./gateway-key:/etc/claude/gateway-key:ro \
  -v ./gateway-known-hosts:/etc/claude/gateway-known-hosts:ro \
  -v claude-home:/home/claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  claude-code
```

#### Example: genuinely remote gateway

Isolation that survives a full compromise of the machine running
`claude-code`, not just the container — the gateway runs on separate
infrastructure you control:

```sh
# on the workload host
docker run -it --rm \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  --security-opt=no-new-privileges --read-only --tmpfs /tmp --tmpfs /run \
  -e CLAUDE_GATEWAY_HOST=<gateway-public-ip-or-hostname> \
  -e CLAUDE_GATEWAY_BOOTSTRAP_ALLOW=<gateway-public-ip> \
  -v ./gateway-key:/etc/claude/gateway-key:ro \
  -v ./gateway-known-hosts:/etc/claude/gateway-known-hosts:ro \
  -v claude-home:/home/claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  claude-code
```

See [`agent-gateway`](agent-gateway.md) for how to run the gateway side of
either example, and
`docs/superpowers/specs/2026-07-17-remote-gateway-container-design.md` in
the repository for the full rationale, trade-offs, and reachability
options.
