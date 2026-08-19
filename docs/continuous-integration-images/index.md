---
icon: lucide/git-pull-request-arrow
---

# Continuous integration images

!!! warning "Sketch, not integrated yet"

    This section documents `ci-images/`, work-in-progress designs — not yet
    wired into the required-integration checklist in `AGENTS.md` (docs
    index, `README.md`/`SECURITY.md`, `just update-issue-templates`). See
    [`claude-code`](claude-code.md) for the first concrete example.

## Why look into this

Every other image in this project ([`agent-images/`](../container-images/index.md))
assumes a human is present for the whole run: watching the terminal,
approving or denying individual tool calls, and free to interrupt if
something looks wrong. That assumption is doing real work — it's a second
safety layer sitting on top of the container's own containment, and it's the
reason `--permission-mode` defaults to asking rather than acting.

A CI trigger like "fix issue 40 on this repository and open a PR" removes
that layer on purpose. Nobody watches a CI job turn by turn; the point of
running it in CI is that nobody has to. That shifts real weight onto the
container: whatever the human's presence used to catch now has to be caught
structurally, by the image and its configuration, or not at all. Worth
designing for deliberately rather than inheriting unexamined from the
interactive images.

## How the threat model shifts

The interactive images' central concern, laid out in
[the containment philosophy](../containment-philosophy.md), is containment:
don't let the agent process escape its sandbox and reach the host, the
network, or another project beyond what's explicitly allowed. That concern
doesn't go away for a CI variant — if anything it matters more, since a CI
runner is more likely to be shared infrastructure with other jobs' secrets
and broader reach than a single developer's laptop. Everything
`ci-images/claude-code` inherits from `agent-images/claude-code` (read-only
rootfs, non-root user, minimal capabilities, deny-by-default egress) is
still doing exactly that job, unchanged.

What's genuinely different is what becomes the *dominant* risk once the
human-in-the-loop layer is gone. Escaping the container is one failure mode;
the other, arguably more likely one, is the agent doing something entirely
*inside* its permitted boundary that's still wrong — for the code it's
editing, or for the repository's own configuration — because nothing was
there to notice and say no before it happened. Two things follow from that:

- **The acting identity carries real, standing authority.** An interactive
  session's blast radius is mostly the project directory bind-mounted for
  that one run. A CI job acts as a credentialed identity — a git author, a
  `gh`-authenticated principal — that pushes commits and opens PRs other
  systems and people will trust and act on. Scoping what that identity is
  authorized to do (see
  ["Scoping what the token can reach"](claude-code.md#scoping-what-the-token-can-reach))
  matters in a way it doesn't for a session where the only lasting effect is
  files changed on a bind-mounted directory a human reviews before doing
  anything with them.
- **The task itself is often untrusted input.** "Fix issue 40" means the
  agent's instructions come from an issue body — text anyone who can open or
  comment on an issue can influence — not from a person typing directly into
  the session. Prompt injection isn't a new concern this project's
  containment philosophy hasn't already named (see "known limitations" in
  that page), but a CI trigger is a more exposed instance of it than an
  interactive session where the operator and the instruction-giver are the
  same person.

The practical consequence: in addition to containment, a CI image needs an
explicit answer to "what is this agent allowed to do, and to touch, given
that nobody's watching turn by turn and the task itself might be hostile."
Token scope and branch protection answer that from *outside* the container.
`ci-images/claude-code/managed-settings.json` is a first attempt at
answering it from *inside* — a build-time, read-only-rootfs-backed denylist
of actions that stay inside the sandbox but would still be bad for the code
or the repo's CI configuration, sitting above `--permission-mode` in Claude
Code's own settings precedence so the agent can't edit or shadow it at
runtime. See
["Bounding what the agent can do, not just where it can escape to"](claude-code.md#bounding-what-the-agent-can-do-not-just-where-it-can-escape-to)
for what it covers, what it deliberately doesn't, and what's still
unverified about it.
