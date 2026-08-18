---
icon: lucide/sparkles
---

# The `adal` container

`adal` packages [AdaL](https://docs.sylph.ai/), SylphAI's terminal coding
agent, in the repository's standard hardened workload environment: non-root
execution, a read-only root filesystem, minimal Linux capabilities, and
deny-by-default outbound networking.

The image uses the documented npm fallback, pinned to
`@sylphai/adal-cli@1.7.1`. The package requires Node.js 20 or newer and
selects its Linux x64 or arm64 runtime during the image build. The native
installer is deliberately not used: it is an unpinned `curl | bash` installer
that manages updates outside the image build.

## Build

```sh
docker build --build-context shared=agent-images/shared \
  -t adal agent-images/adal
```

## Run

AdaL opens a browser on its first run for authentication. Keep its state in
the named home volume; do not put credentials in an image, build argument, or
checked-in file. The initial egress rule permits the documented AdaL sign-in
host. Add only hosts required by a feature you intentionally enable.

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e 'AGENT_ALLOWED_EGRESS=adal.sylph.ai' \
  -v adal-home:/home/adal \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  adal
```

### Hardening flags

| Flag | Purpose |
|---|---|
| `--security-opt=no-new-privileges` | Prevents escalation through setuid binaries. |
| `--read-only` | Keeps the root filesystem immutable. |
| `--tmpfs /tmp` and `--tmpfs /run` | Provide ephemeral writable locations for the egress-control tooling and runtime files. |
| `--cap-drop=ALL` | Removes Docker's default capabilities. |
| `NET_ADMIN` and `NET_RAW` | Required for the default-deny `iptables`/`ip6tables` rules and domain allowlists. |
| `SETUID` and `SETGID` | Let `gosu` switch from the setup user to the unprivileged `adal` user. |

The `adal-home` volume persists AdaL's credentials, settings, session history,
MCP OAuth state, skills, plugin cache, and user-installed npm/Python tools
under `~/.adal`. It is shared state: mount a separate volume when different
projects or trust domains should not share that state.

## Egress and credentials

Without `AGENT_ALLOWED_EGRESS` or a mounted
`/etc/agent/egress-allowlist.txt`, the image denies all outbound traffic. The
sample `agent-images/adal/examples/egress-allowlist.txt` contains only
`adal.sylph.ai`, the documented sign-in host. It is a starting point rather
than a broad service policy: observe and add any further required AdaL
first-party hostname when a tested version needs it.

AdaL features can initiate connections to substantially different services:

- **BYOAK** connects directly to the selected Anthropic, OpenAI, or Google
  provider. Add only that provider's API host and pass a key at runtime; AdaL
  stores keys in `~/.adal/settings.json`.
- **MCP** supports remote HTTP/SSE servers and local stdio processes. Allow
  each remote server explicitly. A local MCP server runs inside this same
  constrained container; its package-registry access is not granted by
  default.
- **Skills and plugins** can clone marketplace repositories. Do not seed a
  marketplace or plugin in the image; add a source-control host only when the
  user elects to install one.
- **Web search, Browser Use, image/video features, and custom tools** may
  each contact separate user-selected services. They require their own narrow
  egress entries and should not enlarge the default policy.

Mount a host-maintained allowlist read-only when the set is larger than one
host:

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only --tmpfs /tmp --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v adal-home:/home/adal \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -v "$PWD/agent-images/adal/examples/egress-allowlist.txt":/etc/agent/egress-allowlist.txt:ro \
  -w "/workspace/$(basename "$PWD")" \
  adal
```

Do not use `-e 'AGENT_ALLOWED_EGRESS=*'` unless unrestricted egress is an
intentional trade-off; quoting prevents shells such as zsh from treating `*`
as a filename pattern.

## Browser Use and local models

AdaL documents Chromium as a manual Linux prerequisite for Browser Use. It
is not included in the baseline image: installing it is optional and must be
tested in a derived image or by editing `packages-apt.txt`. Do not weaken the
browser sandbox with a `--no-sandbox` workaround. Browser Use can operate on
real sites and accounts, so use test accounts and explicitly allow each site
that it must reach.

AdaL's Ollama support is also optional. This image does not install or run an
Ollama server or model. Run it separately and provide a deliberately
reachable, allowlisted endpoint; a service listening on the Docker host is
not implicitly reachable from the container. See the version-recorded
candidate in [local models](../customisation/local-models.md#adal).

## Project code, permissions, and hooks

AdaL can auto-load `.adal/tools.py`, project skills, and `AGENTS.md` from the
mounted project. These are code and instructions supplied by that project,
not trusted image content. Lifecycle hooks are loaded from
`~/.adal/settings.json` and execute as the unprivileged container user. Keep
the home volume and project mount within an appropriate trust boundary.

Interactive AdaL asks for approval before modifications and shell commands.
For headless use, prefer a narrow explicit tool set, for example:

```sh
adal -q "review the change" --enabled-default-tools "Read,Search" --yolo
```

`--yolo` auto-approves every enabled tool. It does not relax the container's
filesystem, capability, or egress boundaries, but it can freely modify the
mounted project and invoke enabled local tools.

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
to add general-purpose tools. No credentials, extensions, skills, plugins,
browser, or local-model runtime is seeded in the image.
