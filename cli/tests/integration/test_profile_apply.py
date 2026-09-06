"""Opt-in Docker integration coverage for the profile apply lifecycle."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_containers.docker import build_run_argv
from agent_containers.lifecycle import apply_profile, rollback_profile
from agent_containers.profile import Profile
from agent_containers.state import load_state

pytestmark = pytest.mark.integration


def test_apply_builds_selects_and_launches_profile(tmp_path: Path) -> None:
    """Apply records a deployment whose generated launch runs safely."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    profile_path = tmp_path / "integration-apply.toml"
    profile = Profile(
        name="integration-apply",
        agent="codex",
        egress={"hosts": ["127.0.0.1"]},
    )
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    record = None
    try:
        record = apply_profile(profile, profile_path, state_path, shortcuts_path)
        assert record.home_volume is not None
        assert load_state(state_path).selected_deployment == record
        shortcut = shortcuts_path.read_text(encoding="utf-8")
        assert "agent_containers_integration_apply" in shortcut
        assert record.image in shortcut
        assert record.home_volume in shortcut

        launch = list(
            build_run_argv(
                profile,
                tmp_path,
                profile_path,
                image=record.image,
                home_volume=record.home_volume,
                agent_args=["--version"],
            )
        )
        launch.remove("-it")
        launch.insert(2, "--network=none")
        subprocess.run(launch, check=True, capture_output=True, text=True)

        security_launch = list(
            build_run_argv(
                profile,
                tmp_path,
                profile_path,
                image=record.image,
                home_volume=record.home_volume,
            )
        )
        security_launch.remove("-it")
        security_launch.insert(2, "--network=none")
        image_index = security_launch.index(record.image)
        security_launch[image_index:] = [
            record.image,
            "sh",
            "-ceu",
            (
                f'test "$(id -u)" = "{os.getuid()}"\n'
                'test -w "$HOME"\n'
                'grep -Eq "^[^ ]+ / [^ ]+ ro[, ]" /proc/mounts\n'
                'grep -Eq "^CapEff:[[:space:]]*0{16}$" /proc/self/status'
            ),
        ]
        subprocess.run(security_launch, check=True, capture_output=True, text=True)

        persistence_launch = list(security_launch)
        persistence_launch[-1] = (
            'test ! -e "$HOME/.agent-containers-integration-sentinel"\n'
            'touch "$HOME/.agent-containers-integration-sentinel"'
        )
        subprocess.run(persistence_launch, check=True, capture_output=True, text=True)
        persistence_launch[-1] = 'test -f "$HOME/.agent-containers-integration-sentinel"'
        subprocess.run(persistence_launch, check=True, capture_output=True, text=True)
    finally:
        if record is not None and record.home_volume is not None:
            subprocess.run(["docker", "volume", "rm", "-f", record.home_volume], check=False, capture_output=True)
            subprocess.run(["docker", "image", "rm", "-f", record.image], check=False, capture_output=True)


def test_apply_refuses_to_overwrite_an_existing_seed_target(tmp_path: Path) -> None:
    """A failed copy-once seed leaves the previously selected deployment active."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    seed_source = tmp_path / "settings.json"
    seed_source.write_text('{"profile":"first"}\n', encoding="utf-8")
    profile_path = tmp_path / "integration-seed.toml"
    state_path = tmp_path / "state.json"
    profile = Profile(
        name="integration-seed",
        agent="codex",
        egress={"hosts": ["127.0.0.1"]},
        mounts=[
            {
                "type": "seed",
                "source": "settings.json",
                "target": "/home/codex/.codex/settings.json",
            }
        ],
    )
    record = None
    try:
        record = apply_profile(profile, profile_path, state_path)
        selected_before = load_state(state_path).selected_deployment
        assert selected_before == record

        changed_profile = Profile.model_validate({**profile.model_dump(), "egress": {"hosts": ["127.0.0.2"]}})
        with pytest.raises(subprocess.CalledProcessError):
            apply_profile(changed_profile, profile_path, state_path)

        assert load_state(state_path).selected_deployment == selected_before
    finally:
        if record is not None and record.home_volume is not None:
            subprocess.run(["docker", "volume", "rm", "-f", record.home_volume], check=False, capture_output=True)
            subprocess.run(["docker", "image", "rm", "-f", record.image], check=False, capture_output=True)


def test_launch_only_update_can_be_rolled_back(tmp_path: Path) -> None:
    """Rollback restores the prior launch record and generated shortcut."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    profile_path = tmp_path / "integration-rollback.toml"
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    initial = Profile(
        name="integration-rollback",
        agent="codex",
        egress={"hosts": ["127.0.0.1"]},
    )
    updated = Profile.model_validate({**initial.model_dump(), "egress": {"hosts": ["127.0.0.2"]}})
    record = None
    try:
        record = apply_profile(initial, profile_path, state_path, shortcuts_path)
        selected_initial = load_state(state_path).selected_deployment
        assert selected_initial == record

        updated_record = apply_profile(updated, profile_path, state_path, shortcuts_path)
        assert updated_record.image == record.image
        assert load_state(state_path).selected_deployment == updated_record
        assert "127.0.0.2" in shortcuts_path.read_text(encoding="utf-8")

        restored = rollback_profile(updated, state_path, shortcuts_path, profile_path)
        assert restored == selected_initial
        assert load_state(state_path).selected_deployment == selected_initial
        assert "127.0.0.1" in shortcuts_path.read_text(encoding="utf-8")
    finally:
        if record is not None and record.home_volume is not None:
            subprocess.run(["docker", "volume", "rm", "-f", record.home_volume], check=False, capture_output=True)
            subprocess.run(["docker", "image", "rm", "-f", record.image], check=False, capture_output=True)
