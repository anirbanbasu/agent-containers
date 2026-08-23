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
# Three independent axes, documented in full (with a requirements matrix)
# in docs/continuous-integration-images/claude-code.md:
#   CI_OUTPUT_MODE     pr (default) | report
#   CI_WORKSPACE_MODE  clone (default) | mounted
#   CI_PROVIDER        github | gitlab — required whenever a provider
#                      action (clone, or push+open) is actually needed
#
# Required environment:
#   CI_TASK             full task prompt for `claude -p`
# Conditionally required — see the doc's requirements matrix:
#   CI_REPO              owner/repo. Required for CI_WORKSPACE_MODE=clone.
#                        Derived from the mounted workspace's 'origin'
#                        remote when unset under CI_WORKSPACE_MODE=mounted
#                        and CI_OUTPUT_MODE=pr. Never required for
#                        CI_WORKSPACE_MODE=mounted + CI_OUTPUT_MODE=report.
#   CI_PROVIDER          Required for CI_WORKSPACE_MODE=clone, or for
#                        CI_OUTPUT_MODE=pr.
#   GH_TOKEN               Required when CI_PROVIDER=github and provider
#                        auth is actually needed.
#   GITLAB_TOKEN          Required when CI_PROVIDER=gitlab and provider
#                        auth is actually needed.
# Optional environment:
#   CI_BASE_BRANCH     base branch for the PR/MR (default: repo's default
#                      branch, looked up via the provider)
#   CI_TITLE           commit/PR/MR title (default: a generic string)
#   CI_HEAD_BRANCH     branch name for the PR/MR (default: claude/task-$$)
#   GIT_AUTHOR_NAME    commit identity (default: "claude-ci")
#   GIT_AUTHOR_EMAIL   commit identity (default: "claude-ci@users.noreply.github.com")

set -euo pipefail

output_mode="${CI_OUTPUT_MODE:-pr}"
workspace_mode="${CI_WORKSPACE_MODE:-clone}"

case "$output_mode" in
    pr|report) ;;
    *) echo "[run-agent-task] Invalid CI_OUTPUT_MODE: $output_mode (must be pr or report)" >&2; exit 1 ;;
esac
case "$workspace_mode" in
    clone|mounted) ;;
    *) echo "[run-agent-task] Invalid CI_WORKSPACE_MODE: $workspace_mode (must be clone or mounted)" >&2; exit 1 ;;
esac

# setup_provider_auth, clone_repo, default_branch, open_request: one flat
# case statement per operation rather than a provider abstraction layer —
# two providers doesn't earn one. Add a third before reaching for
# indirection here.

setup_provider_auth() {
    case "$CI_PROVIDER" in
        github)
            : "${GH_TOKEN:?GH_TOKEN must be set when CI_PROVIDER=github}"
            # gh reads GH_TOKEN directly; this also configures git's
            # credential helper so the later clone/push don't need the
            # token spelled out on any command line.
            gh auth setup-git
            ;;
        gitlab)
            : "${GITLAB_TOKEN:?GITLAB_TOKEN must be set when CI_PROVIDER=gitlab}"
            glab auth login --hostname gitlab.com --token "$GITLAB_TOKEN" \
                --git-protocol https >/dev/null
            git config --global credential."https://gitlab.com".helper \
                '!glab auth git-credential'
            ;;
        *)
            echo "[run-agent-task] Unsupported CI_PROVIDER: $CI_PROVIDER (must be github or gitlab)" >&2
            exit 1
            ;;
    esac
}

clone_repo() {
    local repo="$1" dest="$2"
    local -a clone_args=(--depth=1)
    [ -n "${CI_BASE_BRANCH:-}" ] && clone_args+=(--branch "$CI_BASE_BRANCH")
    case "$CI_PROVIDER" in
        github) gh repo clone "$repo" "$dest" -- "${clone_args[@]}" ;;
        gitlab) glab repo clone "$repo" "$dest" -- "${clone_args[@]}" ;;
        *) echo "[run-agent-task] Unsupported CI_PROVIDER: $CI_PROVIDER (must be github or gitlab)" >&2; exit 1 ;;
    esac
}

default_branch() {
    local repo="$1"
    case "$CI_PROVIDER" in
        github) gh repo view "$repo" --json defaultBranchRef -q .defaultBranchRef.name ;;
        gitlab) glab api "projects/${repo//\//%2F}" | jq -r .default_branch ;;
        *) echo "[run-agent-task] Unsupported CI_PROVIDER: $CI_PROVIDER (must be github or gitlab)" >&2; exit 1 ;;
    esac
}

