#!/bin/bash
# Shared support for installing additional packages in workload-image
# Dockerfiles. Build-time only, unlike
# egress-allowlist.sh: invoked directly during `docker build`, never sourced
# at runtime. Installs each image's
# user-configurable default software from plain package-list files (one
# entry per line, '#' comments, blank lines ignored) — same convention as
# plugins.txt. Each function no-ops if its file is missing or has no
# non-comment entries, so an image can ship empty lists at zero cost.
#
# Two distinct uv-backed installers exist because `uv tool install` and
# `uv pip install --system` put packages in fundamentally incompatible
# places: install_uv_tools gives each entry its own isolated venv (only that
# entry's own console-script wrapper ends up on PATH — nothing importable
# lands anywhere shared), while install_uv_packages installs into the one
# shared system Python so entries can `import` each other and whatever else
# runs in that interpreter. A library with no console-script entry point
# (e.g. a plain SDK) has no wrapper to run in isolation, so it belongs in
# packages-uv.txt/install_uv_packages, not tools-uv.txt/install_uv_tools.

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

install_uv_tools() {
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

install_uv_packages() {
    local file="$1"
    [ -s "$file" ] || return 0
    local -a packages
    mapfile -t packages < <(grep -v '^[[:space:]]*#' "$file" \
        | grep -v '^[[:space:]]*$' \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    [ "${#packages[@]}" -eq 0 ] && return 0
    # --system, unlike uv tool install: lands in the one shared system Python
    # so entries can import each other and whatever else runs in that
    # interpreter. Batched in one resolve/install, same as apt/npm, since
    # there's no per-entry isolation to force one-call-per-line here.
    uv pip install --system "${packages[@]}"
}
