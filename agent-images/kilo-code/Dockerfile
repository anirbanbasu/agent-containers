FROM python:3.14-slim-trixie AS base

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

# packages-uv.txt — general Python libraries (not CLI tools; see
# tools-uv.txt below), installed via `uv pip install --system` into this
# system Python. Runs as root, before the kilo user exists, since it writes
# into the image's system site-packages rather than $HOME.
COPY packages-uv.txt /tmp/packages-uv.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-uv.txt

RUN npm install -g @kilocode/cli

# Everything above this line is UID/GID-independent and layer-cacheable
# across hosts. From here down, the user identity is baked in, so operators
# on a host where they aren't UID/GID 1000 rebuild only this stage with
# --build-arg UID=$(id -u) --build-arg GID=$(id -g) — the base stage above
# is reused unchanged from cache rather than rebuilt per host user.
FROM base AS final
ARG UID=1000
ARG GID=1000

RUN groupadd -g "$GID" kilo \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash kilo \
    && mkdir -p /home/kilo/.config/kilo /workspace \
    && chown -R kilo:kilo /home/kilo /workspace

ENV HOME=/home/kilo
ENV npm_config_prefix=/home/kilo/.npm-global
ENV PATH="/home/kilo/.local/bin:/home/kilo/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY tools-uv.txt /tmp/tools-uv.txt
RUN gosu kilo bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_tools /tmp/tools-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/tools-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared workload-entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh
RUN chmod +x /usr/local/lib/agent/workload-entrypoint.sh

# Strip setuid/setgid bits from the base image and every package installed
# above — required infra (install-workload-base.sh), packages-apt.txt,
# packages-npm.txt, packages-uv.txt, and tools-uv.txt — run last so nothing
# installed by any of those is missed. NoNewPrivs=1 (set by every documented
# run invocation) already makes these bits inert on execve, but that's an
# argument for stripping them, not against: if any single control ever
# regresses, a setuid-root `mount` becomes a live escalation primitive. None
# of these binaries are needed at runtime, so none should ship
# exploitable-shaped.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

WORKDIR /workspace

ENTRYPOINT ["/usr/local/lib/agent/workload-entrypoint.sh", "kilo", "kilo"]
CMD ["kilo"]
