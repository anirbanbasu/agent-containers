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
        "Home Docker volume name (blank uses a user-scoped default)": "existing-codex-home",
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
        "Proxy bypass hosts (comma-separated)": "localhost, 127.0.0.1",
        "CA file path": "corp-ca.pem",
        "CA directory path": "",
        "Egress mode (deny/allowlist/unrestricted)": "allowlist",
        "Egress hosts (comma-separated)": "model.example.test, registry.npmjs.org",
        "Gateway host": "gateway.example.test",
        "Gateway port": 2222,
        "Gateway SSH user": "tunnel",
        "Gateway Access hostname": "gateway-access.example.test",
        "Gateway bootstrap IPs/CIDRs (comma-separated)": "192.0.2.10",
        "Gateway SSH key path": "gateway-key",
        "Gateway known-hosts path": "gateway-known-hosts",
        "Decant source profiles (comma-separated)": "base, tools",
        "Decant bind address": "127.0.0.1",
        "Decant port": 8787,
        "Langfuse base URL": "https://langfuse.example.test",
        "Langfuse public-key environment variable": "LANGFUSE_PUBLIC_KEY",
        "Langfuse secret-key environment variable": "LANGFUSE_SECRET_KEY",
        "Langfuse environment label": "development",
        "Langfuse user ID": "alice",
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
    assert profile.home_volume == "existing-codex-home"
    assert profile.packages.apt == ["git", "jq"]
    assert profile.provider is not None and profile.provider.endpoint is not None
    assert profile.proxy is not None and profile.proxy.ca_file == "corp-ca.pem"
    assert profile.proxy.no_proxy == ["localhost", "127.0.0.1"]
    assert profile.egress.gateway_port == 2222
    assert profile.egress.gateway_user == "tunnel"
    assert profile.egress.gateway_bootstrap_allow == ["192.0.2.10"]
    assert profile.decant.enabled and profile.decant.source_profiles == ["base", "tools"]
    assert profile.langfuse.enabled and profile.langfuse.environment == "development"
    assert profile.mounts[0].target == "/home/codex/settings.json"


def test_prompt_profile_uses_safe_defaults_for_optional_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default wizard path creates a minimal deny-capable profile."""
    answers = {
        "Profile name": "minimal",
        "Agent": "codex",
        "Home Docker volume name (blank uses a user-scoped default)": "",
        "APT packages (comma-separated)": "",
        "NPM packages (comma-separated)": "",
        "uv tools (comma-separated)": "",
        "uv libraries (comma-separated)": "",
        "Egress mode (deny/allowlist/unrestricted)": "deny",
        "Gateway host": "",
        "Number of custom mounts": 0,
    }
    confirms = iter([False, False, False, False])
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
