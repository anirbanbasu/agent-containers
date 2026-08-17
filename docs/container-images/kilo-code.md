---
icon: lucide/box
---

# The `kilo-code` container

`kilo-code` packages [Kilo CLI](https://kilo.ai/cli), the open-source,
provider-neutral terminal coding agent, in the repository's standard hardened
workload environment: non-root execution, a read-only root filesystem, minimal
Linux capabilities, and deny-by-default outbound networking.

It uses `python:3.14-slim-trixie` plus Node LTS. Kilo CLI is installed from
the official `@kilocode/cli` npm package. Python, `uv`, and `uvx` are included
so Kilo can run Python-based MCP servers and project tooling without a custom
derivative image.

## Build

```sh
docker build --build-context shared=agent-images/shared \
  -t kilo-code agent-images/kilo-code
```

## Run

This example permits only Kilo's hosted AI Gateway. It does not implicitly
permit any direct model provider, MCP server, package registry, or source host.
Configure a Kilo account or provider from Kilo's `/connect` flow, then add only
the hosts that configuration needs.

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp:exec --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e 'AGENT_ALLOWED_EGRESS=api.kilo.ai' \
  -v kilo-home:/home/kilo \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  kilo-code
```

### Hardening flags

| Flag | Purpose |
|---|---|
| `--security-opt=no-new-privileges` | Prevents escalation through setuid binaries. |
| `--read-only` | Keeps the root filesystem immutable. |
| `--tmpfs /tmp:exec` and `--tmpfs /run` | Provide ephemeral writable locations for the egress-control tooling and runtime files. Kilo's OpenTUI renderer dynamically loads a native library from `/tmp`, so that mount must be executable. |
| `--cap-drop=ALL` | Removes Docker's default capabilities. |
| `NET_ADMIN` and `NET_RAW` | Required for the default-deny `iptables`/`ip6tables` rules and domain allowlists. |
| `SETUID` and `SETGID` | Let `gosu` switch from the setup user to the unprivileged `kilo` user. |

The `kilo-home` volume persists Kilo's configuration under
`~/.config/kilo`, session and credential state, plugin cache, and
user-installed npm/Python tools. Mounting each project below
`/workspace/<project-name>` keeps its working path distinct while the home
volume is shared across runs.

## Custom configuration

To use a host-maintained global Kilo configuration, add
`-v "$PWD/kilo.json":/home/kilo/.config/kilo/kilo.json:ro` to the run
command. The read-only mount shadows, rather than merges with, the file in the
`kilo-home` volume. See [custom configuration files](custom-configuration.md#kilo-code)
for the JSONC variant, project-scoped alternatives, and egress requirements.

## Providers, plugins, and egress control

The container defaults to deny-all when neither `AGENT_ALLOWED_EGRESS` nor a
mounted `/etc/agent/egress-allowlist.txt` file is provided. The mounted file
takes precedence. The sample
`agent-images/kilo-code/examples/egress-allowlist.txt` permits only Kilo's
hosted AI Gateway, `api.kilo.ai`.
Mount a host-maintained policy file read-only with
`-v "/path/to/egress-allowlist.txt":/etc/agent/egress-allowlist.txt:ro`.

Kilo supports its hosted gateway and direct providers. Add only the model
provider endpoint that you configure, along with any intentionally used MCP
server, source-control host, and package registry. Plugins can execute code
and may require package-registry egress; do not install a plugin unless its
source and required access are understood. Use `-e 'AGENT_ALLOWED_EGRESS=*'`
only when unrestricted egress is intentional; quoting prevents shells such as
zsh from treating `*` as a filename pattern.

Kilo has its own optional sandboxing and permission controls. They can provide
defence in depth, but the outer `kilo-code` container is the security boundary:
it owns the project mount, read-only root filesystem, capability reduction, and
egress policy. Do not mount a Docker or Podman socket into this workload.

## Gateway-client mode

Setting `AGENT_GATEWAY_HOST` switches the image from its in-container
allowlist to an SSH tunnel through [`agent-gateway`](agent-gateway.md). The
gateway then owns all egress enforcement, so
`AGENT_ALLOWED_EGRESS`/`egress-allowlist.txt` are ignored by the workload.
Use the same gateway key, host-key pinning, bootstrap-rule, and Cloudflare
Access configuration described in
[the Claude Code gateway guide](claude-code.md#gateway-client-mode).

## Optional build-time tools

Edit `packages-apt.txt`, `packages-npm.txt`, or `packages-uv.txt` and rebuild
to add general-purpose tools. No credentials, plugins, skills, or provider
configuration are seeded in the image; Kilo stores user-selected state in the
persisted home volume.
