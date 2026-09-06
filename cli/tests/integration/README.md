# Docker integration tests

Runtime integration tests in this directory are explicit and opt-in, using
disposable Docker resources. Unit and packaging tests must remain runnable
without Docker.

Required coverage includes all four agent adapters, read-only root filesystems,
unprivileged execution, populated persistent homes, home-tool precedence warnings,
proxy/CA and gateway routing, Decant access, and update/rollback failure recovery.
Do not use real account logins or weaken containment to make tests pass.

The profile CA and OpenCode provider integration tests can be run explicitly
after the local Docker daemon is available:

```sh
AGENT_CONTAINERS_RUN_INTEGRATION=1 \
  uv run --project cli --group test pytest cli/tests/integration -m integration -v
```

The CA test creates only a one-day self-signed test certificate and removes its
image afterward; the OpenCode provider test likewise builds and removes a
disposable image without credentials. Langfuse-enabled image builds have also
been validated manually, but no integration test sends telemetry or uses real
credentials. The normal `just test-cli` suite remains Docker-free.
