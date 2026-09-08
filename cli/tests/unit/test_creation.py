"""Tests for the interactive profile creator."""

from pathlib import Path

import pytest

from agent_containers.creation import (
    MissingProfileFields,
    ProfileCreationError,
    ProfileOptionValues,
    _apply_options,
    _validate_partial_keys,
    profile_from_options,
    prompt_profile,
    write_profile,
)
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
        "Decant account-matched image override (blank uses a user-scoped default)": "",
        "Decant data Docker volume (blank uses a user-scoped default)": "",
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
    confirms = iter([False, True, True, True, True, True])
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
    confirms = iter([False, False, False, False, False])
    monkeypatch.setattr("agent_containers.creation.typer.prompt", lambda label, **_: answers[label])
    monkeypatch.setattr("agent_containers.creation.typer.confirm", lambda *_args, **_kwargs: next(confirms))
    profile = prompt_profile(tmp_path / "minimal.toml")
    assert profile.provider is None
    assert profile.proxy is None
    assert profile.egress.mode == "deny"
    assert not profile.decant.enabled
    assert profile.mounts == []


def test_prompt_profile_can_delegate_provider_and_observability_to_configuration_mounts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Host-managed settings avoid duplicating provider and Langfuse prompts."""
    answers = {
        "Profile name": "local",
        "Agent": "claude-code",
        "Home Docker volume name (blank uses a user-scoped default)": "",
        "APT packages (comma-separated)": "",
        "NPM packages (comma-separated)": "",
        "uv tools (comma-separated)": "",
        "uv libraries (comma-separated)": "",
        "Number of configuration mounts": 1,
        "Mount type (bind/directory/seed)": "bind",
        "Mount source": "claude-settings.json",
        "Mount target": "/home/claude/.claude/settings.json",
        "Number of custom mounts": 0,
        "Egress mode (deny/allowlist/unrestricted)": "deny",
        "Gateway host": "",
    }
    confirms = iter([True, True, False, False])
    monkeypatch.setattr("agent_containers.creation.typer.prompt", lambda label, **_: answers[label])
    monkeypatch.setattr("agent_containers.creation.typer.confirm", lambda *_args, **_kwargs: next(confirms))

    profile = prompt_profile(tmp_path / "local.toml")

    assert profile.provider is None
    assert not profile.langfuse.enabled
    assert profile.configuration_mounts[0].target == "/home/claude/.claude/settings.json"


def test_write_profile_is_atomic_and_refuses_replacement(tmp_path: Path) -> None:
    """Creation writes parseable TOML once and refuses an existing destination."""
    path = tmp_path / "work.toml"
    profile = Profile(name="work", agent="codex")
    write_profile(path, profile)
    assert "schema_version = 1" in path.read_text(encoding="utf-8")
    with pytest.raises(ProfileCreationError, match="already exists"):
        write_profile(path, profile)


def test_profile_options_apply_all_flat_fields_and_config_import(tmp_path: Path) -> None:
    """The reusable option layer maps package, egress, and import flags."""
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    options = ProfileOptionValues(
        name="work",
        agent="codex",
        home_volume="work-home",
        apt=("jq",),
        npm=("tool",),
        uv_tools=("ruff",),
        uv_libraries=("httpx",),
        egress_mode="allowlist",
        egress_hosts=("api.example.test",),
        gateway_host="gateway.example.test",
        gateway_port=22,
        gateway_user="tunnel",
        gateway_access_hostname="gateway-access.example.test",
        gateway_bootstrap_allow=("192.0.2.1",),
        gateway_key_file="key",
        gateway_known_hosts_file="known-hosts",
        configuration_import=source,
    )
    assert options.has_values()
    profile = profile_from_options(tmp_path / "work.toml", options, non_interactive=True)
    assert profile.name == "work"
    assert profile.packages.uv_libraries == ["httpx"]
    assert profile.egress.gateway_port == 22
    assert profile.configuration_import is not None


def test_profile_options_validate_partial_nested_keys_and_shapes(tmp_path: Path) -> None:
    """Partial config validation recurses through model tables and mount arrays."""
    config = tmp_path / "partial.toml"
    config.write_text(
        'name = "work"\nagent = "codex"\n[provider]\nkind = "custom"\napi_key_env = "MODEL_KEY"\n'
        '[[mounts]]\nsource = "settings"\ntarget = "/home/codex/settings"\n',
        encoding="utf-8",
    )
    profile = profile_from_options(tmp_path / "work.toml", ProfileOptionValues(), config, non_interactive=True)
    assert profile.provider is not None
    assert profile.mounts[0].target.endswith("settings")

    with pytest.raises(ProfileCreationError, match="root must be"):
        _validate_partial_keys([1], tmp_path / "invalid-root.toml")
    invalid_shape = tmp_path / "invalid-shape.toml"
    invalid_shape.write_text('name = "work"\nagent = "codex"\npackages = "bad"\n', encoding="utf-8")
    with pytest.raises(ProfileCreationError, match="packages must"):
        profile_from_options(tmp_path / "work.toml", ProfileOptionValues(), invalid_shape)
    invalid_egress = tmp_path / "invalid-egress.toml"
    invalid_egress.write_text('name = "work"\nagent = "codex"\negress = "bad"\n', encoding="utf-8")
    with pytest.raises(ProfileCreationError, match="egress must"):
        profile_from_options(tmp_path / "work.toml", ProfileOptionValues(), invalid_egress)


def test_profile_options_report_invalid_toml_and_missing_values(tmp_path: Path) -> None:
    """Option construction reports parse errors and all non-interactive omissions."""
    invalid = tmp_path / "invalid.toml"
    invalid.write_text('name = "unterminated\n', encoding="utf-8")
    with pytest.raises(ProfileCreationError, match="invalid --config"):
        profile_from_options(tmp_path / "work.toml", ProfileOptionValues(), invalid)
    with pytest.raises(MissingProfileFields) as error:
        profile_from_options(tmp_path / "work.toml", ProfileOptionValues(), non_interactive=True)
    assert error.value.fields == ["name", "agent"]


def test_profile_options_adds_path_stem_only_for_interactive_mode(tmp_path: Path) -> None:
    """Interactive option mode can derive a name, while unattended mode cannot."""
    profile = profile_from_options(tmp_path / "derived.toml", ProfileOptionValues(agent="codex"), non_interactive=False)
    assert profile.name == "derived"


def test_profile_options_exercises_invalid_nested_tables(tmp_path: Path) -> None:
    """Malformed nested values fail before Pydantic receives a partial profile."""
    with pytest.raises(ProfileCreationError, match="packages must"):
        _apply_options({"packages": "bad"}, ProfileOptionValues(apt=("jq",)))
    with pytest.raises(ProfileCreationError, match="egress must"):
        _apply_options({"egress": "bad"}, ProfileOptionValues(egress_mode="deny"))
    with pytest.raises(ProfileCreationError, match="configuration_import must"):
        _apply_options(
            {"configuration_import": "bad"},
            ProfileOptionValues(configuration_import=tmp_path / "config.json"),
        )
    _validate_partial_keys({"mounts": []}, tmp_path / "empty.toml")
    with pytest.raises(ProfileCreationError, match="packages must"):
        _validate_partial_keys({"packages": "bad"}, tmp_path / "invalid.toml")
    _validate_partial_keys({"packages": None}, tmp_path / "omitted.toml")


def test_profile_options_wraps_profile_validation_errors(tmp_path: Path) -> None:
    """Typed option mode exposes model errors through the creator's public exception."""
    with pytest.raises(ProfileCreationError, match="agent"):
        profile_from_options(
            tmp_path / "work.toml",
            ProfileOptionValues(name="work", agent="not-an-agent"),
            non_interactive=False,
        )


def test_prompt_profile_can_report_missing_documentation_link(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The wizard tolerates an adapter without a documentation link."""
    from agent_containers import creation

    monkeypatch.setattr(creation, "_CONFIGURATION_DOCS", {"codex": None})
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
    confirms = iter([False, False, False, False, False])
    monkeypatch.setattr("agent_containers.creation.typer.prompt", lambda label, **_: answers[label])
    monkeypatch.setattr("agent_containers.creation.typer.confirm", lambda *_args, **_kwargs: next(confirms))
    assert prompt_profile(tmp_path / "minimal.toml").agent.value == "codex"
