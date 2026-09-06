# Docker integration tests

No runtime integration tests exist yet. This directory is reserved for explicit,
opt-in tests against disposable Docker resources. Unit and packaging tests must
remain runnable without Docker.

Required coverage includes all four agent adapters, read-only root filesystems,
unprivileged execution, populated persistent homes, home-tool precedence warnings,
proxy/CA and gateway routing, Decant access, and update/rollback failure recovery.
Do not use real account logins or weaken containment to make tests pass.
