"""The CLI foundation must not require Docker or initialize user state."""

import runpy
import sys
import tomllib
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import cast
from unittest.mock import patch

import click
import pytest
import typer
from typer.testing import CliRunner

from agent_containers.cli import _LOGO, _is_non_interactive, app, main
from agent_containers.creation import ProfileCreationError
from agent_containers.lifecycle import DoctorReport, LifecycleError
from agent_containers.profile import Profile
from agent_containers.state import DeploymentRecord


@pytest.mark.parametrize("args", [[], ["--help"], ["--version"]])
def test_informational_commands_do_not_spawn_processes(args: list[str]) -> None:
    """Help and version work without subprocesses or Docker."""
    with patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")):
        result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.output.startswith(_LOGO)
    if args == ["--version"]:
        assert result.output.rstrip().endswith(f"agent-containers {version('agent-containers-cli')}")
    else:
        assert "apply" in result.output


def test_unknown_command_fails() -> None:
    """Unimplemented lifecycle operations must not silently succeed."""
    result = CliRunner().invoke(app, ["apply", "work"])
    assert result.exit_code != 0


def test_validate_reads_a_profile_without_subprocess(tmp_path: Path) -> None:
    """Validation reports a valid profile without invoking Docker."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    with patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")):
        result = CliRunner().invoke(app, ["validate", str(profile)])
    assert result.exit_code == 0, result.output
    assert result.output.startswith(_LOGO)
    assert result.output.rstrip().endswith("Valid profile: work (codex)")


def test_validate_rejects_invalid_profile(tmp_path: Path) -> None:
    """Validation returns a command error for invalid profile data."""
    profile = tmp_path / "invalid.toml"
    profile.write_text('name = "Work"\nagent = "codex"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(profile)])
    assert result.exit_code != 0
    assert "name" in result.output


def test_create_writes_profile_without_docker(tmp_path: Path) -> None:
    """Create delegates prompting and writing without spawning Docker."""
    profile_path = tmp_path / "new.toml"
    document = Profile(name="new", agent="codex")
    with (
        patch("agent_containers.cli.prompt_profile", return_value=document),
        patch("agent_containers.cli.write_profile"),
    ):
        result = CliRunner().invoke(app, ["create", str(profile_path)])
    assert result.exit_code == 0, result.output
    assert "Created profile" in result.output


def test_create_reports_existing_profile(tmp_path: Path) -> None:
    """Create reports refusal rather than replacing an existing profile."""
    profile_path = tmp_path / "new.toml"
    profile_path.write_text("name = 'old'\n", encoding="utf-8")
    with (
        patch("agent_containers.cli.prompt_profile", return_value=Profile(name="new", agent="codex")),
        patch("agent_containers.cli.write_profile", side_effect=ProfileCreationError("already exists")),
    ):
        result = CliRunner().invoke(app, ["create", str(profile_path)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_create_validates_optional_configuration_import(tmp_path: Path) -> None:
    """Create validates a supplied native configuration before writing the profile."""
    profile_path = tmp_path / "new.toml"
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    document = Profile(name="new", agent="codex", configuration_import={"source": str(source)})
    with (
        patch("agent_containers.cli.prompt_profile", return_value=document),
        patch(
            "agent_containers.cli.load_import_document", return_value=({}, "/home/codex/.codex/config.toml")
        ) as validate,
        patch("agent_containers.cli.write_profile"),
    ):
        result = CliRunner().invoke(app, ["create", str(profile_path), "--configuration-import", str(source)])
    assert result.exit_code == 0, result.output
    validate.assert_called_once()


def test_noninteractive_create_merges_config_and_replaces_lists(tmp_path: Path) -> None:
    """Typed create options override a partial TOML without appending lists."""
    profile_path = tmp_path / "new.toml"
    config = tmp_path / "base.toml"
    config.write_text(
        'name = "base"\nagent = "codex"\n[packages]\napt = ["curl"]\n[egress]\nhosts = ["old.example.test"]\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "--non-interactive",
            "create",
            str(profile_path),
            "--config",
            str(config),
            "--name",
            "work",
            "--agent",
            "codex",
            "--apt",
            "jq",
            "--egress-host",
            "new.example.test",
        ],
    )
    assert result.exit_code == 0, result.output
    with profile_path.open("rb") as profile_file:
        document = tomllib.load(profile_file)
    assert document["name"] == "work"
    assert document["packages"]["apt"] == ["jq"]
    assert document["egress"]["hosts"] == ["new.example.test"]


def test_noninteractive_create_reports_all_missing_fields(tmp_path: Path) -> None:
    """Non-interactive create identifies every required input in stable form."""
    config = tmp_path / "partial.toml"
    config.write_text('name = "work"\n[provider]\nkind = "custom"\n', encoding="utf-8")
    result = CliRunner().invoke(
        app, ["--non-interactive", "create", str(tmp_path / "new.toml"), "--config", str(config)]
    )
    assert result.exit_code != 0
    assert "missing: agent" in result.stderr
    assert "missing: provider.api_key_env" in result.stderr


def test_noninteractive_create_rejects_unknown_config_keys(tmp_path: Path) -> None:
    """Typos in a partial config name the source path and offending key."""
    config = tmp_path / "partial.toml"
    config.write_text('name = "work"\nagent = "codex"\n[egres]\nmode = "deny"\n', encoding="utf-8")
    result = CliRunner().invoke(
        app, ["--non-interactive", "create", str(tmp_path / "new.toml"), "--config", str(config)]
    )
    assert result.exit_code != 0
    assert "unknown key" in result.stderr
    assert "Profile.egres" in result.stderr


def test_plan_without_state_is_read_only(tmp_path: Path) -> None:
    """Planning a profile reports an offline initial deployment."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    with patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")):
        result = CliRunner().invoke(app, ["plan", str(profile)])
    assert result.exit_code == 0, result.output
    assert "create-image" in result.output
    assert "not inspected" in result.output


