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

RUN npm install -g @kilocode/cli

RUN groupadd -g "$GID" kilo \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash kilo \
    && mkdir -p /home/kilo/.config/kilo /workspace \
    && chown -R kilo:kilo /home/kilo /workspace

ENV HOME=/home/kilo
ENV npm_config_prefix=/home/kilo/.npm-global
ENV PATH="/home/kilo/.local/bin:/home/kilo/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu kilo bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared workload-entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh
RUN chmod +x /usr/local/lib/agent/workload-entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/lib/agent/workload-entrypoint.sh", "kilo", "kilo"]
CMD ["kilo"]
