#!/bin/bash
set -euo pipefail

# Older images mounted the persistent volume directly at /home/claude/.claude;
# it's now mounted at /home/claude so uv/npm state under $HOME persists too.
# A volume from before this change has its old .claude contents sitting at
# its own root, so /home/claude/.claude won't exist yet — nest them one
# level down to match where Claude Code still expects them. Both the check
# and the action run as the claude user (via gosu): /home/claude is
# 0700-owned by claude, and root lacks CAP_DAC_OVERRIDE under --cap-drop=ALL,
# so root can't even stat into it — checking as root would misreport
# "missing" on every single start (not just genuinely legacy volumes) and
# re-run the sweep repeatedly, corrupting a volume that's already migrated.
if ! gosu claude test -d /home/claude/.claude; then
    echo "[entrypoint] Migrating legacy claude-home volume layout into ~/.claude ..." >&2
    gosu claude mkdir -p /home/claude/.claude
    gosu claude find /home/claude -mindepth 1 -maxdepth 1 ! -name .claude -exec mv -t /home/claude/.claude -- {} +
fi

source /usr/local/lib/claude/egress-allowlist.sh
configure_egress_allowlist

# `docker run <image> <args>` replaces CMD entirely rather than appending to
# it, so flag-only invocations (e.g. `--agents`) would otherwise try to exec
# a binary literally named after the flag. Prepend `claude` when that happens.
case "${1:-}" in
    -*) set -- claude "$@" ;;
    "") set -- claude ;;
esac

exec gosu claude "$@"
