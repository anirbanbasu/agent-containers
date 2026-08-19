---
icon: lucide/shield-check
---

# Containing CI coding agents

!!! warning "Experimental design notes, not end-user documentation"

    This is a thought-gathering document for an unreleased experimental
    feature. It records candidate designs and security considerations; it is
    not supported end-user documentation and must not be construed as a
    deployment guide or security guarantee.

An unattended CI coding agent needs the same runtime containment as an
interactive CLI agent, but it also needs controls over the durable effects it
can cause. A CI runner's isolation is useful, but it is not sufficient on its
own.

The relevant distinction is between an agent running arbitrary commands *in a
disposable workspace* and an agent possessing authority to alter a repository,
cloud account, deployment, or other external system. Filesystem, process, and
network containment address the first. Provider-side authorization and
workflow governance address the second.

## CI runners are not the whole boundary

GitHub-hosted runners execute jobs in clean, ephemeral virtual machines. That
is a valuable outer boundary: an ordinary compromise of one job should not
persist into a later job or reach a developer workstation. It does not make
the job trusted, however. The agent can still execute untrusted repository
code, use any secrets supplied to the job, make permitted network requests,
and leave code or configuration that another system or person later acts on.

Self-hosted runners have a substantially stronger requirement. Untrusted
workflow code can persistently compromise a non-ephemeral runner, including
any shared state or credentials reachable from it. Use a clean, disposable
VM/runner for untrusted agent workloads; do not share a long-lived runner
between repositories or trust levels.

## The threat model

For an interactive coding-agent container, the central question is generally
where a process can reach. The outer container owns the containment boundary:
an agent may request arbitrary shell commands, but a write to an immutable
root filesystem or a connection to an unallowlisted host fails structurally.
The agent's own command policy is not that boundary.

A CI agent has the same runtime-escape threat, and unattended execution makes
the consequences of an escape greater. It also has a second, often more likely
threat: authorised but unwanted behaviour. Examples include:

- pushing an unsafe change or opening a misleading pull request;
- reading or exfiltrating a supplied token, secret, or proprietary source;
- changing workflow, ownership, release, or deployment configuration for a
  later run to execute;
- poisoning a shared cache or artifact for another job; and
- calling a permitted provider API to close, merge, delete, or administer
  repository resources.

This calls for four independent layers.

| Layer | Question | Primary controls |
| --- | --- | --- |
| Runtime containment | Can the workload escape the job or reach unexpected systems? | Hardened container, unprivileged user, read-only rootfs, no runtime socket or broad host mount, restricted egress, resource limits |
| Capability control | Which external effects may the acting identity cause? | Narrow GitHub App, cloud IAM, OIDC, short-lived credentials |
| Workflow governance | Which changes may become trusted or reach protected branches? | Rulesets/branch protection, required checks and approvals, no bot bypass |
| Task policy | Is the job limited to proposing a PR rather than merging, closing, administering, or deploying? | A trusted publisher or policy broker outside the agent |

## Runtime containment remains necessary

The hardened workload pattern remains useful in CI: a non-root process,
read-only root filesystem, explicitly scoped writable storage, dropped Linux
capabilities, no Docker/container runtime socket, and deny-by-default egress.
It limits what an agent-directed command or a malicious dependency can reach
inside the runner.

The agent image should not inherit a checkout from the runner unless that
mount is deliberately scoped. Prefer a fresh clone or a narrowly mounted,
disposable worktree. Do not mount the runner's home directory, SSH agent,
browser state, cloud-credential directory, Docker socket, or a general
workspace. Do not give the agent a persistent home volume across jobs.

Set CPU, memory, disk, PID, wall-clock, log/artifact-size, and model-cost
limits. Resource exhaustion is a containment failure for availability even if
filesystem and network isolation hold.

## Provider permissions are containment of external effects

When a process receives a GitHub token or cloud credential, that credential is
an explicit capability bridge. Network controls can restrict the process to
`api.github.com`, but cannot distinguish a permitted HTTPS call that creates a
pull request from one that performs another operation the credential allows.

Use a dedicated GitHub App rather than a personal credential when practical.
Mint a short-lived installation token per job, restrict it to the target
repository, and grant only permissions required by the trusted component that
uses it. A provider-enforced permission is a real control; an instruction not
to call a command is not.

Fine-grained permissions do not necessarily express the desired task-level
policy. In particular, GitHub's pull-request merge API requires `Contents:
write`; an identity that needs `Contents: write` to push an agent branch can
therefore have nominal merge API capability as well. Branch protections or
rulesets must make merging impossible without the required checks and human
approval, and the automation app must not be granted a bypass.

## Command denylists are defence in depth, not the root of trust

An agent-managed settings file that blocks `gh pr merge`, destructive Git
commands, or edits to workflow files is useful as friction and can prevent
common mistakes. It is not a complete authorization boundary for a process
that can execute arbitrary shell commands and holds a credential. Alternate
clients, alternate API routes, Git protocol operations, command variations,
and future CLI behaviour can bypass a static command-oriented policy.

Similarly, a hostname allowlist is not an API authorization system. It is
valuable for limiting destinations and exfiltration routes, but it cannot
inspect or constrain action semantics inside authenticated TLS traffic.

When a task must allow only a subset of provider actions, enforce that subset
with a provider policy or an independently trusted intermediary. Do not rely
on the agent's launch script or a CLI command denylist as the sole control.

## Preferred split-authority architecture

The strongest general pattern gives the agent no direct write authority to the
repository provider. It splits the workflow into an untrusted reasoning phase
and a small, trusted publication phase:

```text
Untrusted issue/comment + repository
                |
                v
