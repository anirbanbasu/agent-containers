FROM python:3.12-slim-trixie AS base

ARG TARGETARCH

# Reuse the hardened workload baseline: egress enforcement, gateway-client
# support, and the non-root handoff. Node.js and uv remain available for
# project tooling and optional user-selected packages.
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
# system Python. Runs as root, before the aider user exists, since it
# writes into the image's system site-packages rather than $HOME.
COPY packages-uv.txt /tmp/packages-uv.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-uv.txt

# Aider 0.86.2 supports Python 3.10-3.12. Pin the CLI so a rebuild does not
# silently change the agent or its LLM-provider dependency graph. The default
# package deliberately excludes browser/Playwright extras: installing browser
# binaries at runtime is incompatible with the read-only-rootfs profile.
RUN python -m pip install --no-cache-dir 'aider-chat==0.86.2'

# The aider account is created here, at a fixed placeholder UID/GID
# (1000:1000), purely so the root-only installers below (npm, uv tool) have
# a real non-root account to run as. `final` remaps this account to the
# operator's actual host UID/GID instead of recreating it, so a rebuild for
# a different host user reuses everything installed below unchanged rather
# than reinstalling it over the network.
RUN groupadd -g 1000 aider \
    && useradd -m -u 1000 -g 1000 -s /bin/bash aider \
    && mkdir -p /workspace \
    && chown -R aider:aider /home/aider /workspace

ENV HOME=/home/aider
ENV npm_config_prefix=/home/aider/.npm-global
ENV PATH="/home/aider/.local/bin:/home/aider/.npm-global/bin:${PATH}"

# Aider would otherwise check for updates at startup and may offer to install
# Playwright dynamically. Both expand egress/write requirements without being
# necessary for the core terminal workflow. Analytics is disabled explicitly,
# rather than relying on Aider's prompt-driven opt-in behavior.
ENV AIDER_CHECK_UPDATE=false
ENV AIDER_ANALYTICS=false
ENV AIDER_DISABLE_PLAYWRIGHT=true

COPY packages-npm.txt /tmp/packages-npm.txt
COPY tools-uv.txt /tmp/tools-uv.txt
RUN gosu aider bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_tools /tmp/tools-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/tools-uv.txt

# Everything above this line is UID/GID-independent and layer-cacheable
# across hosts: the aider account exists at the fixed placeholder UID/GID
# only so the installers above have a non-root account to run as. From here
# down, `final` remaps that account to the operator's actual host UID/GID
# with --build-arg UID=$(id -u) --build-arg GID=$(id -g) — the base stage
# above is reused unchanged from cache, and nothing installed above is
# reinstalled, rather than rebuilding per host user.
FROM base AS final
ARG UID=1000
ARG GID=1000

# Only remap when the caller supplied a different UID/GID than the fixed
# placeholder baked into `base` above — usermod/groupmod plus a chown -R
# walk over already-installed content is far cheaper than rerunning the
# npm/uv-tool installs above, but it's skippable entirely for the common
# case where the caller never overrides UID/GID. Deliberately no -o:
# without it, usermod/groupmod refuse to reuse an ID already assigned to
# another account, so a caller can never remap aider onto UID/GID 0 (root)
# or collide it with another in-image identity — the build fails instead of
# silently succeeding.
RUN if [ "$UID" != "1000" ] || [ "$GID" != "1000" ]; then \
        groupmod -g "$GID" aider \
        && usermod -u "$UID" -g "$GID" aider \
        && chown -R "$UID":"$GID" /home/aider /workspace; \
    fi

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

ENTRYPOINT ["/usr/local/lib/agent/workload-entrypoint.sh", "aider", "aider"]
CMD ["aider"]
