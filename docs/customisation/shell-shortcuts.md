---
icon: lucide/terminal
---

# Shell shortcuts

!!! warning "Extra Docker options can defeat containment"

    The user launching the container is trusted and is not the threat this
    repository's containment model is designed to control. The coding agent
    and model running inside the container are the untrusted workload.

    Nevertheless, if the user intentionally or unintentionally supplies an
    unsafe option through `--docker`, that option changes the boundary around
    the agent and can effectively defeat containment. Examples include
    `--privileged`, `--cap-add=SYS_ADMIN`, `--network=host`, mounting `/` or a
    sensitive host directory into the container, mounting
    `/var/run/docker.sock`, replacing the hardened seccomp/AppArmor policy, or
    making sensitive host files writable. Review every extra option with the
    same care as a full `docker run` command. `--docker` is a convenience, not
    a safety filter or an approval mechanism.


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
Arguments normally pass through to the coding agent. To add options to
`docker run` instead, put them between `--docker` and `--`; arguments after
the closing `--` still pass through to the agent.


```sh
agent_egress_args() {
  local agent="$1" fallback="$2" allowlist
  allowlist="$HOME/.config/agent-containers/$agent-egress-allowlist.txt"

  if [ -f "$allowlist" ]; then
    AGENT_EGRESS_ARGS=(-v "$allowlist:/etc/agent/egress-allowlist.txt:ro")
  else
    AGENT_EGRESS_ARGS=(-e "AGENT_ALLOWED_EGRESS=$fallback")
  fi
}

agent_split_args() {
  AGENT_DOCKER_ARGS=()
  AGENT_CLI_ARGS=()

  if [ "${1-}" = "--docker" ]; then
    shift
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
      AGENT_DOCKER_ARGS+=("$1")
      shift
    done
    if [ "${1-}" = "--" ]; then
      shift
    fi
  fi

  AGENT_CLI_ARGS=("$@")
}

contained_claude() {
  agent_split_args "$@"
  agent_egress_args claude "${CONTAINED_CLAUDE_EGRESS:-api.anthropic.com}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v claude-home:/home/claude \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    claude-code claude "${AGENT_CLI_ARGS[@]}"
}

contained_codex() {
  agent_split_args "$@"
  agent_egress_args codex "${CONTAINED_CODEX_EGRESS:-api.openai.com,auth.openai.com,chatgpt.com}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e OPENAI_API_KEY \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v codex-home:/home/codex \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    codex codex "${AGENT_CLI_ARGS[@]}"
}

contained_kilo() {
  agent_split_args "$@"
  agent_egress_args kilo "${CONTAINED_KILO_EGRESS:-api.kilo.ai}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:exec --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v kilo-home:/home/kilo \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    kilo-code kilo "${AGENT_CLI_ARGS[@]}"
}

contained_opencode() {
  agent_split_args "$@"
  agent_egress_args opencode "${CONTAINED_OPENCODE_EGRESS:-opencode.ai,models.dev}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:exec --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v opencode-home:/home/opencode \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    opencode opencode "${AGENT_CLI_ARGS[@]}"
}

contained_qwen() {
  agent_split_args "$@"
  agent_egress_args qwen "${CONTAINED_QWEN_EGRESS:-dashscope.aliyuncs.com}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    -e OPENAI_API_KEY \
    -e "OPENAI_BASE_URL=${CONTAINED_QWEN_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}" \
    -e "OPENAI_MODEL=${CONTAINED_QWEN_MODEL:-qwen3-coder-plus}" \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v qwen-home:/home/qwen \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    qwen-code qwen "${AGENT_CLI_ARGS[@]}"
}

contained_hermes() {
  agent_split_args "$@"
  if [ ! -f "$HOME/.config/agent-containers/hermes-egress-allowlist.txt" ]; then
    : "${CONTAINED_HERMES_EGRESS:?Set CONTAINED_HERMES_EGRESS to the selected provider hosts.}"
  fi
  agent_egress_args hermes "${CONTAINED_HERMES_EGRESS:-}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run:exec \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID --cap-add=CHOWN --cap-add=DAC_OVERRIDE \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v hermes-data:/opt/data \
    "${AGENT_DOCKER_ARGS[@]}" \
    hermes "${AGENT_CLI_ARGS[@]}"
}
```

For example, after building the images:

```sh
contained_codex
contained_opencode
CONTAINED_HERMES_EGRESS='openrouter.ai' contained_hermes
```

To add a genuinely input-only bind mount for one run, pass the Docker options
before the separator:

```sh
contained_codex --docker \
  -v "$PWD/models.json:/home/codex/.codex/models.json:ro" \
  --
```

The same form works with every shortcut. Agent arguments belong after the
separator:

```sh
contained_claude --docker \
  -v "$PWD/claude-settings.json:/home/claude/.claude/settings.json:ro" \
  -- --version
```

Without `--docker`, all arguments continue to pass directly to the agent, as
before. Docker options must precede the image name, so the opening marker is
required even when an option such as `-v` is unambiguous to a person.
Do not infer that an agent's primary configuration file is safe to mount
read-only or as a single read-write file. See [custom configuration
files](custom-configuration.md) and the candidate [local-model
recipes](local-models.md) for the agent-specific constraints.

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
If `$HOME/.config/agent-containers/<agent>-egress-allowlist.txt` exists, the
matching function instead mounts it read-only at
`/etc/agent/egress-allowlist.txt`; the source may be a symlink to a regular
file. The mounted file takes precedence, so the function does not pass
`AGENT_ALLOWED_EGRESS` in that case.
Refer to each image page for the provider-specific allowlist and authentication
requirements.
