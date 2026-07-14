# agent-containers

Restricted Docker images for running command line interface (coding) agents in hardened containerised environments.

## Claude Code

Build and run the Claude Code image from `agent-images/claude-code/Dockerfile`:

```sh
docker build -t claude-code agent-images/claude-code
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v claude-home:/home/claude/.claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  claude-code
```

`/home/claude/.claude` is mounted from a named volume (`claude-home`) so plugins, settings, and Claude's own project memory persist across container runs instead of being lost when the container is removed. That volume is shared by every invocation of this image, and Claude Code keys its per-project memory/session data off the working directory's path — so if every project were mounted at the same `/workspace` path, unrelated projects would collide inside that shared volume. Mounting each project under its own `/workspace/<project_name>` subdirectory (and setting `-w` to match) keeps them distinct.

The rest of the flags harden the container beyond Docker's defaults: `--security-opt=no-new-privileges` blocks privilege escalation via setuid binaries; `--read-only` makes the root filesystem immutable, with `--tmpfs /tmp --tmpfs /run` providing the only writable scratch space the entrypoint needs (dnsmasq's runtime config/pid files, iptables' lock file — `/workspace` and `/home/claude/.claude` stay writable regardless, since mounts are independent of the root filesystem's read-only flag); and `--cap-drop=ALL` strips Docker's full default capability set down to just what's actually used — `NET_ADMIN`/`NET_RAW` for the `iptables`/`ipset`/`dnsmasq` egress enforcement, and `SETUID`/`SETGID` for `gosu` to drop from root to the `claude` user.

### Optional configuration

- **`plugins.txt`** — plugins to install at build time, one per line, as `<plugin>@<marketplace>`. The official Anthropic marketplace is preinstalled as `claude-plugins-official`.
- **`plugin-marketplaces.txt`** — additional plugin marketplaces to add before installing plugins from `plugins.txt`; see the comments in the file for accepted source formats.
- **`examples/settings.local-model.json`** — sample `settings.json` for pointing Claude Code at a custom/local model endpoint (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`).
- **`examples/egress-allowlist.txt`** — sample allowlist of hosts/IPs the container is allowed to reach outbound; defaults to deny-all if neither this file nor `CLAUDE_ALLOWED_EGRESS` is set, or set to `*` for unrestricted egress.

Both of the above can be supplied either by mounting the file into the container or by setting environment variables directly with `-e`.

**Model settings — mount the file:**

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v claude-home:/home/claude/.claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  -v "$PWD/agent-images/claude-code/examples/settings.local-model.json":/home/claude/.claude/settings.json:ro \
  claude-code
```

Mounted `:ro` since this file is bind-mounted directly over whatever `settings.json` already exists in the `claude-home` volume — it shadows that file for the run rather than merging with it, and mounting read-write would mean any settings Claude Code writes back land on your host's checked-in `settings.local-model.json` instead of in the volume. If you want local-model settings to coexist with whatever else lives in the volume's `settings.json`, prefer the environment-variable form below instead.

**Model settings — environment variables:**

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v claude-home:/home/claude/.claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  -e ANTHROPIC_BASE_URL=https://your-local-model.example.com \
  -e ANTHROPIC_AUTH_TOKEN=replace-with-your-token \
  -e ANTHROPIC_MODEL=your-local-model-name \
  claude-code
```

**Egress allowlist — mount the file:**

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v claude-home:/home/claude/.claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  -v "$PWD/agent-images/claude-code/examples/egress-allowlist.txt":/etc/claude/egress-allowlist.txt \
  claude-code
```

**Egress allowlist — environment variable:**

```sh
docker run -it --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v claude-home:/home/claude/.claude \
  -v "$PWD":"/workspace/$(basename "$PWD")" \
  -w "/workspace/$(basename "$PWD")" \
  -e CLAUDE_ALLOWED_EGRESS=api.anthropic.com,your-local-model.example.com \
  claude-code
```

`NET_ADMIN` is required in every case above (even with no allowlist configured) since the entrypoint always sets a default-deny `iptables`/`ip6tables` policy; `NET_RAW` is additionally needed once a domain-based allowlist is in play, since matching `iptables` rules against the resolved-IP `ipset` needs it.

A mounted `egress-allowlist.txt` takes precedence over `CLAUDE_ALLOWED_EGRESS` if both are supplied.

To keep the container fully static/offline (no background update checks), you can set `DISABLE_AUTOUPDATER=1` as an environment variable or mount a file containing this setting. Updates require outbound network access to the marketplace source — relevant given the image's egress allowlist (`api.anthropic.com` etc. would need to be reachable, or marketplace hosts allowed too).