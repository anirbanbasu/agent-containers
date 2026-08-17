#!/bin/bash
# Shared by the workload-image Dockerfiles. Build-time only, unlike
# egress-allowlist.sh: invoked directly during `docker build`, never sourced
# at runtime. Installs each image's
# user-configurable default software from plain package-list files (one
# entry per line, '#' comments, blank lines ignored) — same convention as
# plugins.txt. Each function no-ops if its file is missing or has no
# non-comment entries, so an image can ship empty lists at zero cost.

# Inherited by whatever sources this file, so a failed apt-get/npm/uv install
# aborts the build immediately instead of being masked by a later command
# (e.g. `rm -rf /var/lib/apt/lists/*`) that succeeds regardless.
set -e

install_apt_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local -a packages
    mapfile -t packages < <(grep -v '^[[:space:]]*#' "$file" \
        | grep -v '^[[:space:]]*$' \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    [ "${#packages[@]}" -eq 0 ] && return 0
    apt-get update
    apt-get install -y --no-install-recommends "${packages[@]}"
    rm -rf /var/lib/apt/lists/*
}

install_npm_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local line package
    while IFS= read -r line; do
        # sed, not xargs, to trim -- xargs parses its input for shell-style
        # quoting, which breaks on ordinary text like "there's" or "'#'" in
        # this file's own comment lines.
        package="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        case "$package" in ''|'#'*) continue ;; esac
        npm install -g "$package"
    done < "$file"
}

install_uv_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local line package
    # uv doesn't batch multi-package installs the way apt/npm do — each
    # package gets its own isolated venv, so this must be one call per line.
    while IFS= read -r line; do
        package="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        case "$package" in ''|'#'*) continue ;; esac
        uv tool install "$package"
    done < "$file"
}
