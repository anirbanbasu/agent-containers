#!/bin/sh
set -eu

readonly state_dir=/state
readonly htpasswd_file="$state_dir/htpasswd"
readonly username="${VOLUME_BRIDGE_USERNAME:-bridge}"

if [ ! -w "$state_dir" ]; then
    echo '[volume-bridge] /state must be an empty volume first mounted by this image, or be writable by the bridge UID/GID.' >&2
    exit 1
fi

if [ -n "${VOLUME_BRIDGE_PASSWORD:-}" ] && [ -n "${VOLUME_BRIDGE_PASSWORD_FILE:-}" ]; then
    echo '[volume-bridge] Set only one of VOLUME_BRIDGE_PASSWORD or VOLUME_BRIDGE_PASSWORD_FILE.' >&2
    exit 1
fi

password=""
if [ -n "${VOLUME_BRIDGE_PASSWORD_FILE:-}" ]; then
    password="$(cat "$VOLUME_BRIDGE_PASSWORD_FILE")"
elif [ -n "${VOLUME_BRIDGE_PASSWORD:-}" ]; then
    password="$VOLUME_BRIDGE_PASSWORD"
fi

# The password is accepted only to initialise or rotate a bcrypt verifier in
# the state volume. VOLUME_BRIDGE_PASSWORD_FILE is read once, right here, and
# never lands in the daemon-persisted container config that
# VOLUME_BRIDGE_PASSWORD leaves behind for `docker inspect` to read for the
# container's whole lifetime — prefer it when the password can be
# bind-mounted as a file. Do not put a reader private key or plaintext
# credential in the image or state volume. A Docker administrator can already
# read the source volumes directly, so they are the trusted provisioning
# boundary for this input either way.
if [ -n "$password" ]; then
    case "$username" in
        *:* | *'
'*)
            echo '[volume-bridge] VOLUME_BRIDGE_USERNAME must not contain a colon or newline.' >&2
            exit 1
            ;;
    esac
    umask 077
    printf '%s\n' "$password" \
        | htpasswd -B -C 12 -c -i "$htpasswd_file.new" "$username"
    mv "$htpasswd_file.new" "$htpasswd_file"
fi
unset password

if [ ! -s "$htpasswd_file" ]; then
    echo '[volume-bridge] VOLUME_BRIDGE_PASSWORD or VOLUME_BRIDGE_PASSWORD_FILE is required on first start.' >&2
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
