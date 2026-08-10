# Security Policy

This repository has [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) enabled.

## Reporting a vulnerability

If you find a containment or isolation weakness in one of these images — an egress allowlist bypass, a capability escalation path, a filesystem escape, or anything else that lets a workload break out of its intended sandbox — please report it privately:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Fill in the advisory form with reproduction steps.

Do not open a public issue for suspected vulnerabilities.

## Scope

In scope: anything that defeats the containment guarantees described in `docs/containment-philosophy.md` (egress control, non-root execution, capability restrictions, filesystem isolation) for `claude-code`, `hermes`, `agent-gateway`, or the shared `egress-allowlist.sh` script.

Out of scope: vulnerabilities in the upstream agent CLIs themselves (Claude Code, Hermes Agent) — report those to their respective maintainers.

## Supported versions

This repository does not maintain multiple release branches; only the latest state of `master` is supported.
