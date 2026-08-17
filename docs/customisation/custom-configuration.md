---
icon: lucide/settings-2
---

# Custom configuration files

Each workload image keeps its user configuration in its persistent home
volume. For a reproducible, host-maintained configuration, bind-mount the
agent's global configuration file at the agent-specific destination below.
Add the mount to that image's documented `docker run` command.

Create the host-side file first. Docker may otherwise create a directory at
the source path, which cannot be mounted over the configuration file.

Use `:ro`: a bind mount shadows the same file in the persistent volume for
that run; it does not merge with it. A read-only mount prevents the agent from
rewriting the host file. Authentication, conversation state, caches, and other
state continue to live in the named home volume.

Do not put credentials in a configuration file that is checked into a project.
Use the agent's runtime environment variables or its persisted authentication
state instead. If the configuration selects a model provider, MCP server, or
other network service, also allow only its required host/IP with
`AGENT_ALLOWED_EGRESS` or the mounted egress-policy file. A local service
must be reachable from the container as well as allowlisted.

## Claude Code

Claude Code reads user settings from `/home/claude/.claude/settings.json`.
The [Claude Code image guide](../container-images/claude-code.md#custom-configuration-and-optional-build-time-tools)
includes a complete local-model example:

```sh
-v "$PWD/claude-settings.json":/home/claude/.claude/settings.json:ro
```

## Codex

Codex reads global configuration from `/home/codex/.codex/config.toml`.
It can define the default model/provider, MCP servers, approval policy, and
other CLI settings; see the [official Codex configuration guide](https://developers.openai.com/codex/config-reference).

```sh
-v "$PWD/codex-config.toml":/home/codex/.codex/config.toml:ro
```

Codex also supports trusted project configuration at
`/workspace/<project>/.codex/config.toml`; that is appropriate for
non-secret, project-specific settings.

## OpenCode

OpenCode's global configuration is
`/home/opencode/.config/opencode/opencode.json`. It configures providers,
models, permissions, and integrations; see the [OpenCode configuration
reference](https://dev.opencode.ai/docs/config).

```sh
-v "$PWD/opencode.json":/home/opencode/.config/opencode/opencode.json:ro
```

For non-secret project configuration, OpenCode also reads `opencode.json` at
the project root.

## Kilo Code

Kilo's global configuration is `/home/kilo/.config/kilo/kilo.json` (or the
JSONC variant `kilo.jsonc`). It configures the model/provider, MCP servers,
permissions, and other CLI behaviour; see the [Kilo CLI configuration
reference](https://kilo.ai/docs/code-with-ai/platforms/cli).

```sh
-v "$PWD/kilo.json":/home/kilo/.config/kilo/kilo.json:ro
```

Kilo also supports non-secret project configuration such as `kilo.json` or
`.kilo/` configuration below the mounted project directory.

## Qwen Code

Qwen Code reads its user settings from `/home/qwen/.qwen/settings.json`.
That file configures providers, MCP servers, and other persistent settings;
see the [Qwen Code settings reference](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/).

```sh
-v "$PWD/qwen-settings.json":/home/qwen/.qwen/settings.json:ro
```

For non-secret project settings, Qwen Code also reads
`.qwen/settings.json` in the project root.

## Hermes

Hermes Agent stores its non-secret global settings in
`/opt/data/config.yaml`, because this image maps Hermes's upstream home to
`/opt/data`. Its `auth.json` and other state stay in the `hermes-data` volume.
See the [Hermes configuration guide](https://github.com/hermes-agent-org/hermes/blob/main/website/docs/user-guide/configuration.md).

```sh
-v "$PWD/hermes-config.yaml":/opt/data/config.yaml:ro
```

Use runtime environment variables for provider keys rather than mounting a
host `.env` file over the persistent data volume.