open_request() {
    local repo="$1" base="$2" head="$3" title="$4" body="$5"
    case "$CI_PROVIDER" in
        github)
            gh pr create --repo "$repo" --base "$base" --head "$head" \
                --title "$title" --body "$body"
            ;;
        gitlab)
            glab mr create --repo "$repo" --source-branch "$head" \
                --target-branch "$base" --title "$title" --description "$body"
            ;;
        *) echo "[run-agent-task] Unsupported CI_PROVIDER: $CI_PROVIDER (must be github or gitlab)" >&2; exit 1 ;;
    esac
}

# Turns an 'origin' remote URL into 'owner/repo', for CI_WORKSPACE_MODE=mounted
# when the caller didn't set CI_REPO explicitly. Handles both HTTPS
# (https://host/owner/repo.git) and SSH (git@host:owner/repo.git) remotes,
# for either provider — the shape is the same on github.com and gitlab.com.
derive_repo_from_origin() {
    local url
    url="$(git remote get-url origin 2>/dev/null)" || {
        echo "[run-agent-task] CI_REPO unset and no 'origin' remote in the mounted workspace." >&2
        exit 1
    }
    printf '%s\n' "$url" | sed -E 's#^(https?://[^/]+/|git@[^:]+:)##; s#\.git$##'
}

main() {
    : "${CI_TASK:?CI_TASK must be set}"

    local author_name="${GIT_AUTHOR_NAME:-claude-ci}"
    local author_email="${GIT_AUTHOR_EMAIL:-claude-ci@users.noreply.github.com}"
    local transcript="/tmp/claude-transcript.jsonl"
    local repo_dir base_branch head_branch

    if [ "$workspace_mode" = clone ]; then
        : "${CI_REPO:?CI_REPO must be set when CI_WORKSPACE_MODE=clone}"
        : "${CI_PROVIDER:?CI_PROVIDER (github or gitlab) must be set when CI_WORKSPACE_MODE=clone}"
        setup_provider_auth
        repo_dir="/workspace/$(basename "$CI_REPO")"
        clone_repo "$CI_REPO" "$repo_dir"
        cd "$repo_dir"
    else
        cd /workspace
        if [ "$output_mode" = pr ]; then
            : "${CI_PROVIDER:?CI_PROVIDER (github or gitlab) must be set when CI_OUTPUT_MODE=pr}"
            : "${CI_REPO:=$(derive_repo_from_origin)}"
            setup_provider_auth
        fi
    fi

    if [ "$output_mode" = pr ]; then
        base_branch="${CI_BASE_BRANCH:-$(default_branch "$CI_REPO")}"
        head_branch="${CI_HEAD_BRANCH:-claude/task-$$}"
        git checkout -b "$head_branch"
    fi

    echo "[run-agent-task] Starting: $CI_TASK" >&2
    claude -p "$CI_TASK" \
        --permission-mode bypassPermissions \
        --output-format stream-json --verbose \
        > "$transcript"

    if git diff --quiet && git diff --cached --quiet; then
        echo "[run-agent-task] No changes produced." >&2
        if [ "$output_mode" = pr ]; then
            exit 1
        fi
        echo "[run-agent-task] CI_OUTPUT_MODE=report — a no-op is not a failure." >&2
        exit 0
    fi

    if [ "$output_mode" = report ]; then
        echo "[run-agent-task] CI_OUTPUT_MODE=report — printing the diff, not pushing or opening anything." >&2
        git diff
        git diff --cached
        echo "[run-agent-task] Full tool-call transcript: $transcript (container-local, not pushed)" >&2
        exit 0
    fi

    local title="${CI_TITLE:-Automated fix by claude-code-ci}"
    git add -A
    git -c user.name="$author_name" -c user.email="$author_email" \
        commit -m "$(printf '%s\n\nAutomated by claude-code-ci.' "$title")"
    git push -u origin "$head_branch"

    open_request "$CI_REPO" "$base_branch" "$head_branch" "$title" \
        "$(printf 'Opened automatically by claude-code-ci.\n\nReview before merging — this PR was not reviewed by a human before being opened.')"

    echo "[run-agent-task] Full tool-call transcript: $transcript (container-local, not pushed)" >&2
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
