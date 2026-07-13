# agent-containers

Restricted Docker images for running command line interface (coding) agents.

## Claude Code

Build and run the Claude Code image from `agent-images/claude-code/Dockerfile`:

```sh
docker build -t claude-code agent-images/claude-code
docker run -it --rm -v "$PWD":/workspace claude-code
```

### Optional configuration

- **`plugins.txt`** — plugins to install at build time, one per line, as `<plugin>@<marketplace>`. The official Anthropic marketplace is preinstalled as `claude-plugins-official`.
- **`plugin-marketplaces.txt`** — additional plugin marketplaces to add before installing plugins from `plugins.txt`; see the comments in the file for accepted source formats.
- **`examples/settings.local-model.json`** — sample `settings.json` for pointing Claude Code at a custom/local model endpoint (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`).
- **`examples/egress-allowlist.txt`** — sample allowlist of hosts/IPs the container is allowed to reach outbound; defaults to deny-all if neither this file nor `CLAUDE_ALLOWED_EGRESS` is set, or set to `*` for unrestricted egress.

Both of the above can be supplied either by mounting the file into the container or by setting environment variables directly with `-e`.

**Model settings — mount the file:**

```sh
docker run -it --rm \
  -v "$PWD":/workspace \
  -v "$PWD/agent-images/claude-code/examples/settings.local-model.json":/home/claude/.claude/settings.json \
  claude-code
```

**Model settings — environment variables:**

```sh
docker run -it --rm \
  -v "$PWD":/workspace \
  -e ANTHROPIC_BASE_URL=https://your-local-model.example.com \
  -e ANTHROPIC_AUTH_TOKEN=replace-with-your-token \
  -e ANTHROPIC_MODEL=your-local-model-name \
  claude-code
```

Enforcing the allowlist requires the `NET_ADMIN` capability (`--cap-add=NET_ADMIN`), since the entrypoint sets up `iptables`/`dnsmasq` rules inside the container.

**Egress allowlist — mount the file:**

```sh
docker run -it --rm \
  --cap-add=NET_ADMIN \
  -v "$PWD":/workspace \
  -v "$PWD/agent-images/claude-code/examples/egress-allowlist.txt":/etc/claude/egress-allowlist.txt \
  claude-code
```

**Egress allowlist — environment variable:**

```sh
docker run -it --rm \
  --cap-add=NET_ADMIN \
  -v "$PWD":/workspace \
  -e CLAUDE_ALLOWED_EGRESS=api.anthropic.com,your-local-model.example.com \
  claude-code
```

A mounted `egress-allowlist.txt` takes precedence over `CLAUDE_ALLOWED_EGRESS` if both are supplied.

To keep the container fully static/offline (no background update checks), you can set `DISABLE_AUTOUPDATER=1` as an environment variable or mount a file containing this setting. Updates require outbound network access to the marketplace source — relevant given the image's egress allowlist (`api.anthropic.com` etc. would need to be reachable, or marketplace hosts allowed too).