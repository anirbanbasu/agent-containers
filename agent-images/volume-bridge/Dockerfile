FROM debian:trixie-slim

ARG UID=1000
ARG GID=1000

# rclone's SFTP server is a userspace server: unlike OpenSSH chroot mode, it
# can expose only its configured local backend without CAP_SYS_CHROOT or a
# root-owned source volume. openssh-client supplies ssh-keygen for the
# persistent server host key.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        openssh-client \
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

EXPOSE 2222
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
