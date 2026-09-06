"""The CLI foundation must not require Docker or initialize user state."""

import runpy
import sys
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from agent_containers.cli import app


@pytest.mark.parametrize("args", [[], ["--help"], ["--version"]])
def test_informational_commands_do_not_spawn_processes(args: list[str]) -> None:
    """Help and version work without subprocesses or Docker."""
    with patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess")):
        result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    if args == ["--version"]:
        assert result.output.strip() == f"agent-containers {version('agent-containers')}"
    else:
        assert "not implemented yet" in result.output


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
    assert result.output.strip() == "Valid profile: work (codex)"


def test_validate_rejects_invalid_profile(tmp_path: Path) -> None:
    """Validation returns a command error for invalid profile data."""
    profile = tmp_path / "invalid.toml"
    profile.write_text('name = "Work"\nagent = "codex"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(profile)])
    assert result.exit_code != 0
    assert "name" in result.output


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The python -m entry point invokes the same installed CLI."""
    monkeypatch.setattr(sys, "argv", ["agent-containers", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("agent_containers", run_name="__main__")
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"agent-containers {version('agent-containers')}"
