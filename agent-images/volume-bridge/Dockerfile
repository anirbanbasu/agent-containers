FROM debian:trixie-slim

ARG UID=1000
ARG GID=1000

# rclone's WebDAV server is a userspace server, so it can expose only its
# configured local backend without CAP_SYS_CHROOT or a root-owned source
# volume. apache2-utils creates the persistent bcrypt password verifier.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        apache2-utils \
        rclone \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g "$GID" bridge \
    && useradd -u "$UID" -g "$GID" --no-create-home --shell /usr/sbin/nologin bridge \
    && mkdir -p /exports /state \
    && touch /state/.keep \
    && chown -R bridge:bridge /state \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

USER bridge:bridge
ENV HOME=/tmp

EXPOSE 16080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
