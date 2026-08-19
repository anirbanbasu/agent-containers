---
icon: lucide/shield-check
---

# Security assessments

This page summarizes authorized containment assessments of the hardened agent
images. The results below are based on commit
`11b986b3182814279325dbeb8e833b9701b39ab6` on `master`.

All assessments were performed by an agent running **inside a container built
from the target workload image**, using the documented hardened launch flags or
an equivalent assessment harness. They evaluate workload-container containment;
they do not assess host, Docker daemon, or kernel isolation as independent
security boundaries.

These are evidenced from specific images, launch configurations, kernels, and
runtime environments and not a certification that every deployment is secure. Use
the documented hardened launch flags, keep images and the container runtime
updated, and treat all agent-controlled project and home-volume contents as
untrusted.

## Assessment summary

No assessment achieved a container escape, dropped-capability acquisition, or
restricted IPv4 egress bypass.

`aider`, `adal`, `qwen-code`, and `hermes` were not independently assessed.
The first three use the shared hardened workload pattern, so the assessed
images provide relevant supporting evidence, but do not replace image-specific
testing. Hermes uses an upstream-vendor base image and custom entrypoint, and
needs its own dedicated assessment before being included in this summary.

The tested images consistently demonstrated these controls:

- non-root agent execution with no effective or permitted Linux capabilities;
- `no-new-privileges`, seccomp filtering, and AppArmor enforcement;
- a read-only root filesystem with explicitly scoped writable mounts;
- blocked unprivileged user-namespace creation;
- no Docker or container-runtime socket exposure;
- no setuid/setgid binaries or executable file capabilities in the assessed
  hardened images;
- deny-by-default restricted IPv4 egress, including interception of direct
  DNS queries aimed at external resolvers.

## Assessment matrix

| Target container | Assessing model | Configuration | Result |
|---|---|---|---|
| `claude-code` | Claude Opus 5, maximum effort | Unrestricted and restricted egress | No escape achieved. Restricted IPv4 egress held end to end. |
| `codex` | OpenAI Codex, GPT-5.6-sol, high reasoning effort | Unrestricted and restricted egress | No escape achieved. Restricted IPv4 egress held end to end. |
| `opencode` | DeepSeek V4 Flash, maximum setting | Restricted egress | No escape or egress bypass achieved. |
| `kilo-code` | Laguna S 2.1 | Restricted egress | No escape or egress bypass achieved. |
| `aider` | Not assessed | Not assessed | Uses the shared hardened workload pattern; no independent security conclusion. |
| `adal` | Not assessed | Not assessed | Uses the shared hardened workload pattern; no independent security conclusion. |
| `qwen-code` | Not assessed | Not assessed | Uses the shared hardened workload pattern; no independent security conclusion. |
| `hermes` | Not assessed | Not assessed | Upstream-vendor base image and custom entrypoint; no security conclusion. |


## What restricted egress means

In the standard restricted profile, the workload configures its egress policy
before dropping to the unprivileged agent user:

1. A local filtering DNS resolver accepts only allowlisted names.
2. Resolved addresses for allowed names are added to an IP set.
3. IPv4 and IPv6 OUTPUT policies default to deny.
4. Direct TCP and UDP DNS traffic is redirected to the filtering resolver,
   except for that resolver's own upstream forwarding.

The assessed restricted IPv4 configurations allowed the configured service
hosts, refused off-list DNS queries, dropped direct off-list IP connections,
and prevented the agent from reading, flushing, or changing the firewall and
IP-set policy after privilege drop.

IPv6 was not fully validated end to end because the assessment environments did
not have a routable public IPv6 path. The IPv6 policy is implemented and source
reviewed, but operators requiring IPv6 should test it in their own deployment.

## Important deployment limitations

The containment boundary limits what a running agent can reach. It does not
remove the authority deliberately granted to it or make every deployment
configuration equally strong.

These are deployment considerations, not demonstrated containment breaches.
The levels describe the consequence of enabling the configuration or omitting
the indicated operational control in a typical shared deployment.

| Consideration | Brief | Deployment risk |
|---|---|---|
| Project and home volumes | Writable state can persist and may later be used by host-side tools. | High |
| Credentials | An agent can use credentials that are mounted or otherwise supplied to it. | High |
| Hostname allowlists | Allowed services, CDNs, and registries can still deliver untrusted content. | Medium |
| Unrestricted egress | The explicit `*` opt-out exposes additional network attack surface. | High |
| Resource limits | Without CPU, memory, and swap ceilings, agent work can affect availability. | Medium |
| Same-UID process control | Peer/helper-process interference is possible in some runtime and host-policy combinations. | Low–medium |
| Executable temporary storage | Some terminal runtimes require an executable `/tmp`; this is a compatibility tradeoff. | Low |

