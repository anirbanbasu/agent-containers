---
icon: lucide/code-xml
---

# The `qwen-code` container

`qwen-code` packages [Qwen Code](https://github.com/QwenLM/qwen-code), the
open-source terminal coding agent, in the repository's standard hardened
workload environment: non-root execution, a read-only root filesystem,
minimal Linux capabilities, and deny-by-default outbound networking.

It uses `python:3.14-slim-trixie` plus Node LTS. Qwen Code is installed from
the official `@qwen-code/qwen-code` npm package. Python, `uv`, and `uvx` are
included so Qwen Code can run Python-based MCP servers and project tooling
without a custom derivative image.

## Build

```sh
docker build --build-context shared=agent-images/shared \
  -t qwen-code agent-images/qwen-code
```

### Matching your host user's UID/GID

The image defaults to UID/GID `1000:1000`. Everything the agent writes to
the bind-mounted project directory or the persistent home volume is owned
by whatever UID/GID the container ran as — if that doesn't match your host
account, those files aren't owned by you on the host (permission errors,
needing `sudo` to clean up). Rebuild with matching values instead:

```sh
docker build --build-context shared=agent-images/shared \
  --build-arg UID=$(id -u) --build-arg GID=$(id -g) \
  -t qwen-code:$(whoami) agent-images/qwen-code
```

`Dockerfile` splits into a `base` stage that installs everything —
apt/Node.js/`uv` baseline, `packages-apt.txt`/`packages-uv.txt`, Qwen Code
itself, and the account-scoped `packages-npm.txt`/`tools-uv.txt` — under a
fixed placeholder account (UID/GID `1000:1000`), and a `final` stage that
only remaps that account to the `UID`/`GID` build args (`usermod`/`groupmod`
plus a `chown -R` of what `base` already installed) when they differ from
the placeholder. Nothing in `final` reinstalls packages, so rebuilding for a
different UID after the first build is fast.

On a host shared by multiple accounts, tag the image per user
(`qwen-code:alice`, `qwen-code:bob`) rather than overwriting a shared
`qwen-code` tag — and use that same tag, plus a per-user home volume
(`qwen-home-alice` rather than the shared `qwen-home`), in the run command
below. The [shell-shortcut
functions](../customisation/shell-shortcuts.md) do both
substitutions automatically from a single `CONTAINED_QWEN_TAG` variable; if
invoking `docker run` directly instead, substitute your tag into both the
`qwen-home` volume name and the trailing `qwen-code` image reference in the
command below — copying it unchanged still runs the shared
`qwen-code:latest`.

## Run

This example configures Qwen Code against DashScope's public
OpenAI-compatible endpoint. Supply the API key at runtime; do not put it in
the image, build arguments, or a checked-in file.

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e OPENAI_API_KEY \
  -e OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  -e OPENAI_MODEL=qwen3-coder-plus \
  -e 'AGENT_ALLOWED_EGRESS=dashscope.aliyuncs.com' \
  -v qwen-home:/home/qwen \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  qwen-code
```

### Hardening flags

| Flag | Purpose |
|---|---|
| `--security-opt=no-new-privileges` | Prevents escalation through setuid binaries. |
| `--read-only` | Keeps the root filesystem immutable. |
| `--tmpfs /tmp` and `--tmpfs /run` | Provide ephemeral writable locations for the egress-control tooling and runtime files. |
| `--cap-drop=ALL` | Removes Docker's default capabilities. |
| `NET_ADMIN` and `NET_RAW` | Required for the default-deny `iptables`/`ip6tables` rules and domain allowlists. |
| `SETUID` and `SETGID` | Let `gosu` switch from the setup user to the unprivileged `qwen` user. |

The `qwen-home` volume persists Qwen Code's configuration, authentication
state, MCP definitions, and user-installed npm/Python tools under
`~/.qwen`. As with the other workload images, mounting each project below
`/workspace/<project-name>` keeps its working path distinct while the home
volume is shared across runs.

## Custom configuration

Qwen Code's global settings are below `/home/qwen/.qwen`, but their
single-file bind-mount and mutation behavior has not yet been verified for
this image. Prefer runtime provider environment variables for temporary
routing until that behavior is tested. See [custom configuration
files](../customisation/custom-configuration.md) and the version-recorded
candidate under [local models](../customisation/local-models.md#qwen-code).

## Providers and egress control

The container defaults to deny-all when neither `AGENT_ALLOWED_EGRESS` nor a
mounted `/etc/agent/egress-allowlist.txt` file is provided. The mounted file
takes precedence. The sample
`agent-images/qwen-code/examples/egress-allowlist.txt` lists the mainland and
international DashScope endpoints; use only the endpoint your account uses.
Mount a host-maintained policy file read-only with
`-v "/path/to/egress-allowlist.txt":/etc/agent/egress-allowlist.txt:ro`.

Qwen Code also supports Qwen OAuth, OpenAI-compatible providers, Anthropic,
Gemini, Ollama, and vLLM. Add only the model-provider endpoints that you
configure, along with any intentionally used MCP server, source-control host,
or package registry. A local model service on the Docker host needs an
explicitly reachable address and an allowlist entry; it is not implicitly
reachable from the container. Use `-e 'AGENT_ALLOWED_EGRESS=*'` only when
unrestricted egress is intentional; quoting prevents shells such as zsh from
treating `*` as a filename pattern.

## Nested sandboxing

Qwen Code has an optional Docker/Podman sandbox. This image sets
`QWEN_SANDBOX=false`, which overrides Qwen Code's sandbox setting and command
flag. The outer `qwen-code` container is the sandbox: it owns the project
mount, read-only root filesystem, capability reduction, and egress policy.

Do not mount a Docker or Podman socket into this workload and do not override
`QWEN_SANDBOX`; doing so would weaken the containment model by giving the
agent access to another container runtime.

## Gateway-client mode

Setting `AGENT_GATEWAY_HOST` switches the image from its in-container
allowlist to an SSH tunnel through [`agent-gateway`](00-agent-gateway.md). The
gateway then owns all egress enforcement, so
`AGENT_ALLOWED_EGRESS`/`egress-allowlist.txt` are ignored by the workload.
Use the same gateway key, host-key pinning, bootstrap-rule, and Cloudflare
Access configuration described in
[the Claude Code gateway guide](claude-code.md#gateway-client-mode).

## Optional build-time tools

Edit `packages-apt.txt`, `packages-npm.txt`, `tools-uv.txt`, or
`packages-uv.txt` and rebuild to add general-purpose tools. `tools-uv.txt`
(`uv tool install`) is for standalone Python CLI tools, each in its own
isolated venv; `packages-uv.txt` (`uv pip install --system`) is for plain
importable libraries with no console-script of their own, installed into the
image's system Python instead. No credentials, extensions, skills, or
plugins are seeded in the image; Qwen Code stores user-selected state in the
persisted home volume.
