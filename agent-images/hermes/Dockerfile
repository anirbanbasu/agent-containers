FROM nousresearch/hermes-agent:latest

ARG TARGETARCH

# iptables/ipset/dnsmasq/dnsutils enforce the in-container egress allowlist;
# openssh-client/sshuttle are the gateway-client tunnel (see entrypoint.sh);
# curl fetches cloudflared below. Upstream's own Node/Python/Playwright
# toolchain and its s6-overlay boot sequence are untouched by any of this —
# it only adds the network-containment layer claude-code also has.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        iptables \
        ipset \
        dnsmasq \
        dnsutils \
        openssh-client \
        sshuttle \
    && rm -rf /var/lib/apt/lists/*

# User-configurable default software (gh, jq, ripgrep, ...) — see
# packages-apt.txt. Kept as a separate RUN from the baseline block above so
# the required-infra list stays untouched by editing that file.
COPY --from=shared install-packages.sh /usr/local/lib/agent/install-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

# Unlike claude-code, this image has no build-time privilege-drop tool
# installed (upstream's own runtime drop uses s6-setuidgid, not gosu) — `su`,
# already present in the base image, does the same job here without adding a
# new apt dependency. HOME/npm_config_prefix/PATH point at /opt/data
# (upstream's HERMES_HOME, already owned by the hermes user at this layer)
# so npm/uv installs below, and any further installs the hermes user makes
# at runtime, land there instead of under root's home or the read-only
# rootfs.
ENV HOME=/opt/data
ENV npm_config_prefix=/opt/data/.npm-global
ENV PATH="/opt/data/.local/bin:/opt/data/.npm-global/bin:${PATH}"

# packages-npm.txt / packages-uv.txt — see packages-apt.txt above.
COPY packages-npm.txt /tmp/packages-npm.txt
COPY packages-uv.txt /tmp/packages-uv.txt
RUN su hermes -s /bin/bash -c '. /usr/local/lib/agent/install-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/packages-uv.txt

# cloudflared is always installed but only invoked (see entrypoint.sh) when
# AGENT_GATEWAY_ACCESS_HOSTNAME is set, as an alternative to reaching the
# gateway by direct TCP — TARGETARCH is supplied automatically by Buildx and
# matches cloudflared's own release-asset naming (amd64/arm64/386/...).
RUN curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH}" \
      -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

COPY --from=shared egress-allowlist.sh /usr/local/lib/agent/egress-allowlist.sh

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# No useradd/UID build-arg here (unlike claude-code): upstream already
# ships its own non-root user (hermes, UID 10000, home /opt/data) and its
# own privilege-drop chain; see entrypoint.sh. CMD is deliberately left at
# whatever upstream's own image sets it to, so every documented invocation
# shape keeps working unmodified.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
