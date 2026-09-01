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
  matters; see [What is left before this stops being a sketch](#what-is-left-before-this-stops-being-a-sketch).

## The three independent axes

`run-agent-task.sh` is controlled by three independent environment-variable
axes rather than one big mode flag, so a caller only sets what's actually
relevant to their pipeline:

| Variable | Values | Default | What it controls |
|---|---|---|---|
| `CI_OUTPUT_MODE` | `pr`, `report` | `pr` | `pr` clones/uses the workspace, runs the task, commits, pushes a branch, and opens a PR/MR. `report` runs the task and prints the diff and transcript — never touches the remote, and a no-op diff is not a failure. |
| `CI_WORKSPACE_MODE` | `clone`, `mounted` | `clone` | `clone` has the script clone `CI_REPO` itself into `/workspace`. `mounted` skips cloning — the caller has already populated `/workspace` (e.g. a bind mount, or a prior step in the same CI job), and `CI_REPO` is derived from that workspace's `origin` remote if unset. |
| `CI_PROVIDER` | `github`, `gitlab` | *(none)* | Which CLI (`gh` or `glab`) and API shape to use for cloning, looking up the default branch, and opening a PR/MR. Only required when a provider action is actually needed — see the matrix below. |

Every combination is valid; here's what each one actually requires:

| `CI_WORKSPACE_MODE` | `CI_OUTPUT_MODE` | `CI_REPO` | `CI_PROVIDER` | Token |
|---|---|---|---|---|
| `clone` | `pr` | required | required | required (`GH_TOKEN` or `GITLAB_TOKEN`, matching `CI_PROVIDER`) |
| `clone` | `report` | required | required | required — cloning a private repo still needs auth even though nothing gets pushed |
| `mounted` | `pr` | optional (derived from `origin` if unset) | required | required |
| `mounted` | `report` | not needed | not needed | not needed — this is the fully credential-free combination, see [Testing locally](#testing-locally) below |

`CI_TASK` (the full prompt for `claude -p`) is required in every combination
— there is no default prompt derived from an issue number or anything else.
Older versions of this image had a `CI_ISSUE_NUMBER` parameter for that;
it's gone. If a caller's task is "fix issue #40", they build that sentence
into `CI_TASK` themselves — the container already has `gh`/`glab` available
*inside* the task run, so the agent can look the issue up itself
(`gh issue view 40`) the same way it follows any other instruction in the
prompt. This also generalizes to instructions a single numeric env var
never could: "fix issues 40, 41, and 44", "fix whatever's labeled `bug` and
unassigned", etc.

`CI_TITLE` (optional) sets the commit/PR/MR title; it defaults to a fixed
generic string (`Automated fix by claude-code-ci`) rather than referencing
an issue number.

## Provider support

`CI_PROVIDER=github` uses `gh` (GitHub CLI); `CI_PROVIDER=gitlab` uses
`glab` (GitLab CLI). Both are always present in the image — this is a
runtime switch, not a build-time or per-image choice. That tradeoff was
made deliberately: most individual pipelines only ever talk to one
provider, so most builds of this image do carry a CLI, an install step, and
a `managed-settings.json` deny-list they'll never exercise, in exchange for
one artifact to build and maintain instead of two (or a build-arg-gated
Dockerfile). Revisit this if that dead weight becomes a real problem for a
specific pipeline — the alternatives (split images, a build-arg) were
weighed and explicitly not chosen, not merely undiscovered.

`gh` installs through the same `packages-apt.txt` mechanism as every other
optional package in this image (it's apt-packaged in Debian trixie). `glab`
is not apt-packaged in Debian trixie, so it's pulled from GitLab's own
published multi-arch CLI container image
(`registry.gitlab.com/gitlab-org/cli`) via a Dockerfile `COPY --from=`,
pinned to `v1.114.0` — the same pattern this Dockerfile already uses for
`uv` (`COPY --from=ghcr.io/astral-sh/uv:latest`). That's a slight asymmetry
worth naming: `gh` is technically removable by a user editing
`packages-apt.txt`, `glab` is not (it's baked in like `uv`), so "both CLIs
always present" is only strictly guaranteed for `glab`. Not worth resolving
by moving `gh` out of the user-editable list too — an image builder who
deliberately removes `gh` from `packages-apt.txt` is making an informed
choice about their own build.

Provider dispatch (`setup_provider_auth`, `clone_repo`, `default_branch`,
`open_request` in `run-agent-task.sh`) is four flat
`case "$CI_PROVIDER" in github|gitlab|*)` blocks — no abstraction layer.
Confirmed against a real build of this image and the actual installed
`glab` binary (`glab 1.114.0`, `COPY --from=registry.gitlab.com/gitlab-org/cli:v1.114.0
/usr/bin/glab /usr/local/bin/glab` — the source path was correct on the
first build, no correction needed) and against GitLab's own CLI
documentation for the command shapes below:

- `GITLAB_TOKEN` is a real `glab`-recognized environment variable, taking
  precedence over stored credentials — the same shape as `gh`'s `GH_TOKEN`.
- `glab repo clone <repo> <dir> -- <gitflags>` passes extra `git clone`
  flags after `--`, the same shape as `gh repo clone`.
- `glab mr create --repo <repo> --source-branch <head> --target-branch
  <base> --title <title> --description <body>` is the non-interactive MR
  creation shape.
- There is no documented `glab auth setup-git` (`gh`'s one-shot credential
  helper setup). The equivalent is `glab auth login --hostname gitlab.com
  --token "$GITLAB_TOKEN" --git-protocol https` followed by explicitly
  setting `git config --global credential."https://gitlab.com".helper
  '!glab auth git-credential'` — both included in `run-agent-task.sh`. Note
  this only configures an HTTPS credential helper: if `CI_WORKSPACE_MODE=mounted`
  and the mounted workspace's `origin` remote is an SSH URL
  (`git@gitlab.com:...`), the later `git push` still has no SSH key
  configured and will fail — this image assumes HTTPS remotes throughout.
- Default-branch lookup uses `glab api "projects/<url-encoded-repo>"` piped
  through `jq -r .default_branch`, mirroring `gh repo view --json
  defaultBranchRef -q .defaultBranchRef.name`. `glab api` mirrors `gh api`
  closely enough that it's also included in `managed-settings.json`'s deny
  list as the same kind of blanket escape hatch.

The `glab mr create`/`api` command shapes above have not themselves been
run against a live GitLab project — see [What is left before this stops being a sketch](#what-is-left-before-this-stops-being-a-sketch).

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

## Installing additional software

Same four build-time package-list files as
[`claude-code`](../container-images/claude-code.md#custom-configuration-and-optional-build-time-tools),
and the same split between them: `packages-apt.txt` (`apt-get install`, prefilled
with `gh`, `jq`, `ripgrep`, `fd-find`, `tree`, `unzip`, `less`, `file`, `lsof`,
`yq`, `miller` — `gh` is what `CI_PROVIDER=github` actually needs, the rest is
generically useful for a fix task) and `packages-npm.txt` (`npm install -g`)
ship the same defaults as the interactive image. `tools-uv.txt` runs
`uv tool install`, one isolated venv
per entry, for standalone Python CLI tools (e.g. `ruff`) — only that entry's
own console-script ends up on `PATH`, nothing importable lands anywhere
shared. `packages-uv.txt` runs `uv pip install --system` into the image's
system Python instead, for plain importable libraries with no console-script
of their own (e.g. `langfuse`) that need to be importable by whatever runs
inside the image. `glab`, unlike `gh`, is baked in rather than
user-editable — see [Provider support](#provider-support) above. Edit any of
the four and rebuild the image to change what's installed.

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
  -e CI_PROVIDER='github' \
  -e CI_TASK='Fix issue #40 in owner/repo. Make the smallest correct change that resolves it, matching the existing conventions in this repository.' \
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
          CI_PROVIDER: github
          CI_TASK: "Fix issue #${{ inputs.issue_number }} in ${{ github.repository }}. Make the smallest correct change that resolves it, matching the existing conventions in this repository."
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
            -e CI_REPO -e CI_PROVIDER -e CI_TASK -e GH_TOKEN -e ANTHROPIC_API_KEY \
            ghcr.io/<org>/claude-code-ci:<tag>
```

Branch protection on the target repo (required review, required status
checks) is what actually stops the resulting PR from merging itself —
see above.

### If no pre-built image is published yet

The example above assumes `claude-code-ci` has already been built and
pushed somewhere reachable (a registry). Until that's set up, build it in
the same job instead — this needs a second checkout to pull in the
Dockerfile/build context from `agent-containers`, since the workflow above
lives in the *target* repo being fixed, not in `agent-containers` itself:

```yaml
jobs:
  fix-issue:
    runs-on: ubuntu-latest
    steps:
      - name: Check out agent-containers for the CI image build context
        uses: actions/checkout@v4
        with:
          repository: <org>/agent-containers
          path: agent-containers
          # Only needed if agent-containers is private:
          # token: ${{ secrets.AGENT_CONTAINERS_READ_TOKEN }}

      - name: Build claude-code-ci
        run: |
          docker build --build-context shared=agent-containers/agent-images/shared \
            -t claude-code-ci:local agent-containers/ci-images/claude-code

      - name: Run claude-code-ci
        env:
          CI_REPO: ${{ github.repository }}
          CI_PROVIDER: github
          CI_TASK: "Fix issue #${{ inputs.issue_number }} in ${{ github.repository }}. Make the smallest correct change that resolves it, matching the existing conventions in this repository."
          GH_TOKEN: ${{ secrets.CI_AGENT_GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          docker run --rm \
            --security-opt=no-new-privileges \
            --read-only \
            --tmpfs /tmp --tmpfs /run --tmpfs /home/claude \
            --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
            -e AGENT_ALLOWED_EGRESS='api.anthropic.com,github.com,api.github.com,codeload.github.com' \
            -e CI_REPO -e CI_PROVIDER -e CI_TASK -e GH_TOKEN -e ANTHROPIC_API_KEY \
            claude-code-ci:local
```

If `agent-containers` is private, the checkout step needs its own
read-scoped credential (a PAT or GitHub App installation token), separate
from the `GH_TOKEN` used *inside* the container for the target repo. This
costs a full image build on every run (no layer cache by default on
`ubuntu-latest`) — add `actions/cache` or
`docker/build-push-action`'s GHA cache backend if build time becomes a
problem, or move to a publish-once-and-pull setup (a separate workflow in
`agent-containers` that builds and pushes to `ghcr.io` on changes to
`ci-images/claude-code/**`) once more than one target repo uses this image.

## GitLab CI example

The equivalent for a GitLab pipeline, triggered manually with a merge
request opened against a target branch:

```yaml
fix-issue:
  image: docker:24
  services:
    - docker:24-dind
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
  variables:
    CI_TARGET_REPO: $CI_PROJECT_PATH
  script:
    - >
      docker run --rm
      --security-opt=no-new-privileges
      --read-only
      --tmpfs /tmp --tmpfs /run --tmpfs /home/claude
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID
      -e AGENT_ALLOWED_EGRESS='api.anthropic.com,gitlab.com'
      -e CI_REPO="$CI_TARGET_REPO"
      -e CI_PROVIDER=gitlab
      -e CI_TASK="$CI_TASK"
      -e GITLAB_TOKEN="$CI_AGENT_GITLAB_TOKEN"
      -e ANTHROPIC_API_KEY
      registry.example.com/claude-code-ci:latest
```

`CI_TASK` and `CI_AGENT_GITLAB_TOKEN` (a project or group access token
scoped to this project only, `Reporter`+ role with API access, no
`Owner`/`Maintainer`) are set as pipeline variables (masked, and protected
if this pipeline only runs on protected branches) rather than hardcoded —
same reasoning as ["Scoping what the token can
reach"](#scoping-what-the-token-can-reach) above, just with GitLab's own
token/role vocabulary instead of GitHub App installation tokens and
fine-grained PAT scopes. `docker:dind` is one way to get a Docker daemon
inside a GitLab CI job; use whatever this project's existing pipelines
already use to run containers if that differs.

### If no pre-built image is published yet

Same tradeoff as the GitHub Actions case above: until
`registry.example.com/claude-code-ci:latest` (or wherever this gets
published) actually exists, clone `agent-containers` in the job and build
from it instead:

```yaml
fix-issue:
  image: docker:24
  services:
    - docker:24-dind
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
  variables:
    CI_TARGET_REPO: $CI_PROJECT_PATH
  before_script:
    # If agent-containers is private, clone with a read-scoped credential
    # separate from $CI_AGENT_GITLAB_TOKEN (used inside the container for
    # the target project) — e.g. a deploy token or a group access token
    # with read_repository only, stored as its own masked/protected
    # variable.
    - git clone --depth=1 https://gitlab.com/<group>/agent-containers.git /tmp/agent-containers
    - >
      docker build --build-context shared=/tmp/agent-containers/agent-images/shared
      -t claude-code-ci:local /tmp/agent-containers/ci-images/claude-code
  script:
    - >
      docker run --rm
      --security-opt=no-new-privileges
      --read-only
      --tmpfs /tmp --tmpfs /run --tmpfs /home/claude
      --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID
      -e AGENT_ALLOWED_EGRESS='api.anthropic.com,gitlab.com'
      -e CI_REPO="$CI_TARGET_REPO"
      -e CI_PROVIDER=gitlab
      -e CI_TASK="$CI_TASK"
      -e GITLAB_TOKEN="$CI_AGENT_GITLAB_TOKEN"
      -e ANTHROPIC_API_KEY
      claude-code-ci:local
```

Same costs as the GitHub Actions build-in-job variant: a full image build
on every pipeline run (no layer cache by default), and an extra read-scoped
credential if `agent-containers` is private. Move to a publish-once
pipeline (build and push to a registry on changes to
`ci-images/claude-code/**`) once that cost matters or more than one project
uses this image.

## Testing locally

`claude-code-ci` is not a self-hosted GitHub Actions/GitLab CI runner —
nothing here registers with either platform's runner protocol. It's a
one-shot task container: whatever calls `docker run` (a terminal, or a CI
job) is just the trigger, and the container doesn't know or care which.
That means local testing never requires installing a runner — only Docker
(or Podman) itself, with the ability to grant `--cap-add=NET_ADMIN
--cap-add=NET_RAW` (the container sets up its own egress-allowlist
`iptables` rules on start).

The fully credential-free path is `CI_WORKSPACE_MODE=mounted` +
`CI_OUTPUT_MODE=report`: bind-mount a real local checkout into
`/workspace`, and the script runs the task and prints the diff/transcript
without ever needing `CI_REPO`, a provider, or a token (see the
requirements matrix above). For example:

```sh
docker build --build-context shared=agent-images/shared \
  -t claude-code-ci:local ci-images/claude-code

docker run --rm \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp --tmpfs /run --tmpfs /home/claude \
  --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
  -v "$PWD/some-local-checkout":/workspace \
  -e AGENT_ALLOWED_EGRESS='api.anthropic.com' \
  -e CI_WORKSPACE_MODE=mounted \
  -e CI_OUTPUT_MODE=report \
  -e CI_TASK='Explain what this repository does in one paragraph.' \
  -e ANTHROPIC_API_KEY \
  claude-code-ci:local
```

Testing the actual clone/push/PR-or-MR path (`CI_OUTPUT_MODE=pr`, either
`CI_WORKSPACE_MODE`) does require a real, ideally disposable, repository
and a token scoped to it — there is currently no mock provider. Don't point
this at `agent-containers` itself for a real end-to-end test.

## What is left before this stops being a sketch

- **Partially smoke-tested.** `docker build` succeeds; `glab --version`
  reports `1.114.0` and `gh --version` runs; the container drops to the
  unprivileged `claude` user (confirmed via `id`/`whoami` through the real
  `ci-entrypoint.sh` → `workload-entrypoint.sh` path, not a bypassed
  entrypoint) with a read-only rootfs (`touch /etc/...` fails as expected);
  the egress-allowlist setup runs; `run-agent-task.sh`'s env-var validation
  (missing `CI_TASK`, invalid `CI_PROVIDER`) fails cleanly with the expected
  messages, tested inside the real container under the full security flags
  (`--read-only --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW
  --cap-add=SETUID --cap-add=SETGID`). **Not yet tested: an actual `claude -p`
  run** (no `ANTHROPIC_API_KEY` available at verification time) — so nothing
  about `CI_OUTPUT_MODE=report`'s diff/transcript output, the `pr`/`mr`
  push-and-open path, or `managed-settings.json`'s actual enforcement
  (next bullet) has been exercised end-to-end yet.
- `managed-settings.json`'s actual enforcement under `bypassPermissions`
  mode and its pattern-matching semantics are unverified — see
  [above](#bounding-what-the-agent-can-do-not-just-where-it-can-escape-to).
- No published image yet, so the GitHub Actions example above is
  necessarily hypothetical about where `claude-code-ci` comes from.
- **No package-cache volume, and none is planned.** A shared, writable cache
  volume across jobs would reintroduce the cross-job state leak
  `--tmpfs /home/claude` exists to prevent: a cache entry written by one job
  (including postinstall script output) would be read, and potentially
  executed, by the next — a poisoning channel that doesn't require breaking
  out of the container. It's also arguably not this image's problem: the slow
  part is almost always the *target repo's* dependency install inside
  `/workspace`, not anything Claude Code itself needs, and that's ordinary CI
  caching the calling workflow already has a tool for (`actions/cache` keyed
  on the lockfile hash, bind-mounted into `/workspace`), independent of
  whether `/home/claude` is a tmpfs. If cold installs get expensive enough
  that this isn't sufficient, the shape to reach for is a cache volume
  populated out-of-band by a separate trusted step and mounted **read-only**
  into the CI container — never a volume the agent job itself can write to.
- **"Fix N issues" is a wrapper concern, resolved as: an external loop or
  matrix over independent `docker run` invocations, not an entrypoint
  change.** `run-agent-task.sh` stays single repo/issue per container. Fanning
  out inside the entrypoint (or one long-lived process working a queue) would
  let one issue's failure mode — a hang, a runaway loop, a prompt injection
  in the issue body — bleed into the handling of the next issue in the same
  process. A `strategy.matrix` (or an outer shell loop) over `CI_TASK`
  values, each a separate `docker run` with its own fresh tmpfs home, keeps
  blast radius per-issue and keeps the container's own contract at "one
  clone, one fix, one PR, exit." Concurrency caps (GitHub Actions
  `max-parallel`) and any per-issue/total cost or time budget belong at that
  orchestration layer, not duplicated inside every container. No example of
  this wrapper exists yet in this doc.
- **`glab`'s actual command behavior is unverified.** The image build and
  the `glab` binary itself were confirmed for real (`docker build` succeeds,
  `glab --version` reports `1.114.0`), but the specific command shapes
  `run-agent-task.sh` calls — `glab repo clone`, `glab mr create`, `glab api
  "projects/<id>"`, `glab auth login` + the `git-credential` helper — were
  only confirmed against GitLab's own CLI documentation, not run against a
  live GitLab project. Confirm flag names/shapes against the real binary
  (`docker run --rm --entrypoint glab claude-code-ci:local --help` and the
  relevant subcommand `--help`) and, ideally, a disposable GitLab project
  before relying on this for anything that matters.
- **`managed-settings.json`'s GitHub/GitLab deny-rule parity is incomplete
  by design, not oversight.** `gh repo edit *` has no confirmed `glab`
  equivalent (GitLab CLI has no `glab repo edit`; project-setting changes
  go through `glab api`, which is already denied). `gh workflow
  enable/disable *`'s closest GitLab analogue would be a pipeline-schedule
  command under `glab ci`/`glab pipeline`, but the exact subcommand wasn't
  confirmed, so no rule was added for it rather than guessing one that
  might not match the real syntax (a wrong glob is silently a no-op, which
  is worse than an honest gap).
