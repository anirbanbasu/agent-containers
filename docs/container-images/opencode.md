---
icon: lucide/square-code
---

# The `opencode` container

`opencode` packages [OpenCode](https://opencode.ai), the provider-agnostic
terminal coding agent, in the repository's standard hardened workload
environment: non-root execution, a read-only root filesystem, minimal Linux
capabilities, and deny-by-default outbound networking.

It uses `python:3.14-slim-trixie` plus Node LTS. OpenCode is installed from
the official `opencode-ai` npm package. Python, `uv`, and `uvx` are included
so OpenCode can run Python-based MCP servers and project tooling without a
custom derivative image.

## Build

```sh
docker build --build-context shared=agent-images/shared \
  -t opencode agent-images/opencode
```

## Run

`models.dev` is included because OpenCode fetches its provider/model catalog
on startup; `opencode.ai` covers OpenCode's first-party hosted services.

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp:exec --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e 'AGENT_ALLOWED_EGRESS=opencode.ai,models.dev' \
  -v opencode-home:/home/opencode \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  opencode
```

### Hardening flags

| Flag | Purpose |
|---|---|
| `--security-opt=no-new-privileges` | Prevents escalation through setuid binaries. |
| `--read-only` | Keeps the root filesystem immutable. |
| `--tmpfs /tmp:exec` and `--tmpfs /run` | Provide ephemeral writable locations for the egress-control tooling and runtime files. OpenCode's OpenTUI renderer dynamically loads a native library from `/tmp`, so that mount must be executable. |
| `--cap-drop=ALL` | Removes Docker's default capabilities. |
| `NET_ADMIN` and `NET_RAW` | Required for the default-deny `iptables`/`ip6tables` rules and domain allowlists. |
| `SETUID` and `SETGID` | Let `gosu` switch from the setup user to the unprivileged `opencode` user. |

The `opencode-home` volume persists OpenCode's configuration and credentials,
including its XDG locations under `~/.config/opencode` and
`~/.local/share/opencode`, along with user-installed npm/Python tools.

## Providers and egress control

The container defaults to deny-all when neither `AGENT_ALLOWED_EGRESS` nor a
mounted `/etc/agent/egress-allowlist.txt` file is provided. The mounted file
takes precedence. See `agent-images/opencode/examples/egress-allowlist.txt`
for the default OpenCode hosts.
Mount a host-maintained policy file read-only with
`-v "/path/to/egress-allowlist.txt":/etc/agent/egress-allowlist.txt:ro`.

Add each provider endpoint that you configure, for example
`api.anthropic.com`, `api.openai.com`, or `openrouter.ai`; package registries,
MCP servers, and source-control hosts also need explicit entries when used.
Use `-e 'AGENT_ALLOWED_EGRESS=*'` only when unrestricted egress is
intentional; quoting prevents shells such as zsh from treating `*` as a
filename pattern.

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
to add general-purpose tools. No plugins or skills are seeded in v1; all
OpenCode state lives under the persisted home volume.
