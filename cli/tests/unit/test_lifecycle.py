"""Failure-safe deployment lifecycle tests without Docker."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_containers.build_context import BuildContexts
from agent_containers.lifecycle import (
    LifecycleError,
    _new_record,
    apply_profile,
    build_user_ids,
    doctor_profile,
    rollback_preview,
    rollback_profile,
)
from agent_containers.profile import Profile
from agent_containers.state import DeploymentState, load_state, save_state


def make_profile(**overrides: object) -> Profile:
    """Create a minimal valid profile with selected overrides."""
    payload: dict[str, object] = {"name": "work", "agent": "codex"}
    payload.update(overrides)
    return Profile.model_validate(payload)


def test_apply_builds_then_selects_after_success(tmp_path: Path) -> None:
    """State is created only after the Docker build succeeds."""
    state_path = tmp_path / "state.json"
    contexts = BuildContexts(tmp_path / "image", tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    with (
        patch("agent_containers.lifecycle.prepare_build_contexts", return_value=contexts),
        patch("agent_containers.lifecycle.os.getuid", return_value=501),
        patch("agent_containers.lifecycle.os.getgid", return_value=20),
        patch("agent_containers.lifecycle.subprocess.run") as run,
    ):
        record = apply_profile(make_profile(), tmp_path / "work.toml", state_path)
    assert record.selected
    assert load_state(state_path).selected_deployment == record
    assert run.call_args.args[0][:2] == ("docker", "build")


def test_build_user_ids_preserves_linux_matching_and_macos_collision_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """MacOS uses the known safe image GID instead of weakening Dockerfile checks."""
    monkeypatch.setattr("agent_containers.lifecycle.os.getuid", lambda: 501)
    monkeypatch.setattr("agent_containers.lifecycle.os.getgid", lambda: 20)
    monkeypatch.setattr("agent_containers.lifecycle.sys.platform", "linux")
    assert build_user_ids() == (501, 20)
    monkeypatch.setattr("agent_containers.lifecycle.sys.platform", "darwin")
    assert build_user_ids() == (501, 1000)


def test_apply_failure_does_not_select_or_create_state(tmp_path: Path) -> None:
    """A failed build leaves prior machine-managed selection untouched."""
    state_path = tmp_path / "state.json"
    with (
        patch("agent_containers.lifecycle.subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")),
        pytest.raises(subprocess.CalledProcessError),
    ):
        apply_profile(make_profile(), tmp_path / "work.toml", state_path)
    assert not state_path.exists()


def test_apply_noop_inspects_existing_image_without_rewriting_state(tmp_path: Path) -> None:
    """A matching profile verifies its selected image and retains its record."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    state = DeploymentState(profile_name="work")
    state.deployments = [_new_record(profile, "agent-containers/codex:test")]
    save_state(state_path, state)
    with patch("agent_containers.lifecycle.subprocess.run") as run:
        actual = apply_profile(profile, tmp_path / "work.toml", state_path)
    assert actual == state.deployments[0]
    assert run.call_args.args[0] == ("docker", "image", "inspect", "agent-containers/codex:test")


def test_apply_rejects_state_for_another_profile(tmp_path: Path) -> None:
    """An explicit override cannot accidentally cross deployment identities."""
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="other"))
    with pytest.raises(LifecycleError, match="belongs"):
        apply_profile(make_profile(), tmp_path / "work.toml", state_path)


