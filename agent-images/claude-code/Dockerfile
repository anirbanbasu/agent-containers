FROM python:3.14-slim-trixie

ARG UID=1000
ARG GID=1000

# Node.js LTS (for the Claude Code CLI, an npm package) + firewall/DNS tooling
# used by entrypoint.sh to enforce the egress allowlist, plus gosu for
# dropping from root (needed to set up iptables/dnsmasq) to the claude user.
RUN apt-get update \
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
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN groupadd -g "$GID" claude \
    && useradd -m -u "$UID" -g "$GID" -s /bin/bash claude \
    && mkdir -p /home/claude/.claude /workspace \
    && chown -R claude:claude /home/claude /workspace

# gosu switches UID/GID but, unlike a login shell, does not reset $HOME —
# without this, plugin install (below) and the runtime `claude` process would
# both try to use root's $HOME instead of /home/claude.
ENV HOME=/home/claude

COPY plugins.txt /tmp/plugins.txt
RUN gosu claude claude plugin marketplace add anthropics/claude-plugins-official
RUN while IFS= read -r plugin; do \
        [ -z "$plugin" ] && continue; \
        gosu claude claude plugin install "${plugin}@claude-plugins-official" --scope user; \
    done < /tmp/plugins.txt \
    && rm /tmp/plugins.txt

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude"]
