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
uv tool install agent-containers
```

For development from this repository:

```sh
uv sync --project cli --group test
uv run --project cli agent-containers --help
```

Every invocation prints the onboarding banner, including `--help`,
`--version`, and parser errors.

## Create and validate a profile

Create a new profile interactively:

```sh
agent-containers create ~/.config/agent-containers/profiles/work.toml
```

The wizard uses the same strict validation model as noninteractive use. It
refuses to replace an existing file, writes atomically with restrictive
permissions, and never asks for credential values. Provider and observability
credentials are represented by environment-variable names only.

Validate without contacting Docker or changing state:

```sh
agent-containers validate ~/.config/agent-containers/profiles/work.toml
```

Profiles contain the selected agent, complete replacement package lists,
provider settings, proxy and certificate inputs, egress policy, optional
mounts/seeds, and an optional explicit home-volume name. If no volume is
specified, the CLI derives a Docker-safe name from the image, profile,
sanitized host username, and host UID.

## Plan and apply

Inspect the offline change plan first:

```sh
agent-containers plan ~/.config/agent-containers/profiles/work.toml
```

Apply builds the profile-owned image, performs copy-once seeds, selects the
deployment only after those steps succeed, and refreshes the generated profile
shortcut:

```sh
agent-containers apply ~/.config/agent-containers/profiles/work.toml
```

Copy-once seeds run in a short-lived, networkless helper with only the
capabilities needed to inspect and chown the mounted home volume. This includes
`DAC_OVERRIDE` so a remapped host UID cannot block a seed targeted inside a
mode-0700 home directory; the workload container itself still starts with all
capabilities dropped.

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
without changing them:

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
reached through a configured gateway.

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
