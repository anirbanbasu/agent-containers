"""The CLI foundation must not require Docker or initialize user state."""

import runpy
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from agent_containers.cli import _LOGO, app
from agent_containers.lifecycle import DoctorReport, LifecycleError
from agent_containers.state import DeploymentRecord


@pytest.mark.parametrize("args", [[], ["--help"], ["--version"]])
def test_informational_commands_do_not_spawn_processes(args: list[str]) -> None:
    """Help and version work without subprocesses or Docker."""
    with patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")):
        result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.output.startswith(_LOGO)
    if args == ["--version"]:
        assert result.output.rstrip().endswith(f"agent-containers {version('agent-containers')}")
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


def test_plan_without_state_is_read_only(tmp_path: Path) -> None:
    """Planning a profile reports an offline initial deployment."""
    profile = tmp_path / "work.toml"
    profile.write_text('name = "work"\nagent = "codex"\n', encoding="utf-8")
    with patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")):
        result = CliRunner().invoke(app, ["plan", str(profile)])
    assert result.exit_code == 0, result.output
    assert "create-image" in result.output
    assert "not inspected" in result.output


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
    output = capsys.readouterr().out
    assert output.startswith(_LOGO)
    assert output.rstrip().endswith(f"agent-containers {version('agent-containers')}")
