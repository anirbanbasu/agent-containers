#!/bin/bash
# Shared by agent-images/claude-code/Dockerfile and agent-images/hermes/Dockerfile.
# Build-time only, unlike egress-allowlist.sh: invoked directly during
# `docker build`, never sourced at runtime. Installs each image's
# user-configurable default software from plain package-list files (one
# entry per line, '#' comments, blank lines ignored) — same convention as
# plugins.txt. Each function no-ops if its file is missing or has no
# non-comment entries, so an image can ship empty lists at zero cost.

install_apt_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local -a packages
    mapfile -t packages < <(grep -v '^\s*#' "$file" | grep -v '^\s*$')
    [ "${#packages[@]}" -eq 0 ] && return 0
    apt-get update
    apt-get install -y --no-install-recommends "${packages[@]}"
    rm -rf /var/lib/apt/lists/*
}

install_npm_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local package
    while IFS= read -r package; do
        case "$package" in ''|'#'*) continue ;; esac
        npm install -g "$package"
    done < "$file"
}

install_uv_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local package
    # uv doesn't batch multi-package installs the way apt/npm do — each
    # package gets its own isolated venv, so this must be one call per line.
    while IFS= read -r package; do
        case "$package" in ''|'#'*) continue ;; esac
        uv tool install "$package"
    done < "$file"
}
