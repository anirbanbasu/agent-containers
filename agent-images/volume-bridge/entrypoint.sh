#!/bin/sh
set -eu

readonly state_dir=/state
readonly htpasswd_file="$state_dir/htpasswd"
readonly username="${VOLUME_BRIDGE_USERNAME:-bridge}"

if [ ! -w "$state_dir" ]; then
    echo '[volume-bridge] /state must be an empty volume first mounted by this image, or be writable by the bridge UID/GID.' >&2
    exit 1
fi

# The password is accepted only to initialise or rotate a bcrypt verifier in
# the state volume. Do not put a reader private key or plaintext credential in
# the image or state volume. A Docker administrator can already read the source
# volumes, so they are the trusted provisioning boundary for this input.
if [ -n "${VOLUME_BRIDGE_PASSWORD:-}" ]; then
    case "$username" in
        *:* | *'
'*)
            echo '[volume-bridge] VOLUME_BRIDGE_USERNAME must not contain a colon or newline.' >&2
            exit 1
            ;;
    esac
    umask 077
    printf '%s\n' "$VOLUME_BRIDGE_PASSWORD" \
        | htpasswd -B -C 12 -c -i "$htpasswd_file.new" "$username"
    mv "$htpasswd_file.new" "$htpasswd_file"
fi

if [ ! -s "$htpasswd_file" ]; then
    echo '[volume-bridge] VOLUME_BRIDGE_PASSWORD is required on first start.' >&2
    exit 1
fi
chmod 600 "$htpasswd_file"

# The source is the deliberately narrow /exports tree. rclone's WebDAV server
# authenticates against the bcrypt verifier and exposes this backend as its
# virtual root. The service listens on all container interfaces because Docker's
# host-loopback port publishing forwards to the container address, not its
# loopback address.
exec rclone --config /dev/null --cache-dir /tmp/rclone-cache serve webdav \
    --addr "${VOLUME_BRIDGE_LISTEN_ADDR:-0.0.0.0:16080}" \
    --htpasswd "$htpasswd_file" \
    --realm volume-bridge \
    --read-only \
    --dir-cache-time "${VOLUME_BRIDGE_DIR_CACHE_TIME:-1s}" \
    :local:/exports
