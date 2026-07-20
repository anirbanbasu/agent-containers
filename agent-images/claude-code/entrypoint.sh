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

if [ -n "${CLAUDE_GATEWAY_HOST:-}" ]; then
    echo "[entrypoint] CLAUDE_GATEWAY_HOST=$CLAUDE_GATEWAY_HOST — tunneling all egress through the gateway." >&2
    if [ -n "${CLAUDE_ALLOWED_EGRESS:-}" ] || [ -f /etc/claude/egress-allowlist.txt ]; then
        echo "[entrypoint] CLAUDE_ALLOWED_EGRESS/egress-allowlist.txt are ignored in gateway mode — set the allowlist on the gateway container instead." >&2
    fi
    if [ -n "${CLAUDE_GATEWAY_BOOTSTRAP_ALLOW:-}" ]; then
        echo "[entrypoint] Seeding a bootstrap allow rule for ${CLAUDE_GATEWAY_BOOTSTRAP_ALLOW} until the tunnel is up." >&2
        iptables -P OUTPUT DROP
        iptables -A OUTPUT -o lo -j ACCEPT
        iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
        ip6tables -P OUTPUT DROP
        ip6tables -A OUTPUT -o lo -j ACCEPT
        ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
        IFS=',' read -ra BOOTSTRAP_ALLOW <<< "$CLAUDE_GATEWAY_BOOTSTRAP_ALLOW"
        for addr in "${BOOTSTRAP_ALLOW[@]}"; do
            if [[ "$addr" == *:* ]]; then
                ip6tables -A OUTPUT -d "$addr" -j ACCEPT
            else
                iptables -A OUTPUT -d "$addr" -j ACCEPT
            fi
        done
    fi
    install -m 600 /etc/claude/gateway-key /tmp/gateway-key
    sshuttle -r "${CLAUDE_GATEWAY_USER:-tunnel}@${CLAUDE_GATEWAY_HOST}:${CLAUDE_GATEWAY_PORT:-2222}" \
        0.0.0.0/0 ::/0 --dns --daemon --pidfile=/tmp/sshuttle.pid \
        -e "ssh -i /tmp/gateway-key -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/claude/gateway-known-hosts"
else
    source /usr/local/lib/claude/egress-allowlist.sh
    configure_egress_allowlist
fi

# `docker run <image> <args>` replaces CMD entirely rather than appending to
# it, so flag-only invocations (e.g. `--agents`) would otherwise try to exec
# a binary literally named after the flag. Prepend `claude` when that happens.
case "${1:-}" in
    -*) set -- claude "$@" ;;
    "") set -- claude ;;
esac

exec gosu claude "$@"
