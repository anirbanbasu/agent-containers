"""Pure direct-Docker command construction for hardened workload launches."""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from pathlib import Path

from agent_containers.build_context import BuildContexts
from agent_containers.profile import AgentName, MountType, Profile, resolve_mount_source
from agent_containers.state import profile_digest


class DockerCommandError(ValueError):
    """Raised when a profile cannot be represented safely as a Docker run."""


_HOME_PATHS = {
    AgentName.CLAUDE_CODE: "/home/claude",
    AgentName.OPENCODE: "/home/opencode",
    AgentName.CODEX: "/home/codex",
    AgentName.HERMES: "/opt/data",
}
_IMAGE_NAMES = {
    AgentName.CLAUDE_CODE: "claude-code",
    AgentName.OPENCODE: "opencode",
    AgentName.CODEX: "codex",
    AgentName.HERMES: "hermes",
}
_AGENT_COMMANDS = {
    AgentName.CLAUDE_CODE: "claude",
    AgentName.OPENCODE: "opencode",
    AgentName.CODEX: "codex",
    AgentName.HERMES: None,
}
_CAPABILITIES = ("NET_ADMIN", "NET_RAW", "SETUID", "SETGID")
_WORKSPACE_EXEC = {AgentName.OPENCODE, AgentName.HERMES}
_SEED_USER_IDS = {
    AgentName.CLAUDE_CODE: 1000,
    AgentName.OPENCODE: 1000,
    AgentName.CODEX: 1000,
    AgentName.HERMES: 10000,
}
_SEED_COPY_SCRIPT = """set -eu
test ! -e "$SEED_TARGET"
mkdir -p "$(dirname "$SEED_TARGET")"
cp -a /tmp/agent-seed "$SEED_TARGET"
chown -R "$SEED_UID:$SEED_UID" "$SEED_TARGET"
"""


def default_image_tag(profile: Profile) -> str:
    """Return a local tag tied to the profile's complete desired content."""
    return f"agent-containers/{_IMAGE_NAMES[profile.agent]}:{profile.name}-{profile_digest(profile)[:12]}"


