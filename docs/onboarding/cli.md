---
icon: lucide/command
---

# The onboarding CLI

The `agent-containers` CLI turns the repository's hardened image recipes into
repeatable, user-scoped deployments. It validates a TOML profile, builds a
profile-specific image, records the selected deployment, and maintains a
matching shell shortcut. It uses direct Docker commands and does not launch an
agent during `apply`.

## Install

The supported installation is through `uv`:

```sh
uv tool install agent-containers-cli
```

The published distribution is named `agent-containers-cli`; it installs the
`agent-containers` executable and the `agent_containers` Python package.

For development from this repository:

```sh
uv sync --project cli --group test
uv run --project cli agent-containers --help
```

Every invocation prints the onboarding banner to stderr, including `--help`,
`--version`, and parser errors.

For unattended creation, pass `--non-interactive` before the command and use
typed options such as `--name`, `--agent`, `--apt`, `--npm`, `--uv-tool`,
`--uv-package`, `--egress-mode`, `--egress-host`, and the flat `--gateway-*`
options. Repeated package and host options replace the corresponding list from
`--config`, rather than appending to it. A partial TOML supplied with
`--config PATH` is merged first; flags override it, and model defaults fill the
remaining optional fields. Unknown keys are rejected before validation, and
non-interactive creation reports every missing required field instead of
prompting.

## Create and validate a profile

Create a new profile interactively:

```sh
agent-containers create ~/.config/agent-containers/profiles/work.toml
```

The wizard uses the same strict validation model as noninteractive use. It
refuses to replace an existing file, writes atomically with restrictive
permissions, and never asks for credential values. Provider and observability
credentials are represented by environment-variable names only.

At the beginning, the wizard displays the six stages it will cover—identity,
packages, configuration, network, integrations, and mounts—and reports progress
as it advances. Agent configuration is optional. When an import is not supplied,
the wizard prints a link to the selected agent's official configuration guide.

To validate and record an agent-native configuration for import during `apply`,
pass its source file to `create`:

```sh
agent-containers create \
  --configuration-import ~/.config/agent-containers/claude-settings.json \
  ~/.config/agent-containers/profiles/work.toml
```

The supported native formats are JSON/JSONC for Claude Code, TOML for Codex,
JSON/JSONC for OpenCode, and YAML for Hermes. The source is parsed during
`create`; credentials and other values remain in the source file and are never
copied into the profile.

Validate without contacting Docker or changing state:

```sh
agent-containers validate ~/.config/agent-containers/profiles/work.toml
```

Profiles contain the selected agent, complete replacement package lists,
provider settings, proxy and certificate inputs, egress policy, optional
configuration mounts, additional mounts/seeds, and an optional explicit
home-volume name. If no volume is
specified, the CLI derives a Docker-safe name from the image, profile,
sanitized host username, and host UID.

When provider and observability settings already live in a host-managed agent
configuration file, the interactive creator can record those inputs under
`configuration_mounts` and omit the duplicate provider and Langfuse fields:

```toml
[[configuration_mounts]]
type = "bind"
source = "claude-settings-api.json"
target = "/home/claude/.claude/settings.json"
read_only = true
```

Configuration mounts are still ordinary Docker inputs. The source must exist
before `apply`; a read-only primary settings file may fail if the agent rewrites
it, and a mount does not install plugins or hooks referenced by that file.
Keep build-time integrations in the package or image configuration and mount
any separate hook files explicitly. The CLI preserves the existing lower-level
`mounts` field for gateway inputs and other advanced cases.

### Native configuration import

An import is merged into the selected agent's configuration file in its
persistent home volume; it is not mounted over that file. Existing object keys
that are absent from the import are preserved. If a scalar, type, or array
value differs, `on_conflict = "keep"` (the default) preserves the existing
value and `on_conflict = "replace"` takes the imported value. `apply` reports
conflicting paths and their resolution on stderr; values themselves are not
printed, so secrets are not echoed.

Before replacement, the existing file is saved as a
`.agent-containers.bak` file in the same volume. The new file is written via a
networkless disposable Docker helper, with the volume read-only during
inspection and ownership/mode preserved during the atomic replacement. Imported
configuration is not executed: plugin declarations, hooks, and dependencies
must still be installed or mounted through their normal explicit mechanisms.

For advanced users who need continuous host control, `configuration_mounts`
remains available and is mutually exclusive with native import for a profile.

## Plan and apply

Inspect the offline change plan first:

```sh
agent-containers plan ~/.config/agent-containers/profiles/work.toml
```

Apply builds the profile-owned image, reconciles seeds by content, and selects the
deployment only after those steps succeed, and refreshes the generated profile
shortcut:

```sh
agent-containers apply ~/.config/agent-containers/profiles/work.toml
```

