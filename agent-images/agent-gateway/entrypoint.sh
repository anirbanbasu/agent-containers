#!/bin/bash
set -euo pipefail

gosu tunnel install -m 600 /etc/claude/gateway-key.pub /home/tunnel/.ssh/authorized_keys

HOST_KEY_DIR=/etc/ssh/keys
mkdir -p "$HOST_KEY_DIR"
if [ ! -f "$HOST_KEY_DIR/ssh_host_ed25519_key" ]; then
    echo "[entrypoint] Generating gateway SSH host key ..." >&2
    ssh-keygen -q -t ed25519 -f "$HOST_KEY_DIR/ssh_host_ed25519_key" -N ""
fi
echo "HostKey $HOST_KEY_DIR/ssh_host_ed25519_key" > /etc/ssh/sshd_config.d/hostkey.conf

source /usr/local/lib/claude/egress-allowlist.sh
configure_egress_allowlist

if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    echo "[entrypoint] Starting cloudflared tunnel (no inbound port needed)." >&2
    cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
fi

mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
