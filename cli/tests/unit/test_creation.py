"""Tests for the interactive profile creator."""

from pathlib import Path

import pytest

from agent_containers.creation import ProfileCreationError, prompt_profile, write_profile
from agent_containers.profile import Profile


def test_prompt_profile_collects_all_sections(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The wizard maps every answer into the strict profile model."""
    answers = {
        "Profile name": "work",
        "Agent": "codex",
        "APT packages (comma-separated)": "git, jq",
        "NPM packages (comma-separated)": "typescript",
        "uv tools (comma-separated)": "ruff",
        "uv libraries (comma-separated)": "httpx",
        "Provider kind": "local",
        "Provider endpoint": "http://model.example.test/v1",
        "Provider model": "model-1",
        "API-key environment variable": "MODEL_KEY",
        "HTTP proxy URL": "http://proxy.example.test:8080",
        "HTTPS proxy URL": "https://proxy.example.test:8443",
        "CA file path": "corp-ca.pem",
        "Egress mode (deny/allowlist/unrestricted)": "allowlist",
        "Egress hosts (comma-separated)": "model.example.test, registry.npmjs.org",
        "Gateway host": "gateway.example.test",
        "Gateway port": 2222,
        "Decant source profiles (comma-separated)": "base, tools",
        "Decant bind address": "127.0.0.1",
        "Decant port": 8787,
        "Number of custom mounts": 1,
        "Mount type (bind/directory/seed)": "bind",
        "Mount source": "settings.json",
        "Mount target": "/home/codex/settings.json",
    }
    confirms = iter([True, True, True, True, True])
    monkeypatch.setattr("agent_containers.creation.typer.prompt", lambda label, **_: answers[label])
    monkeypatch.setattr("agent_containers.creation.typer.confirm", lambda *_args, **_kwargs: next(confirms))
    profile = prompt_profile(tmp_path / "work.toml")
    assert profile.name == "work"
    assert profile.packages.apt == ["git", "jq"]
    assert profile.provider is not None and profile.provider.endpoint is not None
    assert profile.proxy is not None and profile.proxy.ca_file == "corp-ca.pem"
    assert profile.egress.gateway_port == 2222
    assert profile.decant.enabled and profile.decant.source_profiles == ["base", "tools"]
    assert profile.mounts[0].target == "/home/codex/settings.json"


def test_prompt_profile_uses_safe_defaults_for_optional_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default wizard path creates a minimal deny-capable profile."""
    answers = {
        "Profile name": "minimal",
        "Agent": "codex",
        "APT packages (comma-separated)": "",
        "NPM packages (comma-separated)": "",
        "uv tools (comma-separated)": "",
        "uv libraries (comma-separated)": "",
        "Egress mode (deny/allowlist/unrestricted)": "deny",
        "Gateway host": "",
        "Number of custom mounts": 0,
    }
    confirms = iter([False, False, False])
    monkeypatch.setattr("agent_containers.creation.typer.prompt", lambda label, **_: answers[label])
    monkeypatch.setattr("agent_containers.creation.typer.confirm", lambda *_args, **_kwargs: next(confirms))
    profile = prompt_profile(tmp_path / "minimal.toml")
    assert profile.provider is None
    assert profile.proxy is None
    assert profile.egress.mode == "deny"
    assert not profile.decant.enabled
    assert profile.mounts == []


def test_write_profile_is_atomic_and_refuses_replacement(tmp_path: Path) -> None:
    """Creation writes parseable TOML once and refuses an existing destination."""
    path = tmp_path / "work.toml"
    profile = Profile(name="work", agent="codex")
    write_profile(path, profile)
    assert "schema_version = 1" in path.read_text(encoding="utf-8")
    with pytest.raises(ProfileCreationError, match="already exists"):
        write_profile(path, profile)