def build_image_argv(
    profile: Profile,
    contexts: BuildContexts,
    *,
    image: str | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> tuple[str, ...]:
    """Build argv for a materialized profile context without executing Docker."""
    if not contexts.image.is_dir() or not contexts.shared.is_dir():
        raise DockerCommandError("materialized image and shared contexts must be directories")
    if (uid is None) != (gid is None):
        raise DockerCommandError("uid and gid must be supplied together")
    if uid is not None and (uid < 1 or gid is None or gid < 1):
        raise DockerCommandError("uid and gid must be positive")
    argv = [
        "docker",
        "build",
        "--build-context",
        f"shared={contexts.shared}",
        "--tag",
        image or default_image_tag(profile),
    ]
    if profile.agent != AgentName.HERMES and uid is not None and gid is not None:
        argv.extend(["--build-arg", f"UID={uid}", "--build-arg", f"GID={gid}"])
    argv.append(str(contexts.image))
    return tuple(argv)


def build_seed_argv(
    profile: Profile,
    mount_target: str,
    profile_path: Path,
    *,
    image: str,
    home_volume: str | None = None,
) -> tuple[str, ...]:
    """Build a networkless, create-only copy-once seed command without running it."""
    mount = next((item for item in profile.mounts if item.target == mount_target), None)
    if mount is None or mount.type != MountType.SEED:
        raise DockerCommandError(f"seed mount is not configured: {mount_target}")
    home_path = _HOME_PATHS[profile.agent]
    if not mount.target.startswith(f"{home_path}/"):
        raise DockerCommandError(f"seed target must be inside the persistent home: {mount.target}")
    source = resolve_mount_source(profile, mount, profile_path)
    if not source.exists():
        raise DockerCommandError(f"seed source does not exist: {source}")
    home = home_volume or f"{_IMAGE_NAMES[profile.agent]}-home-{profile.name}"
    uid = _SEED_USER_IDS[profile.agent]
    return (
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--user",
        "0:0",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        "--cap-drop=ALL",
        "--cap-add=CHOWN",
        "--mount",
        f"type=volume,src={home},dst={home_path}",
        "--mount",
        f"type=bind,src={source},dst=/tmp/agent-seed,readonly",
        "-e",
        f"SEED_TARGET={mount.target}",
        "-e",
        f"SEED_UID={uid}",
        "--entrypoint",
        "/bin/sh",
        image,
        "-ceu",
        _SEED_COPY_SCRIPT,
    )


def build_run_argv(
    profile: Profile,
    workspace: Path,
    profile_path: Path,
    *,
    image: str | None = None,
    home_volume: str | None = None,
    agent_args: Iterable[str] = (),
    permit_unrestricted: bool = False,
) -> tuple[str, ...]:
    """Build a hardened docker run argv without executing Docker."""
    workspace = workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise DockerCommandError(f"workspace is not a directory: {workspace}")
    if profile.egress.mode == "unrestricted" and not permit_unrestricted:
        raise DockerCommandError("unrestricted egress requires explicit permit_unrestricted=True")
    image_ref = image or f"{_IMAGE_NAMES[profile.agent]}:latest"
    home = home_volume or f"{_IMAGE_NAMES[profile.agent]}-home-{profile.name}"
    workspace_target = f"/workspace/{workspace.name}"
    tmpfs_suffix = ":exec" if profile.agent in _WORKSPACE_EXEC else ""
    argv = [
        "docker",
        "run",
        "-it",
        "--rm",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs",
        f"/tmp{tmpfs_suffix}",
        "--tmpfs",
        f"/run{tmpfs_suffix}",
        "--cap-drop=ALL",
        *[f"--cap-add={cap}" for cap in _CAPABILITIES],
        "-v",
        f"{home}:{_HOME_PATHS[profile.agent]}",
        "-v",
        f"{workspace}:{workspace_target}",
        "-w",
        workspace_target,
    ]
    if profile.agent == AgentName.HERMES:
        argv.extend(["--cap-add=CHOWN", "--cap-add=DAC_OVERRIDE"])
    _append_network_args(argv, profile)
    _append_proxy_args(argv, profile, profile_path)
    _append_mount_args(argv, profile, profile_path)
    argv.append(image_ref)
    command = _AGENT_COMMANDS[profile.agent]
    if command is not None:
        argv.append(command)
    argv.extend(agent_args)
    return tuple(argv)


def _append_network_args(argv: list[str], profile: Profile) -> None:
    """Append explicit gateway, allowlist and secret-reference arguments."""
    if profile.egress.gateway_host is not None:
        argv.extend(
            [
                "-e",
                f"AGENT_GATEWAY_HOST={profile.egress.gateway_host}",
                "-e",
                f"AGENT_GATEWAY_PORT={profile.egress.gateway_port}",
            ]
        )
    elif profile.egress.mode == "allowlist" and profile.egress.hosts:
        argv.extend(["-e", f"AGENT_ALLOWED_EGRESS={','.join(profile.egress.hosts)}"])
    if profile.provider and profile.provider.api_key_env:
        argv.extend(["-e", profile.provider.api_key_env])


def _append_proxy_args(argv: list[str], profile: Profile, profile_path: Path) -> None:
    """Append proxy environment and a read-only CA mount."""
    if profile.proxy is None:
        return
    if profile.proxy.http is not None:
        argv.extend(["-e", f"HTTP_PROXY={_url_value(profile.proxy.http)}"])
    if profile.proxy.https is not None:
        argv.extend(["-e", f"HTTPS_PROXY={_url_value(profile.proxy.https)}"])
    if profile.proxy.ca_file is not None:
        ca_source = (profile_path.parent / profile.proxy.ca_file).resolve()
        target = "/etc/ssl/certs/agent-containers-custom-ca.pem"
        argv.extend(["-v", f"{ca_source}:{target}:ro", "-e", f"SSL_CERT_FILE={target}"])


def _url_value(value: object) -> str:
    """Render a validated URL without Pydantic's cosmetic root slash."""
    return str(value).rstrip("/")


def _append_mount_args(argv: list[str], profile: Profile, profile_path: Path) -> None:
    """Append explicit bind/directory mounts and reject copy-once seeds."""
    targets = {"/etc/ssl/certs/agent-containers-custom-ca.pem"}
    for mount in profile.mounts:
        if mount.type == MountType.SEED:
            raise DockerCommandError(f"seed mount requires apply before run: {mount.target}")
        if mount.target in targets:
            raise DockerCommandError(f"mount target conflicts with generated mount: {mount.target}")
        targets.add(mount.target)
        source = resolve_mount_source(profile, mount, profile_path)
        access = "ro" if mount.read_only else "rw"
        argv.extend(["-v", f"{source}:{mount.target}:{access}"])


def shell_command(argv: Iterable[str]) -> str:
    """Render argv safely for diagnostic output or a shell shortcut."""
    return shlex.join(tuple(argv))
