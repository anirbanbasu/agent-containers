#!/bin/bash
# Local Docker test matrix for the workload images. It intentionally uses no
# agent credentials or public test endpoint: containment probes target two
# throwaway HTTP servers on an isolated Docker network.

set -euo pipefail

readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RUN_ID="$$-$(date +%s)"
readonly TEST_NETWORK="agent-containers-test-${RUN_ID}"
readonly TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-containers-test.XXXXXX")"

readonly -a ALL_IMAGES=(adal aider claude-code codex hermes kilo-code opencode qwen-code agent-gateway volume-bridge)
readonly -a WORKLOADS=(
    'adal:adal:/home/adal:adal'
    'aider:aider:/home/aider:aider'
    'claude-code:claude:/home/claude:claude'
    'codex:codex:/home/codex:codex'
    'kilo-code:kilo:/home/kilo:kilo'
    'opencode:opencode:/home/opencode:opencode'
    'qwen-code:qwen:/home/qwen:qwen'
)

declare -a built_images=()
declare -a test_volumes=()
declare -a test_containers=()
GATEWAY_CONTAINER=''

fail() {
    echo "[test-images] ERROR: $*" >&2
    exit 1
}

image_tag() {
    printf 'agent-containers-test/%s:%s\n' "$1" "$RUN_ID"
}

track_volume() {
    test_volumes+=("$1")
    docker volume create "$1" >/dev/null
}

cleanup() {
    local container volume image
    for container in "${test_containers[@]-}"; do
        [ -n "$container" ] || continue
        docker rm -f "$container" >/dev/null 2>&1 || true
    done
    docker network rm "$TEST_NETWORK" >/dev/null 2>&1 || true
    for volume in "${test_volumes[@]-}"; do
        [ -n "$volume" ] || continue
        docker volume rm "$volume" >/dev/null 2>&1 || true
    done
    for image in "${built_images[@]-}"; do
        [ -n "$image" ] || continue
        docker image rm -f "$image" >/dev/null 2>&1 || true
    done
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

require_docker() {
    command -v docker >/dev/null || fail 'Docker is required.'
    docker info >/dev/null || fail 'Docker is installed but its daemon is unavailable.'
}

run_static_checks() {
    local -a scripts=()
    local script
    while IFS= read -r script; do
        scripts+=("$script")
    done < <(find "$ROOT_DIR/agent-images" "$ROOT_DIR/scripts" -type f -name '*.sh' -print)
    bash -n "${scripts[@]}"
    git -C "$ROOT_DIR" diff --check
}

build_images() {
    local image tag
    require_docker
    for image in "${ALL_IMAGES[@]}"; do
        tag="$(image_tag "$image")"
        echo "[test-images] Building $image"
        docker build \
            --quiet \
            --build-context "shared=$ROOT_DIR/agent-images/shared" \
            --tag "$tag" \
            "$ROOT_DIR/agent-images/$image"
        built_images+=("$tag")
    done
}

ensure_network() {
    docker network inspect "$TEST_NETWORK" >/dev/null 2>&1 \
        || docker network create "$TEST_NETWORK" >/dev/null
}

workload_volume_name() {
    printf 'agent-containers-test-%s-%s-%s\n' "$RUN_ID" "$1" "$2"
}

run_workload() {
    local image="$1"
    local home="$2"
    local allowlist="$3"
    shift 3

    # OpenCode and Kilo's OpenTUI renderers dynamically load a native library
    # from /tmp. Docker mounts tmpfs with noexec by default, so their
    # documented hardened invocations need this narrow exception.
    local tmpfs_tmp=/tmp
    case "$image" in
        kilo-code|opencode) tmpfs_tmp=/tmp:exec ;;
    esac

    local home_volume workspace_volume
    home_volume="$(workload_volume_name "$image" home)"
    workspace_volume="$(workload_volume_name "$image" workspace)"
    if ! docker volume inspect "$home_volume" >/dev/null 2>&1; then
        track_volume "$home_volume"
        track_volume "$workspace_volume"
    fi

    local -a command=(
        docker run --rm --network "$TEST_NETWORK"
        --security-opt=no-new-privileges
        --read-only --tmpfs "$tmpfs_tmp" --tmpfs /run
        --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID
        --mount "type=volume,src=$home_volume,dst=$home"
        --mount "type=volume,src=$workspace_volume,dst=/workspace"
    )
    if [ -n "$allowlist" ]; then
        command+=(-e "AGENT_ALLOWED_EGRESS=$allowlist")
    fi
    command+=("$(image_tag "$image")" "$@")
    "${command[@]}"
}

