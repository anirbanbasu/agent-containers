# Docker integration tests

Runtime integration tests in this directory are explicit and opt-in, using
disposable Docker resources. Unit and packaging tests must remain runnable
without Docker.

Required coverage includes all four agent adapters, read-only root filesystems,
unprivileged execution, populated persistent homes, home-tool precedence warnings,
proxy/CA and gateway routing, Decant access, and update/rollback failure recovery.
Do not use real account logins or weaken containment to make tests pass.

The profile apply/update/rollback, CA, OpenCode provider, and opt-in Langfuse
integration tests can be run explicitly after the local Docker daemon is
available:

```sh
AGENT_CONTAINERS_RUN_INTEGRATION=1 \
  uv run --project cli --group test pytest cli/tests/integration -m integration -v
```

The apply test builds a disposable Codex image, creates a profile-specific home
volume, launches `codex --version` with the profile's read-only and unprivileged
flags, verifies home ownership/writability and persistence across a second run,
and removes both resources afterward. The same test module exercises a
launch-only update followed by rollback and verifies the retained image,
selected state, and generated shortcut. The image-update test builds two
disposable profile images and confirms rollback restores the first. The CA test
creates only a one-day self-signed test certificate and removes its image
afterward; the OpenCode provider and Langfuse tests likewise build disposable
images without credentials. No integration test sends telemetry or uses real
credentials. The normal `just test-cli` suite remains Docker-free.

The adapter runtime test also builds and launches disposable Claude Code and
Hermes images without credentials. The Decant test is separately opt-in because
the account-renumbering image is an operator-built downstream image rather than
a repository image:

```sh
AGENT_CONTAINERS_RUN_INTEGRATION=1 \
AGENT_CONTAINERS_RUN_DECANT_INTEGRATION=1 \
  uv run --project cli --group test pytest cli/tests/integration/test_decant_runtime.py -m integration -v
```

Build the account-matched image from the direct-mount recipe in
[`01-volume-bridge.md`](../../docs/container-images/01-volume-bridge.md). With
no `AGENT_CONTAINERS_DECANT_IMAGE` override, the generated shortcut and test
use the user-scoped default tag
`agent-containers/decant:<user>-<uid>-integration-decant`; the explicit
environment variable above is only for an intentionally different prebuilt
image. The test creates disposable Claude/Codex source volumes with
`.claude`/`.codex`
subdirectories, verifies the generated direct `volume-subpath` mounts, waits
for the Decant web service, checks the account-renumbered process UID, and
writes a sentinel into the separate Decant data volume. It performs no login
or telemetry request.
