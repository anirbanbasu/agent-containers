# agent-containers

Restricted Docker images for running command line interface (coding) agents in hardened containerised environments.

Full documentation: <https://docs-agent-containers.anirbanbasu.com/> (or browse `docs/` in this repository, starting at `docs/index.md`).

## Images

- **`claude-code`** — hardened container for running the [Claude Code](https://claude.com/product/claude-code) CLI: non-root user, read-only root filesystem, minimal capability set, egress denied by default. See `docs/container-images/claude-code.md`.
- **`agent-gateway`** — a disposable sibling container that a workload like `claude-code` can tunnel all its egress through over SSH, so egress enforcement lives outside the workload container entirely. See `docs/container-images/agent-gateway.md`.

## Quickstart: Claude Code

Build and run the `claude-code` image from `agent-images/claude-code/Dockerfile`. The build needs `agent-images/shared` supplied as a named build context, since the image pulls a shared egress-allowlist script from it:

```sh
docker build --build-context shared=agent-images/shared \
  -t claude-code agent-images/claude-code
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

`/home/claude` is mounted from a named volume (`claude-home`) so plugins, settings, Claude's own project memory, and any Python/Node package state persist across container runs; each project is mounted under its own `/workspace/<project_name>` subdirectory to keep per-project state distinct within that shared volume. See `docs/container-images/claude-code.md` for the full flag-by-flag rationale, runtime package installation, plugin/model/egress configuration, and the opt-in `agent-gateway` tunnelling mode.