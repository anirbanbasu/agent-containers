FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000
ARG TARGETARCH

# Node.js LTS (for the Claude Code CLI, an npm package) + firewall/DNS tooling
# used by entrypoint.sh to enforce the egress allowlist, plus gosu for
# dropping from root (needed to set up iptables/dnsmasq) to the claude user.
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

# uv/uvx (Python package & venv manager), copied in rather than switching
# the base image — uv manages venvs against this image's existing system
# Python just as well as against a uv-provisioned one, without disturbing
# the apt/Node.js setup above.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN npm install -g @anthropic-ai/claude-code

# cloudflared is always installed but only invoked (see entrypoint.sh) when
# CLAUDE_GATEWAY_ACCESS_HOSTNAME is set, as an alternative to reaching the
# gateway by direct TCP — TARGETARCH is supplied automatically by Buildx and
# matches cloudflared's own release-asset naming (amd64/arm64/386/...).
RUN curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
      -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

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
ENV PATH="/home/claude/.npm-global/bin:${PATH}"

COPY --from=shared egress-allowlist.sh /usr/local/lib/claude/egress-allowlist.sh

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
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