def test_plan_json_is_stdout_only_and_has_warning_codes(tmp_path: Path) -> None:
    """JSON planning remains parseable while the unconditional banner is stderr."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n[egress]\nmode = "unrestricted"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["plan", str(profile), "--json"])
    assert result.exit_code == 0, result.stderr
    import json

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert {warning["code"] for warning in payload["warnings"]} >= {"unrestricted_egress"}
    assert result.stderr.startswith(_LOGO)


def test_validate_warns_for_non_loopback_decant(tmp_path: Path) -> None:
    """Validation surfaces a LAN-facing Decant bind without rejecting it."""
    profile = tmp_path / "work.toml"
    profile.write_text(
        'name = "work"\nagent = "codex"\n[decant]\nenabled = true\nsource_profiles = ["source"]\nbind_address = "0.0.0.0"\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["validate", str(profile)])
    assert result.exit_code == 0, result.stderr
    assert "non-loopback" in result.stderr


def test_plan_reports_invalid_state(tmp_path: Path) -> None:
    """Planning reports malformed recorded state as a command error."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{not-json", encoding="utf-8")
    result = CliRunner().invoke(app, ["plan", str(profile), "--state", str(state)])
    assert result.exit_code != 0
    assert "state" in result.output.lower()


def test_apply_delegates_to_the_lifecycle_without_starting_docker(tmp_path: Path) -> None:
    """Apply parses its profile then leaves Docker work to the tested lifecycle layer."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    record = DeploymentRecord(
        deployment_id="work-1",
        image="agent-containers/codex:test",
        profile_digest="a" * 64,
        profile_snapshot={},
        launch_digest="a" * 64,
        created_at=datetime.now(UTC),
        selected=True,
    )
    with patch("agent_containers.cli.apply_profile", return_value=record):
        result = CliRunner().invoke(app, ["apply", str(profile)])
    assert result.exit_code == 0, result.output
    assert "Selected deployment: work-1" in result.output


def test_apply_notes_macos_uid_gid_compatibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply documents the macOS-specific image group choice when applicable."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    record = DeploymentRecord(
        deployment_id="work-1",
        image="agent-containers/codex:test",
        profile_digest="a" * 64,
        profile_snapshot={},
        launch_digest="a" * 64,
        created_at=datetime.now(UTC),
        selected=True,
    )
    monkeypatch.setattr("agent_containers.cli.sys.platform", "darwin")
    with patch("agent_containers.cli.apply_profile", return_value=record):
        result = CliRunner().invoke(app, ["apply", str(profile)])
    assert result.exit_code == 0, result.output
    assert "macOS Docker Desktop" in result.output
    monkeypatch.setattr("agent_containers.cli.sys.platform", "linux")
    with patch("agent_containers.cli.apply_profile", return_value=record):
        result = CliRunner().invoke(app, ["apply", str(profile)])
    assert result.exit_code == 0, result.output
    assert "macOS Docker Desktop" not in result.output


@pytest.mark.parametrize("command", ["apply", "rollback"])
def test_noninteractive_global_flag_reaches_lifecycle_commands(command: str) -> None:
    """The global no-prompt setting is available to both lifecycle commands."""
    context = cast(typer.Context, click.Context(click.Command("agent-containers")))
    context.invoked_subcommand = command
    main(context, version_flag=False, non_interactive=True)
    assert _is_non_interactive(context)


def test_noninteractive_global_flag_defaults_off() -> None:
    """The global no-prompt setting remains opt-in."""
    context = cast(typer.Context, click.Context(click.Command("agent-containers")))
    context.invoked_subcommand = "apply"
    main(context, version_flag=False, non_interactive=False)
    assert not _is_non_interactive(context)


def test_apply_reports_lifecycle_failures(tmp_path: Path) -> None:
    """Docker lifecycle errors are rendered as ordinary CLI parameter errors."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    with patch("agent_containers.cli.apply_profile", side_effect=LifecycleError("build failed")):
        result = CliRunner().invoke(app, ["apply", str(profile)])
    assert result.exit_code != 0
    assert "build failed" in result.output


