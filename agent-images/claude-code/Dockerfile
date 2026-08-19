FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Shared Node.js, containment, gateway-client, and cloudflared baseline for
# the first-party Python-and-Node workload images.
COPY --from=shared install-workload-base.sh /usr/local/lib/agent/install-workload-base.sh
RUN TARGETARCH="$TARGETARCH" bash /usr/local/lib/agent/install-workload-base.sh

# User-configurable default software (gh, jq, ripgrep, ...) — see
# packages-apt.txt. Kept as a separate RUN from the baseline block above so
# the required-infra list stays untouched by editing that file.
COPY --from=shared install-additional-packages.sh /usr/local/lib/agent/install-additional-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

# uv/uvx (Python package & venv manager), copied in rather than switching
# the base image — uv manages venvs against this image's existing system
# Python just as well as against a uv-provisioned one, without disturbing
# the apt/Node.js setup above.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN npm install -g @anthropic-ai/claude-code

RUN groupadd -g "$GID" claude \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash claude \
    && mkdir -p /home/claude/.claude /workspace \
    && chown -R claude:claude /home/claude /workspace

# gosu switches UID/GID but, unlike a login shell, does not reset $HOME —
# without this, plugin install (below) and the runtime `claude` process would
# both try to use root's $HOME instead of /home/claude.
ENV HOME=/home/claude

# npm's default global-install prefix (/usr/local) sits on the read-only
# rootfs at runtime; repoint it to a location under the claude user's home
# so `npm install -g` works there instead. This doesn't affect the
# `npm install -g @anthropic-ai/claude-code` above, which already ran as
# root before this user/prefix existed. Set via ENV (not `npm config set`,
# which would only write ~/.npmrc into the image — that file wouldn't reach
# a volume that already has content the first time it's mounted here, since
# Docker's volume copy-up only seeds genuinely empty volumes) so the prefix
# applies regardless of what's already in the mounted $HOME volume.
ENV npm_config_prefix=/home/claude/.npm-global
ENV PATH="/home/claude/.local/bin:/home/claude/.npm-global/bin:${PATH}"

# packages-npm.txt / packages-uv.txt — see packages-apt.txt above. Run as the
# claude user (not root) so npm/uv installs land under $HOME, per the ENV
# block just above.
COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu claude bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared workload-entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh

COPY plugin-marketplaces.txt /tmp/plugin-marketplaces.txt
COPY plugins.txt /tmp/plugins.txt

# The official marketplace is always available; plugin-marketplaces.txt lists
# any additional (non-official) marketplaces to add before installing plugins,
# since plugins.txt entries may reference any of them via "<plugin>@<marketplace>".
RUN gosu claude claude plugin marketplace add anthropics/claude-plugins-official \
    && while IFS= read -r marketplace; do \
        case "$marketplace" in ''|'#'*) continue ;; esac; \
        gosu claude claude plugin marketplace add "${marketplace}"; \
    done < /tmp/plugin-marketplaces.txt \
    && while IFS= read -r plugin; do \
        case "$plugin" in ''|'#'*) continue ;; esac; \
        gosu claude claude plugin install "${plugin}" --scope user; \
    done < /tmp/plugins.txt \
    && rm /tmp/plugin-marketplaces.txt /tmp/plugins.txt

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh

# Strip setuid/setgid bits from the base image and every package installed
# above — required infra (install-workload-base.sh), packages-apt.txt,
# packages-npm.txt, packages-uv.txt, and installed plugins — run last so
# nothing installed by any of those is missed. NoNewPrivs=1 (set by every
# documented run invocation) already makes these bits inert on execve, but
# that's an argument for stripping them, not against: if any single control
# ever regresses, a setuid-root `mount` becomes a live escalation primitive.
# None of these binaries are needed at runtime, so none should ship
# exploitable-shaped.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
