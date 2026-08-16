#!/bin/bash
set -euo pipefail

if [ -n "${AGENT_GATEWAY_HOST:-}" ]; then
    echo "[entrypoint] AGENT_GATEWAY_HOST=$AGENT_GATEWAY_HOST — tunneling all egress through the gateway." >&2
    if [ -n "${AGENT_ALLOWED_EGRESS:-}" ] || [ -f /etc/agent/egress-allowlist.txt ]; then
        echo "[entrypoint] AGENT_ALLOWED_EGRESS/egress-allowlist.txt are ignored in gateway mode — set the allowlist on the gateway container instead." >&2
    fi
    if [ -n "${AGENT_GATEWAY_BOOTSTRAP_ALLOW:-}" ]; then
        echo "[entrypoint] Seeding a bootstrap allow rule for ${AGENT_GATEWAY_BOOTSTRAP_ALLOW} until the tunnel is up." >&2
        iptables -P OUTPUT DROP
        iptables -A OUTPUT -m addrtype --dst-type LOCAL -j ACCEPT
        iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
        ip6tables -P OUTPUT DROP
        ip6tables -A OUTPUT -m addrtype --dst-type LOCAL -j ACCEPT
        ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
        IFS=',' read -ra BOOTSTRAP_ALLOW <<< "$AGENT_GATEWAY_BOOTSTRAP_ALLOW"
        for addr in "${BOOTSTRAP_ALLOW[@]}"; do
            if [[ "$addr" == *:* ]]; then
                ip6tables -A OUTPUT -d "$addr" -j ACCEPT
            else
                iptables -A OUTPUT -d "$addr" -j ACCEPT
            fi
        done
    fi
    install -m 600 /etc/agent/gateway-key /tmp/gateway-key
    SSH_CMD="ssh -i /tmp/gateway-key -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/agent/gateway-known-hosts"
    if [ -n "${AGENT_GATEWAY_ACCESS_HOSTNAME:-}" ]; then
        echo "[entrypoint] Reaching the gateway via Cloudflare Access hostname ${AGENT_GATEWAY_ACCESS_HOSTNAME}." >&2
        SSH_CMD="$SSH_CMD -o ProxyCommand='cloudflared access ssh --hostname ${AGENT_GATEWAY_ACCESS_HOSTNAME}'"
    fi
    sshuttle -r "${AGENT_GATEWAY_USER:-tunnel}@${AGENT_GATEWAY_HOST}:${AGENT_GATEWAY_PORT:-2222}" \
        0.0.0.0/0 ::/0 --dns --daemon --pidfile=/tmp/sshuttle.pid \
        -e "$SSH_CMD"
else
    source /usr/local/lib/agent/egress-allowlist.sh
    configure_egress_allowlist
fi

case "${1:-}" in
    -*) set -- qwen "$@" ;;
    "") set -- qwen ;;
esac

exec gosu qwen "$@"
