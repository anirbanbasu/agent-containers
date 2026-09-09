"""Failure-safe deployment lifecycle tests without Docker."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_containers.build_context import BuildContexts
from agent_containers.configuration import ConfigurationError
from agent_containers.lifecycle import (
    LifecycleError,
    _apply_configuration_import,
    _apply_seeds,
    _inspect_tool_shadows,
    _new_record,
    _read_home_file,
    _resolve_decant_sources,
    _volume_helper_argv,
    _write_home_file,
    apply_profile,
    build_user_ids,
    doctor_profile,
    rollback_preview,
    rollback_profile,
)
from agent_containers.profile import Profile
from agent_containers.shortcuts import ShortcutError
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


def test_new_record_persists_effective_home_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    """New deployment records retain the resolved volume for future shortcuts."""
    monkeypatch.setattr("agent_containers.docker.getpass.getuser", lambda: "alice")
    monkeypatch.setattr("agent_containers.docker.os.getuid", lambda: 501)
    record = _new_record(make_profile(), "image")
    assert record.home_volume == "codex-home-alice-501-work"
    explicit = _new_record(make_profile(home_volume="existing-home"), "image")
    assert explicit.home_volume == "existing-home"


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


def test_apply_updates_shortcuts_for_new_and_noop_deployments(tmp_path: Path) -> None:
    """Apply refreshes the generated profile function after successful selection."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    contexts = BuildContexts(tmp_path / "image", tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    with (
        patch("agent_containers.lifecycle.prepare_build_contexts", return_value=contexts),
        patch("agent_containers.lifecycle.os.getuid", return_value=501),
        patch("agent_containers.lifecycle.subprocess.run"),
    ):
        apply_profile(profile, tmp_path / "work.toml", state_path, shortcuts_path)
    assert "agent_containers_work" in shortcuts_path.read_text(encoding="utf-8")
    with patch("agent_containers.lifecycle.subprocess.run"):
        apply_profile(profile, tmp_path / "work.toml", state_path, shortcuts_path)
    assert shortcuts_path.exists()


