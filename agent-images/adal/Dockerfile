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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The official npm fallback ships the platform-specific AdaL runtime as an
# optional dependency. Pin it so rebuilding does not silently change the CLI.
RUN npm install -g @sylphai/adal-cli@1.7.1

RUN groupadd -g "$GID" adal \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash adal \
    && mkdir -p /home/adal/.adal /workspace \
    && chown -R adal:adal /home/adal /workspace

ENV HOME=/home/adal
ENV npm_config_prefix=/home/adal/.npm-global
ENV PATH="/home/adal/.local/bin:/home/adal/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu adal bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared workload-entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh
RUN chmod +x /usr/local/lib/agent/workload-entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/lib/agent/workload-entrypoint.sh", "adal", "adal"]
CMD ["adal"]
