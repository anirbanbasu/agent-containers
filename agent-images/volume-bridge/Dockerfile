FROM debian:trixie-slim

ARG UID=1000
ARG GID=1000

# rclone's WebDAV server is a userspace server, so it can expose only its
# configured local backend without CAP_SYS_CHROOT or a root-owned source
# volume. apache2-utils creates the persistent bcrypt password verifier.
# iptables installs this image's own fixed deny-by-default INPUT/OUTPUT
# policy (see entrypoint.sh); gosu drops from root to the unprivileged bridge
# user once that policy is in place.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        apache2-utils \
        rclone \
        iptables \
        gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g "$GID" bridge \
    && useradd -u "$UID" -g "$GID" --no-create-home --shell /usr/sbin/nologin bridge \
    && mkdir -p /exports /state \
    && touch /state/.keep \
    && chown -R bridge:bridge /state \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

COPY serve.sh /usr/local/lib/agent/volume-bridge-serve.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/lib/agent/volume-bridge-serve.sh

# The image starts as root: entrypoint.sh installs the fixed deny-by-default
# network policy (needs NET_ADMIN/NET_RAW), then gosu drops to bridge before
# rclone ever runs. This image no longer sets USER at build time.
ENV HOME=/tmp

EXPOSE 16080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
