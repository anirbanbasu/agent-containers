FROM debian:trixie-slim

ARG TARGETARCH

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        iptables \
        ipset \
        dnsmasq \
        dnsutils \
        openssh-server \
        python3 \
        curl \
    && curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
         -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && rm -f /etc/ssh/ssh_host_* \
    && rm -rf /var/lib/apt/lists/*
# python3 isn't used by anything in this image — it's what sshuttle execs
# remotely over the SSH session from the claude-code side. The entrypoint
# copies the mounted public key to a root-owned runtime path under /run, so
# it works with a read-only root filesystem without CAP_CHOWN. cloudflared
# is always installed but only ever invoked (see entrypoint.sh) when
# CLOUDFLARE_TUNNEL_TOKEN is set — the direct-TCP path (Task 4) needs no
# Cloudflare account and stays completely unaffected by its presence.
# TARGETARCH is supplied automatically by Buildx and matches cloudflared's
# own release-asset naming (amd64/arm64/386/...).

RUN useradd -m -s /bin/bash -d /home/tunnel tunnel \
    && passwd -l tunnel

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY sshd_config.agent-gateway /etc/ssh/sshd_config.d/agent-gateway.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Strip setuid/setgid bits from the base image and packages above (mount,
# umount, passwd, chfn, gpasswd, newgrp, ...) — none of them are this image's
# own privilege mechanism. sshd runs as real root throughout (not via a
# setuid binary) and dnsmasq drops root->its own user via the CAP_SETUID/
# CAP_SETGID this container is granted directly, not through any setuid-bit
# binary, so both keep working unaffected. The build's own `passwd -l
# tunnel` step above already ran as root before this point, so it isn't
# affected either.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

EXPOSE 2222
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
