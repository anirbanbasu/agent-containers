#!/bin/sh
set -eu

readonly state_dir=/state
readonly authorized_keys="$state_dir/authorized_keys"
readonly host_key="$state_dir/ssh_host_ed25519_key"

if [ ! -w "$state_dir" ]; then
    echo '[volume-bridge] /state must be an empty volume first mounted by this image, or be writable by the bridge UID/GID.' >&2
    exit 1
fi

# A public key is safe to pass at container creation and avoids bind-mounting a
# host directory into the sidecar. It is copied into the persistent state volume
# so later starts do not need the environment variable.
if [ -n "${VOLUME_BRIDGE_AUTHORIZED_KEY:-}" ]; then
    umask 077
    printf '%s\n' "$VOLUME_BRIDGE_AUTHORIZED_KEY" > "$authorized_keys"
fi

if [ ! -s "$authorized_keys" ]; then
    echo '[volume-bridge] VOLUME_BRIDGE_AUTHORIZED_KEY is required on first start.' >&2
    exit 1
fi
chmod 600 "$authorized_keys"

if [ ! -f "$host_key" ]; then
    echo '[volume-bridge] Generating persistent ED25519 host key.' >&2
    umask 077
    ssh-keygen -q -t ed25519 -f "$host_key" -N ''
fi
chmod 600 "$host_key"

if [ ! -f "$host_key.pub" ]; then
    ssh-keygen -y -f "$host_key" > "$host_key.pub"
fi
chmod 644 "$host_key.pub"

# The source is the deliberately narrow /exports tree. rclone's SFTP server
# authenticates against the supplied public keys and exposes this backend as its
# virtual root; it has no shell or arbitrary-command channel. The service
# listens on all container interfaces because Docker's host-loopback port
# publishing forwards to the container address, not its loopback address.
exec rclone --config /dev/null --cache-dir /tmp/rclone-cache serve sftp \
    --addr "${VOLUME_BRIDGE_LISTEN_ADDR:-0.0.0.0:2222}" \
    --authorized-keys "$authorized_keys" \
    --key "$host_key" \
    --read-only \
    --dir-cache-time "${VOLUME_BRIDGE_DIR_CACHE_TIME:-1s}" \
    :local:/exports