wait_for_running() {
    local container="$1"
    local attempt
    for attempt in $(seq 1 20); do
        if [ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" = true ]; then
            return 0
        fi
        sleep 1
    done
    docker logs "$container" >&2 || true
    fail "$container did not remain running."
}

smoke_workloads() {
    ensure_network
    local spec image user home cli
    for spec in "${WORKLOADS[@]}"; do
        IFS=: read -r image user home cli <<< "$spec"
        echo "[test-images] Smoke testing $image"
        run_workload "$image" "$home" '' --version >/dev/null
        run_workload "$image" "$home" '' sh -ceu '
            test "$(id -un)" = "$0"
            test -w "$HOME"
            grep -Eq "^[^ ]+ / [^ ]+ ro[, ]" /proc/mounts
            grep -Eq "^CapEff:[[:space:]]*0{16}$" /proc/self/status
        ' "$user"
    done
}

smoke_hermes() {
    ensure_network
    local volume="agent-containers-test-${RUN_ID}-hermes-data"
    local container="agent-containers-test-${RUN_ID}-hermes"
    track_volume "$volume"
    test_containers+=("$container")
    echo '[test-images] Smoke testing hermes'
    docker run -d --name "$container" --network "$TEST_NETWORK" \
        --security-opt=no-new-privileges \
        --read-only --tmpfs /tmp --tmpfs /run:exec \
        --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
        --cap-add=CHOWN --cap-add=DAC_OVERRIDE \
        --mount "type=volume,src=$volume,dst=/opt/data" \
        "$(image_tag hermes)" >/dev/null
    wait_for_running "$container"
}

write_gateway_known_hosts() {
    local gateway_container="$1"
    local hostname="$2"
    local output="$3"
    printf '%s ' "$hostname" > "$output"
    docker exec "$gateway_container" cat /etc/ssh/keys/ssh_host_ed25519_key.pub >> "$output"
}

start_gateway() {
    ensure_network
    local gateway_public_key="$1"
    local allowlist="$2"
    local container="agent-containers-test-${RUN_ID}-gateway"
    local volume="agent-containers-test-${RUN_ID}-gateway-hostkeys"
    track_volume "$volume"
    test_containers+=("$container")
    docker run -d --name "$container" --network "$TEST_NETWORK" --network-alias gateway \
        --security-opt=no-new-privileges \
        --read-only --tmpfs /tmp --tmpfs /run \
        --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID --cap-add=SYS_CHROOT \
        -e "AGENT_ALLOWED_EGRESS=$allowlist" \
        --mount "type=bind,src=$gateway_public_key,dst=/etc/agent/gateway-key.pub,readonly" \
        --mount "type=volume,src=$volume,dst=/etc/ssh/keys" \
        "$(image_tag agent-gateway)" >/dev/null
    wait_for_running "$container"
    GATEWAY_CONTAINER="$container"
}

smoke_gateway() {
    local key="$TEMP_DIR/gateway-key"
    local known_hosts="$TEMP_DIR/gateway-known-hosts"
    ssh-keygen -q -t ed25519 -N '' -f "$key"
    start_gateway "$key.pub" 'allowed.test'
    write_gateway_known_hosts "$GATEWAY_CONTAINER" gateway "$known_hosts"
    echo '[test-images] Smoke testing agent-gateway SSH authentication'
    docker run --rm --network "$TEST_NETWORK" \
        --mount "type=bind,src=$key,dst=/tmp/gateway-key,readonly" \
        --mount "type=bind,src=$known_hosts,dst=/tmp/gateway-known-hosts,readonly" \
        --entrypoint ssh "$(image_tag codex)" \
        -i /tmp/gateway-key -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/gateway-known-hosts \
        tunnel@gateway id -un | grep -qx tunnel
}

smoke_volume_bridge() {
    local container="agent-containers-test-${RUN_ID}-volume-bridge"
    local volume="agent-containers-test-${RUN_ID}-volume-bridge-state"
    local key="$TEMP_DIR/volume-bridge-key"
    track_volume "$volume"
    test_containers+=("$container")
    ssh-keygen -q -t ed25519 -N '' -f "$key"
    echo '[test-images] Smoke testing volume-bridge'
    docker run -d --name "$container" --network "$TEST_NETWORK" \
        --security-opt=no-new-privileges \
        --read-only --tmpfs /tmp --tmpfs /run \
        --cap-drop=ALL \
        -e "VOLUME_BRIDGE_AUTHORIZED_KEY=$(cat "$key.pub")" \
        --mount "type=volume,src=$volume,dst=/state" \
        "$(image_tag volume-bridge)" >/dev/null
    wait_for_running "$container"
    docker exec "$container" sh -ceu '
        test "$(id -un)" = bridge
        test -s /state/authorized_keys
        test -s /state/ssh_host_ed25519_key
        grep -Eq "^[^ ]+ / [^ ]+ ro[, ]" /proc/mounts
        grep -Eq "^CapEff:[[:space:]]*0{16}$" /proc/self/status
    '
}

start_http_server() {
    local name="$1"
    local alias="$2"
    test_containers+=("$name")
    docker run -d --name "$name" --network "$TEST_NETWORK" --network-alias "$alias" \
        --entrypoint python "$(image_tag codex)" \
        -m http.server 8080 --bind 0.0.0.0 >/dev/null
    wait_for_running "$name"
}

run_containment_tests() {
    ensure_network
    local allowed="agent-containers-test-${RUN_ID}-allowed"
    local blocked="agent-containers-test-${RUN_ID}-blocked"
    start_http_server "$allowed" allowed.test
    start_http_server "$blocked" blocked.test

    local spec image user home cli
    for spec in "${WORKLOADS[@]}"; do
        IFS=: read -r image user home cli <<< "$spec"
        echo "[test-images] Testing deny-by-default and allowlisted egress for $image"
        if run_workload "$image" "$home" '' sh -c 'curl -fsS --connect-timeout 3 http://allowed.test:8080/ >/dev/null'; then
            fail "$image reached an endpoint with no egress allowlist."
        fi
        run_workload "$image" "$home" allowed.test \
            sh -c 'curl -fsS --connect-timeout 3 http://allowed.test:8080/ | grep -q "Directory listing"'
        if run_workload "$image" "$home" allowed.test \
            sh -c 'curl -fsS --connect-timeout 3 http://blocked.test:8080/ >/dev/null'; then
            fail "$image reached a host outside its egress allowlist."
        fi
    done
}

run_gateway_integration() {
    ensure_network
    local allowed="agent-containers-test-${RUN_ID}-gateway-allowed"
    local blocked="agent-containers-test-${RUN_ID}-gateway-blocked"
    start_http_server "$allowed" allowed.test
    start_http_server "$blocked" blocked.test

    local key="$TEMP_DIR/gateway-key"
    local known_hosts="$TEMP_DIR/gateway-known-hosts"
    ssh-keygen -q -t ed25519 -N '' -f "$key"
    local gateway_ip
    start_gateway "$key.pub" allowed.test
    gateway_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$GATEWAY_CONTAINER")"
    [ -n "$gateway_ip" ] || fail 'Could not determine the gateway container IP address.'
    write_gateway_known_hosts "$GATEWAY_CONTAINER" "$gateway_ip" "$known_hosts"

    local home_volume="agent-containers-test-${RUN_ID}-gateway-workload-home"
    local workspace_volume="agent-containers-test-${RUN_ID}-gateway-workspace"
    track_volume "$home_volume"
    track_volume "$workspace_volume"

    echo '[test-images] Testing workload-to-gateway egress enforcement'
    docker run --rm --network "$TEST_NETWORK" \
        --security-opt=no-new-privileges \
        --read-only --tmpfs /tmp --tmpfs /run \
        --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
        -e "AGENT_GATEWAY_HOST=$gateway_ip" -e "AGENT_GATEWAY_BOOTSTRAP_ALLOW=$gateway_ip" \
        --mount "type=bind,src=$key,dst=/etc/agent/gateway-key,readonly" \
        --mount "type=bind,src=$known_hosts,dst=/etc/agent/gateway-known-hosts,readonly" \
        --mount "type=volume,src=$home_volume,dst=/home/codex" \
        --mount "type=volume,src=$workspace_volume,dst=/workspace" \
        "$(image_tag codex)" \
        sh -c '
            # sshuttle daemonizes before its local forwarding listener is
            # necessarily ready. Keep this probe in the same workload so
            # retries wait for that listener instead of starting a fresh
            # tunnel on every attempt.
            for attempt in $(seq 1 10); do
                if curl -fsS --connect-timeout 5 --max-time 5 http://allowed.test:8080/ 2>/dev/null \
                    | grep -q "Directory listing"; then
                    exit 0
                fi
                sleep 1
            done
            curl -fsS --connect-timeout 5 --max-time 5 http://allowed.test:8080/ | grep -q "Directory listing"
        '
    if docker run --rm --network "$TEST_NETWORK" \
        --security-opt=no-new-privileges \
        --read-only --tmpfs /tmp --tmpfs /run \
        --cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=SETUID --cap-add=SETGID \
        -e "AGENT_GATEWAY_HOST=$gateway_ip" -e "AGENT_GATEWAY_BOOTSTRAP_ALLOW=$gateway_ip" \
        --mount "type=bind,src=$key,dst=/etc/agent/gateway-key,readonly" \
        --mount "type=bind,src=$known_hosts,dst=/etc/agent/gateway-known-hosts,readonly" \
        --mount "type=volume,src=$home_volume,dst=/home/codex" \
        --mount "type=volume,src=$workspace_volume,dst=/workspace" \
        "$(image_tag codex)" \
        sh -c 'curl -fsS --connect-timeout 5 --max-time 5 http://blocked.test:8080/ >/dev/null'; then
        fail 'Gateway allowed a host outside its egress allowlist.'
    fi
}

usage() {
    cat <<'EOF'
Usage: scripts/test-images.sh <all|build|smoke|containment|gateway|static>

all          Static checks, build every image, then smoke-test every image and
             test in-container egress enforcement for every workload image.
gateway      Build every image and run the workload-to-agent-gateway egress test.
EOF
}

main() {
    local mode="${1:-all}"
    case "$mode" in
        static) run_static_checks ;;
        build) build_images ;;
        smoke) build_images; smoke_workloads; smoke_hermes; smoke_gateway; smoke_volume_bridge ;;
        containment) build_images; run_containment_tests ;;
        gateway) build_images; run_gateway_integration ;;
        all) run_static_checks; build_images; smoke_workloads; smoke_hermes; smoke_gateway; smoke_volume_bridge; run_containment_tests ;;
        *) usage >&2; exit 2 ;;
    esac
    echo "[test-images] PASS: $mode"
}

main "$@"
