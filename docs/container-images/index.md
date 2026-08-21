---
icon: lucide/table-properties
---

# Summary of container images

This project ships ten container images, all hardened by default
(non-root user, read-only root filesystem, minimal capability set, deny-all
egress unless configured otherwise): eight workload images that each run a
different coding/agentic CLI, a network-tunnelling image that lets you move
egress enforcement out of a workload entirely, and a read-only volume bridge.

## Shared Python-and-Node workload implementation

`adal`, `aider`, `claude-code`, `codex`, `kilo-code`, `opencode`, and `qwen-code` remain
independently buildable images, but share their required Node.js,
containment, gateway-client, and cloudflared setup through
`agent-images/shared/install-workload-base.sh`. They also share the
root-only network setup and non-root handoff through
`agent-images/shared/workload-entrypoint.sh`. Each image still owns its
CLI package, persistent-home layout, unprivileged user, optional package
lists, and any agent-specific initialization; this is source-level sharing,
not a separately published base image.

## Shell shortcuts

The fully spelled-out `docker run` commands are the reference invocations.
For repeat use, [set up shell functions](../customisation/shell-shortcuts.md) that preserve
each image's hardened profile while launching an agent from the current
project directory.

## Custom configuration files

Each agent has a different configuration path inside its persistent home
volume. See [custom configuration files](../customisation/custom-configuration.md) for the
agent-specific configuration guidance for AdaL, Aider, Claude Code, Codex,
OpenCode, Kilo Code, Qwen Code, and Hermes.

## Network tunnelling

[`agent-gateway`](00-agent-gateway.md) is a small, disposable sibling container
that owns the egress allowlist on behalf of a workload container, which
tunnels all of its outbound traffic to it over SSH instead of enforcing an
allowlist on itself. This means a compromise of the workload gives an
attacker no access to the rules governing its own network egress. It runs
equally well as a same-host sibling or on a genuinely separate machine —
same image, same mechanism, only reachability differs.

## Volume bridge

[`volume-bridge`](01-volume-bridge.md) is a read-only WebDAV sidecar for named
agent-home volumes. It lets a trusted Docker operator expose selected volume
paths to a host reader without placing the agent and consumer on the same Docker
network. This supports host-side session-analysis tools as well as interactive
inspection.

## AdaL

[`adal`](adal.md) packages SylphAI's AdaL terminal coding agent. Its
browser-based sign-in, persistent settings/session state, MCP OAuth state,
skills, and plugins stay in the mounted AdaL home volume; direct model
providers and each optional integration require explicit egress.

## Aider

[`aider`](aider.md) packages Aider's git-native terminal pair-programming
workflow. It pins the Python CLI, keeps its configuration and optional
credential state in a persisted home volume, and disables update checks,
analytics, and runtime Playwright installation by default.

## Claude Code

[`claude-code`](claude-code.md) packages the Claude Code CLI in a hardened
container, with either an in-container egress allowlist (the default) or
opt-in gateway-client mode via `agent-gateway` (above) for stronger
isolation.

## Codex

[`codex`](codex.md) packages the OpenAI Codex CLI in the same Python-and-Node
workload environment as `claude-code`. It supports API-key authentication and
the CLI's device authorization flow, while keeping its configuration and
authenticated state in a persisted home volume.

## Hermes

[`hermes`](hermes.md) packages [Hermes Agent](https://github.com/NousResearch/hermes-agent),
Nous Research's self-improving, multi-provider agentic CLI, with the same
network-containment posture as `claude-code` — the same in-container
allowlist or `agent-gateway` gateway-client mode, applied to a different
workload.

## Kilo Code

[`kilo-code`](kilo-code.md) packages [Kilo CLI](https://kilo.ai/cli), the
open-source, provider-neutral terminal coding agent. Its documentation starts
with Kilo's hosted gateway, then explains how to add only the direct model
provider, MCP server, source-control host, and package registry a user selects.

## OpenCode

[`opencode`](opencode.md) packages OpenCode, a provider-agnostic terminal
coding agent, with the same standard containment and gateway-client options.
Its documentation starts with the OpenCode and model-catalog hosts, then
explains how to add only the model-provider endpoints a user configures.

## Qwen Code

[`qwen-code`](qwen-code.md) packages Qwen Code, an open-source terminal
coding agent that supports Qwen, OpenAI-compatible, Anthropic, Gemini, and
local model providers. Its own optional Docker/Podman sandbox is disabled:
the hardened outer container is the security boundary, and is deliberately
not given access to a container runtime.
