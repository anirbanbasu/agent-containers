#!/bin/bash
# Shared build-time baseline for the first-party Python-and-Node workload
# images: adal, claude-code, codex, kilo-code, opencode, and qwen-code. Keep this
# separate from install-additional-packages.sh: this file owns required
# containment and runtime infrastructure, whereas that script consumes each
# image's optional user-selected package lists.

set -euo pipefail

: "${TARGETARCH:?TARGETARCH must be set by the Dockerfile}"

# Node.js installs each image's CLI. The remaining packages support the
# in-container egress allowlist, the optional gateway tunnel, and gosu's
# privilege drop after root installs those firewall rules.
apt-get update
apt-get upgrade -y
apt-get install -y --no-install-recommends \
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
    sshuttle
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt-get install -y --no-install-recommends nodejs
rm -rf /var/lib/apt/lists/*

# cloudflared is only invoked when AGENT_GATEWAY_ACCESS_HOSTNAME is set, but
# installing it in every workload keeps the gateway-client contract uniform.
# TARGETARCH is supplied automatically by Buildx and matches Cloudflare's
# release-asset naming (amd64/arm64/386/...).
curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
    -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
