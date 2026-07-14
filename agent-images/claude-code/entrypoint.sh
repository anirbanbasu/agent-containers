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

ALLOWLIST_FILE="/etc/claude/egress-allowlist.txt"
IPSET_NAME="claude_allowed"
IPSET6_NAME="claude_allowed6"

# --- Determine the effective allowlist -------------------------------------
# File mount takes precedence over the env var; neither set means deny-all.
if [ -f "$ALLOWLIST_FILE" ]; then
    mapfile -t ALLOWLIST < <(grep -v '^\s*#' "$ALLOWLIST_FILE" | grep -v '^\s*$')
elif [ -n "${CLAUDE_ALLOWED_EGRESS:-}" ]; then
    IFS=',' read -ra ALLOWLIST <<< "$CLAUDE_ALLOWED_EGRESS"
else
    ALLOWLIST=()
fi

is_ipv4() {
    [[ "$1" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$ ]]
}

is_ipv6() {
    [[ "$1" == *:* ]]
}

if [ "${#ALLOWLIST[@]}" -eq 1 ] && [ "${ALLOWLIST[0]}" = "*" ]; then
    echo "[entrypoint] CLAUDE_ALLOWED_EGRESS=* — no egress restrictions applied (IPv4 and IPv6)." >&2

elif [ "${#ALLOWLIST[@]}" -eq 0 ]; then
    echo "[entrypoint] No egress allowlist configured (\$CLAUDE_ALLOWED_EGRESS unset, no $ALLOWLIST_FILE mount)." >&2
    echo "[entrypoint] Defaulting to deny-all outbound traffic (IPv4 and IPv6). Set CLAUDE_ALLOWED_EGRESS=host1,host2 (or '*' for unrestricted) to change this." >&2
    iptables -P OUTPUT DROP
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    ip6tables -P OUTPUT DROP
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

else
    echo "[entrypoint] Restricting egress to: ${ALLOWLIST[*]}" >&2

    # Preserve whatever resolvers were in place before we take over DNS.
    UPSTREAM_DNS=$(grep '^nameserver' /etc/resolv.conf | awk '{print $2}')

    ipset create "$IPSET_NAME" hash:ip family inet -exist
    ipset create "$IPSET6_NAME" hash:ip family inet6 -exist

    # /tmp rather than /etc: entrypoint runs before rootfs is guaranteed
    # writable (a --read-only container only gets /tmp and /run as tmpfs).
    DNSMASQ_CONF=/tmp/dnsmasq.claude.conf
    {
        echo "no-resolv"
        echo "listen-address=127.0.0.1"
        echo "bind-interfaces"
        # Pin dnsmasq to a known, unprivileged UID so the NAT rules below can
        # tell its own upstream forwarding apart from every other process's
        # DNS traffic (both otherwise share the same destination: $UPSTREAM_DNS).
        echo "user=dnsmasq"
        for ns in $UPSTREAM_DNS; do
            echo "server=$ns"
        done
    } > "$DNSMASQ_CONF"

    for entry in "${ALLOWLIST[@]}"; do
        entry="$(echo "$entry" | xargs)" # trim whitespace
        if is_ipv6 "$entry"; then
            ipset add "$IPSET6_NAME" "$entry" -exist
        elif is_ipv4 "$entry"; then
            ipset add "$IPSET_NAME" "$entry" -exist
        else
            # dnsmasq routes A records into the first set and AAAA records
            # into the second, based on each set's own address family.
            echo "ipset=/$entry/$IPSET_NAME,$IPSET6_NAME" >> "$DNSMASQ_CONF"
        fi
    done

    dnsmasq --conf-file="$DNSMASQ_CONF"

    iptables -P OUTPUT DROP
    iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    ip6tables -P OUTPUT DROP
    ip6tables -A OUTPUT -d ::1/128 -j ACCEPT
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    for ns in $UPSTREAM_DNS; do
        if is_ipv6 "$ns"; then
            ip6tables -A OUTPUT -p udp -d "$ns" --dport 53 -j ACCEPT
            ip6tables -A OUTPUT -p tcp -d "$ns" --dport 53 -j ACCEPT
        else
            iptables -A OUTPUT -p udp -d "$ns" --dport 53 -j ACCEPT
            iptables -A OUTPUT -p tcp -d "$ns" --dport 53 -j ACCEPT
        fi
    done
    iptables -A OUTPUT -m set --match-set "$IPSET_NAME" dst -j ACCEPT
    ip6tables -A OUTPUT -m set --match-set "$IPSET6_NAME" dst -j ACCEPT

    # Force every process's DNS traffic to the local filtering dnsmasq
    # instance via NAT instead of rewriting /etc/resolv.conf, which isn't
    # writable under --read-only. dnsmasq's own upstream forwarding (to the
    # same $UPSTREAM_DNS) must not be redirected back to itself, so it's
    # excluded by UID rather than by destination — a destination-only
    # exclusion would also match every other process's DNS queries, since
    # they're sent to that same resolver address, letting them bypass the
    # filtering dnsmasq (and its ipset population) entirely.
    for ns in $UPSTREAM_DNS; do
        if is_ipv6 "$ns"; then
            ip6tables -t nat -A OUTPUT -p udp -d "$ns" --dport 53 -m owner --uid-owner dnsmasq -j RETURN
            ip6tables -t nat -A OUTPUT -p tcp -d "$ns" --dport 53 -m owner --uid-owner dnsmasq -j RETURN
        else
            iptables -t nat -A OUTPUT -p udp -d "$ns" --dport 53 -m owner --uid-owner dnsmasq -j RETURN
            iptables -t nat -A OUTPUT -p tcp -d "$ns" --dport 53 -m owner --uid-owner dnsmasq -j RETURN
        fi
    done
    iptables -t nat -A OUTPUT -p udp --dport 53 -j REDIRECT --to-ports 53
    iptables -t nat -A OUTPUT -p tcp --dport 53 -j REDIRECT --to-ports 53
    ip6tables -t nat -A OUTPUT -p udp --dport 53 -j REDIRECT --to-ports 53
    ip6tables -t nat -A OUTPUT -p tcp --dport 53 -j REDIRECT --to-ports 53
fi

# `docker run <image> <args>` replaces CMD entirely rather than appending to
# it, so flag-only invocations (e.g. `--agents`) would otherwise try to exec
# a binary literally named after the flag. Prepend `claude` when that happens.
case "${1:-}" in
    -*) set -- claude "$@" ;;
    "") set -- claude ;;
esac

exec gosu claude "$@"
