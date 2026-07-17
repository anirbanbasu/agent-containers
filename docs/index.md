---
icon: lucide/shield-check
---

# Why hardened containers for coding agents?

A command-line coding agent is valuable precisely because it can read
files, run a build, install packages, and shell out to fix what is broken,
all without a human typing the commands directly. That same list of
capabilities is also the entire problem. Each capability is a door, and the
agent does not always know which door it has just opened. A prompt buried
in a scraped web page, a typosquatted package pulled in during a routine
install, or simply an ordinary bad decision by the model — any of these can
turn helpful automation into full run of a home directory, stored
credentials, and the open internet, because on a bare host that is
precisely the access an agent already has to work with.

## The bargain nobody explicitly agreed to

Running an agent directly on a machine implicitly accepts the following:

- it can read anything the user account can read: SSH keys, cloud
  credentials, browser profiles, and every other project on the machine
- it can write and delete just as freely, at whatever speed it happens to
  be operating
- it can talk to any host on the internet, so a bad instruction does not
  stay local: data can be exfiltrated, malicious payloads fetched, or a
  compromised process can report back to its controller
- a single permission prompt, approved on the fifth "yes" of a long
  session, is the entire boundary between a contained mistake and an
  uncontained one

None of this reflects a flaw in any particular agent. It is the shape of
the capability itself: a language model directing a real shell, on a real
filesystem, with real network access. As these agents become more
autonomous and longer-running, a human has fewer opportunities to catch a
bad step before it executes.

## Containment is the answer

This project's answer is not to ask for more careful prompting. It is to
make the blast radius a property of the environment rather than of the
model's judgement. Each image runs as a non-root user, on a read-only root
filesystem, with Linux capabilities dropped to only what the entrypoint
actually needs, and outbound network access **denied by default** and
opened only against an explicit allowlist. None of this asks the agent to
behave well; it limits what misbehaviour can reach in the first place. A
sandbox that depends on the thing inside it choosing to respect its own
walls is not a sandbox.

The diagram below shows where each of those constraints sits relative to
the host machine, the container, and the network beyond it.

The coding agent runs inside the container as an unprivileged process.
Only the project directory chosen for the current task crosses into the
container, by way of an explicit bind mount; the rest of the host
filesystem, including credentials and other projects, has no path in.
Outbound traffic follows the same principle: every connection is checked
against the allowlist before it reaches the internet, and anything not
explicitly permitted is dropped.

## Not just Claude Code

The risk profile described above is not specific to any one agent. It is
simply what a command-line, tool-calling language model looks like once it
is given a terminal. Claude Code is where this project started, but the
pattern — restricted by default, hardened at the container boundary,
configurable rather than permissive — is meant to generalise to whatever
other coding agents end up living in this repository next.
