FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Shared Node.js, containment, gateway-client, and cloudflared baseline —
# identical to agent-images/claude-code's, since a CI run needs the same
# egress/process containment as an interactive session, just no interactive
# session on top.
COPY --from=shared install-workload-base.sh /usr/local/lib/agent/install-workload-base.sh
RUN TARGETARCH="$TARGETARCH" bash /usr/local/lib/agent/install-workload-base.sh

# packages-apt.txt keeps agent-images/claude-code's default list — `gh` is
# required (PR creation), the rest (jq, ripgrep, ...) are generically useful
# for a fix task and cheap to keep for parity with the interactive image.
COPY --from=shared install-additional-packages.sh /usr/local/lib/agent/install-additional-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN npm install -g @anthropic-ai/claude-code

RUN groupadd -g "$GID" claude \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash claude \
    && mkdir -p /home/claude/.claude /workspace \
    && chown -R claude:claude /home/claude /workspace

ENV HOME=/home/claude
ENV npm_config_prefix=/home/claude/.npm-global
ENV PATH="/home/claude/.local/bin:/home/claude/.npm-global/bin:${PATH}"

COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN gosu claude bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh
COPY --from=shared workload-entrypoint.sh /usr/local/lib/agent/workload-entrypoint.sh

# No plugins.txt/plugin-marketplaces.txt layer here: a one-shot headless run
# has no interactive session for a plugin to extend, and every plugin added
# here is one more thing with build-time network access and runtime file
# access to vet. Add it back deliberately if a specific CI task needs one.

# Enterprise managed policy settings — highest-precedence permission layer
# Claude Code has, above --permission-mode and any settings.json in $HOME.
# Baked into the read-only rootfs (root-owned, not under /home/claude, which
# is a --tmpfs mount the claude user can write to) so it cannot be edited or
# shadowed at runtime, by the agent or by a project's own .claude/settings*.
# Denies actions that stay inside the container's own containment but would
# be bad for the *code* it's operating on or the repo's CI configuration —
# see docs/continuous-integration-images/claude-code.md for the reasoning
# and for what this file deliberately does not cover.
COPY managed-settings.json /etc/claude-code/managed-settings.json

COPY ci-entrypoint.sh /usr/local/bin/ci-entrypoint.sh
COPY run-agent-task.sh /usr/local/bin/run-agent-task.sh
RUN chmod +x /usr/local/bin/ci-entrypoint.sh /usr/local/bin/run-agent-task.sh \
    /usr/local/lib/agent/workload-entrypoint.sh

RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/ci-entrypoint.sh"]
CMD []
