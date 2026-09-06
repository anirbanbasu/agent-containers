"""Pure direct-Docker command construction for hardened workload launches."""

from __future__ import annotations

import getpass
import json
import os
import re
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
_HERMES_BASE_URL_ENV = {
    "anthropic": "ANTHROPIC_BASE_URL",
    "custom": "OPENAI_BASE_URL",
    "openai": "OPENAI_BASE_URL",
}


def default_image_tag(profile: Profile, profile_path: Path | None = None) -> str:
    """Return a local tag tied to the profile's complete desired content."""
    return (
        f"agent-containers/{_IMAGE_NAMES[profile.agent]}:{_resource_owner()}-{profile.name}-"
        f"{profile_digest(profile, profile_path)[:12]}"
    )


def default_home_volume(profile: Profile) -> str:
    """Return the user-scoped default home volume for a profile."""
    return f"{_IMAGE_NAMES[profile.agent]}-home-{_resource_owner()}-{profile.name}"


def legacy_home_volume(profile: Profile) -> str:
    """Return the pre-user-scoped volume name used by older deployments."""
    return f"{_IMAGE_NAMES[profile.agent]}-home-{profile.name}"


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
    home = home_volume or profile.home_volume or default_home_volume(profile)
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
        # A populated home directory may be mode 0700 and owned by the
        # remapped host UID. The short-lived root seed helper needs DAC
        # override to inspect/create the target, while the workload itself
        # never receives this capability.
        "--cap-add=DAC_OVERRIDE",
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
    home = home_volume or profile.home_volume or default_home_volume(profile)
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
    argv.extend(_provider_agent_args(profile))
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
        if profile.egress.gateway_user is not None:
            argv.extend(["-e", f"AGENT_GATEWAY_USER={profile.egress.gateway_user}"])
        if profile.egress.gateway_access_hostname is not None:
            argv.extend(["-e", f"AGENT_GATEWAY_ACCESS_HOSTNAME={profile.egress.gateway_access_hostname}"])
        if profile.egress.gateway_bootstrap_allow:
            argv.extend(["-e", f"AGENT_GATEWAY_BOOTSTRAP_ALLOW={','.join(profile.egress.gateway_bootstrap_allow)}"])
    elif profile.egress.mode == "allowlist" and profile.egress.hosts:
        argv.extend(["-e", f"AGENT_ALLOWED_EGRESS={','.join(profile.egress.hosts)}"])
    if profile.provider and profile.provider.api_key_env:
        argv.extend(["-e", profile.provider.api_key_env])
    if profile.provider and profile.agent == AgentName.CLAUDE_CODE:
        if profile.provider.endpoint is not None:
            argv.extend(["-e", f"ANTHROPIC_BASE_URL={_url_value(profile.provider.endpoint)}"])
        if profile.provider.model is not None:
            argv.extend(["-e", f"ANTHROPIC_MODEL={profile.provider.model}"])
    if profile.provider and profile.agent == AgentName.HERMES and profile.provider.endpoint is not None:
        environment = _HERMES_BASE_URL_ENV.get(profile.provider.kind)
        if environment is None:
            raise DockerCommandError(
                f"provider endpoint mapping is not implemented for Hermes provider {profile.provider.kind!r}"
            )
        argv.extend(["-e", f"{environment}={_url_value(profile.provider.endpoint)}"])
    if profile.agent == AgentName.OPENCODE and (
        profile.langfuse.enabled
        or (
            profile.provider is not None
            and (profile.provider.endpoint is not None or profile.provider.model is not None)
        )
    ):
        argv.extend(["-e", f"AGENT_OPENCODE_CONFIG_JSON={_opencode_config(profile)}"])
    _append_langfuse_args(argv, profile)


def _provider_agent_args(profile: Profile) -> list[str]:
    """Render provider settings through the selected agent's supported surface."""
    provider = profile.provider
    if profile.agent == AgentName.CLAUDE_CODE:
        return []
    if profile.agent == AgentName.CODEX:
        args = []
        if profile.langfuse.enabled:
            args.extend(
                [
                    "--config",
                    "features.hooks=true",
                    "--config",
                    'plugins."tracing@codex-observability-plugin".enabled=true',
                ]
            )
        if provider is None:
            return args
        if provider.model is not None:
            args.extend(["--model", provider.model])
        if provider.endpoint is not None:
            if provider.kind == "openai":
                args.extend(["--config", f'openai_base_url="{_toml_string(_url_value(provider.endpoint))}"'])
            else:
                provider_id = "agent_containers"
                args.extend(
                    [
                        "--config",
                        f'model_provider="{provider_id}"',
                        "--config",
                        f'model_providers.{provider_id}.name="{provider.kind}"',
                        "--config",
                        f'model_providers.{provider_id}.base_url="{_toml_string(_url_value(provider.endpoint))}"',
                        "--config",
                        f'model_providers.{provider_id}.wire_api="responses"',
                    ]
                )
        return args
    if profile.agent == AgentName.HERMES:
        if provider is None:
            return []
        args = []
        if provider.kind:
            args.extend(["--provider", provider.kind])
        if provider.model is not None:
            args.extend(["--model", provider.model])
        return args
    return []


