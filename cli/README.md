# agent-containers CLI

Implementation is starting. A Python package and help/version entry point are
implemented and tested on Python 3.13 (with Python 3.12+ support). Profile
and runtime commands and bundled image assets are not implemented yet.

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

If the host mounts `/tmp` with `noexec`, use a dedicated executable temporary
directory for pytest's `--basetemp` option. Pytest owns and clears that directory:
never point it at an existing directory containing your files. No mount flags
need changing. Tests still install outside the repository and use a fresh venv.

Six foundation tests currently pass with 100% source coverage. This does not
establish runtime containment or agent compatibility; Docker integration tests
and image-asset packaging coverage remain to be implemented.

Profile-managed npm and uv tools will be installed into image-owned locations
outside the persistent home during image creation only. Runtime root filesystems
stay read-only, with the existing explicit writable mounts preserved. Manual
home installations take PATH precedence; diagnostics must warn when they shadow
image-managed executables. Do not delete existing home tools.

The private implementation handoff is maintained in
`../tmp-onboarding-codex.log`; the original discussion is in
`../tmp-onboarding.md`. Both are intentionally ignored by Git.

## Current command

`agent-containers validate PROFILE.toml` parses and validates a profile without
contacting Docker or changing files. Lifecycle commands will be added behind the
same validated model.
