"""Tests for generated profile-specific shell shortcuts."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_containers.profile import Profile
from agent_containers.shortcuts import (
    ShortcutError,
    default_shortcuts_path,
    render_shortcut,
    shortcut_function_name,
    update_shortcuts,
)
from agent_containers.state import DeploymentRecord


def make_profile(**overrides: object) -> Profile:
    """Create a minimal profile fixture."""
    payload: dict[str, object] = {"name": "work-codex", "agent": "codex"}
    payload.update(overrides)
    return Profile.model_validate(payload)


def make_record(profile: Profile) -> DeploymentRecord:
    """Create a selected deployment fixture."""
    return DeploymentRecord(
        deployment_id="work-1",
        image="agent-containers/codex:work",
        profile_digest="a" * 64,
        profile_snapshot=profile.model_dump(mode="json"),
        launch_digest="a" * 64,
        created_at=datetime.now(UTC),
        selected=True,
    )


def test_default_shortcuts_path_uses_xdg_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Generated shortcuts follow the standard per-user config directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert default_shortcuts_path() == (tmp_path / "config/agent-containers/profiles.sh").resolve()


def test_render_shortcut_namespaces_and_recomputes_workspace(tmp_path: Path) -> None:
    """A profile function selects its image while evaluating PWD at invocation."""
    profile = make_profile()
    text = render_shortcut(profile, make_record(profile), tmp_path / "work.toml")
    assert "agent_containers_work_codex()" in text
    assert '"$PWD:/workspace/$(basename "$PWD")"' in text
    assert '"/workspace/$(basename "$PWD")"' in text
    assert "agent-containers/codex:work" in text
    assert "codex-home-work-codex:/home/codex" in text
    assert '"$@"' in text
    assert shortcut_function_name(profile) == "agent_containers_work_codex"


def test_update_shortcuts_replaces_only_matching_profile_block(tmp_path: Path) -> None:
    """Regeneration preserves other generated profiles and replaces the target atomically."""
    path = tmp_path / "profiles.sh"
    first = make_profile()
    second = make_profile(name="local-codex")
    update_shortcuts(path, first, make_record(first), tmp_path / "work.toml")
    update_shortcuts(path, second, make_record(second), tmp_path / "local.toml")
    update_shortcuts(path, first, make_record(first), tmp_path / "work.toml")
    text = path.read_text(encoding="utf-8")
    assert text.count("# BEGIN agent-containers profile work-codex") == 1
    assert text.count("# BEGIN agent-containers profile local-codex") == 1


def test_render_shortcut_includes_opencode_provider_config(tmp_path: Path) -> None:
    """Shortcut generation carries the ephemeral OpenCode adapter config."""
    profile = make_profile(agent="opencode", provider={"kind": "custom", "endpoint": "https://model.example.test"})
    text = render_shortcut(profile, make_record(profile), tmp_path / "work.toml")
    assert "AGENT_OPENCODE_CONFIG_JSON=" in text


def test_render_shortcut_reports_invalid_gateway_inputs(tmp_path: Path) -> None:
    """Shortcut generation preserves safe Docker validation failures."""
    profile = make_profile(egress={"gateway_host": "gateway", "gateway_port": 2222})
    with pytest.raises(ShortcutError, match="gateway key input is required"):
        render_shortcut(profile, make_record(profile), tmp_path / "work.toml")
