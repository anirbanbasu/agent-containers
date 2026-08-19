#!/bin/bash
set -euo pipefail

# No legacy-volume migration here (unlike agent-images/claude-code's
# entrypoint.sh): this image has no persistent claude-home volume to migrate
# in the first place — see run-agent-task.sh and ci-images/claude-code's
# notes on why $HOME is ephemeral in this variant.
exec /usr/local/lib/agent/workload-entrypoint.sh run-agent-task.sh claude "$@"
