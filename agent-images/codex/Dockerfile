FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Shared Node.js, containment, gateway-client, and cloudflared baseline for
# the first-party Python-and-Node workload images.
COPY --from=shared install-node-workload-base.sh /usr/local/lib/agent/install-node-workload-base.sh
RUN TARGETARCH="$TARGETARCH" bash /usr/local/lib/agent/install-node-workload-base.sh

COPY --from=shared install-packages.sh /usr/local/lib/agent/install-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

# Keep Python tooling available for Python-based MCP servers and project work,
# matching the other first-party CLI workload image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN npm install -g @openai/codex

RUN groupadd -g "$GID" codex \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash codex \
    && mkdir -p /home/codex/.codex /workspace \
    && chown -R codex:codex /home/codex /workspace

ENV HOME=/home/codex
ENV npm_config_prefix=/home/codex/.npm-global
ENV PATH="/home/codex/.local/bin:/home/codex/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu codex bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared node-workload-entrypoint.sh /usr/local/lib/agent/node-workload-entrypoint.sh
RUN chmod +x /usr/local/lib/agent/node-workload-entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/lib/agent/node-workload-entrypoint.sh", "codex", "codex"]
CMD ["codex"]
