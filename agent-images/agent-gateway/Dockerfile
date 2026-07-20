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
        gosu \
        curl \
    && curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
         -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && rm -rf /var/lib/apt/lists/*
# python3 isn't used by anything in this image — it's what sshuttle execs
# remotely over the SSH session from the claude-code side. gosu lets the
# entrypoint (root) install authorized_keys as the tunnel user itself (see
# entrypoint.sh) rather than chowning it there as root — sshd's pubkey check
# reads authorized_keys back as the login user, so the file has to be
# genuinely tunnel-owned, and chowning it as root at runtime would need
# CAP_CHOWN, which --cap-drop=ALL doesn't grant back. cloudflared is always
# installed but only ever invoked (see entrypoint.sh) when
# CLOUDFLARE_TUNNEL_TOKEN is set — the direct-TCP path (Task 4) needs no
# Cloudflare account and stays completely unaffected by its presence.
# TARGETARCH is supplied automatically by Buildx and matches cloudflared's
# own release-asset naming (amd64/arm64/386/...).

RUN useradd -m -s /bin/bash -d /home/tunnel tunnel \
    && passwd -l tunnel \
    && mkdir -p /home/tunnel/.ssh \
    && chmod 700 /home/tunnel/.ssh \
    && chown -R tunnel:tunnel /home/tunnel

COPY --from=shared egress-allowlist.sh /usr/local/lib/claude/egress-allowlist.sh
COPY sshd_config.agent-gateway /etc/ssh/sshd_config.d/agent-gateway.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 2222
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
