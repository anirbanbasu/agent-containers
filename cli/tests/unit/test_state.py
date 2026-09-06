"""Tests for recorded deployment state and offline planning."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_containers.planner import PlanAction, build_plan
from agent_containers.profile import Profile
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


def make_profile(**overrides: object) -> Profile:
    """Create a minimal profile with selected field overrides."""
    payload: dict[str, object] = {"name": "work", "agent": "codex"}
    payload.update(overrides)
    return Profile.model_validate(payload)


def make_state(profile: Profile, profile_path: Path | None = None) -> DeploymentState:
    """Create a selected record representing an applied profile."""
    snapshot = profile_snapshot(profile)
    digest = profile_digest(profile, profile_path)
    record = DeploymentRecord(
        deployment_id="work-1",
        image="agent-containers/codex:local",
        profile_digest=digest,
        profile_snapshot=snapshot,
        launch_digest=digest,
        created_at=datetime.now(UTC),
        selected=True,
    )
    return DeploymentState(profile_name=profile.name, deployments=[record])


def test_state_round_trips_json(tmp_path: Path) -> None:
    """Machine-managed state can be persisted and loaded."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    save_state(state_path, make_state(profile))
    loaded = load_state(state_path)
    assert loaded.selected_deployment is not None
    assert loaded.selected_deployment.profile_digest == profile_digest(profile)


def test_default_state_path_uses_xdg_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Default machine state is separate from user-editable profile files."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_state_path(make_profile()) == tmp_path / "state" / "agent-containers" / "work.json"


def test_plan_initial_deployment_is_explicitly_offline() -> None:
    """No state produces a create-image plan and live-state warning."""
    plan = build_plan(make_profile())
    assert plan.actions == [PlanAction.CREATE_IMAGE]
    assert not plan.live_state_checked
    assert "No selected deployment" in "\n".join(plan.warnings)


def test_plan_noop_for_matching_selected_profile() -> None:
    """Matching recorded state produces a no-op."""
    profile = make_profile()
    plan = build_plan(profile, make_state(profile))
    assert plan.is_noop
    assert plan.changed_sections == []


def test_default_home_volume_field_is_compatible_with_older_state() -> None:
    """Adding the optional volume override does not invalidate old snapshots."""
    profile = make_profile()
    snapshot = profile_snapshot(profile)
    assert "home_volume" not in snapshot
    assert build_plan(profile, make_state(profile)).is_noop


def test_explicit_home_volume_is_recorded_in_profile_snapshot() -> None:
    """An explicit volume choice participates in deployment identity and planning."""
    profile = make_profile(home_volume="existing-home")
    assert profile_snapshot(profile)["home_volume"] == "existing-home"
    plan = build_plan(make_profile(), make_state(profile))
    assert plan.actions == [PlanAction.UPDATE_LAUNCH]
    assert plan.changed_sections == ["home_volume"]


def test_plan_classifies_image_and_launch_changes() -> None:
    """Package and endpoint changes are separated for future apply ordering."""
    previous = make_profile()
    current = make_profile(
        packages={"apt": ["jq"]},
        provider={"kind": "custom", "endpoint": "http://localhost:8080", "model": "local"},
    )
    plan = build_plan(current, make_state(previous))
    assert plan.actions == [PlanAction.UPDATE_IMAGE, PlanAction.UPDATE_LAUNCH]
    assert plan.changed_sections == ["packages", "provider"]
    assert not plan.live_state_checked


def test_plan_detects_rotated_proxy_ca_contents(tmp_path: Path) -> None:
    """Changing a certificate file triggers an image rebuild even if TOML is unchanged."""
    ca = tmp_path / "corp-ca.pem"
    ca.write_text("CERTIFICATE-ONE", encoding="utf-8")
    profile_path = tmp_path / "work.toml"
    profile = make_profile(proxy={"ca_file": "corp-ca.pem"})
    state = make_state(profile, profile_path)
    ca.write_text("CERTIFICATE-TWO", encoding="utf-8")
    plan = build_plan(profile, state, profile_path)
    assert plan.actions == [PlanAction.UPDATE_IMAGE]
    assert plan.changed_sections == ["proxy CA contents"]


def test_profile_digest_covers_ca_directory_and_rejects_bad_inputs(tmp_path: Path) -> None:
    """Directory contents participate in identity and invalid sources fail safely."""
    ca_dir = tmp_path / "certs"
    ca_dir.mkdir()
    (ca_dir / "one.pem").write_text("ONE", encoding="utf-8")
    profile = make_profile(proxy={"ca_dir": "certs"})
    profile_path = tmp_path / "work.toml"
    first = profile_digest(profile, profile_path)
    (ca_dir / "two.pem").write_text("TWO", encoding="utf-8")
    assert profile_digest(profile, profile_path) != first
    with pytest.raises(ValueError, match="CA directory does not exist"):
        profile_digest(make_profile(proxy={"ca_dir": "missing"}), profile_path)
    with pytest.raises(ValueError, match="CA file does not exist"):
        profile_digest(make_profile(proxy={"ca_file": "missing.pem"}), profile_path)
    empty_dir = tmp_path / "empty-certs"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="CA directory is empty"):
        profile_digest(make_profile(proxy={"ca_dir": "empty-certs"}), profile_path)


def test_state_rejects_two_selected_records() -> None:
    """State cannot have two active deployments."""
    profile = make_profile()
    state = make_state(profile)
    duplicate = state.deployments[0].model_copy(update={"deployment_id": "work-2", "selected": True})
    try:
        DeploymentState(profile_name="work", deployments=[state.deployments[0], duplicate])
    except ValueError as exc:
        assert "at most one" in str(exc)
    else:
        raise AssertionError("expected selected-state validation failure")


def test_state_rejects_naive_timestamp() -> None:
    """Deployment records require timezone-aware timestamps."""
    profile = make_profile()
    snapshot = profile_snapshot(profile)
    with pytest.raises(ValueError, match="timezone"):
        DeploymentRecord(
            deployment_id="work-1",
            image="image",
            profile_digest=profile_digest(profile),
            profile_snapshot=snapshot,
            launch_digest=profile_digest(profile),
            created_at=datetime(2026, 1, 1),  # noqa: DTZ001 - intentionally tests rejection
        )


def test_new_deployment_id_contains_profile_and_digest() -> None:
    """Deployment IDs are stable enough to identify their desired profile."""
    profile = make_profile()
    identifier = new_deployment_id(profile)
    assert identifier.startswith("work-")
    assert identifier.endswith(profile_digest(profile)[:12])
