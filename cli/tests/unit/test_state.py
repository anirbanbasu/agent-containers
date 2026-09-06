"""Tests for recorded deployment state and offline planning."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_containers.planner import PlanAction, build_plan
from agent_containers.profile import Profile
from agent_containers.state import (
    DeploymentRecord,
    DeploymentState,
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


def make_state(profile: Profile) -> DeploymentState:
    """Create a selected record representing an applied profile."""
    snapshot = profile_snapshot(profile)
    digest = profile_digest(profile)
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