def _append_proxy_args(argv: list[str], profile: Profile, profile_path: Path) -> None:
    """Append proxy environment, runtime trust pointers and a read-only CA mount."""
    if profile.proxy is None:
        return
    if profile.proxy.http is not None:
        value = _url_value(profile.proxy.http)
        argv.extend(["-e", f"HTTP_PROXY={value}", "-e", f"http_proxy={value}"])
    if profile.proxy.https is not None:
        value = _url_value(profile.proxy.https)
        argv.extend(["-e", f"HTTPS_PROXY={value}", "-e", f"https_proxy={value}"])
    if profile.proxy.no_proxy:
        value = ",".join(profile.proxy.no_proxy)
        argv.extend(["-e", f"NO_PROXY={value}", "-e", f"no_proxy={value}"])
    if profile.proxy.http is not None or profile.proxy.https is not None:
        argv.extend(["-e", "NODE_USE_ENV_PROXY=1"])
    if profile.proxy.ca_file is not None:
        _resolve_input_file(profile_path, profile.proxy.ca_file, "proxy CA")
    if profile.proxy.ca_dir is not None:
        _resolve_input_directory(profile_path, profile.proxy.ca_dir, "proxy CA directory")
    if profile.proxy.ca_file is not None or profile.proxy.ca_dir is not None:
        target = "/etc/ssl/certs/ca-certificates.crt"
        argv.extend(
            [
                "-e",
                f"SSL_CERT_FILE={target}",
                "-e",
                f"REQUESTS_CA_BUNDLE={target}",
                "-e",
                f"NODE_EXTRA_CA_CERTS={target}",
            ]
        )


def _url_value(value: object) -> str:
    """Render a validated URL without Pydantic's cosmetic root slash."""
    return str(value).rstrip("/")


def _resource_owner() -> str:
    """Return a stable, Docker-safe host-user namespace for local resources."""
    try:
        username = getpass.getuser().strip().lower()
    except (KeyError, OSError):
        username = ""
    username = re.sub(r"[^a-z0-9_.-]+", "-", username).strip("-_.")[:32].strip("-_.")
    uid = getattr(os, "getuid", lambda: 0)()
    return f"{username or 'user'}-{uid}"


