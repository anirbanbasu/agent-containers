"""Failure-safe Docker application of a desired profile."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_containers.build_context import prepare_build_contexts
from agent_containers.docker import build_image_argv, build_seed_argv, default_home_volume, default_image_tag
from agent_containers.planner import PlanAction, build_plan
from agent_containers.profile import MountType, Profile
from agent_containers.shortcuts import render_shortcut, update_shortcuts
from agent_containers.state import (
    DeploymentRecord,
    DeploymentState,
    default_state_path,
    load_state,
    new_deployment_id,
    profile_digest,
    profile_snapshot,
    save_state,
)


class LifecycleError(ValueError):
    """Raised when a state file is not safe to apply for a profile."""


@dataclass(frozen=True)
class DoctorReport:
    """Read-only host and selected-deployment diagnostics."""

    lines: tuple[str, ...]
    healthy: bool


def build_user_ids() -> tuple[int, int]:
    """Return safe image IDs while preserving Dockerfile collision rejection."""
    # macOS's conventional staff GID (20) is already assigned in Debian-based
    # images. Keep the documented groupmod rejection; Docker Desktop builds use
    # the baked-in safe GID while retaining the host UID for bind-mount ownership.
    return os.getuid(), 1000 if sys.platform == "darwin" else os.getgid()


def apply_profile(
    profile: Profile,
    profile_path: Path,
    state_path: Path | None = None,
    shortcuts_path: Path | None = None,
) -> DeploymentRecord:
    """Build or verify a deployment, seed it safely, then atomically select it."""
    target_state_path = state_path or default_state_path(profile)
    state = load_state(target_state_path) if target_state_path.exists() else DeploymentState(profile_name=profile.name)
    if state.profile_name != profile.name:
        raise LifecycleError(f"state belongs to profile {state.profile_name!r}, not {profile.name!r}")
    plan = build_plan(profile, state, profile_path)
    selected = state.selected_deployment
    image = selected.image if selected is not None else default_image_tag(profile)
    if PlanAction.CREATE_IMAGE in plan.actions or PlanAction.UPDATE_IMAGE in plan.actions:
        image = _build_image(profile, profile_path)
    else:
        _docker("docker", "image", "inspect", image)
    if not plan.is_noop:
        record = _new_record(profile, image, profile_path)
        if shortcuts_path is not None:
            # Validate the complete launch before seeds or state can make this
            # deployment visible. The later atomic write still refreshes the
            # generated file after state selection succeeds.
            render_shortcut(profile, record, profile_path)
        _apply_seeds(profile, profile_path, image)
        state.deployments = [item.model_copy(update={"selected": False}) for item in state.deployments]
        state.deployments.append(record)
        save_state(target_state_path, state)
        if shortcuts_path is not None:
            update_shortcuts(shortcuts_path, profile, record, profile_path)
        return record
    assert selected is not None
    if shortcuts_path is not None:
        update_shortcuts(shortcuts_path, profile, selected, profile_path)
    return selected


def rollback_profile(
    profile: Profile,
    state_path: Path | None = None,
    shortcuts_path: Path | None = None,
    profile_path: Path | None = None,
) -> DeploymentRecord:
    """Select the immediately preceding retained image after verifying it exists."""
    target_state_path = state_path or default_state_path(profile)
    state = load_state(target_state_path)
    if state.profile_name != profile.name:
        raise LifecycleError(f"state belongs to profile {state.profile_name!r}, not {profile.name!r}")
    selected_index = next((index for index, item in enumerate(state.deployments) if item.selected), None)
    if selected_index is None:
        raise LifecycleError("rollback requires a selected deployment")
    if selected_index == 0:
        raise LifecycleError("no prior deployment is retained for rollback")
    target = state.deployments[selected_index - 1]
    _docker("docker", "image", "inspect", target.image)
    restored_profile = Profile.model_validate(target.profile_snapshot)
    shortcut_profile_path = profile_path or Path.cwd() / "profile.toml"
    if shortcuts_path is not None:
        # A historical profile may reference an input that no longer exists;
        # refuse before changing state so rollback cannot strand the shortcut.
        render_shortcut(restored_profile, target, shortcut_profile_path)
    state.deployments = [
        item.model_copy(update={"selected": item.deployment_id == target.deployment_id}) for item in state.deployments
    ]
    save_state(target_state_path, state)
    if shortcuts_path is not None:
        update_shortcuts(shortcuts_path, restored_profile, target, shortcut_profile_path)
    return state.selected_deployment or target


def rollback_preview(record: DeploymentRecord) -> list[str]:
    """Render the managed launch choices restored by a rollback without secrets."""
    snapshot = record.profile_snapshot
    egress = snapshot.get("egress", {})
    proxy = snapshot.get("proxy")
    provider = snapshot.get("provider")
    return [
        f"Rollback target: {record.deployment_id} ({record.image})",
        f"Restored egress mode: {egress.get('mode', 'unknown')}",
        f"Restored egress hosts: {', '.join(egress.get('hosts', [])) or '(none)'}",
        f"Restored proxy/CA: {'configured' if proxy else 'none'}",
        f"Restored provider endpoint: {'configured' if provider and provider.get('endpoint') else 'none'}",
        "Warning: persistent home-volume data is not rolled back.",
        "Warning: existing agent sessions are not stopped.",
    ]


def doctor_profile(profile: Profile, state_path: Path | None = None) -> DoctorReport:
    """Inspect local Docker/state prerequisites without building or mutating resources."""
    lines: list[str] = []
    docker_available = _probe("docker", "version", "--format", "{{.Server.Version}}")
    lines.append(f"Docker daemon: {'available' if docker_available else 'unavailable'}")
    target_state_path = state_path or default_state_path(profile)
    if not target_state_path.exists():
        lines.append(f"Deployment state: absent ({target_state_path})")
        return DoctorReport(tuple(lines), healthy=False)
    state = load_state(target_state_path)
    if state.profile_name != profile.name:
        raise LifecycleError(f"state belongs to profile {state.profile_name!r}, not {profile.name!r}")
    selected = state.selected_deployment
    if selected is None:
        lines.append("Selected deployment: absent")
        return DoctorReport(tuple(lines), healthy=False)
    image_available = docker_available and _probe("docker", "image", "inspect", selected.image)
    lines.append(f"Selected deployment: {selected.deployment_id} ({selected.image})")
    lines.append(f"Selected image: {'available' if image_available else 'unavailable'}")
    return DoctorReport(tuple(lines), healthy=docker_available and image_available)


def _build_image(profile: Profile, profile_path: Path) -> str:
    """Build a profile context in an automatically removed private directory."""
    image = default_image_tag(profile, profile_path)
    with tempfile.TemporaryDirectory(prefix="agent-containers-") as temporary:
        contexts = prepare_build_contexts(profile, Path(temporary) / "context", profile_path)
        uid, gid = build_user_ids()
        _docker(*build_image_argv(profile, contexts, image=image, uid=uid, gid=gid))
    return image


def _apply_seeds(profile: Profile, profile_path: Path, image: str) -> None:
    """Copy new seed inputs only after the image is available for its adapter."""
    for mount in profile.mounts:
        if mount.type == MountType.SEED:
            _docker(*build_seed_argv(profile, mount.target, profile_path, image=image, home_volume=profile.home_volume))


def _new_record(profile: Profile, image: str, profile_path: Path | None = None) -> DeploymentRecord:
    """Create an unambiguous selected deployment record after successful work."""
    digest = profile_digest(profile, profile_path)
    return DeploymentRecord(
        deployment_id=new_deployment_id(profile, profile_path),
        image=image,
        home_volume=profile.home_volume or default_home_volume(profile),
        profile_digest=digest,
        profile_snapshot=profile_snapshot(profile),
        launch_digest=digest,
        created_at=datetime.now(UTC),
        selected=True,
    )


def _docker(*argv: str) -> None:
    """Run Docker without shell interpolation or captured credential-bearing output."""
    subprocess.run(argv, check=True)


def _probe(*argv: str) -> bool:
    """Return whether a harmless Docker inspection succeeds without raising."""
    return subprocess.run(argv, check=False, capture_output=True, text=True).returncode == 0
