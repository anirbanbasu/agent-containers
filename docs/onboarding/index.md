---
icon: lucide/rocket
---

# Onboarding

The onboarding section explains how to turn the repository's hardened Docker
images into a repeatable setup for a person, project, or team.

The [`agent-containers` CLI](cli.md) is the deterministic foundation. It
creates and validates TOML profiles, builds user-scoped images, records
deployment state, and maintains profile-specific shell shortcuts. It does not
need an AI agent and does not launch an agent while applying a profile.

For users who want conversational setup, [agent skills](skills.md) can guide an
agent through the same workflow. Skills are an interaction layer around the
CLI, not a replacement for its validation, explicit egress policy, or human
confirmation before Docker changes.

## Suggested path

1. Read the [CLI guide](cli.md) and install the tool.
2. Create a profile interactively, or ask a configured setup skill to gather
   the requirements and write one for review.
3. Run `validate` and `plan` before `apply`.
4. Source the generated `profiles.sh` shortcut after applying the profile.
5. Use `doctor` and `rollback` for maintenance; keep image-specific runtime
   details in the [container image documentation](../container-images/index.md).

The CLI and skills preserve the project's containment defaults: credentials are
provided at runtime by environment-variable reference, egress remains
deny-by-default, and profile-specific changes are visible before they are
applied.
