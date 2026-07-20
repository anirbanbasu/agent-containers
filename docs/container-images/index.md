---
icon: lucide/table-properties
---

# Summary of container images

This project ships two container images, both hardened by default
(non-root user, read-only root filesystem, minimal capability set, deny-all
egress unless configured otherwise): a workload image that runs a coding
agent, and a network-tunnelling image that lets you move egress enforcement
out of that workload entirely.

## Network tunnelling

[`agent-gateway`](agent-gateway.md) is a small, disposable sibling container
that owns the egress allowlist on behalf of a workload container, which
tunnels all of its outbound traffic to it over SSH instead of enforcing an
allowlist on itself. This means a compromise of the workload gives an
attacker no access to the rules governing its own network egress. It runs
equally well as a same-host sibling or on a genuinely separate machine —
same image, same mechanism, only reachability differs.

## Claude Code

[`claude-code`](claude-code.md) packages the Claude Code CLI in a hardened
container, with either an in-container egress allowlist (the default) or
opt-in gateway-client mode via `agent-gateway` (above) for stronger
isolation.
