---
icon: lucide/git-pull-request-arrow
---

# The `claude-code-ci` container (sketch)

!!! warning "Not integrated yet"

    This page documents `ci-images/claude-code/`, a sketch built during
    design discussion — not yet wired into the required-integration
    checklist in `AGENTS.md` (docs index, `README.md`/`SECURITY.md`,
    `just update-issue-templates`). Treat everything below as a candidate,
    same spirit as `docs/customisation/local-models.md`.

`claude-code-ci` runs [Claude Code](https://claude.com/product/claude-code)
headlessly, one task per container, to fix an issue and open a pull request
without a human approving each tool call. It reuses
[`claude-code`](../container-images/claude-code.md)'s containment
(read-only rootfs, non-root user, minimal capabilities, deny-by-default
egress) and changes three things to fit a CI job instead of an interactive
session: no persistent home volume, a fixed non-interactive permission mode,
and an entrypoint that drives the fix-and-PR workflow instead of dropping
into a shell.

## Why `--permission-mode bypassPermissions`

`run-agent-task.sh` runs `claude -p` with
`--permission-mode bypassPermissions` rather than relying on whatever
`claude`'s own default is. Regardless of what an interactive session
defaults to, a headless run has no terminal for a permission prompt to
appear in — if a tool call needed approval, it would simply fail partway
through the task rather than pausing for one, which turns "fix the issue"
into a silent partial failure. Pinning the mode explicitly also means
behaviour doesn't shift under this image when the CLI's own default changes
between versions.

This is the same trade this project makes everywhere else: don't ask the
thing inside the sandbox to behave, put the walls where it can't reach them
([containment philosophy](../containment-philosophy.md)). The container's
read-only rootfs, dropped capabilities, and egress allowlist are what stand
in for the approval dialog here — not trust in the model's judgement calls.

## Bounding what the agent can do, not just where it can escape to

The threat model for a CI variant is different in emphasis from the
interactive images — see
[Why CI, and how the threat model shifts](index.md) for the full argument.
The short version: escaping the container onto the runner still matters, but
the more likely failure mode is the agent doing something *inside* its own
permissions that's still bad — for the code it's operating on, or for the
repository's own CI configuration — since `bypassPermissions` mode (above)
removes the one gate (a human clicking "allow") that would normally catch
that in an interactive session.

`managed-settings.json` is a first attempt at closing that gap. Claude Code
supports an enterprise-managed policy settings file
(`/etc/claude-code/managed-settings.json`, confirmed present as a path
string in the installed `claude-code` 2.1.235 binary) that sits above
`--permission-mode`, project settings, and anything in `$HOME` in the
settings precedence order — which is also why this file, and not
`$HOME/.claude/settings.json`, is where a hard restriction belongs in this
image. It's `COPY`'d into the Dockerfile at build time, landing on the
read-only rootfs rather than the `--tmpfs /home/claude` mount, so nothing
running inside the container — the agent, an injected instruction from a
malicious issue body, or a prompt trying to talk its way out of a
restriction — can edit or shadow it at runtime.

The current `deny` list targets two things distinct from container escape:

- **Actions that don't break containment but would be bad for the code**:
  force-pushes, deleted remote branches/tags, `git reset --hard`,
  `git clean -f`, `git rebase`, `rm -rf`, and the `curl|sh` /
  `wget|sh` fetch-and-execute pattern a prompt-injected instruction would
  reach for first.
- **Actions that would widen the agent's own footprint for next time**:
  editing `.github/workflows/**` or `.github/CODEOWNERS`, `gh api` (an
  escape hatch around every other `gh` subcommand-specific rule below it),
  `gh secret set/delete`, `gh workflow enable/disable`, `gh repo
  edit/delete`, `gh pr merge/close`, and writing to `.env`/`.env.*` files.

What this deliberately does **not** attempt:

- **Scoping pushes to the branch this job created.** The file is static and
  baked at build time; it has no way to know a given job's generated head
  branch name, so it can't express "may push to `claude/issue-40-123`, may
  not push to `main`." That has to come from the token
  ([below](#scoping-what-the-token-can-reach)) and branch protection, not
  from this file.
- **Being a complete list.** It's a first pass at the shape of the two
  categories above, not an audited denylist. Extend it per pipeline as
  specific tasks show a gap.
- **Verified precedence/matching semantics.** Whether `deny` rules in
  managed settings are actually enforced as hard blocks under
  `--permission-mode bypassPermissions` specifically (rather than only
  under interactive "ask" modes), and whether the `Bash(git push --force
  *)`-style glob matches the way the pattern's shape suggests, is
  unverified. Confirm both before relying on this file for anything that
  matters; see [Known gaps](#known-gaps-in-this-sketch).

## Model provider configuration

There's no browser in this container for an interactive OAuth login, so
`claude-code-ci` is meant to be pointed at a provider entirely through
environment variables — confirmed against the installed CLI binary
(`claude-code` 2.1.235) rather than assumed:

=== "Amazon Bedrock"

    ```sh
    -e CLAUDE_CODE_USE_BEDROCK=1 \
    -e ANTHROPIC_MODEL=<bedrock-model-id> \
    -e AWS_REGION=<region> \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    ```

    Resolve short-lived credentials outside the container (e.g. the CI
    platform's own OIDC-to-AWS-role exchange) and pass them in as already-
    resolved env vars, rather than giving the sandboxed container the
    ability to assume roles itself — keeps the egress allowlist down to
    `bedrock-runtime.<region>.amazonaws.com` instead of also needing `sts.amazonaws.com`
    reachable from inside the sandbox.

=== "Local / self-hosted endpoint"

    Same pattern `docs/customisation/local-models.md` already documents for
    the interactive `claude-code` image:

    ```sh
    -e ANTHROPIC_BASE_URL=http://LOCAL_MODEL_HOST:LOCAL_MODEL_PORT \
    -e ANTHROPIC_AUTH_TOKEN=local-placeholder \
    -e ANTHROPIC_MODEL=LOCAL_MODEL_ID \
    ```

    Add `LOCAL_MODEL_HOST` to the egress allowlist; do not use `localhost` —
    from inside the container that refers to the container itself, not the
    Docker host.

=== "Hosted Anthropic API"

    ```sh
    -e ANTHROPIC_API_KEY \
    ```

    Simplest option if the CI platform's secret store already holds one;
    keep `api.anthropic.com` on the egress allowlist.

Google Vertex (`CLAUDE_CODE_USE_VERTEX=1`, `ANTHROPIC_VERTEX_PROJECT_ID`,
`CLOUD_ML_REGION`) and Microsoft Foundry follow the same shape — confirmed
present in the CLI binary but not written up here since nothing prompted a
concrete config for either yet.

None of this needs an image change: `run-agent-task.sh` doesn't hardcode a
provider, it just execs `claude` and lets these env vars decide.

## Scoping what the token can reach

`run-agent-task.sh` never calls `gh pr merge` — merging stays a human
decision. That's a property of the script, but the token it's handed is a
second, independent control worth setting deliberately rather than relying
on the script alone:

- Use a **fine-grained PAT or, better, a GitHub App installation token**
  scoped to exactly this repository, with **Contents: write** and
  **Pull requests: write** — nothing else. No **Administration**, no
  **Contents: write** on other repos the credential store might otherwise
  default to.
- Leaving merge-adjacent scopes off the token is a second layer, not a
  substitute for **branch protection** (required review, required status
  checks, "include administrators") on the target branch. A token that
  technically could merge is still stopped by branch protection; a script
  that simply doesn't call `gh pr merge` is not a security boundary on its
  own, since anything running inside the container with that token could,
  in principle, call it too. Treat the two as independent layers: script
  behaviour is not a substitute for token scope, and token scope is not a
  substitute for branch protection.
- Prefer a short-lived installation token (minted per job) over a
  long-lived PAT sitting in a secret store indefinitely.

## Build

```sh
docker build --build-context shared=agent-images/shared \
  -t claude-code-ci ci-images/claude-code
```

## Run

```sh
docker run --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp --tmpfs /run --tmpfs /home/claude \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -e AGENT_ALLOWED_EGRESS='api.anthropic.com,github.com,api.github.com,codeload.github.com,registry.npmjs.org,pypi.org,files.pythonhosted.org' \
  -e CI_REPO='owner/repo' \
  -e CI_ISSUE_NUMBER='40' \
  -e GH_TOKEN \
  -e ANTHROPIC_API_KEY \
  claude-code-ci
```

Notes on what changed from `claude-code`'s documented `docker run`:

| Difference | Why |
|---|---|
| `--tmpfs /home/claude` instead of `-v claude-home:/home/claude` | Every job starts from nothing and leaves nothing behind — no shared, persistent home volume for one job's state (or a compromised job's leftovers) to reach the next. Trades away package-cache reuse for reproducibility; add a separate cache-only volume later if cold installs get expensive. |
| No `-v "$PWD":...` project mount | The repository isn't already checked out on the CI runner's filesystem the way an interactive project is — `run-agent-task.sh` clones it itself, from `CI_REPO`, into `/workspace` inside the container. |
| `AGENT_ALLOWED_EGRESS` fixed per pipeline | No human present to choose an allowlist per session; set it once for what the target repo(s) actually need (see `examples/egress-allowlist.txt`). |
| No `-it` | Nothing interactive to attach to; the container runs the task and exits. |

`AWS_REGION`/`AWS_ACCESS_KEY_ID`/etc. or `ANTHROPIC_BASE_URL`/etc. get added
to that `-e` list depending on which provider tab above applies.

## GitHub Actions example

This runs in the **target repository being fixed**, not in
`agent-containers` itself — so it assumes `claude-code-ci` has already been
built and pushed somewhere reachable (a registry), or that a prior step in
the same job builds it from a checkout of this repo. The example below
assumes a published image; swap in a build step if you'd rather not stand up
a registry yet.

```yaml
name: Fix issue with claude-code-ci

on:
  workflow_dispatch:
    inputs:
      issue_number:
        description: Issue number to fix
        required: true
        type: number

jobs:
  fix-issue:
    runs-on: ubuntu-latest
    steps:
      - name: Run claude-code-ci
        env:
          CI_REPO: ${{ github.repository }}
          CI_ISSUE_NUMBER: ${{ inputs.issue_number }}
          # Installation token for a GitHub App scoped to this repo only —
          # Contents: write, Pull requests: write, nothing else. See
          # "Scoping what the CI agent can do" above.
          GH_TOKEN: ${{ secrets.CI_AGENT_GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          docker run --rm \
            --security-opt=no-new-privileges \
            --read-only \
            --tmpfs /tmp --tmpfs /run --tmpfs /home/claude \
            --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
            -e AGENT_ALLOWED_EGRESS='api.anthropic.com,github.com,api.github.com,codeload.github.com' \
            -e CI_REPO -e CI_ISSUE_NUMBER -e GH_TOKEN -e ANTHROPIC_API_KEY \
            ghcr.io/<org>/claude-code-ci:<tag>
```

Branch protection on the target repo (required review, required status
checks) is what actually stops the resulting PR from merging itself —
see above.

## Known gaps in this sketch

- Not smoke-tested. `bash -n` passes on both scripts and
  `managed-settings.json` parses as valid JSON; the Dockerfile hasn't been
  built.
- `managed-settings.json`'s actual enforcement under `bypassPermissions`
  mode and its pattern-matching semantics are unverified — see
  [above](#bounding-what-the-agent-can-do-not-just-where-it-can-escape-to).
- No published image yet, so the GitHub Actions example above is
  necessarily hypothetical about where `claude-code-ci` comes from.
- No package-cache volume — every job re-fetches npm/uv/apt state from
  nothing, which is correct for reproducibility but slower than the
  interactive image.
- `run-agent-task.sh` supports a single repo/issue per container invocation
  only; a "fix N issues" or queue-based workflow would need a wrapper around
  this, not a change to the image itself.