Agent container: read-only repository access,
no provider-write credential, narrow egress
                |
          untrusted patch
                |
                v
Trusted publisher: fresh checkout, validates patch
and allowed paths, creates a unique agent branch
and opens one pull request
                |
                v
Ruleset + automated checks + required human review
                |
                v
Separate merge authority
```

The publisher is a narrow, deterministic component. It accepts an agent
output as untrusted data, rather than executing it. It should:

- start from a fresh checkout of an expected base revision;
- apply a patch with safe Git configuration and no agent-controlled hooks;
- validate all identifiers passed to provider commands and use a unique,
  job-scoped branch name;
- reject or route sensitive paths for manual handling, including workflow,
  ownership, release, deployment, and credential-policy configuration;
- run only fixed validation steps in an environment separate from the agent;
- create at most the branch and pull request described by the job; and
- hold the short-lived write credential only for that publication step.

The publisher can itself have `Contents: write`; the security improvement is
that it is much smaller than the agent, does not interpret natural-language
instructions, and does not execute arbitrary agent-selected commands.

Merging remains a separate authority. Protected-branch rules should require
the appropriate reviews and checks, prevent force pushes and deletion, and
not list the agent or publisher app as a bypass actor.

## Treat inputs, code, and outputs as untrusted

Issue bodies, comments, pull-request text, branch names, commit messages, and
the repository's content are untrusted input. They can contain prompt
injections and, if interpolated into shell or workflow expressions, conventional
script injections. A privileged agent job should therefore not be triggered
directly from arbitrary public comments. Use a maintainer-applied label, an
allowlisted actor, or an explicitly reviewed dispatch event.

The checked-out repository is also untrusted executable content. Package
scripts, build tools, Git hooks, CI configuration, and development-tool
configuration can all be mechanisms for a malicious change to execute later.
The fact that the agent proposes a change through a pull request does not make
that change safe; review and protected-branch gates still decide whether it is
accepted.

Agent-produced patches, artifacts, cache entries, and logs are untrusted as
well. Avoid sharing writable caches between trust levels. Never execute an
artifact from an agent phase in a credentialed publisher or deployment phase
without a narrow, purpose-built validation step.

## Secrets, model access, and egress

No secret should enter the agent phase unless the task cannot function without
it. In particular, keep deployment credentials, package-publishing tokens,
signing keys, broad cloud credentials, and long-lived personal access tokens
outside it. Resolve temporary credentials in a trusted outer workflow, rather
than giving the agent permission to mint or assume broader credentials.

A hosted model endpoint is also an external data boundary. Source code,
issue content, logs, and any accessible repository material may be included in
model requests. The selected provider, account policy, and egress configuration
must be acceptable for that disclosure. An egress allowlist limits
destinations; it does not decide which data is safe to send to an allowed
destination.

## Operational checklist

- Run agent jobs in clean, ephemeral runners; require this for self-hosted
  environments.
- Use the hardened outer-container controls and remove access to runtime
  sockets, host homes, SSH agents, and broad mounts.
- Keep the agent's provider token read-only or absent; use a separate,
  short-lived app token in a trusted publisher where possible.
- Enforce default-branch rulesets, required current approvals, required
  checks, and no automation bypass.
- Do not directly privilege jobs triggered by untrusted issue, comment, or
  pull-request content.
- Treat repository code, agent patches, artifacts, logs, and caches as
  untrusted across phase boundaries.
- Keep secrets and deployment authority out of the agent phase.
- Bound resources, execution time, model spending, logs, and artifacts.
- Record task source, image digest, model/configuration, acting credential,
  patch hash, and resulting pull request for auditing and incident response.
- Give agent branches an expiry and retain an operator kill switch.

## Principle

An unattended agent may reason and propose changes freely inside a disposable
sandbox. Only a small, independently trusted system should convert its output
into durable external effects.

## Pre-built public CI images

Publishing reviewed CI-agent images to a public registry is a useful part of
this model. A consuming repository should pull a known image pinned by digest,
for example:

```yaml
image: ghcr.io/<organisation>/claude-code-ci@sha256:<digest>
```

It should not need to build the agent environment as part of its own workflow.
That separates the trusted agent runtime from the untrusted target repository
and task input, avoids target-repository-controlled Docker build contexts or
build-time logic, and makes the deployed CLI, operating-system packages, and
agent configuration reproducible.

Pre-built images also allow a central release process to perform image review,
vulnerability scanning, provenance and signature publication, SBOM generation,
and prompt rebuilds when base images or agent dependencies require security
updates. A digest pin is essential: a mutable image tag alone does not identify
the exact reviewed image a CI job will run.

Public pre-built images do not replace runtime containment. The consuming job
must still use the documented hardened launch configuration, restrict egress,
avoid Docker sockets and broad mounts, keep provider-write credentials outside
the agent phase, and enforce protected-branch governance. Images must never
contain credentials, tokens, private keys, user authentication state, or other
per-user persistent configuration.

## References

- [GitHub Actions secure use reference](https://docs.github.com/en/actions/reference/security/secure-use?learn=getting_started&learnProduct=actions)
- [GitHub Actions script injections](https://docs.github.com/en/actions/concepts/security/script-injections)
- [GitHub App installation access tokens](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)
- [GitHub pull request merge API permissions](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)
- [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [Project containment philosophy](containment-philosophy.md)
