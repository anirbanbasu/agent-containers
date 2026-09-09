"""Opt-in Docker integration coverage for the profile apply lifecycle."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_containers.docker import build_run_argv, default_home_volume, default_image_tag
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


def test_apply_reconciles_an_existing_seed_target_by_content(tmp_path: Path) -> None:
    """An unchanged seed is idempotent while modified data needs explicit replacement."""
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
        assert selected_before is not None
        home_volume = selected_before.home_volume
        assert home_volume is not None

        modified = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "-v",
                f"{home_volume}:/home/codex",
                "alpine:latest",
                "sh",
                "-c",
                "echo changed > /home/codex/.codex/settings.json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if modified.returncode != 0:
            pytest.skip("test helper image unavailable")
        changed_profile = Profile.model_validate({**profile.model_dump(), "egress": {"hosts": ["127.0.0.2"]}})
        with pytest.raises(subprocess.CalledProcessError):
            apply_profile(changed_profile, profile_path, state_path)

        replace_profile = Profile.model_validate(
            {
                **changed_profile.model_dump(),
                "mounts": [{**changed_profile.mounts[0].model_dump(), "on_conflict": "replace"}],
            }
        )
        changed_record = apply_profile(replace_profile, profile_path, state_path)
        assert changed_record is not None
        assert load_state(state_path).selected_deployment is not None
    finally:
        home_volume = (
            record.home_volume
            if record is not None and record.home_volume is not None
            else default_home_volume(profile)
        )
        image = record.image if record is not None else default_image_tag(profile, profile_path)
        subprocess.run(["docker", "volume", "rm", "-f", home_volume], check=False, capture_output=True)
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)


def test_configuration_import_creates_agent_owned_nested_directory(tmp_path: Path) -> None:
    """A configuration import makes newly created parent directories writable by the agent."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    source = tmp_path / "settings.toml"
    source.write_text('model = "integration-model"\n', encoding="utf-8")
    profile_path = tmp_path / "integration-config-directory.toml"
    state_path = tmp_path / "state.json"
    profile = Profile(
        name="integration-config-directory",
        agent="codex",
        egress={"hosts": ["127.0.0.1"]},
        configuration_import={
            "source": source.name,
            "target": "/home/codex/.config/newdir/settings.toml",
            "format": "toml",
        },
    )
    record = None
    try:
        record = apply_profile(profile, profile_path, state_path)
        launch = list(
            build_run_argv(profile, tmp_path, profile_path, image=record.image, home_volume=record.home_volume)
        )
        launch.remove("-it")
        launch.insert(2, "--network=none")
        image_index = launch.index(record.image)
        launch[image_index:] = [
            record.image,
            "sh",
            "-ceu",
            (
                'test "$(stat -c \'%u:%g\' /home/codex/.config/newdir)" = "$(id -u):$(id -g)"\n'
                "touch /home/codex/.config/newdir/created-by-agent\n"
                "test -f /home/codex/.config/newdir/created-by-agent"
            ),
        ]
        subprocess.run(launch, check=True, capture_output=True, text=True)
    finally:
        volume = (
            record.home_volume
            if record is not None and record.home_volume is not None
            else default_home_volume(profile)
        )
        image = record.image if record is not None else default_image_tag(profile, profile_path)
        subprocess.run(["docker", "volume", "rm", "-f", volume], check=False, capture_output=True)
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)


