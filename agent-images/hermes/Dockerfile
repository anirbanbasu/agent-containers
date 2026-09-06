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

# Optional profile-managed organisational CAs; see claude-code/Dockerfile.
COPY proxy-ca.d/ /tmp/agent-containers-proxy-ca/
RUN set -eu; \
    mkdir -p /usr/local/share/ca-certificates/custom; \
    found=0; \
    for cert in /tmp/agent-containers-proxy-ca/*; do \
        [ -f "$cert" ] || continue; \
        name="$(basename "$cert")"; \
        [ "$name" = ".keep" ] && continue; \
        case "$name" in *.crt) ;; *) name="${name%.*}.crt" ;; esac; \
        cp "$cert" "/usr/local/share/ca-certificates/custom/$name"; \
        found=1; \
    done; \
    if [ "$found" -eq 1 ]; then update-ca-certificates; fi; \
    rm -rf /tmp/agent-containers-proxy-ca

# User-configurable default software (gh, jq, ripgrep, ...) — see
# packages-apt.txt. Kept as a separate RUN from the baseline block above so
# the required-infra list stays untouched by editing that file.
COPY --from=shared install-additional-packages.sh /usr/local/lib/agent/install-additional-packages.sh
COPY packages-apt.txt /tmp/packages-apt.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_apt_packages /tmp/packages-apt.txt' \
    && rm -f /tmp/packages-apt.txt

# packages-uv.txt — general Python libraries (not CLI tools; see
# tools-uv.txt below), installed via `uv pip install --system` into
# upstream's system Python (already on PATH in this base image — no
# separate uv/uvx COPY needed here, unlike claude-code). Runs as root, since
# it writes into the image's system site-packages rather than $HOME.
COPY packages-uv.txt /tmp/packages-uv.txt
RUN bash -c '. /usr/local/lib/agent/install-additional-packages.sh \
        && install_uv_packages /tmp/packages-uv.txt' \
    && rm -f /tmp/packages-uv.txt

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
# Home-managed installations intentionally precede profile-managed tools. The
# latter are image-owned under /opt so a populated data volume cannot hide a
# rebuilt profile image's requested versions.
ENV PATH="/opt/data/.local/bin:/opt/data/.npm-global/bin:/opt/agent-tools/bin:/opt/agent-tools/npm/bin:${PATH}"

# $HOME (uv's default cache location) and /workspace are deliberately
# separate mounts in this containment model, so uv's hardlink/reflink
# optimisation can never apply between them — declare the copy fallback
# explicit rather than have uv warn about it on every install.
ENV UV_LINK_MODE=copy

# packages-npm.txt / tools-uv.txt — see packages-apt.txt above. These managed
# tools are deliberately separate from /opt/data, the upstream persistent home.
COPY packages-npm.txt /tmp/packages-npm.txt
COPY tools-uv.txt /tmp/tools-uv.txt
RUN mkdir -p /opt/agent-tools/npm /opt/agent-tools/uv-tools /opt/agent-tools/bin \
    && chown -R hermes:hermes /opt/agent-tools \
    && su hermes -s /bin/bash -c 'export \
        npm_config_prefix=/opt/agent-tools/npm \
        UV_TOOL_DIR=/opt/agent-tools/uv-tools \
        UV_TOOL_BIN_DIR=/opt/agent-tools/bin; \
        . /usr/local/lib/agent/install-additional-packages.sh \
        && install_npm_packages /tmp/packages-npm.txt \
        && install_uv_tools /tmp/tools-uv.txt' \
    && rm -f /tmp/packages-npm.txt /tmp/tools-uv.txt

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

# Strip setuid/setgid bits picked up from upstream's base image and the
# packages installed above (mount, passwd, su, ...). --security-opt
# no-new-privileges (every documented run invocation) already makes these
# inert on execve; stripping them removes the exploitable shape instead of
# relying solely on that flag never regressing. Safe after this point:
# upstream's runtime privilege drop is s6-setuidgid, which runs as root
# under the container's own granted CAP_SETUID/CAP_SETGID rather than
# through any setuid-bit binary.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

# No useradd/UID build-arg here (unlike claude-code): upstream already
# ships its own non-root user (hermes, UID 10000, home /opt/data) and its
# own privilege-drop chain; see entrypoint.sh. CMD is deliberately left at
# whatever upstream's own image sets it to, so every documented invocation
# shape keeps working unmodified.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
