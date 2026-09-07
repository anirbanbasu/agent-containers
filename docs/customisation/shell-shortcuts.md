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

contained_adal() {
  agent_split_args "$@"
  agent_egress_args adal "${CONTAINED_ADAL_EGRESS:-adal.sylph.ai}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v "adal-home${CONTAINED_ADAL_TAG:+-$CONTAINED_ADAL_TAG}":/home/adal \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "adal:${CONTAINED_ADAL_TAG:-latest}" adal "${AGENT_CLI_ARGS[@]}"
}

contained_aider() {
  agent_split_args "$@"
  if [ ! -f "$HOME/.config/agent-containers/aider-egress-allowlist.txt" ]; then
    : "${CONTAINED_AIDER_EGRESS:?Set CONTAINED_AIDER_EGRESS to the selected provider hosts.}"
  fi
  agent_egress_args aider "${CONTAINED_AIDER_EGRESS:-}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v "aider-home${CONTAINED_AIDER_TAG:+-$CONTAINED_AIDER_TAG}":/home/aider \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "aider:${CONTAINED_AIDER_TAG:-latest}" aider "${AGENT_CLI_ARGS[@]}"
}

contained_claude() {
  agent_split_args "$@"
  agent_egress_args claude "${CONTAINED_CLAUDE_EGRESS:-api.anthropic.com}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v "claude-home${CONTAINED_CLAUDE_TAG:+-$CONTAINED_CLAUDE_TAG}":/home/claude \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "claude-code:${CONTAINED_CLAUDE_TAG:-latest}" claude "${AGENT_CLI_ARGS[@]}"
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
    -v "codex-home${CONTAINED_CODEX_TAG:+-$CONTAINED_CODEX_TAG}":/home/codex \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "codex:${CONTAINED_CODEX_TAG:-latest}" codex "${AGENT_CLI_ARGS[@]}"
}

contained_kilo() {
  agent_split_args "$@"
  agent_egress_args kilo "${CONTAINED_KILO_EGRESS:-api.kilo.ai}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:exec --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v "kilo-home${CONTAINED_KILO_TAG:+-$CONTAINED_KILO_TAG}":/home/kilo \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "kilo-code:${CONTAINED_KILO_TAG:-latest}" kilo "${AGENT_CLI_ARGS[@]}"
}

contained_opencode() {
  agent_split_args "$@"
  agent_egress_args opencode "${CONTAINED_OPENCODE_EGRESS:-opencode.ai,models.dev}"
  docker run -it --rm \
    --security-opt=no-new-privileges \
    --read-only --tmpfs /tmp:exec --tmpfs /run \
    --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
    "${AGENT_EGRESS_ARGS[@]}" \
    -v "opencode-home${CONTAINED_OPENCODE_TAG:+-$CONTAINED_OPENCODE_TAG}":/home/opencode \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "opencode:${CONTAINED_OPENCODE_TAG:-latest}" opencode "${AGENT_CLI_ARGS[@]}"
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
    -v "qwen-home${CONTAINED_QWEN_TAG:+-$CONTAINED_QWEN_TAG}":/home/qwen \
    -v "$PWD":"/workspace/$(basename "$PWD")" \
    -w "/workspace/$(basename "$PWD")" \
    "${AGENT_DOCKER_ARGS[@]}" \
    "qwen-code:${CONTAINED_QWEN_TAG:-latest}" qwen "${AGENT_CLI_ARGS[@]}"
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
    "hermes:${CONTAINED_HERMES_TAG:-latest}" "${AGENT_CLI_ARGS[@]}"
}
```

For example, after building the images:

```sh
contained_codex
contained_adal
contained_opencode
CONTAINED_AIDER_EGRESS='api.anthropic.com' contained_aider --docker -e ANTHROPIC_API_KEY --
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

## CLI-managed profile shortcuts

The onboarding CLI leaves this generic file available and maintains a separate
`$XDG_CONFIG_HOME/agent-containers/profiles.sh` (falling back to
`~/.config/agent-containers/profiles.sh`). Source the generated file once from
your shell startup file:

```sh
source "$HOME/.config/agent-containers/profiles.sh"
```

It contains one namespaced function for each profile that has been applied, such
as `agent_containers_work_codex` or `agent_containers_local_codex`. These
functions evaluate `$PWD` at invocation time but select the profile's retained
image, home volume, egress policy, proxy/CA mounts, and other managed launch
settings. Unless the profile sets `home_volume`, its image tag and home volume
are namespaced with the host username and UID, so equal profile names used by
different host users remain isolated. Profile proxy launches provide both
uppercase and lowercase proxy and bypass variables, plus the runtime CA pointers used by common Node.js and
Python clients. Profile CA files or certificate directories are baked into the
profile-owned image's system trust store during `apply`, and those pointers use
the resulting merged bundle. Certificate inputs remain deployment-specific and
are not copied into canonical image assets, as described in
[`network-proxy-considerations.md`](../network-proxy-considerations.md).
Gateway profiles also carry their pinned SSH key and known-hosts mounts and
explicit gateway bootstrap settings; missing gateway inputs are rejected before
Docker is invoked.
`apply` and `rollback` refresh the matching function atomically; the
CLI does not overwrite this generic `shortcuts.sh` file.

Generated functions do not expose the generic shortcut's `--docker` escape
hatch. Keep using the generic functions above for deliberate one-off Docker
options, and review those options against the containment warning at the top of
this page.

For Codex device authentication, forward the login subcommand through the
same function. Do not add another `codex`: the function already supplies the
CLI command required after the image name.

```sh
contained_codex login --device-auth
```

Each function defaults to the `:latest` tag (e.g. `adal:latest`), matching a
plain `docker build -t adal agent-images/adal` with no `--build-arg
UID`/`GID` override — the common single-user-per-host case needs no further
configuration. On a host shared by multiple accounts where each user built
their own UID-matched tag (see [Matching your host user's
UID/GID](../container-images/claude-code.md#matching-your-host-users-uidgid)),
set the matching `CONTAINED_<IMAGE>_TAG` variable (e.g.
`CONTAINED_ADAL_TAG=alice`) in that user's own shell profile before sourcing
`shortcuts.sh`. For the seven workload images built from the shared
UID/GID template (every function above except `contained_hermes`), setting
that variable changes two things together: the function runs the matching
`adal:alice` instead of whatever happens to be tagged `adal:latest`, *and*
it mounts a per-user home volume (`adal-home-alice` instead of the shared
`adal-home`) — each affected function suffixes its home volume's name with
the same tag, so two UID-tagged images on the same host never collide over
one account's persistent state. `hermes` has no build-time UID/GID and
always keeps the single shared `hermes-data` volume regardless of
`CONTAINED_HERMES_TAG`.

The functions deliberately do not set unrestricted egress. Override a
specific image's `CONTAINED_<IMAGE>_EGRESS` variable only with the hosts its
selected provider, MCP server, source-control integration, or package
registry requires. Quote a wildcard value, for example
`CONTAINED_HERMES_EGRESS='*'`, when unrestricted egress is intentional.
An allowlist containing `*` is unrestricted even if other entries are present;
omit it when you want the remaining hosts to be enforced.
If `$HOME/.config/agent-containers/<agent>-egress-allowlist.txt` exists, the
matching function instead mounts it read-only at
`/etc/agent/egress-allowlist.txt`; the source may be a symlink to a regular
file. The mounted file takes precedence, so the function does not pass
`AGENT_ALLOWED_EGRESS` in that case.
Refer to each image page for the provider-specific allowlist and authentication
requirements.
