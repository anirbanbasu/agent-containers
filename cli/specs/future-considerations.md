# Future considerations

This document records directions considered while developing the onboarding
CLI specification and explicitly not pursued for the initial scope, together
with the reason. It differs from the "remains to be specified" markers in the
other documents: those are decisions not yet made; these are decisions to
defer, made deliberately. Listing something here does not authorize
implementation later without going through the normal approval process in
`README.md`, and does not commit the project to ever adopting it.

## Application-layer (L7) egress policy granularity

Some comparable tools enforce egress at the HTTP method/path level and can
reload policy without restarting the sandbox. The current and planned model
enforces at the DNS/IP allowlist level only (`egress-allowlist.sh`, and the
gateway's equivalent). Method/path-level filtering would materially increase
the size and complexity of the enforcement code for a benefit that is
narrower than it first appears: an allowed host that is itself compromised or
malicious at a specific path is a smaller share of the threat model this
project targets than an agent reaching a host it should never have been able
to resolve at all. Not pursued for the initial scope.

## Audited break-glass egress overrides

Some comparable tools support temporarily opening a specific denied
destination with a mandatory reason and expiry, logged for later review,
rather than only a static pre-launch allowlist. This is a reasonable idea for
a future iteration once the base allowlist and gateway model are stable, but
adds a new consequential-decision surface (who can grant an override, how
expiry is enforced, what happens if it is forgotten) that is out of scope
until the core network journeys are implemented and in use. Not pursued for
the initial scope.

## Live interactive allow/deny prompts

Some comparable tools can show a desktop notification for a blocked outbound
connection from a running session and let a human approve or deny it in real
time, rather than only defining policy before launch. This is a different
interaction model from everything else in `user-journey.md`, which treats
network access as reviewed and configured before a session starts, not
negotiated during one. It would also require a persistent, trusted
host-side process to receive and act on prompts, which is new infrastructure.
Not pursued for the initial scope.

## Cluster and multi-host orchestration

This project's purpose is local, single-user containment for interactive
coding-agent sessions on one machine, not a cluster control plane. Kubernetes
support, multi-host scheduling, and centralized fleet management are out of
scope, not merely deferred — they would change what this project is for.
This applies to container-runtime backend support too: see
[issue #29](https://github.com/anirbanbasu/agent-containers/issues/29) for
local, non-cluster backend alternatives to Docker, which is a deferred
workstream, unlike this section.

## Stronger-than-container isolation (microVM)

A microVM boundary (separate guest kernel, e.g. via `krun`/libkrun,
Virtualization.framework, or `urunc`) is a stronger isolation primitive than
namespaces/capabilities/seccomp on a shared kernel, and `docs/containment-philosophy.md`
already records that this project considered and declined it in favour of
lightweight containers. Comparable tools show the approach is viable on both
Linux and macOS today, but it is a platform and packaging change with a real
cost, not a configuration option. Worth revisiting if the lightweight-container
model turns out to be insufficient for a specific documented threat, not
worth adopting speculatively. Not pursued for the initial scope.