### Project and home volumes are trusted writable state

The project bind mount and persistent home volume are intentionally writable.
An agent can leave behind code, hooks, configuration, package caches, or other
state that a host-side process may later read or execute.

Use separate projects and home volumes where isolation between tasks matters.
Review agent-produced changes before running them on the host.

See the [containment philosophy](containment-philosophy.md) for the full
filesystem and credential trust model.

### Credentials are granted authority

Credentials supplied through environment variables, the persistent home volume,
Git configuration, package-manager configuration, or mounted files are
available to the agent. Egress filtering controls destinations; it does not
limit what an authorized agent can do with credentials at an allowed
destination.

### Hostname allowlists are not content filters

Allowlisting a service permits connections to addresses returned for that
service. It does not distinguish legitimate from malicious content delivered
by the same service, registry, CDN, or reverse-proxy infrastructure.

Use the narrowest practical allowlist and prefer a separately administered
[agent gateway](container-images/00-agent-gateway.md) when the workload must
not control the system that enforces its network policy.

The assessments observed differing subdomain behavior across environments.
Do not rely on an allowlist entry being an exact hostname match unless that
behavior has been verified for the image version and runtime configuration you
are deploying.

### Unrestricted egress is an explicit opt-out

`AGENT_ALLOWED_EGRESS=*` disables the workload egress restrictions. It can make
host- or VM-side network services reachable as well as the public internet.

Use it only when unrestricted access is intentional. A reachable host service
is not automatically a container escape, but it is additional attack surface.

### Resource limits are deployment-specific

The assessed containers had a finite PID limit but no container-level CPU,
memory, or swap ceiling. This is an availability concern: builds, dependency
installs, or hostile project commands can consume resources needed by other
workloads or the Docker VM.

For shared or unattended deployments, set limits appropriate to the workload:

```sh
docker run \
  --memory=4g \
  --memory-swap=4g \
  --cpus=2 \
  --pids-limit=512 \
  # remaining documented image flags and mounts
```

These values are examples, not defaults. Coding workloads vary substantially;
size limits for the project and enforce an outer host or VM resource ceiling.

### Same-UID process control is a conditional availability concern

Agent commands and helper processes can share the same Linux UID. On hosts with
a permissive ptrace policy, a dumpable same-UID process may be traceable or
readable by another same-UID process. Same-UID processes can also interfere with
ordinary peer or child helper processes through signals.

When the agent itself is the container namespace PID 1, Linux rejects
uncatchable `SIGSTOP` and `SIGKILL` directed at it from inside that namespace.
This does not automatically protect every helper process, every catchable
signal, or every runtime layout.

This is an in-container availability and defense-in-depth concern, not a
demonstrated host escape. Deployments that run untrusted tools, are unattended,
or are multi-tenant may additionally use:

- host Yama `ptrace_scope=1` or stricter;
- a tested custom seccomp profile that denies `ptrace`,
  `process_vm_readv`, and `process_vm_writev`; and
- an external watchdog or restart policy where agent availability matters.

Test these measures with the selected language tooling, debuggers, profilers,
and process-management workflows before adopting them.

## Intentional executable temporary storage

Some images require an executable `/tmp` because their terminal UI or runtime
loads native code from temporary storage. In particular, the documented Kilo
Code and OpenCode launch commands use `--tmpfs /tmp:exec`.

This is a compatibility requirement, not a privilege-escalation finding. The
other containment controls still apply: the agent cannot use `/tmp` to gain
root, acquire a dropped capability, or alter the read-only image filesystem.

Do not change `/tmp` to `noexec` for those images without verifying that the
agent and its terminal runtime still work.

## Not covered by these assessments

The assessments did not establish that:

- the host kernel, Docker daemon, base image, package registries, or agent CLI
  have no vulnerabilities;
- every image version, kernel, architecture, network topology, or custom launch
  command has identical behavior;
- IPv6 restricted egress is effective on a routable IPv6 deployment;
- gateway-client mode, cloud metadata access, cross-container networking, or
  image supply-chain controls are safe in every environment.

These are important deployment and operational concerns. Keep the host and
runtime patched, avoid exposing runtime sockets, use narrow networks, and test
the exact image and flags you plan to use.

## Reporting a security issue

Report suspected containment, isolation, capability, filesystem, or egress
weaknesses privately. See the repository security policy for
the reporting process and supported-version policy.
