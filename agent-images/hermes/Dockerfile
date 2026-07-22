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
