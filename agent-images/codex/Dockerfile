FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Shared Node.js, containment, gateway-client, and cloudflared baseline for
# the first-party Python-and-Node workload images.
COPY --from=shared install-workload-base.sh /usr/local/lib/agent/install-workload-base.sh
RUN TARGETARCH="$TARGETARCH" bash /usr/local/lib/agent/install-workload-base.sh

COPY --from=shared install-additional-packages.sh /usr/local/lib/agent/install-additional-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

# Keep Python tooling available for Python-based MCP servers and project work,
# matching the other first-party CLI workload image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN npm install -g @openai/codex \
    && codex_path="$(command -v codex)" \
    && codex_target="$(readlink -f "$codex_path")" \
    && ln -s "$codex_target" /usr/local/bin/codex-cli \
    && rm -f "$codex_path"

COPY codex-wrapper.sh /usr/local/bin/codex
RUN chmod +x /usr/local/bin/codex

RUN groupadd -g "$GID" codex \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash codex \
    && mkdir -p /home/codex/.codex /workspace \
    && chown -R codex:codex /home/codex /workspace

ENV HOME=/home/codex
ENV npm_config_prefix=/home/codex/.npm-global
ENV PATH="/home/codex/.local/bin:/home/codex/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu codex bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared workload-entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh
RUN chmod +x /usr/local/lib/agent/workload-entrypoint.sh

# Strip setuid/setgid bits from the base image and every package installed
# above — required infra (install-workload-base.sh), packages-apt.txt,
# packages-npm.txt, and packages-uv.txt — run last so nothing installed by
# any of those is missed. NoNewPrivs=1 (set by every documented run
# invocation) already makes these bits inert on execve, but that's an
# argument for stripping them, not against: if any single control ever
# regresses, a setuid-root `mount` becomes a live escalation primitive. None
# of these binaries are needed at runtime, so none should ship
# exploitable-shaped.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

WORKDIR /workspace

ENTRYPOINT ["/usr/local/lib/agent/workload-entrypoint.sh", "codex", "codex"]
CMD ["codex"]
