# agent-containers CLI

`agent-containers` is a Python CLI for creating and maintaining user-scoped
deployments of hardened coding-agent containers. It validates human-editable
TOML profiles, builds profile-specific images, records deployment state, and
generates shell shortcuts. `apply` uses direct Docker commands and does not
launch an agent session.

The package supports Python 3.12+ and is published as the
`agent-containers-cli` distribution with the `agent_containers` import package.

Full lifecycle documentation is available in the
[onboarding CLI guide](https://github.com/anirbanbasu/agent-containers/blob/main/docs/onboarding/cli.md).

## Install

Install the published CLI with `uv`:

```sh
uv tool install agent-containers-cli
```

Every invocation prints the onboarding banner, including `--help`, `--version`,
and parser errors.

## What it manages

- Human-editable, versioned TOML profiles, with separate machine-managed
  deployment state. Interactive prompts and noninteractive inputs use the same
  validation model; unknown fields are errors.
- Claude Code, OpenCode, Codex, and Hermes adapters, targeting Linux Docker Engine
  and macOS Docker Desktop. Support claims require actual integration tests.
- All four optional package categories: apt packages, npm packages, isolated uv
  tools, and system Python libraries installed with uv.
- Explicit configuration mounts, additional file/directory mounts, and
  copy-once configuration seeds, without duplicating each agent's settings
  schema. Relative input paths resolve against the profile directory; the
  workspace defaults to the launch directory. Configuration mounts can own
  provider and observability settings while build-time plugins remain explicit.
- Composable hosted/local/custom model endpoints, HTTP(S) proxies, CA trust,
  egress gateways, and experimental observability integrations. Decant is
  experimental and currently limited to Claude Code and Codex; it is disabled
  unless a profile opts in. Opted-in Decant launches use user-scoped image,
  container, and data-volume names and mount selected agent collection
  subdirectories directly; the delegated volume bridge remains a separate
  manual setup. Local inference engine installation and model
  downloads are outside the agreed initial scope.
- Explicit application and updates, retained prior deployments, and rollback of
  the selected image and managed launch configuration. Rollback does not restore
  mutable home-volume data or terminate existing sessions automatically.
- Profile-specific images are built from the image recipes bundled with the
  distribution. The package does not seed credentials, plugins, or skills.

## Safety and verification

The CLI preserves hardened-container defaults. Package selection must not
silently expand runtime egress. Credentials must not appear in profiles, build
arguments, images, logs, or command output; profiles reference runtime inputs.

When a profile declares a proxy, its generated Docker launch exports both
uppercase and lowercase `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` variables,
and enables Node's environment proxy support. A profile `proxy.ca_file` or
`proxy.ca_dir` is copied into the isolated image build context and installed
into the image's system trust store. The generated launch points
`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and `NODE_EXTRA_CA_CERTS` at the merged
system bundle. Certificate inputs are never placed in the shared canonical
image assets; they are deployment-specific and excluded from command output.

Gateway profiles require a host and port plus a read-only SSH key and pinned
known-hosts input. These can be supplied through the dedicated profile paths or
explicit mounts at `/etc/agent/gateway-key` and
`/etc/agent/gateway-known-hosts`; bootstrap rules are restricted to literal
IP addresses/CIDRs. Gateway user, Cloudflare Access hostname, and bootstrap
allow rules are emitted only when gateway mode is explicitly configured.

Langfuse support is experimental and opt-in for Claude Code, Codex, and
OpenCode. The CLI installs the vendor-supported integration for the selected
agent and emits only references to credential environment variables; it never
stores credential values. A Langfuse endpoint must be present in the profile's
egress allowlist (or be reached through a configured gateway). Langfuse is one
of many possible OpenTelemetry backends, not a default telemetry provider.

The CLI prints its required ASCII banner before every invocation. Deployment
state defaults to `$XDG_STATE_HOME/agent-containers/` (or
`~/.local/state/agent-containers/`). On macOS Docker Desktop, `apply` keeps the
host UID but uses image GID `1000`: the conventional macOS GID 20 collides with
an existing Linux image group, and the project deliberately retains its
Dockerfile collision rejection rather than silently joining that group.

Profile-managed npm and uv tools are installed into image-owned locations
outside the persistent home during image creation only. Runtime root filesystems
stay read-only, with the existing explicit writable mounts preserved. Manual
home installations take PATH precedence; diagnostics must warn when they shadow
image-managed executables. Do not delete existing home tools.

## Development

When developing from the source checkout, install contributor dependencies with
`uv sync --project cli --group test`. The repository's `just test-cli` and
`just check-cli` recipes run the unit, packaging, coverage, Ruff, and type checks.
The packaging test builds and installs the wheel in temporary environments; it
does not require Docker or real account logins. Docker integration tests are
explicit and disposable. If `/tmp` is mounted `noexec`, use a dedicated
executable temporary directory for pytest's `--basetemp` option.

## Current commands

`agent-containers create PROFILE.toml` interactively prompts for every profile
section, validates the resulting model, and writes a new TOML file atomically.
It refuses to replace an existing file and never contacts Docker. Secrets are
never prompted for; provider authentication is represented only by an
environment-variable name. The wizard displays its six stages—identity,
packages, configuration, network, integrations, and mounts—and prints the
selected agent's official configuration guide when no native import is used.

To validate and record an optional native configuration for merging during
`apply`, pass its source file to `create`:

```sh
agent-containers create \
  --configuration-import ~/.config/agent-containers/claude-settings.json \
  ~/.config/agent-containers/profiles/work.toml
```

Claude Code accepts JSON/JSONC, Codex TOML, OpenCode JSON/JSONC, and Hermes
YAML. The source is parsed during `create`; credentials remain in the source
file and are never copied into the profile.

During `apply`, an import is merged into the agent's configuration file in the
persistent home volume rather than mounted over it. Existing object keys not
present in the import are preserved. Scalar, type, and array conflicts prompt
for a choice without printing the conflicting values. The previous file is
backed up as `.agent-containers.bak`, then replaced atomically with its mode
and ownership preserved. Imported hooks, plugins, and dependencies are not
executed or installed automatically.

Advanced users can instead use `configuration_mounts` for continuous host
control. Native imports and configuration mounts are mutually exclusive in a
profile.

`agent-containers validate PROFILE.toml` parses and validates a profile without
contacting Docker or changing files.

`agent-containers plan PROFILE.toml` compares the desired profile with optional
recorded deployment JSON (`--state STATE.json`). It reports image versus launch
changes and always discloses that live Docker state was not inspected.

`agent-containers apply PROFILE.toml` materializes an isolated profile-owned
build context, builds or verifies its retained image, copies any new seed only
when its target is absent, and atomically selects deployment state. State is
written to the standard per-user location unless `--state STATE.json` overrides
it. `apply` does not launch an agent or terminate an existing session. After a
successful apply it also refreshes the CLI-managed
`$XDG_CONFIG_HOME/agent-containers/profiles.sh` (or
`~/.config/agent-containers/profiles.sh`) with a namespaced shortcut for the
profile. Source that file once from your shell startup file:

```sh
source "$HOME/.config/agent-containers/profiles.sh"
```

For example, a profile named `work-codex` becomes
`agent_containers_work_codex`. The generated function evaluates the current
directory when invoked, selects the profile's retained image and home volume,
and forwards arguments to the agent. It does not accept arbitrary Docker
options; use the documented generic shortcuts when an intentional one-off
override is needed.

By default, profile resources are namespaced with the host username and UID:
an image tag and home volume created for `work` by one user cannot collide with
the corresponding `work` resources created by another user on the same Docker
host. Set `home_volume = "an-existing-volume"` in the profile when an existing
named volume should be reused; that explicit name is an intentional sharing
choice and is never silently renamed.

Provider launch mappings are agent-specific: Claude Code uses its endpoint and
model environment variables, Codex uses per-run configuration overrides, and
Hermes uses per-run `--provider`/`--model` flags plus the documented base-URL
environment for supported `custom`, `openai`, and `anthropic` routes. OpenCode
endpoint/model fields are rendered into a secret-free JSON provider
configuration for that invocation. The shared entrypoint writes it under
`/tmp` and sets `OPENCODE_CONFIG`, so the profile does not modify the
persistent OpenCode home.

`agent-containers rollback PROFILE.toml` verifies and selects the immediately
previous retained image and launch record. It previews restored egress,
proxy/CA, and endpoint choices. It never restores persistent-home data or stops
an existing agent session, and refreshes that profile's generated shortcut.

`agent-containers doctor PROFILE.toml` is read-only. It reports Docker-daemon
availability, the expected deployment-state file, and whether the selected
image can be inspected; it creates, starts, and changes nothing.

Before building a distribution, run `uv run --project cli python cli/scripts/bundle_image_assets.py`; 
`just build-cli` does this automatically.
The generated package-data directory is ignored, derived only from canonical
`agent-images/`, and included in the wheel and source distribution.