def _toml_string(value: str) -> str:
    """Escape a value embedded in a Codex TOML string override."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _opencode_config(profile: Profile) -> str:
    """Render a secret-free, per-run OpenCode provider configuration."""
    provider = profile.provider
    options: dict[str, str] = {}
    document: dict[str, object] = {
        "$schema": "https://opencode.ai/config.json",
    }
    if provider is not None:
        if provider.endpoint is not None:
            options["baseURL"] = _url_value(provider.endpoint)
        if provider.api_key_env is not None:
            options["apiKey"] = "{env:" + provider.api_key_env + "}"
        provider_config: dict[str, object] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider.kind,
            "options": options,
            "models": {},
        }
        if provider.model is not None:
            provider_config["models"] = {provider.model: {"name": provider.model}}
            document["model"] = f"agent_containers/{provider.model}"
        document["provider"] = {"agent_containers": provider_config}
    if profile.langfuse.enabled:
        document["experimental"] = {"openTelemetry": True}
        document["plugin"] = ["@langfuse/opencode-observability-plugin@latest"]
    return json.dumps(document, separators=(",", ":"))


def _append_langfuse_args(argv: list[str], profile: Profile) -> None:
    """Append opt-in Langfuse environment references and enforce egress scope."""
    config = profile.langfuse
    if not config.enabled:
        return
    base_url = config.base_url
    assert base_url is not None
    host = base_url.host
    assert host is not None
    host = host.lower()
    if profile.egress.gateway_host is None:
        if profile.egress.mode == "deny":
            raise DockerCommandError("Langfuse requires an egress allowlist entry or gateway")
        if profile.egress.mode == "allowlist" and host not in {entry.lower() for entry in profile.egress.hosts}:
            raise DockerCommandError(f"Langfuse host must be included in egress hosts: {host}")
    base_url_value = _url_value(base_url)
    base_environment = "LANGFUSE_BASEURL" if profile.agent == AgentName.OPENCODE else "LANGFUSE_BASE_URL"
    argv.extend(
        [
            "-e",
            "TRACE_TO_LANGFUSE=true",
            "-e",
            config.public_key_env,
            "-e",
            f"AGENT_LANGFUSE_PUBLIC_KEY_ENV={config.public_key_env}",
            "-e",
            config.secret_key_env,
            "-e",
            f"AGENT_LANGFUSE_SECRET_KEY_ENV={config.secret_key_env}",
            "-e",
            f"{base_environment}={base_url_value}",
        ]
    )
    if config.environment is not None:
        environment = "LANGFUSE_ENVIRONMENT" if profile.agent == AgentName.OPENCODE else "LANGFUSE_TRACING_ENVIRONMENT"
        argv.extend(["-e", f"{environment}={config.environment}"])
    if config.user_id is not None:
        argv.extend(["-e", f"LANGFUSE_USER_ID={config.user_id}"])


def _append_mount_args(argv: list[str], profile: Profile, profile_path: Path) -> None:
    """Append explicit bind/directory mounts and reject copy-once seeds."""
    targets = {"/etc/ssl/certs/ca-certificates.crt"}
    if profile.egress.gateway_host is not None:
        key_mount = next((mount for mount in profile.mounts if mount.target == "/etc/agent/gateway-key"), None)
        known_hosts_mount = next(
            (mount for mount in profile.mounts if mount.target == "/etc/agent/gateway-known-hosts"), None
        )
        if profile.egress.gateway_key_file is None and key_mount is None:
            raise DockerCommandError("gateway key input is required when gateway mode is enabled")
        if profile.egress.gateway_known_hosts_file is None and known_hosts_mount is None:
            raise DockerCommandError("gateway known-hosts input is required when gateway mode is enabled")
        for mount, label in ((key_mount, "gateway key"), (known_hosts_mount, "gateway known-hosts")):
            if mount is not None:
                if not mount.read_only:
                    raise DockerCommandError(f"{label} mount must be read-only")
                if not resolve_mount_source(profile, mount, profile_path).is_file():
                    source = resolve_mount_source(profile, mount, profile_path)
                    raise DockerCommandError(f"{label} does not exist: {source}")
    if profile.egress.gateway_key_file is not None:
        key_source = _resolve_input_file(profile_path, profile.egress.gateway_key_file, "gateway key")
        argv.extend(["-v", f"{key_source}:/etc/agent/gateway-key:ro"])
        targets.add("/etc/agent/gateway-key")
    if profile.egress.gateway_known_hosts_file is not None:
        hosts_source = _resolve_input_file(
            profile_path, profile.egress.gateway_known_hosts_file, "gateway known-hosts file"
        )
        argv.extend(["-v", f"{hosts_source}:/etc/agent/gateway-known-hosts:ro"])
        targets.add("/etc/agent/gateway-known-hosts")
    for mount in profile.mounts:
        if mount.type == MountType.SEED:
            raise DockerCommandError(f"seed mount requires apply before run: {mount.target}")
        if mount.target in targets:
            raise DockerCommandError(f"mount target conflicts with generated mount: {mount.target}")
        targets.add(mount.target)
        source = resolve_mount_source(profile, mount, profile_path)
        access = "ro" if mount.read_only else "rw"
        argv.extend(["-v", f"{source}:{mount.target}:{access}"])


def _resolve_input_file(profile_path: Path, value: str, label: str) -> Path:
    """Resolve a profile-relative file input and reject Docker-created directories."""
    source = (profile_path.expanduser().resolve().parent / value).resolve()
    if not source.is_file():
        raise DockerCommandError(f"{label} does not exist: {source}")
    return source


def _resolve_input_directory(profile_path: Path, value: str, label: str) -> Path:
    """Resolve a profile-relative directory input and reject Docker-created paths."""
    source = (profile_path.expanduser().resolve().parent / value).resolve()
    if not source.is_dir():
        raise DockerCommandError(f"{label} does not exist: {source}")
    return source


def shell_command(argv: Iterable[str]) -> str:
    """Render argv safely for diagnostic output or a shell shortcut."""
    return shlex.join(tuple(argv))
