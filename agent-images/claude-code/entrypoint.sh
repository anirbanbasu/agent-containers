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

# Claude-specific state migration stays here; all containment setup and the
# privilege drop are shared with the other first-party Node workload images.
exec /usr/local/lib/agent/node-workload-entrypoint.sh claude claude "$@"
