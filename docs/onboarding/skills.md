---
icon: lucide/sparkles
---

# Agent skills for onboarding

The CLI is deterministic and should remain usable without an AI model. Agent
skills are an optional conversational layer that helps a user gather setup
requirements, create a profile, and understand the plan before Docker changes
are made. A skill should call the CLI or produce its profile as reviewable
artifacts; it should not reimplement profile validation in prose.

## Recommended skills

### `agent-containers-onboard`

This skill guides a first-time setup:

1. Ask which supported agent and model/provider the user wants.
2. Ask about package lists, proxy and certificate inputs, egress hosts,
   gateway requirements, workspace mounts, and an existing home volume.
3. Offer Decant and Langfuse only as explicit experimental opt-ins. Never
   assume either integration or invent a fallback endpoint.
4. Write a TOML profile with credential environment-variable names, never
   credential values.
5. Run `agent-containers validate` and show the resulting `plan`.
6. Ask for explicit confirmation before running `apply`.

The skill should explain that package lists replace the image's optional
defaults, that a profile can reuse a named volume intentionally, and that
equal profile names are isolated per host user by default.

### `agent-containers-maintain`

This skill helps with an existing deployment. It can run `doctor`, explain
plan differences, prepare a profile edit, and summarize rollback implications.
It must not silently rebuild, replace a home volume, broaden egress, or delete
retained images. Changes to credentials remain host-environment operations.

## Safety contract

An onboarding skill should:

- keep secrets out of prompts, profile files, generated image contexts, logs,
  and command-line values;
- preserve deny-by-default egress and require every new endpoint to be named;
- show the profile diff and offline plan before `apply`;
- refuse unsupported agent/integration combinations rather than guessing;
- treat `apply` as a build/state operation and use generated `profiles.sh` for
  launches; and
- report Docker, certificate, gateway, and home-volume failures without
  weakening containment to make progress.

## What skills do not replace

Skills do not replace the CLI's Pydantic validation, Docker hardening, image
documentation, or human decisions about network access and persistent data.
They also do not make Decant or Langfuse non-experimental. A skill can explain
those integrations and prepare an opted-in profile, but the user remains
responsible for deciding what telemetry and session data may leave the host.

The repository currently documents this skill contract; the skill packages and
their host-specific installation instructions should be added and tested as a
separate integration work item.