Seeds run in a short-lived, networkless helper with only the
capabilities needed to inspect and chown the mounted home volume. This includes
`DAC_OVERRIDE` so a remapped host UID cannot block a seed targeted inside a
mode-0700 home directory; the workload container itself still starts with all
capabilities dropped. A missing target is copied, an unchanged target is a
no-op, and a changed target is kept by default with an error. Set
`on_conflict = "replace"` on that `type = "seed"` mount to back up and replace
the target.

`plan --json` emits one versioned JSON document with `schema_version = 1`, the
profile name, ordered `{kind, reason}` actions, and warning objects such as
`{"code":"unrestricted_egress"}` and
`{"code":"decant_non_loopback_bind"}`. Skills may pin to this schema; breaking
payload changes increment `schema_version`.

The default deployment record is stored under
`$XDG_STATE_HOME/agent-containers/` or `~/.local/state/agent-containers/`.
Use `--state PATH` to select another JSON state file. A profile's generated
image tag and home volume are user-scoped, so two host users can both use a
profile named `work` without sharing image or home-volume resources. An
explicit `home_volume` can intentionally reuse an existing named volume.

`apply` does not start an interactive agent. The generated shortcut is the
launch surface:

```sh
source "$HOME/.config/agent-containers/profiles.sh"
agent_containers_work
```

The shortcut evaluates the current `$PWD` at invocation time while retaining
the selected image, home volume, workspace mount, provider settings, proxy/CA,
egress policy, and gateway inputs.

## Inspect, rollback, and failure safety

`doctor` checks Docker availability, recorded state, and the selected image
without changing them. It also reports whether the selected profile-specific
home volume already exists; an absent volume is reported as not created yet
because Docker can create it lazily at the first launch. When the volume is
available, it compares executable names in the writable home tool directories
with the image-managed tool directories and warns about overlaps; it never
reads or prints file contents:

```sh
agent-containers doctor ~/.config/agent-containers/profiles/work.toml
```

`rollback` selects the immediately preceding retained deployment after
verifying its image:

```sh
agent-containers rollback ~/.config/agent-containers/profiles/work.toml
```

Rollback does not restore mutable home-volume contents or stop existing agent
sessions. A failed image build or seed leaves the previous selected deployment
and state file untouched.

## Network, certificates, and credentials

The CLI preserves deny-by-default egress. An explicit allowlist must include
each provider, registry, proxy, gateway bootstrap, or observability endpoint
the profile needs. A Langfuse endpoint is rejected unless it is allowlisted or
reached through a configured gateway. To disable egress filtering, set
`egress.mode = "unrestricted"` and leave `egress.hosts` empty. A wildcard host
entry is rejected; name each host explicitly for an allowlist.

`proxy.ca_file` accepts one certificate; `proxy.ca_dir` accepts a directory of
certificates. The selected certificates are copied into the profile-owned build
context and installed into the image's merged system trust store. They are not
added to canonical image assets.

Authentication values remain outside profiles, images, build arguments, and
logs. At launch, Docker imports the host environment variables named by the
profile.

## Experimental integrations

Decant is experimental, disabled by default, and currently limited to Claude
Code and Codex. The user must opt in; there is no automatic fallback setup.
When enabled, `source_profiles` names the deployed Claude/Codex profiles whose
`.claude` and `.codex` subdirectories are mounted directly read-only into an
account-matched Decant image. The generated `profiles.sh` includes an
`agent_containers_decant_<profile>` function alongside the agent shortcut;
it does not use `volume-bridge` and therefore requires the operator to have
Docker access. Build the account-renumbering image described in
[`01-volume-bridge.md`](../container-images/01-volume-bridge.md). By default,
the CLI expects the user-scoped
`agent-containers/decant:<user>-<uid>-<profile>` tag and matching
`agent-containers-decant-<user>-<uid>-<profile>` container name; set
`decant.image` for an explicit prebuilt image override. Decant's writable
database uses a user-scoped volume by default and can reuse an existing named
volume with `decant.data_volume`. There is no unscoped `decant-matched:local`
fallback: an operator-built image must be tagged with the generated
user-scoped reference (or supplied through `decant.image`).

Langfuse is experimental, disabled by default, and currently available for
Claude Code, Codex, and OpenCode. The CLI installs the vendor-supported agent
integration and configures it per profile. Langfuse is one possible
OpenTelemetry provider, not a default telemetry backend. Existing populated
home volumes may hide newly image-seeded plugins; use a fresh volume or follow
the relevant image documentation when enabling an integration on an existing
volume.

## Verification

The normal test suite does not require Docker:

```sh
just check-cli
just test-cli
```

Opt-in Docker integration tests are documented in
`cli/tests/integration/README.md` in the repository. The image pages remain
the authoritative references for each agent's runtime flags and authentication
flow; this guide documents the profile lifecycle that composes those images.
