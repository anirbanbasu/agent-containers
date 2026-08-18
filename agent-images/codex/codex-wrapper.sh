#!/bin/sh

# The outer container provides the filesystem and process sandbox. Avoid
# starting Codex's nested sandbox, which cannot create its required namespaces
# under the container's deliberately restricted runtime security flags. Keep
# an explicit caller-selected sandbox mode intact.
for arg in "$@"; do
  case "$arg" in
    --sandbox|--sandbox=*|-s) exec /usr/local/bin/codex-cli "$@" ;;
  esac
done

exec /usr/local/bin/codex-cli --sandbox danger-full-access "$@"
