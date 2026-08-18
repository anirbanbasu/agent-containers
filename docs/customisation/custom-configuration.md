---
icon: lucide/settings-2
---

# Custom configuration files

Each workload image keeps configuration and runtime state in its persistent
home volume. Do not assume that an agent's documented configuration file is a
read-only input: some agents update the same file for project trust, provider
selection, migrations, or UI preferences.

A single-file bind mount also has different semantics from a normal file in a
writable directory. A `:ro` mount rejects every write. Removing `:ro` permits
ordinary writes only when host ownership and permissions allow them, but an
application may still fail if it updates the file by atomically renaming a new
file over the bind-mount point. Mounting a file also shadows the copy in the
persistent volume; it never merges the two.

Consequently, there is no repository-wide rule that every global
configuration file should be bind-mounted. Use one of these patterns only when
the agent-specific documentation says it is appropriate:

- pass provider selection through supported CLI flags or environment
  variables, leaving mutable state in the persistent home volume;
- mount a genuinely input-only file with `:ro`;
- use an agent-supported configuration layer that does not replace its mutable
  primary file;
- keep the configuration in the persistent home volume when the agent owns and
  rewrites it;
- mount a whole writable configuration directory only when intentionally
  moving all state in that directory onto the host.

The compatibility details below have not yet been exercised against every
agent. See [Local models](local-models.md) for version-recorded candidate
recipes and the verification checklist. Do not treat either page as an
always-works guide.

Create every host-side bind source before starting Docker. Otherwise Docker
may create a directory at a missing source path. Keep credentials out of
checked-in configuration; use runtime environment variables or authentication
state in the persistent home volume.

If configuration selects a model provider, MCP server, or other network
service, allow only its required host or IP with `AGENT_ALLOWED_EGRESS` or the
mounted egress-policy file. A service on the host or LAN must be reachable
from the container as well as allowlisted.

## Current configuration locations

| Agent | Global configuration | Persistent state relationship | Single-file mount status |
|---|---|---|---|
| Claude Code | `/home/claude/.claude/settings.json` | Other Claude state remains below `/home/claude` | Candidate only; prefer environment variables for temporary provider routing |
| Codex | `/home/codex/.codex/config.toml` | Configuration, trust, authentication, and sessions share `/home/codex/.codex` | Do not mount the mutable primary file; Codex may replace it while saving trust |
| Kilo Code | `/home/kilo/.config/kilo/kilo.json` or `kilo.jsonc` | Configuration and session state persist in `kilo-home` | Candidate only; prefer `KILO_CONFIG` with a separate read-only input for testing |
| OpenCode | `/home/opencode/.config/opencode/opencode.json` or `.jsonc` | Configuration and credentials use multiple XDG paths in `opencode-home` | Candidate only; a project configuration layer avoids shadowing the global file |
| Qwen Code | `/home/qwen/.qwen/settings.json` | Settings, authentication, and MCP state share `qwen-home` | Candidate only; prefer runtime provider environment variables for temporary routing |
| Hermes | `/opt/data/config.yaml` | Configuration, auth, memories, sessions, and skills share `hermes-data` | Do not assume it is input-only; Hermes persists model/provider changes to it |

These paths identify where each agent normally stores configuration; they are
not blanket recommendations to mount those files.

## Project configuration

Project-scoped configuration can be useful for non-secret settings when the
agent supports it, but it has different trust and precedence rules:

- Codex reads `.codex/config.toml` only for trusted projects and does not allow
  project configuration to redirect provider or authentication settings.
- OpenCode searches for `opencode.json(c)` and `.opencode/opencode.json(c)` in
  the project hierarchy and merges those layers with global configuration.
- Kilo supports project configuration, but secret environment/file references
  are restricted outside trusted configuration locations.
- Qwen Code supports `.qwen/settings.json` in a project.

Do not use a repository-controlled file to supply credentials or silently
redirect a trusted user's model traffic.

## Runtime overrides with shell shortcuts

The [shell shortcuts](shell-shortcuts.md) accept additional Docker arguments
between `--docker` and `--`, followed by agent arguments. This is useful for
candidate configuration files and environment variables without changing the
shortcut itself:

```sh
contained_codex --docker \
  -v "$PWD/input.json:/etc/agent/input.json:ro" \
  -- --version
```

The shortcut is a convenience for the user, not an additional containment
boundary. The agent running inside the container does not receive access to
the host shell function or Docker socket.