def test_replace_directory_seed_refreshes_owned_non_nested_backup(tmp_path: Path) -> None:
    """Replacing a directory seed backs up exactly the prior tree for the agent."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    seed_source = tmp_path / "settings"
    seed_source.mkdir()
    (seed_source / "config.txt").write_text("seed", encoding="utf-8")
    profile_path = tmp_path / "integration-directory-seed.toml"
    state_path = tmp_path / "state.json"
    profile = Profile(
        name="integration-directory-seed",
        agent="codex",
        egress={"hosts": ["127.0.0.1"]},
        mounts=[
            {
                "type": "seed",
                "source": "settings",
                "target": "/home/codex/.codex/settings",
                "on_conflict": "replace",
            }
        ],
    )
    record = None
    try:
        record = apply_profile(profile, profile_path, state_path)
        assert record.home_volume is not None
        seed_target = "/home/codex/.codex/settings"
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--mount",
                f"type=volume,src={record.home_volume},dst=/home/codex",
                "--entrypoint",
                "/bin/sh",
                record.image,
                "-ceu",
                f"echo first > {seed_target}/manual.txt",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        first_replace = Profile.model_validate({**profile.model_dump(), "egress": {"hosts": ["127.0.0.2"]}})
        apply_profile(first_replace, profile_path, state_path)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--mount",
                f"type=volume,src={record.home_volume},dst=/home/codex",
                "--entrypoint",
                "/bin/sh",
                record.image,
                "-ceu",
                f"echo second > {seed_target}/manual.txt",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        second_replace = Profile.model_validate({**first_replace.model_dump(), "egress": {"hosts": ["127.0.0.3"]}})
        apply_profile(second_replace, profile_path, state_path)
        inspected = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--mount",
                f"type=volume,src={record.home_volume},dst=/home/codex,readonly",
                "--entrypoint",
                "/bin/sh",
                record.image,
                "-ceu",
                (
                    "uid=$(id -u codex)\n"
                    "gid=$(id -g codex)\n"
                    f'test "$(stat -c %u:%g {seed_target}.agent-containers.bak)" = "$uid:$gid"\n'
                    f'test "$(cat {seed_target}.agent-containers.bak/manual.txt)" = second\n'
                    f"test ! -e {seed_target}.agent-containers.bak/settings"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert inspected.returncode == 0
    finally:
        volume = (
            record.home_volume
            if record is not None and record.home_volume is not None
            else default_home_volume(profile)
        )
        image = record.image if record is not None else default_image_tag(profile, profile_path)
        subprocess.run(["docker", "volume", "rm", "-f", volume], check=False, capture_output=True)
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)


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

        restored = rollback_profile(updated, state_path, shortcuts_path, profile_path=profile_path)
        assert restored == selected_initial
        assert load_state(state_path).selected_deployment == selected_initial
        assert "127.0.0.1" in shortcuts_path.read_text(encoding="utf-8")
    finally:
        if record is not None and record.home_volume is not None:
            subprocess.run(["docker", "volume", "rm", "-f", record.home_volume], check=False, capture_output=True)
            subprocess.run(["docker", "image", "rm", "-f", record.image], check=False, capture_output=True)


def test_image_update_retains_previous_build_for_rollback(tmp_path: Path) -> None:
    """An image-changing profile update retains and can restore the old image."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    profile_path = tmp_path / "integration-image-update.toml"
    state_path = tmp_path / "state.json"
    initial = Profile(
        name="integration-image-update",
        agent="codex",
        packages={"apt": ["jq"]},
        egress={"hosts": ["127.0.0.1"]},
    )
    updated = Profile.model_validate({**initial.model_dump(), "packages": {"apt": ["jq", "tree"]}})
    records = []
    try:
        records.append(apply_profile(initial, profile_path, state_path))
        records.append(apply_profile(updated, profile_path, state_path))
        assert records[1].image != records[0].image
        state = load_state(state_path)
        assert state.selected_deployment == records[1]
        assert len(state.deployments) == 2

        restored = rollback_profile(updated, state_path, profile_path=profile_path)
        assert restored == records[0]
        assert load_state(state_path).selected_deployment == records[0]
    finally:
        volume = records[0].home_volume if records and records[0].home_volume is not None else None
        if volume is not None:
            subprocess.run(["docker", "volume", "rm", "-f", volume], check=False, capture_output=True)
        for record in records:
            subprocess.run(["docker", "image", "rm", "-f", record.image], check=False, capture_output=True)
