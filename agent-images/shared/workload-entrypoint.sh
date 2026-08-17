#!/bin/bash
# Shared runtime entrypoint for first-party workloads that use Python and
# Node.js. The Dockerfile supplies the fixed default executable and
# unprivileged user as the first two positional arguments, rather than mutable
# environment variables, so a runtime -e option cannot alter the privilege
# drop target.

set -euo pipefail

agent_command="$1"
agent_user="$2"
shift 2

if [ -n "${AGENT_GATEWAY_HOST:-}" ]; then
    echo "[entrypoint] AGENT_GATEWAY_HOST=$AGENT_GATEWAY_HOST — tunneling all egress through the gateway." >&2
    if [ -n "${AGENT_ALLOWED_EGRESS:-}" ] || [ -f /etc/agent/egress-allowlist.txt ]; then
        echo "[entrypoint] AGENT_ALLOWED_EGRESS/egress-allowlist.txt are ignored in gateway mode — set the allowlist on the gateway container instead." >&2
    fi
    if [ -n "${AGENT_GATEWAY_BOOTSTRAP_ALLOW:-}" ]; then
        echo "[entrypoint] Seeding a bootstrap allow rule for ${AGENT_GATEWAY_BOOTSTRAP_ALLOW} until the tunnel is up." >&2
        # -m addrtype --dst-type LOCAL, not -o lo: sshuttle's own REDIRECT
        # rules retarget outbound connections to 127.0.0.1:<its local proxy
        # port> before this chain runs, but that retargeted packet's
        # out-interface isn't reliably "lo" by the time OUTPUT filtering
        # sees it. Matching the resolved destination instead reliably covers
        # both loopback and this redirect-to-local-port case.
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

# `docker run <image> <args>` replaces CMD entirely rather than appending to
# it, so a flag-only invocation must prepend the image's default executable.
case "${1:-}" in
    -*) set -- "$agent_command" "$@" ;;
    "") set -- "$agent_command" ;;
esac

exec gosu "$agent_user" "$@"
