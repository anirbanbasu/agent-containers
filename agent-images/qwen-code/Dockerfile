FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Node.js LTS installs Qwen Code. Python plus uv/uvx remain available for
# Python-based MCP servers and project tooling, matching the other Node-based
# workload images.
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

RUN npm install -g @qwen-code/qwen-code

RUN curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
      -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

RUN groupadd -g "$GID" qwen \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash qwen \
    && mkdir -p /home/qwen/.qwen /workspace \
    && chown -R qwen:qwen /home/qwen /workspace

ENV HOME=/home/qwen
ENV npm_config_prefix=/home/qwen/.npm-global
ENV PATH="/home/qwen/.local/bin:/home/qwen/.npm-global/bin:${PATH}"
# The outer container is the sandbox. Never let Qwen Code start a nested
# Docker/Podman sandbox, which would require access to a container runtime.
ENV QWEN_SANDBOX=false

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu qwen bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["qwen"]
