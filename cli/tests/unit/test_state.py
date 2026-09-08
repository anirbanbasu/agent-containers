"""Tests for recorded deployment state and offline planning."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from agent_containers.planner import Plan, PlanAction, build_plan
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
    snapshot = profile_snapshot(profile, profile_path)
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


def test_plan_renders_human_and_versioned_json_forms() -> None:
    """The plan model supplies complete human and machine-readable output."""
    plan = Plan(
        profile_name="work",
        profile_digest="a" * 64,
        actions=[PlanAction.CREATE_IMAGE, PlanAction.UPDATE_IMAGE, PlanAction.UPDATE_LAUNCH],
        changed_sections=["packages", "provider"],
        warnings=[
            "Unrestricted egress is enabled.",
            "Decant is bound to a non-loopback address.",
            "Live Docker state was not inspected.",
            "No selected deployment is recorded.",
            "",
        ],
        live_state_checked=True,
    )
    lines = plan.summary_lines()
    assert "Live Docker state checked: yes" in lines
    payload = plan.json_payload()
    assert payload["schema_version"] == 1
    assert payload["actions"] == [
        {"kind": "create-image", "reason": "initial deployment"},
        {"kind": "update-image", "reason": "packages"},
        {"kind": "update-launch", "reason": "provider"},
    ]
    warnings = cast(list[dict[str, str]], payload["warnings"])
    assert {warning["code"] for warning in warnings} == {
        "unrestricted_egress",
        "decant_non_loopback_bind",
        "live_state_unchecked",
        "no_selected_deployment",
        "unknown_warning",
    }
    mixed = Plan(profile_name="work", profile_digest="a" * 64, actions=[PlanAction.NOOP, PlanAction.UPDATE_LAUNCH])
    mixed_actions = cast(list[dict[str, str]], mixed.json_payload()["actions"])
    assert mixed_actions[1]["reason"] == "profile launch changed"


def test_plan_noop_for_matching_selected_profile() -> None:
    """Matching recorded state produces a no-op."""
    profile = make_profile()
    plan = build_plan(profile, make_state(profile))
    assert plan.is_noop
    assert plan.changed_sections == []


def test_plan_json_noop_and_empty_sections() -> None:
    """No-op JSON plans have a stable reason and empty human sections."""
    plan = Plan(profile_name="work", profile_digest="a" * 64, actions=[PlanAction.NOOP])
    assert plan.summary_lines() == ["Profile: work", "Live Docker state checked: no", "Actions:", "- no-op"]
    assert plan.json_payload()["actions"] == [{"kind": "no-op", "reason": "profile matches selected deployment"}]
    empty = Plan(profile_name="work", profile_digest="a" * 64, actions=[])
    assert empty.summary_lines() == ["Profile: work", "Live Docker state checked: no"]


def test_default_home_volume_field_is_compatible_with_older_state() -> None:
    """Adding the optional volume override does not invalidate old snapshots."""
    profile = make_profile()
    snapshot = profile_snapshot(profile)
    assert "home_volume" not in snapshot
    assert "image" not in snapshot["decant"]
    assert "data_volume" not in snapshot["decant"]
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


def test_plan_classifies_langfuse_as_image_and_launch_change() -> None:
    """Opting into observability rebuilds the plugin image and launch config."""
    current = make_profile(
        langfuse={"enabled": True, "base_url": "https://langfuse.example.test"},
        egress={"hosts": ["langfuse.example.test"]},
    )
    plan = build_plan(current, make_state(make_profile(egress={"hosts": ["langfuse.example.test"]})))
    assert plan.actions == [PlanAction.UPDATE_IMAGE, PlanAction.UPDATE_LAUNCH]
    assert plan.changed_sections == ["langfuse"]


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


def test_plan_warns_for_non_loopback_decant() -> None:
    """Planning exposes the LAN bind warning alongside the offline warning."""
    profile = make_profile(decant={"enabled": True, "source_profiles": ["source"], "bind_address": "0.0.0.0"})
    assert "Decant is bound to a non-loopback address." in build_plan(profile).warnings


def test_plan_legacy_state_falls_back_to_ca_content_detection(tmp_path: Path) -> None:
    """Older state without private content metadata still detects a CA change."""
    ca = tmp_path / "corp-ca.pem"
    ca.write_text("CERT", encoding="utf-8")
    profile = make_profile(proxy={"ca_file": ca.name})
    state = make_state(profile)
    ca.write_text("ROTATED", encoding="utf-8")
    plan = build_plan(profile, state, tmp_path / "work.toml")
    assert plan.changed_sections == ["proxy CA contents"]


def test_plan_detects_changed_configuration_import_contents(tmp_path: Path) -> None:
    """Changing an imported file schedules a launch-time merge."""
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    profile_path = tmp_path / "work.toml"
    profile = make_profile(configuration_import={"source": source.name})
    state = make_state(profile, profile_path)
    source.write_text('{"model":"new"}', encoding="utf-8")
    plan = build_plan(profile, state, profile_path)
    assert plan.actions == [PlanAction.UPDATE_LAUNCH]
    assert plan.changed_sections == ["configuration import contents"]


def test_plan_reports_both_rotated_ca_and_import_contents(tmp_path: Path) -> None:
    """Independent digest fallbacks preserve both content-change reasons."""
    ca = tmp_path / "corp-ca.pem"
    ca.write_text("CERTIFICATE-ONE", encoding="utf-8")
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    profile_path = tmp_path / "work.toml"
    profile = make_profile(
        proxy={"ca_file": ca.name},
        configuration_import={"source": source.name},
    )
    state = make_state(profile, profile_path)
    source.write_text('{"model":"new"}', encoding="utf-8")
    plan = build_plan(profile, state, profile_path)
    assert plan.actions == [PlanAction.UPDATE_LAUNCH]
    assert plan.changed_sections == ["configuration import contents"]


def test_plan_detects_removed_configuration_import() -> None:
    """Removing an import is a launch change even when no file remains to hash."""
    previous = make_profile(configuration_import={"source": "settings.json"})
    plan = build_plan(make_profile(), make_state(previous))
    assert plan.actions == [PlanAction.UPDATE_LAUNCH]
    assert plan.changed_sections == ["configuration_import"]


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


def test_profile_digest_covers_native_configuration_source(tmp_path: Path) -> None:
    """Changing an imported source invalidates the deployment launch digest."""
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    profile = make_profile(configuration_import={"source": source.name})
    profile_path = tmp_path / "work.toml"
    first = profile_digest(profile, profile_path)
    source.write_text('{"model":"new"}', encoding="utf-8")
    assert profile_digest(profile, profile_path) != first
    missing = make_profile(configuration_import={"source": "missing.json"})
    assert profile_digest(missing, profile_path) != first
    absolute = make_profile(configuration_import={"source": str(source)})
    assert profile_digest(absolute, profile_path)


def test_profile_snapshot_handles_optional_decant_shapes() -> None:
    """Snapshot normalization handles both omitted and explicitly configured fields."""
    explicit = profile_snapshot(
        make_profile(decant={"enabled": True, "source_profiles": ["source"], "image": "decant", "data_volume": "data"})
    )
    assert explicit["decant"]["image"] == "decant"
    assert explicit["decant"]["data_volume"] == "data"
    with patch.object(Profile, "model_dump", return_value={"decant": None}):
        assert profile_snapshot(make_profile()) == {"decant": None}


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
