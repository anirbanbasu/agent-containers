FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Node.js LTS installs Kilo CLI. Python plus uv/uvx are included for
# Python-based MCP servers and project tooling, matching the other Node-based
# workload images. The remaining packages provide the shared egress allowlist,
# gateway-client mode, and the privilege drop after their setup completes.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        iptables \
        ipset \
        dnsmasq \
        dnsutils \
        gosu \
        openssh-client \
        sshuttle \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=shared install-packages.sh /usr/local/lib/agent/install-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN npm install -g @kilocode/cli

RUN curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
      -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

RUN groupadd -g "$GID" kilo \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash kilo \
    && mkdir -p /home/kilo/.config/kilo /workspace \
    && chown -R kilo:kilo /home/kilo /workspace

ENV HOME=/home/kilo
ENV npm_config_prefix=/home/kilo/.npm-global
ENV PATH="/home/kilo/.local/bin:/home/kilo/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu kilo bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["kilo"]