def test_apply_renders_direct_decant_shortcut_for_current_source(tmp_path: Path) -> None:
    """An opted-in profile can expose its own Claude/Codex collection directly to Decant."""
    profile = make_profile(decant={"enabled": True, "source_profiles": ["work"]})
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    contexts = BuildContexts(tmp_path / "image", tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    with (
        patch("agent_containers.lifecycle.prepare_build_contexts", return_value=contexts),
        patch("agent_containers.lifecycle.os.getuid", return_value=501),
        patch("agent_containers.lifecycle.subprocess.run"),
    ):
        apply_profile(profile, tmp_path / "work.toml", state_path, shortcuts_path)
    text = shortcuts_path.read_text(encoding="utf-8")
    assert "agent_containers_decant_work()" in text
    assert "target=/sources/codex,readonly,volume-subpath=.codex" in text
    with patch("agent_containers.lifecycle.subprocess.run"):
        apply_profile(profile, tmp_path / "work.toml", state_path, shortcuts_path)


def test_apply_requires_selected_external_decant_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Decant setup refuses to create a shortcut when another profile is not deployed."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    profile = make_profile(decant={"enabled": True, "source_profiles": ["claude"]})
    with (
        patch("agent_containers.lifecycle.prepare_build_contexts"),
        patch("agent_containers.lifecycle.subprocess.run"),
        pytest.raises(LifecycleError, match="unavailable"),
    ):
        apply_profile(profile, tmp_path / "work.toml", tmp_path / "work-state.json", tmp_path / "profiles.sh")


def test_apply_loads_external_decant_source_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Decant source profile names resolve through the standard per-user state directory."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    claude = Profile(name="claude", agent="claude-code")
    source_path = tmp_path / "xdg-state/agent-containers/claude.json"
    save_state(source_path, DeploymentState(profile_name="claude", deployments=[_new_record(claude, "claude:image")]))
    profile = make_profile(decant={"enabled": True, "source_profiles": ["claude"]})
    contexts = BuildContexts(tmp_path / "image", tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    shortcuts_path = tmp_path / "profiles.sh"
    with (
        patch("agent_containers.lifecycle.prepare_build_contexts", return_value=contexts),
        patch("agent_containers.lifecycle.subprocess.run"),
    ):
        apply_profile(profile, tmp_path / "work.toml", tmp_path / "work-state.json", shortcuts_path)
    text = shortcuts_path.read_text(encoding="utf-8")
    assert "target=/sources/claude,readonly,volume-subpath=.claude" in text


def test_resolve_decant_sources_rejects_mismatched_or_unselected_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source state must name the requested profile and have an active deployment."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    profile = make_profile(decant={"enabled": True, "source_profiles": ["claude"]})
    source_path = tmp_path / "xdg-state/agent-containers/claude.json"
    save_state(source_path, DeploymentState(profile_name="other"))
    with pytest.raises(LifecycleError, match="belongs"):
        _resolve_decant_sources(profile, _new_record(profile, "image"), tmp_path / "work-state.json")
    save_state(source_path, DeploymentState(profile_name="claude"))
    with pytest.raises(LifecycleError, match="no selected"):
        _resolve_decant_sources(profile, _new_record(profile, "image"), tmp_path / "work-state.json")


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
        home_volume="existing-codex-home",
        mounts=[{"type": "seed", "source": "settings.json", "target": "/home/codex/.codex/settings.json"}],
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
    seed_calls = [call.args[0] for call in run.call_args_list if call.args[0][:2] == ("docker", "run")]
    assert seed_calls
    assert any("type=volume,src=existing-codex-home,dst=/home/codex" in call for call in seed_calls[0])


def test_configuration_import_merges_and_writes_a_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native imports preserve existing keys and use the atomic volume writer."""
    source = tmp_path / "settings.toml"
    source.write_text('model = "new"\nkeep = false\n', encoding="utf-8")
    profile = make_profile(
        configuration_import={"source": source.name, "on_conflict": "replace"},
        home_volume="codex-home",
    )
    writes: list[str] = []
    monkeypatch.setattr(
        "agent_containers.lifecycle._read_home_file",
        lambda *_args: 'model = "old"\nextra = true\n',
    )
    monkeypatch.setattr(
        "agent_containers.lifecycle._write_home_file",
        lambda *_args: writes.append(_args[-1]),
    )
    _apply_configuration_import(profile, tmp_path / "work.toml", "image")
    assert 'model = "new"' in writes[0]
    assert "extra = true" in writes[0]


def test_configuration_import_keeps_existing_values_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default policy is deterministic and reports paths without values."""
    source = tmp_path / "settings.toml"
    source.write_text('model = "new"\n', encoding="utf-8")
    profile = make_profile(configuration_import={"source": source.name})
    monkeypatch.setattr("agent_containers.lifecycle._read_home_file", lambda *_args: 'model = "old"\n')
    writes: list[str] = []
    monkeypatch.setattr("agent_containers.lifecycle._write_home_file", lambda *args: writes.append(args[-1]))
    _apply_configuration_import(profile, tmp_path / "work.toml", "image")
    assert 'model = "old"' in writes[0]
    error = capsys.readouterr().err
    assert "model" in error
    assert "new" not in error
    monkeypatch.setattr(
        "agent_containers.lifecycle.merge_documents",
        lambda *_args: (_ for _ in ()).throw(ValueError("bad merge")),
    )
    with pytest.raises(ValueError, match="bad merge"):
        _apply_configuration_import(profile, tmp_path / "work.toml", "image")
    monkeypatch.setattr(
        "agent_containers.lifecycle.merge_documents",
        lambda *_args: (_ for _ in ()).throw(ConfigurationError("invalid merge")),
    )
    with pytest.raises(LifecycleError, match="invalid merge"):
        _apply_configuration_import(profile, tmp_path / "work.toml", "image")
    _apply_configuration_import(make_profile(), tmp_path / "work.toml", "image")


def test_configuration_import_merges_with_an_empty_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero-byte existing config is an empty document, not an absent file."""
    source = tmp_path / "settings.toml"
    source.write_text('model = "new"\n', encoding="utf-8")
    profile = make_profile(configuration_import={"source": source.name})
    writes: list[str] = []
    monkeypatch.setattr("agent_containers.lifecycle._read_home_file", lambda *_args: "")
    monkeypatch.setattr("agent_containers.lifecycle._write_home_file", lambda *args: writes.append(args[-1]))
    _apply_configuration_import(profile, tmp_path / "work.toml", "image")
    assert writes == ['model = "new"\n']


def test_apply_reconciles_configuration_import_on_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a matching deployment rechecks its optional persistent configuration."""
    source = tmp_path / "settings.toml"
    source.write_text('model = "new"\n', encoding="utf-8")
    profile = make_profile(configuration_import={"source": source.name})
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    reconciled: list[str] = []
    monkeypatch.setattr(
        "agent_containers.lifecycle._apply_configuration_import", lambda *_args: reconciled.append("yes")
    )
    with patch("agent_containers.lifecycle.subprocess.run"):
        apply_profile(profile, tmp_path / "work.toml", state_path)
    assert reconciled == ["yes"]


def test_configuration_volume_helpers_are_networkless_and_fail_safely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Read/write helpers use disposable root access and report Docker failures."""
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr("agent_containers.lifecycle.subprocess.run", lambda argv, **_: calls.append(argv) or Result())
    assert _read_home_file("image", "volume", "/home/codex", "/home/codex/config.json") == "{}"
    _write_home_file("image", "volume", "/home/codex", "/home/codex/config.json", "{}\n")
    assert all("--network=none" in argv for argv in calls)
    assert any("type=volume,src=volume,dst=/home/codex,readonly" in value for value in calls[0])
    assert any("type=volume,src=volume,dst=/home/codex" in value and "readonly" not in value for value in calls[-1])
    assert any("type=bind" in value for value in calls[-1])
    assert "stat -c '%u:%g' /home/codex" in calls[-1][-1]
    assert 'while [ "$probe" != "$home" ]' in calls[-1][-1]
    assert 'chmod 700 "$created"' in calls[-1][-1]
    assert "--cap-add=CHOWN" in _volume_helper_argv("image", "volume", "/home/codex", "true")

    class Failed(Result):
        returncode = 1
        stdout = ""
        stderr = "no access"

    monkeypatch.setattr("agent_containers.lifecycle.subprocess.run", lambda *_args, **_kwargs: Failed())
    with pytest.raises(LifecycleError, match="could not read"):
        _read_home_file("image", "volume", "/home/codex", "/home/codex/config.json")
    with pytest.raises(LifecycleError, match="could not write"):
        _write_home_file("image", "volume", "/home/codex", "/home/codex/config.json", "{}\n")


def test_read_home_file_distinguishes_empty_and_absent_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """The volume helper preserves zero-byte content while marking absence."""

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    outputs = iter(["", "__AGENT_CONTAINERS_FILE_ABSENT__"])
    monkeypatch.setattr(
        "agent_containers.lifecycle.subprocess.run",
        lambda *_args, **_kwargs: Result(next(outputs)),
    )
    assert _read_home_file("image", "volume", "/home/codex", "/home/codex/empty") == ""
    assert _read_home_file("image", "volume", "/home/codex", "/home/codex/missing") is None


def test_seed_application_without_seeds_is_a_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Re-running the seed stage safely handles profiles with no seed mounts."""
    calls: list[object] = []
    monkeypatch.setattr("agent_containers.lifecycle._docker", lambda *args: calls.append(args))
    _apply_seeds(make_profile(), tmp_path / "work.toml", "image")
    assert calls == []


def test_seed_application_skips_non_seed_mounts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only seed mounts invoke the privileged copy helper."""
    calls: list[object] = []
    monkeypatch.setattr("agent_containers.lifecycle._docker", lambda *args: calls.append(args))
    profile = make_profile(mounts=[{"type": "bind", "source": "settings.json", "target": "/tmp/settings.json"}])
    _apply_seeds(profile, tmp_path / "work.toml", "image")
    assert calls == []


def test_inspect_tool_shadows_parses_home_and_managed_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctor identifies only executable names present in both tool trees."""

    class Result:
        returncode = 0
        stderr = ""
        stdout = "home\truff\nmanaged\truff\nhome\tonly-home\nother\tignored\nmalformed\n"

    monkeypatch.setattr("agent_containers.lifecycle.subprocess.run", lambda *_args, **_kwargs: Result())
    assert _inspect_tool_shadows("image", "volume", "codex") == ("ruff",)


def test_rollback_inspects_previous_image_and_warns_about_home_data(tmp_path: Path) -> None:
    """Rollback only changes the selected managed deployment after inspection."""
    profile = make_profile(egress={"mode": "allowlist", "hosts": ["api.example.test"]})
    state_path = tmp_path / "state.json"
    previous = _new_record(profile, "agent-containers/codex:previous")
    current = _new_record(make_profile(egress={"mode": "deny"}), "agent-containers/codex:current")
    state = DeploymentState(profile_name="work", deployments=[previous.model_copy(update={"selected": False}), current])
    save_state(state_path, state)
    with patch("agent_containers.lifecycle.subprocess.run") as run:
        restored = rollback_profile(profile, state_path, profile_path=tmp_path / "work.toml")
    assert restored.deployment_id == previous.deployment_id
    assert run.call_args.args[0] == ("docker", "image", "inspect", previous.image)
    preview = "\n".join(rollback_preview(restored))
    assert "api.example.test" in preview
    assert "home-volume" in preview
    assert load_state(state_path).selected_deployment == restored


def test_rollback_updates_profile_shortcut(tmp_path: Path) -> None:
    """Rollback refreshes the generated wrapper to point at the restored record."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    previous = _new_record(profile, "agent-containers/codex:previous")
    current = _new_record(make_profile(egress={"mode": "deny"}), "agent-containers/codex:current")
    state = DeploymentState(profile_name="work", deployments=[previous.model_copy(update={"selected": False}), current])
    save_state(state_path, state)
    with patch("agent_containers.lifecycle.subprocess.run"):
        rollback_profile(profile, state_path, shortcuts_path, profile_path=tmp_path / "work.toml")
    assert "agent-containers/codex:previous" in shortcuts_path.read_text(encoding="utf-8")


def test_rollback_refreshes_direct_decant_shortcut(tmp_path: Path) -> None:
    """Rollback preflights and restores the Decant direct-mount function too."""
    profile = make_profile(decant={"enabled": True, "source_profiles": ["work"]})
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    previous = _new_record(profile, "agent-containers/codex:previous").model_copy(update={"selected": False})
    current = _new_record(profile, "agent-containers/codex:current")
    save_state(state_path, DeploymentState(profile_name="work", deployments=[previous, current]))
    with patch("agent_containers.lifecycle.subprocess.run"):
        rollback_profile(profile, state_path, shortcuts_path, profile_path=tmp_path / "work.toml")
    text = shortcuts_path.read_text(encoding="utf-8")
    assert "agent_containers_decant_work()" in text
    assert "agent-containers/codex:previous" in text


def test_rollback_preflights_shortcut_before_state_change(tmp_path: Path) -> None:
    """Invalid historical launch inputs cannot leave rollback partially selected."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    shortcuts_path = tmp_path / "profiles.sh"
    previous = _new_record(
        make_profile(
            egress={
                "gateway_host": "gateway",
                "gateway_port": 2222,
                "gateway_key_file": "missing-key",
                "gateway_known_hosts_file": "missing-hosts",
            }
        ),
        "agent-containers/codex:previous",
    )
    current = _new_record(profile, "agent-containers/codex:current")
    save_state(
        state_path,
        DeploymentState(profile_name="work", deployments=[previous.model_copy(update={"selected": False}), current]),
    )
    with patch("agent_containers.lifecycle.subprocess.run"), pytest.raises(ShortcutError, match="gateway key"):
        rollback_profile(profile, state_path, shortcuts_path, profile_path=tmp_path / "work.toml")
    assert load_state(state_path).selected_deployment == current


def test_rollback_refuses_missing_prior_deployment(tmp_path: Path) -> None:
    """The first selected deployment cannot manufacture a rollback target."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    with pytest.raises(LifecycleError, match="no prior"):
        rollback_profile(profile, state_path, profile_path=tmp_path / "work.toml")


def test_rollback_rejects_unselected_or_mismatched_state(tmp_path: Path) -> None:
    """Rollback cannot infer a target from unrelated or unselected records."""
    profile = make_profile()
    unselected_path = tmp_path / "unselected.json"
    save_state(unselected_path, DeploymentState(profile_name="work"))
    with pytest.raises(LifecycleError, match="selected"):
        rollback_profile(profile, unselected_path, profile_path=tmp_path / "work.toml")
    mismatched_path = tmp_path / "mismatched.json"
    save_state(mismatched_path, DeploymentState(profile_name="other"))
    with pytest.raises(LifecycleError, match="belongs"):
        rollback_profile(profile, mismatched_path, profile_path=tmp_path / "work.toml")


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
    with (
        patch("agent_containers.lifecycle._probe", side_effect=[True, True, True]),
        patch("agent_containers.lifecycle._inspect_tool_shadows", return_value=()),
    ):
        available = doctor_profile(profile, state_path)
    assert available.healthy
    assert "Selected image: available" in available.lines
    assert "Home volume:" in "\n".join(available.lines)
    assert "Tool shadowing: none detected" in available.lines


def test_doctor_reports_unavailable_docker_and_rejects_mismatched_state(tmp_path: Path) -> None:
    """Docker failure is diagnostic, while mismatched state remains unsafe input."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    with patch("agent_containers.lifecycle._probe", return_value=False):
        unavailable = doctor_profile(profile, state_path)
    assert not unavailable.healthy
    assert "Selected image: unavailable" in unavailable.lines
    assert "Home volume:" in "\n".join(unavailable.lines)
    assert "Tool shadowing: skipped" in "\n".join(unavailable.lines)
    mismatch = tmp_path / "mismatch.json"
    save_state(mismatch, DeploymentState(profile_name="other"))
    with pytest.raises(LifecycleError, match="belongs"):
        doctor_profile(profile, mismatch)


def test_doctor_reports_tool_shadowing_and_inspection_failure(tmp_path: Path) -> None:
    """Doctor exposes executable-name overlaps without making them fatal."""
    profile = make_profile()
    state_path = tmp_path / "state.json"
    save_state(state_path, DeploymentState(profile_name="work", deployments=[_new_record(profile, "image")]))
    with (
        patch("agent_containers.lifecycle._probe", side_effect=[True, True, True]),
        patch("agent_containers.lifecycle._inspect_tool_shadows", return_value=("codex",)),
    ):
        shadowed = doctor_profile(profile, state_path)
    assert shadowed.healthy
    assert "Tool shadowing: codex" in shadowed.lines
    with (
        patch("agent_containers.lifecycle._probe", side_effect=[True, True, True]),
        patch("agent_containers.lifecycle._inspect_tool_shadows", return_value=None),
    ):
        unavailable = doctor_profile(profile, state_path)
    assert unavailable.healthy
    assert "Tool shadowing: unavailable" in "\n".join(unavailable.lines)


def test_doctor_probe_reports_failed_subprocess() -> None:
    """A nonzero inspection result is diagnostic rather than an exception."""
    from agent_containers.lifecycle import _probe

    completed = subprocess.CompletedProcess(("docker", "version"), returncode=1)
    with patch("agent_containers.lifecycle.subprocess.run", return_value=completed):
        assert not _probe("docker", "version")


def test_inspect_tool_shadows_returns_overlaps_and_handles_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctor reports only executable-name overlaps and degrades on Docker errors."""
    from agent_containers.lifecycle import _inspect_tool_shadows

    completed = subprocess.CompletedProcess(
        ("docker", "run"),
        returncode=0,
        stdout="home\truff\nhome\tcustom\nmanaged\truff\nmanaged\tother\ninvalid\n",
    )
    with patch("agent_containers.lifecycle.subprocess.run", return_value=completed):
        assert _inspect_tool_shadows("image", "volume", "codex") == ("ruff",)
    failed = subprocess.CompletedProcess(("docker", "run"), returncode=1, stdout="")
    with patch("agent_containers.lifecycle.subprocess.run", return_value=failed):
        assert _inspect_tool_shadows("image", "volume", "codex") is None
    with patch("agent_containers.lifecycle.subprocess.run", side_effect=OSError):
        assert _inspect_tool_shadows("image", "volume", "codex") is None
    assert _inspect_tool_shadows("image", "volume", "unknown") is None