def test_apply_runs_create_only_seed_before_selecting_state(tmp_path: Path) -> None:
    """A new seed is copied before its deployment record can become active."""
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    profile = make_profile(
        mounts=[{"type": "seed", "source": "settings.json", "target": "/home/codex/.codex/settings.json"}]
    )
    contexts = BuildContexts(tmp_path / "image", tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    with (
        patch("agent_containers.lifecycle.prepare_build_contexts", return_value=contexts),
        patch("agent_containers.lifecycle.os.getuid", return_value=501),
        patch("agent_containers.lifecycle.os.getgid", return_value=20),
        patch("agent_containers.lifecycle.subprocess.run") as run,
    ):
        apply_profile(profile, tmp_path / "work.toml", tmp_path / "state.json")
    assert any(call.args[0][:2] == ("docker", "run") for call in run.call_args_list)


def test_rollback_inspects_previous_image_and_warns_about_home_data(tmp_path: Path) -> None:
    """Rollback only changes the selected managed deployment after inspection."""
    profile = make_profile(egress={"mode": "allowlist", "hosts": ["api.example.test"]})
    state_path = tmp_path / "state.json"
    previous = _new_record(profile, "agent-containers/codex:previous")
    current = _new_record(make_profile(egress={"mode": "deny"}), "agent-containers/codex:current")
    state = DeploymentState(profile_name="work", deployments=[previous.model_copy(update={"selected": False}), current])
    save_state(state_path, state)
    with patch("agent_containers.lifecycle.subprocess.run") as run:
        restored = rollback_profile(profile, state_path)
    assert restored.deployment_id == previous.deployment_id
    assert run.call_args.args[0] == ("docker", "image", "inspect", previous.image)
    preview = "\n".join(rollback_preview(restored))
    assert "api.example.test" in preview
    assert "home-volume" in preview
    assert load_state(state_path).selected_deployment == restored


def test_rollback_refuses_missing_prior_deployment(tmp_path: Path) -> None:
    """The first selected deployment cannot manufacture a rollback target."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    with pytest.raises(LifecycleError, match="no prior"):
        rollback_profile(profile, state_path)


def test_rollback_rejects_unselected_or_mismatched_state(tmp_path: Path) -> None:
    """Rollback cannot infer a target from unrelated or unselected records."""
    profile = make_profile()
    unselected_path = tmp_path / "unselected.json"
    save_state(unselected_path, DeploymentState(profile_name="work"))
    with pytest.raises(LifecycleError, match="selected"):
        rollback_profile(profile, unselected_path)
    mismatched_path = tmp_path / "mismatched.json"
    save_state(mismatched_path, DeploymentState(profile_name="other"))
    with pytest.raises(LifecycleError, match="belongs"):
        rollback_profile(profile, mismatched_path)


def test_doctor_reports_absent_state_and_selected_image(tmp_path: Path) -> None:
    """Doctor distinguishes unconfigured profiles from inspectable deployments."""
    profile = make_profile()
    absent = doctor_profile(profile, tmp_path / "missing.json")
    assert not absent.healthy
    assert "absent" in "\n".join(absent.lines)
    unselected_path = tmp_path / "unselected.json"
    save_state(unselected_path, DeploymentState(profile_name="work"))
    unselected = doctor_profile(profile, unselected_path)
    assert not unselected.healthy
    assert "Selected deployment: absent" in unselected.lines
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    with patch("agent_containers.lifecycle._probe", side_effect=[True, True]):
        available = doctor_profile(profile, state_path)
    assert available.healthy
    assert "Selected image: available" in available.lines


def test_doctor_reports_unavailable_docker_and_rejects_mismatched_state(tmp_path: Path) -> None:
    """Docker failure is diagnostic, while mismatched state remains unsafe input."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    with patch("agent_containers.lifecycle._probe", return_value=False):
        unavailable = doctor_profile(profile, state_path)
    assert not unavailable.healthy
    assert "Selected image: unavailable" in unavailable.lines
    mismatch = tmp_path / "mismatch.json"
    save_state(mismatch, DeploymentState(profile_name="other"))
    with pytest.raises(LifecycleError, match="belongs"):
        doctor_profile(profile, mismatch)


def test_doctor_probe_reports_failed_subprocess() -> None:
    """A nonzero inspection result is diagnostic rather than an exception."""
    from agent_containers.lifecycle import _probe

    completed = subprocess.CompletedProcess(("docker", "version"), returncode=1)
    with patch("agent_containers.lifecycle.subprocess.run", return_value=completed):
        assert not _probe("docker", "version")
