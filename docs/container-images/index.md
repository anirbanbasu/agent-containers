---
icon: lucide/table-properties
---

# Summary of container images

This project ships three container images, all hardened by default
(non-root user, read-only root filesystem, minimal capability set, deny-all
egress unless configured otherwise): two workload images that each run a
different coding/agentic CLI, and a network-tunnelling image that lets you
move egress enforcement out of either workload entirely.

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

## Hermes

[`hermes`](hermes.md) packages [Hermes Agent](https://github.com/NousResearch/hermes-agent),
Nous Research's self-improving, multi-provider agentic CLI, with the same
network-containment posture as `claude-code` — the same in-container
allowlist or `agent-gateway` gateway-client mode, applied to a different
workload.
