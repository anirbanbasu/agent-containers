"""Generate namespaced shell shortcuts for selected profile deployments."""

from __future__ import annotations

import os
import shlex
import tempfile
from collections.abc import Mapping
from pathlib import Path

from agent_containers.docker import (
    DockerCommandError,
    WorkspaceMountToken,
    WorkspaceTargetToken,
    build_decant_run_argv,
    build_run_argv,
    legacy_home_volume,
)
from agent_containers.profile import AgentName, Profile
from agent_containers.state import DeploymentRecord, profile_from_snapshot


class ShortcutError(ValueError):
    """Raised when a profile cannot be rendered as a safe shell shortcut."""


def default_shortcuts_path() -> Path:
    """Return the CLI-managed profile shortcut path under the XDG config home."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return (root / "agent-containers" / "profiles.sh").resolve()


def shortcut_function_name(profile: Profile) -> str:
    """Return the reserved, namespaced shell function name for a profile."""
    return f"agent_containers_{profile.name.replace('-', '_')}"


def decant_shortcut_function_name(profile: Profile) -> str:
    """Return the reserved function name for an experimental Decant launch."""
    return f"agent_containers_decant_{profile.name.replace('-', '_')}"


def render_shortcut(profile: Profile, record: DeploymentRecord, profile_path: Path) -> str:
    """Render one profile function without embedding secrets or shell interpolation."""
    workspace = profile_path.expanduser().resolve().parent
    try:
        argv = build_run_argv(
            profile,
            workspace,
            profile_path,
            image=record.image,
            home_volume=record.home_volume or legacy_home_volume(profile),
            permit_unrestricted=profile.egress.mode == "unrestricted",
        )
    except DockerCommandError as exc:
        raise ShortcutError(str(exc)) from exc
    tokens: list[str | object] = [token for token in argv]
    rendered = " \\\n    ".join(_render_token(token) for token in tokens)
    name = shortcut_function_name(profile)
    notice = (
        f"  echo \"[agent-containers] egress filtering is DISABLED for profile '{profile.name}'\" >&2\n"
        if profile.egress.mode == "unrestricted"
        else ""
    )
    return (
        f"# BEGIN agent-containers profile {profile.name}\n"
        f"{name}() {{\n"
        f'{notice}  {rendered} "$@"\n'
        f"}}\n"
        f"# END agent-containers profile {profile.name}\n"
    )


def render_decant_shortcut(profile: Profile, source_records: Mapping[str, DeploymentRecord]) -> str:
    """Render a direct-mount Decant function from selected agent deployments."""
    volumes: dict[AgentName, str] = {}
    for source_name in profile.decant.source_profiles:
        record = source_records.get(source_name)
        if record is None:
            raise ShortcutError(f"Decant source profile state is unavailable: {source_name}")
        try:
            source_profile = profile_from_snapshot(record.profile_snapshot)
        except ValueError as exc:
            raise ShortcutError(f"Decant source profile state is invalid: {source_name}") from exc
        if source_profile.agent not in {AgentName.CLAUDE_CODE, AgentName.CODEX}:
            raise ShortcutError(f"Decant source profile must use Claude Code or Codex: {source_name}")
        if source_profile.agent in volumes:
            raise ShortcutError(f"Decant has multiple {source_profile.agent.value} source profiles")
        volumes[source_profile.agent] = record.home_volume or legacy_home_volume(source_profile)
    try:
        argv = build_decant_run_argv(
            profile,
            claude_volume=volumes.get(AgentName.CLAUDE_CODE),
            codex_volume=volumes.get(AgentName.CODEX),
        )
    except DockerCommandError as exc:
        raise ShortcutError(str(exc)) from exc
    rendered = " \\\n    ".join(shlex.quote(token) for token in argv)
    name = decant_shortcut_function_name(profile)
    return (
        f"# BEGIN agent-containers decant {profile.name}\n"
        f"{name}() {{\n"
        f'  {rendered} "$@"\n'
        f"}}\n"
        f"# END agent-containers decant {profile.name}\n"
    )


def update_shortcuts(
    path: Path,
    profile: Profile,
    record: DeploymentRecord,
    profile_path: Path,
    decant_sources: Mapping[str, DeploymentRecord] | None = None,
) -> None:
    """Atomically replace one generated profile block in the managed shortcuts file."""
    path = path.expanduser().resolve()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = render_shortcut(profile, record, profile_path)
    content = _replace_block(existing, f"profile {profile.name}", block)
    decant_begin = f"decant {profile.name}"
    if profile.decant.enabled:
        if decant_sources is None:
            raise ShortcutError("Decant source deployments are required when Decant is enabled")
        content = _replace_block(content, decant_begin, render_decant_shortcut(profile, decant_sources))
    else:
        content = _replace_block(content, decant_begin, "")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as shortcuts_file:
            shortcuts_file.write(content)
            shortcuts_file.flush()
            os.fsync(shortcuts_file.fileno())
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _replace_block(existing: str, key: str, block: str) -> str:
    """Replace or remove one generated block while preserving user shell text."""
    begin = f"# BEGIN agent-containers {key}\n"
    end = f"# END agent-containers {key}\n"
    if begin in existing:
        start = existing.index(begin)
        try:
            finish = existing.index(end, start) + len(end)
        except ValueError as exc:
            profile_name = key.removeprefix("profile ")
            raise ShortcutError(f"incomplete generated block for profile {profile_name} in profiles.sh") from exc
        replacement = block
        return existing[:start] + replacement + existing[finish:]
    if not block:
        return existing
    return existing.rstrip() + ("\n\n" if existing.strip() else "") + block


def _render_token(token: str | object) -> str:
    if isinstance(token, WorkspaceMountToken):
        return '"$PWD:/workspace/$(basename "$PWD")"'
    if isinstance(token, WorkspaceTargetToken):
        return '"/workspace/$(basename "$PWD")"'
    return shlex.quote(str(token))
