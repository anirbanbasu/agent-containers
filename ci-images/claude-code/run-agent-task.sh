#!/bin/bash
# CI task runner — replaces the interactive `claude` CMD from
# agent-images/claude-code. Runs as the unprivileged `claude` user, invoked
# by workload-entrypoint.sh after containment (rootfs, capabilities, egress
# allowlist) is already in place. There is no terminal here for a permission
# prompt to appear in, so this script pins --permission-mode
# bypassPermissions explicitly rather than relying on whatever claude's own
# default happens to be — an unmet prompt in headless mode fails the task
# partway rather than pausing for one. The containment this project builds
# is what stands in for that approval instead, per the project's own
# containment philosophy (docs/containment-philosophy.md): the walls, not
# the agent's behaviour, are what's trusted.
#
# Model provider (Bedrock, a local endpoint, the hosted Anthropic API, ...)
# is deliberately not this script's concern — claude reads its own env vars
# (CLAUDE_CODE_USE_BEDROCK, ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY, ...) and
# this script doesn't inspect or default any of them. See
# docs/continuous-integration-images/claude-code.md for the confirmed
# variable names per provider.
#
# Required environment:
#   CI_REPO           owner/repo to operate on (github.com only, for now)
#   CI_ISSUE_NUMBER    issue number to fix
#   GH_TOKEN           token gh/git use to clone, push, and open the PR —
#                      scope it to Contents:write + Pull requests:write on
#                      this repo only, nothing merge-adjacent; see
#                      docs/continuous-integration-images/claude-code.md
# Optional environment:
#   CI_BASE_BRANCH     base branch for the PR (default: repo's default branch)
#   CI_TASK            full task prompt, overrides the CI_ISSUE_NUMBER default
#   GIT_AUTHOR_NAME     commit identity (default: "claude-ci")
#   GIT_AUTHOR_EMAIL    commit identity (default: "claude-ci@users.noreply.github.com")

set -euo pipefail

: "${CI_REPO:?CI_REPO (owner/repo) must be set}"
: "${GH_TOKEN:?GH_TOKEN must be set}"

if [ -z "${CI_TASK:-}" ]; then
    : "${CI_ISSUE_NUMBER:?either CI_TASK or CI_ISSUE_NUMBER must be set}"
fi

author_name="${GIT_AUTHOR_NAME:-claude-ci}"
author_email="${GIT_AUTHOR_EMAIL:-claude-ci@users.noreply.github.com}"
head_branch="${CI_HEAD_BRANCH:-claude/issue-${CI_ISSUE_NUMBER:-task}-$$}"
transcript="/tmp/claude-transcript.jsonl"

# gh reads GH_TOKEN directly; this also configures git's credential helper
# so the later clone/push don't need the token spelled out on any command
# line (and therefore don't leak it into `ps` output or shell history).
gh auth setup-git

repo_dir="/workspace/$(basename "$CI_REPO")"
clone_args=(--depth=1)
if [ -n "${CI_BASE_BRANCH:-}" ]; then
    clone_args+=(--branch "$CI_BASE_BRANCH")
fi
gh repo clone "$CI_REPO" "$repo_dir" -- "${clone_args[@]}"
cd "$repo_dir"

base_branch="${CI_BASE_BRANCH:-$(gh repo view "$CI_REPO" --json defaultBranchRef -q .defaultBranchRef.name)}"
git checkout -b "$head_branch"

task="${CI_TASK:-Fix issue #${CI_ISSUE_NUMBER} in ${CI_REPO}. Make the smallest correct change that resolves it, matching the existing conventions in this repository.}"

echo "[run-agent-task] Starting: $task" >&2
claude -p "$task" \
    --permission-mode bypassPermissions \
    --output-format stream-json --verbose \
    > "$transcript"

if git diff --quiet && git diff --cached --quiet; then
    echo "[run-agent-task] No changes produced — not opening a PR." >&2
    exit 1
fi

git add -A
git -c user.name="$author_name" -c user.email="$author_email" \
    commit -m "$(printf 'Fix issue #%s\n\nAutomated by claude-code-ci.' "${CI_ISSUE_NUMBER:-N/A}")"
git push -u origin "$head_branch"

gh pr create \
    --repo "$CI_REPO" \
    --base "$base_branch" \
    --head "$head_branch" \
    --title "Fix issue #${CI_ISSUE_NUMBER:-N/A}" \
    --body "$(printf 'Opened automatically by claude-code-ci from issue #%s.\n\nReview before merging — this PR was not reviewed by a human before being opened.' "${CI_ISSUE_NUMBER:-N/A}")"

echo "[run-agent-task] Full tool-call transcript: $transcript (container-local, not pushed)" >&2
