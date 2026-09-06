# agent-containers CLI

The Python package is tested on Python 3.14 (with Python 3.12+ support). It
validates profiles, produces offline plans, materializes bundled image recipes,
and applies a direct-Docker deployment without launching an agent session.

This directory will contain the standalone Python project for deterministic
onboarding and maintenance of this repository's hardened agent images. The
distribution and executable name is `agent-containers`; the Python import
package will be `agent_containers`.

## Agreed scope

- Human-editable, versioned TOML profiles, with separate machine-managed
  deployment state. Interactive prompts and noninteractive inputs use the same
  validation model; unknown fields are errors.
- Claude Code, OpenCode, Codex, and Hermes adapters, targeting Linux Docker Engine
  and macOS Docker Desktop. Support claims require actual integration tests.
- All four optional package categories: apt packages, npm packages, isolated uv
  tools, and system Python libraries installed with uv.
- Explicit custom file/directory mounts and copy-once configuration seeds,
  without duplicating each agent's settings schema. Relative input paths resolve
  against the profile directory; the workspace defaults to the launch directory.
- Composable hosted/local/custom model endpoints, HTTP(S) proxies, CA trust,
  egress gateways, and Decant. These belong to the complete initial product,
  not a deferred integration wishlist. Local inference engine installation and
  model downloads are outside the agreed initial scope.
- Explicit application and updates, retained prior deployments, and rollback of
  the selected image and managed launch configuration. Rollback does not restore
  mutable home-volume data or terminate existing sessions automatically.
- Image recipes bundled from canonical `../agent-images/` sources in both wheel
  and source distributions. No maintained duplicate or installed-package edits.

## Safety and verification

Preserve the repository's containment contract. Package selection must not
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

Unit and distribution tests must run without Docker. Integration tests require
Docker and disposable resources, without real account logins. Offline plans and
diagnostics must distinguish recorded state from inspected live state and mark
runtime checks unavailable when Docker cannot be reached.

Use direct Docker commands, not Compose, and package with `uv build` and the
native `uv_build` backend, not Hatchling, with Python 3.12 or newer. Use `ty`
for type checking and Ruff for linting/formatting. Both live in the `dev`
dependency group; pytest and coverage live in `test`.

From this directory, install contributor dependencies with
`uv sync --group test --python 3.12`. Root `just test-cli` runs unit and packaging
tests under coverage; `just check-cli` runs Ruff and ty. Coverage must reach 100%.
Do not suppress type or coverage errors without a demonstrated, documented need.
The packaging test builds a standalone source distribution and installs its
rebuilt wheel in a fresh temporary environment; dependency downloads may be needed.

The CLI prints its required ASCII banner before every invocation. Deployment
state defaults to `$XDG_STATE_HOME/agent-containers/` (or
`~/.local/state/agent-containers/`). On macOS Docker Desktop, `apply` keeps the
host UID but uses image GID `1000`: the conventional macOS GID 20 collides with
an existing Linux image group, and the project deliberately retains its
Dockerfile collision rejection rather than silently joining that group.

If the host mounts `/tmp` with `noexec`, use a dedicated executable temporary
directory for pytest's `--basetemp` option. Pytest owns and clears that directory:
never point it at an existing directory containing your files. No mount flags
need changing. Tests still install outside the repository and use a fresh venv.

The test suite covers CLI behavior, profile/state validation, generated build
contexts, Docker argv construction, lifecycle transitions, and standalone
sdist-to-wheel installation at 100% source coverage. It does not establish all
runtime containment or agent compatibility claims; broader Docker integration
tests remain to be implemented.

Profile-managed npm and uv tools are installed into image-owned locations
outside the persistent home during image creation only. Runtime root filesystems
stay read-only, with the existing explicit writable mounts preserved. Manual
home installations take PATH precedence; diagnostics must warn when they shadow
image-managed executables. Do not delete existing home tools.

The private implementation handoff is maintained in
`../tmp-onboarding-codex.log`; the original discussion is in
`../tmp-onboarding.md`. Both are intentionally ignored by Git.

## Current commands

`agent-containers create PROFILE.toml` interactively prompts for every profile
section, validates the resulting model, and writes a new TOML file atomically.
It refuses to replace an existing file and never contacts Docker. Secrets are
never prompted for; provider authentication is represented only by an
environment-variable name.

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
