FROM debian:trixie-slim

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
    && rm -rf /var/lib/apt/lists/*
# python3 isn't used by anything in this image — it's what sshuttle execs
# remotely over the SSH session from the claude-code side.

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
