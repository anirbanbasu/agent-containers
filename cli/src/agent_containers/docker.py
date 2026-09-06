"""Pure direct-Docker command construction for hardened workload launches."""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from pathlib import Path

from agent_containers.profile import AgentName, MountType, Profile, resolve_mount_source


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
