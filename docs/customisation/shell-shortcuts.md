---
icon: lucide/terminal
---

# Shell shortcuts

The documented `docker run` commands deliberately show every containment flag,
but retyping them is tedious. Use shell functions rather than aliases: a
function evaluates `$PWD` when it is invoked, forwards arguments to the agent,
and keeps the image-specific flags in one auditable place.

Create `~/.config/agent-containers/shortcuts.sh` with the functions below,
then source it from `~/.bashrc` or `~/.zshrc`:

```sh
source "$HOME/.config/agent-containers/shortcuts.sh"
```

Restart the shell or run the same `source` command once to activate them.
Each function mounts the current directory at
`/workspace/<current-directory-name>` and starts the matching local image.

```sh
contained_claude() {
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e "AGENT_ALLOWED_EGRESS=${CONTAINED_CLAUDE_EGRESS:-api.anthropic.com}" \
    -v claude-home:/home/claude \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    claude-code claude "$@"
}

contained_codex() {
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e OPENAI_API_KEY \
    -e "AGENT_ALLOWED_EGRESS=${CONTAINED_CODEX_EGRESS:-api.openai.com,auth.openai.com,chatgpt.com}" \
    -v codex-home:/home/codex \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    codex codex "$@"
}

contained_kilo() {
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:exec --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e "AGENT_ALLOWED_EGRESS=${CONTAINED_KILO_EGRESS:-api.kilo.ai}" \
    -v kilo-home:/home/kilo \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    kilo-code kilo "$@"
}

contained_opencode() {
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:exec --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e "AGENT_ALLOWED_EGRESS=${CONTAINED_OPENCODE_EGRESS:-opencode.ai,models.dev}" \
    -v opencode-home:/home/opencode \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    opencode opencode "$@"
}

contained_qwen() {
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e OPENAI_API_KEY \
    -e "OPENAI_BASE_URL=${CONTAINED_QWEN_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}" \
    -e "OPENAI_MODEL=${CONTAINED_QWEN_MODEL:-qwen3-coder-plus}" \
    -e "AGENT_ALLOWED_EGRESS=${CONTAINED_QWEN_EGRESS:-dashscope.aliyuncs.com}" \
    -v qwen-home:/home/qwen \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    qwen-code qwen "$@"
}

contained_hermes() {
  : "${CONTAINED_HERMES_EGRESS:?Set CONTAINED_HERMES_EGRESS to the selected provider hosts.}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run:exec \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID --cap-add=CHOWN --cap-add=DAC_OVERRIDE \
    -e "AGENT_ALLOWED_EGRESS=$CONTAINED_HERMES_EGRESS" \
    -v hermes-data:/opt/data \
    hermes "$@"
}
```

For example, after building the images:

```sh
contained_codex
contained_opencode
CONTAINED_HERMES_EGRESS='openrouter.ai' contained_hermes
```

For Codex device authentication, forward the login subcommand through the
same function. Do not add another `codex`: the function already supplies the
CLI command required after the image name.

```sh
contained_codex login --device-auth
```

The functions deliberately do not set unrestricted egress. Override a
specific image's `CONTAINED_<IMAGE>_EGRESS` variable only with the hosts its
selected provider, MCP server, source-control integration, or package
registry requires. Quote a wildcard value, for example
`CONTAINED_HERMES_EGRESS='*'`, when unrestricted egress is intentional.
Refer to each image page for the provider-specific allowlist and authentication
requirements.