def test_rollback_delegates_and_shows_data_warning(tmp_path: Path) -> None:
    """Rollback renders its safety warning after the lifecycle selects a record."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    record = DeploymentRecord(
        deployment_id="work-previous",
        image="agent-containers/codex:previous",
        profile_digest="a" * 64,
        profile_snapshot={"egress": {"mode": "deny", "hosts": []}},
        launch_digest="a" * 64,
        created_at=datetime.now(UTC),
        selected=True,
    )
    with (
        patch("agent_containers.cli.rollback_profile", return_value=record),
        patch(
            "agent_containers.cli.rollback_preview",
            return_value=["Warning: persistent home-volume data is not rolled back."],
        ),
    ):
        result = CliRunner().invoke(app, ["rollback", str(profile)])
    assert result.exit_code == 0, result.output
    assert "home-volume" in result.output


def test_rollback_reports_lifecycle_failures(tmp_path: Path) -> None:
    """Rollback failures do not turn into an unreported state mutation."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    with patch("agent_containers.cli.rollback_profile", side_effect=LifecycleError("no previous image")):
        result = CliRunner().invoke(app, ["rollback", str(profile)])
    assert result.exit_code != 0
    assert "no previous image" in result.output


def test_doctor_renders_read_only_report(tmp_path: Path) -> None:
    """Doctor exits nonzero for unhealthy diagnostics without changing state."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    report = DoctorReport(("Docker daemon: unavailable",), healthy=False)
    with patch("agent_containers.cli.doctor_profile", return_value=report):
        result = CliRunner().invoke(app, ["doctor", str(profile)])
    assert result.exit_code == 1
    assert "unavailable" in result.output


def test_doctor_healthy_report_exits_zero(tmp_path: Path) -> None:
    """Healthy doctor output takes the successful CLI branch."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    report = DoctorReport(("Docker daemon: available",), healthy=True)
    with patch("agent_containers.cli.doctor_profile", return_value=report):
        result = CliRunner().invoke(app, ["doctor", str(profile)])
    assert result.exit_code == 0


def test_doctor_reports_invalid_state(tmp_path: Path) -> None:
    """State/profile mismatch errors remain clear CLI failures."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    with patch("agent_containers.cli.doctor_profile", side_effect=LifecycleError("state mismatch")):
        result = CliRunner().invoke(app, ["doctor", str(profile)])
    assert result.exit_code != 0
    assert "state mismatch" in result.output


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The python -m entry point invokes the same installed CLI."""
    monkeypatch.setattr(sys, "argv", ["agent-containers", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("agent_containers", run_name="__main__")
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == f"agent-containers {version('agent-containers-cli')}\n"
    assert captured.err.startswith(_LOGO)
    runpy.run_module("agent_containers", run_name="not_main")
