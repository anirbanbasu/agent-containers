---
icon: lucide/terminal-square
---

# The `codex` container

`codex` packages the [OpenAI Codex CLI](https://developers.openai.com/) in a
hardened container: it runs as a non-root user on a read-only root filesystem,
has only the capabilities required for egress enforcement, and denies outbound
network access until the user supplies an allowlist.

The image is based on `python:3.14-slim-trixie` and Node LTS. Although Codex
is implemented in Rust, its npm package supplies the native CLI executable, so
the runtime image does not install a Rust toolchain. Python, `uv`, and `uvx`
remain available for Python-based MCP servers and project tooling.

## Nested sandboxing

The image starts Codex with `--sandbox danger-full-access` by default. This
disables Codex's nested process sandbox, which cannot create the namespaces it
needs under the documented container security flags. It does not give Codex
additional access outside the container: the outer container remains the
security boundary and continues to enforce its read-only root filesystem,
explicit writable mounts, unprivileged user, dropped capabilities, and egress
policy.

The image supplies this default through its `codex` wrapper, so it also applies
when a Docker command overrides the image's `CMD`, such as `codex codex login`.
Pass another global `--sandbox` option explicitly to override the default for a
container started with different runtime permissions.

## Build

```sh
docker build --build-context shared=agent-images/shared \
  -t codex agent-images/codex
```

## Run

For API-key authentication, pass the key at runtime rather than baking it into
the image or an image layer. This starts Codex with API-key authentication; it
does not initiate a ChatGPT login:

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e OPENAI_API_KEY \
  -e 'AGENT_ALLOWED_EGRESS=api.openai.com,auth.openai.com,chatgpt.com' \
  -v codex-home:/home/codex \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  codex
```

### Hardening flags

| Flag | Purpose |
|---|---|
| `--security-opt=no-new-privileges` | Prevents escalation through setuid binaries. |
| `--read-only` | Keeps the root filesystem immutable. |
| `--tmpfs /tmp` and `--tmpfs /run` | Provide ephemeral writable locations for the egress-control tooling and runtime files. |
| `--cap-drop=ALL` | Removes Docker's default capabilities. |
| `NET_ADMIN` and `NET_RAW` | Required for the default-deny `iptables`/`ip6tables` rules and domain allowlists. |
| `SETUID` and `SETGID` | Let `gosu` switch from the setup user to the unprivileged `codex` user. |

`codex-home` persists Codex configuration, conversation state, authentication
material, and user-installed npm/Python tools. Mounting each project below
`/workspace/<project-name>` keeps per-project state distinct while retaining a
shared home volume.

## Custom configuration

To use a host-maintained global Codex configuration, add
`-v "$PWD/codex-config.toml":/home/codex/.codex/config.toml:ro` to the run
command. The read-only mount shadows, rather than merges with, the file in the
`codex-home` volume. See [custom configuration files](../customisation/custom-configuration.md#codex)
for configuration precedence, project-scoped alternatives, and egress
requirements.

## Authentication

Choose one authentication mode:

### API key

Use `OPENAI_API_KEY`, as in the example above, or store a key in the
persistent home volume with:

```sh
printf '%s\n' "$OPENAI_API_KEY" | docker run -i --rm \
  --security-opt=no-new-privileges --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e 'AGENT_ALLOWED_EGRESS=api.openai.com,auth.openai.com,chatgpt.com' \
  -v codex-home:/home/codex \
  codex codex login --with-api-key
```

### ChatGPT account

Use the CLI's device-authorization flow. Do not rely on Codex's usual
localhost callback login: the browser runs on the host, while that callback
listener is isolated inside the hardened container and no port is published to
the host.

```sh
docker run -it --rm \
  --security-opt=no-new-privileges --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e 'AGENT_ALLOWED_EGRESS=api.openai.com,auth.openai.com,chatgpt.com' \
  -v codex-home:/home/codex \
  codex codex login --device-auth
```

The CLI displays a URL and user code. Open the URL on the host, complete the
sign-in, and leave the container running while it waits for completion. The
`codex-home` volume retains the resulting credentials. For later runs, omit
`OPENAI_API_KEY` and keep the identity hosts in the allowlist if Codex needs
to refresh the login. If the current CLI reports another identity host, add it
to the allowlist rather than opening unrestricted egress. The first `codex`
above is the image name; the second invokes the CLI because providing a Docker
command replaces the image's default command.

After login completes, start the agent in a new container without the login
arguments:

```sh
docker run -it --rm \
  --security-opt=no-new-privileges --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e 'AGENT_ALLOWED_EGRESS=api.openai.com,auth.openai.com,chatgpt.com' \
  -v codex-home:/home/codex \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  codex
```

## Egress and gateway-client mode

The entrypoint accepts the repository-wide `AGENT_ALLOWED_EGRESS` variable or
a mounted `/etc/agent/egress-allowlist.txt` file; the file takes precedence.
Mount a host-maintained policy file read-only with
`-v "/path/to/egress-allowlist.txt":/etc/agent/egress-allowlist.txt:ro`.
The sample file at `agent-images/codex/examples/egress-allowlist.txt` includes
`api.openai.com`, `auth.openai.com`, and `chatgpt.com`, which are required by
the documented ChatGPT-account flow and the `codex_apps` MCP integration. Add
MCP server, package registry, source-control, and other explicit service hosts
as needed. Unset both inputs to retain deny-all, or use
`-e 'AGENT_ALLOWED_EGRESS=*'` only when unrestricted egress is deliberate.
Quoting prevents shells such as zsh from treating `*` as a filename pattern.

Set `AGENT_GATEWAY_HOST` to tunnel all traffic through
[`agent-gateway`](agent-gateway.md) instead. In gateway-client mode, the
workload's local allowlist is ignored and the gateway owns the policy. The
gateway key, host-key pinning, bootstrap rule, and optional Cloudflare Access
settings use the same contract documented in
[the Claude Code gateway guide](claude-code.md#gateway-client-mode).

## Optional build-time tools

Edit `packages-apt.txt`, `packages-npm.txt`, or `packages-uv.txt` and rebuild
to add general-purpose tools. They are installed separately from the image's
required infrastructure, so edits cannot remove egress enforcement or the
privilege-drop tooling.
