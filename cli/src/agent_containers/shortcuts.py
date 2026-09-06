"""Generate namespaced shell shortcuts for selected profile deployments."""

from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path

from agent_containers.docker import DockerCommandError, build_run_argv, legacy_home_volume
from agent_containers.profile import Profile
from agent_containers.state import DeploymentRecord

_WORKSPACE_MOUNT = object()
_WORKSPACE_TARGET = object()


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
        )
    except DockerCommandError as exc:
        raise ShortcutError(str(exc)) from exc
    workspace_mount = f"{workspace}:/workspace/{workspace.name}"
    tokens: list[str | object] = [
        _WORKSPACE_MOUNT
        if token == workspace_mount
        else _WORKSPACE_TARGET
        if token == f"/workspace/{workspace.name}"
        else token
        for token in argv
    ]
    rendered = " \\\n    ".join(_render_token(token) for token in tokens)
    name = shortcut_function_name(profile)
    return f'# BEGIN agent-containers profile {profile.name}\n{name}() {{\n  {rendered} "$@"\n}}\n# END agent-containers profile {profile.name}\n'


def update_shortcuts(path: Path, profile: Profile, record: DeploymentRecord, profile_path: Path) -> None:
    """Atomically replace one generated profile block in the managed shortcuts file."""
    path = path.expanduser().resolve()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = render_shortcut(profile, record, profile_path)
    begin = f"# BEGIN agent-containers profile {profile.name}\n"
    end = f"# END agent-containers profile {profile.name}\n"
    if begin in existing:
        start = existing.index(begin)
        finish = existing.index(end, start) + len(end)
        content = existing[:start] + block + existing[finish:]
    else:
        content = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
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


def _render_token(token: str | object) -> str:
    if token is _WORKSPACE_MOUNT:
        return '"$PWD:/workspace/$(basename "$PWD")"'
    if token is _WORKSPACE_TARGET:
        return '"/workspace/$(basename "$PWD")"'
    return shlex.quote(str(token))
