---
icon: lucide/wand-sparkles
---

# Customisation

The fully spelled-out `docker run` commands on each image's page are the
reference invocations — everything else here builds on top of them without
weakening the hardened defaults. These pages cover the ways to adapt a
container's launch, configuration, and model provider to your own setup.

## Custom configuration files

Each workload image keeps configuration and runtime state in its persistent
home volume, and not every configuration file is safe to bind-mount as a
read-only input. [Custom configuration files](custom-configuration.md)
explains the difference between input-only files, agent-owned mutable state,
and whole configuration directories, and which pattern applies to each case.

## Local models

Pointing an agent at a local or self-hosted model server is a per-agent,
per-server combination that this repository cannot verify exhaustively.
[Local models](local-models.md) is a test plan and a set of **candidate**
configurations — a record of what to test and how, not a set of proven
recipes — for routing an agent's traffic to llama.cpp, Ollama, vLLM, LM
Studio, or another local server instead of a hosted provider.

## Shell shortcuts

The reference `docker run` commands are deliberately explicit about every
containment flag, which makes them tedious to retype. [Shell
shortcuts](shell-shortcuts.md) shows how to wrap each one in a shell function
that mounts the current directory and starts the matching image, while
keeping the image-specific flags in one auditable place.
