---
icon: lucide/handshake
---

# The `aider` container

`aider` packages [Aider](https://aider.chat/) — the git-native terminal
pair-programming agent — in a hardened container. It runs as an unprivileged
user with a read-only root filesystem, a minimal capability set, and
deny-by-default outbound networking. This is particularly useful for Aider:
it can edit a project, run shell commands and configured tests, fetch URLs,
and send the selected code context to a model provider.

The image uses Python 3.12 because the packaged Aider release supports Python
3.10--3.12. It pins `aider-chat==0.86.2`; rebuilding does not silently change
the agent or its model-provider dependency graph. The normal terminal CLI is
included, but the optional browser UI and Playwright/Chromium web scraper are
not.

## Build

The image's build context needs `agent-images/shared` supplied as a named
[Buildx build context](https://docs.docker.com/build/building/context/#additional-build-contexts),
because the `Dockerfile` uses the shared egress and entrypoint scripts:

```sh
docker build --build-context shared=agent-images/shared \
  -t aider agent-images/aider
```

## Run

Choose one model provider and allow only its API hostname. For example, this
invocation forwards an Anthropic key from the host environment without placing
it in the image, build arguments, project, or command history:

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e ANTHROPIC_API_KEY \
  -e 'AGENT_ALLOWED_EGRESS=api.anthropic.com' \
  -v aider-home:/home/aider \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  aider
```

For OpenAI, forward `OPENAI_API_KEY` and allow `api.openai.com` instead.
Aider supports many other providers and custom API bases. Add only the
hostname(s) required by the provider and the project's package or
source-control tooling; the image does not carry a broad provider allowlist.

| Flag | Why it is present |
|---|---|
| `--read-only` | Stops Aider, project commands, and dependencies changing the image filesystem. |
| `--tmpfs /tmp` and `--tmpfs /run` | Provide ephemeral writable locations for the egress-control tooling and runtime files. |
| `--cap-drop=ALL` | Removes Docker's default capabilities. |
| `NET_ADMIN` and `NET_RAW` | Required for the in-container default-deny egress rules. |
| `SETUID` and `SETGID` | Let `gosu` hand off from firewall setup to the unprivileged `aider` user. |

The `aider-home` volume keeps Aider's home-level configuration, optional
provider credentials, caches, and user-installed npm/Python tools outside the
image. It is shared mutable state; use a separate volume for a different trust
boundary. The mounted project is also writable, so review Aider's edits and
anything it leaves for the host to execute later.

## Credentials and configuration

Pass an API key as a runtime environment variable as above, or retain
user-managed credentials in `aider-home`. Do **not** put credentials in a
repository `.env` or `.aider.conf.yml`: Aider searches for `.env` files in its
home, the git root, and the current directory, so a project-controlled file can
both expose a secret and redirect how an invocation behaves.

Aider's home-level configuration can live at `/home/aider/.aider.conf.yml`.
Keep it in `aider-home` for normal use. A separately managed, non-secret
configuration can be mounted read-only after testing it with the selected
Aider version. It can also read project `.aider.conf.yml`,
`.aider.model.settings.yml`, and `.aiderignore` files. Treat these project
files as configuration supplied by the project: they can select model settings
and configure commands Aider runs. See
[custom configuration files](../customisation/custom-configuration.md) for
mounting guidance.

The image sets these upstream options by default:

- `AIDER_CHECK_UPDATE=false` prevents a startup version check.
- `AIDER_ANALYTICS=false` prevents analytics prompting or collection.
- `AIDER_DISABLE_PLAYWRIGHT=true` prevents a prompt to install a browser and
  browser dependencies at runtime.

Users may intentionally override these at runtime, but doing so can require
additional egress or a derived image.

## Egress control

Without `AGENT_ALLOWED_EGRESS` or a mounted
`/etc/agent/egress-allowlist.txt`, the image denies all outbound traffic. The
sample at `agent-images/aider/examples/egress-allowlist.txt` lists the direct
Anthropic and OpenAI API hosts only as a starting point. It is not a default
policy and should be narrowed to the provider actually selected.

Mount an allowlist file when the policy includes several deliberate services:

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e ANTHROPIC_API_KEY \
  -v aider-home:/home/aider \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  -v "$PWD/agent-images/aider/examples/egress-allowlist.txt":/etc/agent/egress-allowlist.txt:ro \
  aider
```

Do not set `AGENT_ALLOWED_EGRESS=*` unless unrestricted egress is an explicit
trade-off. Quoting prevents shells such as zsh from expanding the wildcard.

Aider's `/web` can scrape arbitrary user-provided URLs, while `/run`, `/test`,
configured linters, and configured test commands execute in the container.
Those commands retain the container boundary, but can write the mounted
project and reach every host you allow. Add web hosts, package registries,
source-control hosts individually and only when a workflow needs them.

## Optional browser and voice support

The standard Python package can fetch ordinary URLs with its HTTP client. The
optional Playwright/Chromium support and experimental browser UI are omitted:
they require extra Python packages, browser binaries, and a substantial set of
system libraries. Do not let an interactive session install them into the
home volume. If the capability is needed, create and test a derived image that
installs the chosen extras at build time, then add only the site's hostname to
the runtime allowlist.

Voice input is also omitted from the base container's operating-system
dependencies. Aider documents `libportaudio2` (and, in some environments,
`libasound2-plugins`) for voice capture. Add it only in a derived image and
provide an audio device deliberately; the documented hardened invocation does
not expose host audio devices.

## Gateway-client mode

Set `AGENT_GATEWAY_HOST` to tunnel all workload egress to an
[`agent-gateway`](00-agent-gateway.md) container or separately operated
gateway. The gateway, rather than Aider, then owns the allowlist;
`AGENT_ALLOWED_EGRESS` and `/etc/agent/egress-allowlist.txt` are ignored by
the workload. Follow [the Claude Code gateway guide](claude-code.md#gateway-client-mode)
for the key, host-key pinning, narrow bootstrap rule, and Cloudflare Access
configuration.

## Optional build-time tools

Edit `packages-apt.txt`, `packages-npm.txt`, or `packages-uv.txt` and rebuild
to add general-purpose tools. `packages-apt.txt` starts with the common CLI
utilities used by the other first-party images. Do not seed API keys, provider
configuration, plugins, a browser, or a local-model runtime in the image.
