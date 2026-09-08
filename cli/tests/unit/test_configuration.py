"""Tests for optional native configuration imports."""

import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from agent_containers.configuration import (
    ConfigurationConflict,
    ConfigurationError,
    _strip_json_comments,
    configuration_target,
    load_import_document,
    merge_documents,
    parse_document,
    serialize_document,
)
from agent_containers.profile import Profile


def test_native_targets_and_jsonc_comments_are_supported() -> None:
    """Agent-specific targets and comment-aware JSONC parsing are deterministic."""
    profile = Profile(name="work", agent="opencode", configuration_import={"source": "settings.jsonc"})
    assert configuration_target(profile) == (
        "/home/opencode",
        "/home/opencode/.config/opencode/opencode.json",
        "jsonc",
    )
    assert parse_document('{"endpoint":"https://example.test" // comment\n}', "jsonc") == {
        "endpoint": "https://example.test"
    }
    assert parse_document('{"url":"https://example.test", /* comment */ "escaped":"a\\"b"}', "jsonc") == {
        "url": "https://example.test",
        "escaped": 'a"b',
    }
    explicit = Profile(
        name="work",
        agent="opencode",
        configuration_import={"source": "settings.jsonc", "format": "json", "target": "/home/opencode/x.jsonc"},
    )
    assert configuration_target(explicit)[2] == "jsonc"
    assert _strip_json_comments("// trailing comment") == ""
    assert _strip_json_comments("/* unterminated") == ""


def test_configuration_target_rejects_escape_and_formats_round_trip() -> None:
    """Targets cannot escape the home volume and TOML remains parseable."""
    profile = Profile(
        name="work",
        agent="codex",
        configuration_import={"source": "settings.toml", "target": "/tmp/settings.toml"},
    )
    with pytest.raises(ConfigurationError, match="inside /home/codex"):
        configuration_target(profile)
    with pytest.raises(ConfigurationError, match="must use toml"):
        configuration_target(
            Profile(name="work", agent="codex", configuration_import={"source": "x", "format": "json"})
        )
    document = parse_document("[model]\nname = 'gpt'\n", "toml")
    assert 'name = "gpt"' in serialize_document(document, "toml")
    assert parse_document(serialize_document(document, "toml"), "toml") == document


def test_load_import_document_detects_format_from_source(tmp_path: Path) -> None:
    """Source suffixes select native parsers and malformed files are rejected."""
    source = tmp_path / "settings.json"
    source.write_text('{"model":"test"}', encoding="utf-8")
    profile = Profile(name="work", agent="claude-code", configuration_import={"source": source.name})
    document, target = load_import_document(profile, tmp_path / "work.toml")
    assert document == {"model": "test"}
    assert target.endswith("settings.json")

    missing_profile = Profile(name="work", agent="claude-code", configuration_import={"source": "missing.json"})
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_import_document(missing_profile, tmp_path / "work.toml")

    with pytest.raises(ConfigurationError, match="no configuration"):
        load_import_document(Profile(name="work", agent="codex"), tmp_path / "work.toml")

    toml_source = tmp_path / "settings.toml"
    toml_source.write_text("name = 'test'", encoding="utf-8")
    toml_profile = Profile(name="work", agent="codex", configuration_import={"source": toml_source.name})
    assert load_import_document(toml_profile, tmp_path / "work.toml")[0] == {"name": "test"}

    other_source = tmp_path / "settings.conf"
    other_source.write_text('{"name":"other"}', encoding="utf-8")
    other_profile = Profile(name="work", agent="claude-code", configuration_import={"source": other_source.name})
    assert load_import_document(other_profile, tmp_path / "work.toml")[0] == {"name": "other"}

    yaml_source = tmp_path / "settings.yaml"
    yaml_source.write_text("name: test\n", encoding="utf-8")
    fake_yaml = types.SimpleNamespace(safe_load=lambda text: {"name": text.strip().split(": ")[1]})
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "yaml", fake_yaml)
        yaml_profile = Profile(name="work", agent="hermes", configuration_import={"source": yaml_source.name})
        assert load_import_document(yaml_profile, tmp_path / "work.toml")[0] == {"name": "test"}
        invalid_yaml = types.SimpleNamespace(
            YAMLError=ValueError,
            safe_load=lambda _text: (_ for _ in ()).throw(ValueError("bad yaml")),
        )
        patch.setitem(sys.modules, "yaml", invalid_yaml)
        with pytest.raises(ConfigurationError, match="invalid YAML"):
            parse_document("bad", "yaml")

    source.write_text("not-json", encoding="utf-8")
    invalid_profile = Profile(
        name="work",
        agent="claude-code",
        configuration_import={"source": source.name, "format": "json"},
    )
    with pytest.raises(ConfigurationError, match="invalid json"):
        load_import_document(invalid_profile, tmp_path / "work.toml")


def test_merge_preserves_unspecified_values_and_resolves_conflicts() -> None:
    """Nested objects preserve unrelated keys while conflicts require a choice."""
    existing = {"model": {"name": "old", "temperature": 0.2}, "keep": True, "hooks": ["a"]}
    incoming = {"model": {"name": "new"}, "hooks": ["b"]}
    with pytest.raises(ConfigurationConflict, match="model.name"):
        merge_documents(existing, incoming)
    merged = merge_documents(existing, incoming, lambda path, _old, _new: path == "model.name")
    assert merged == {"model": {"name": "new", "temperature": 0.2}, "keep": True, "hooks": ["a"]}
    assert merge_documents(None, incoming) == incoming
    assert merge_documents({"same": 1}, {"same": 1}) == {"same": 1}


def test_parse_and_serialize_reject_invalid_roots_and_formats() -> None:
    """Unsupported formats and roots fail without writing ambiguous data."""
    with pytest.raises(ConfigurationError, match="root"):
        parse_document("1", "json")
    with pytest.raises(ConfigurationError, match="unsupported"):
        parse_document("{}", "ini")
    with pytest.raises(ConfigurationError, match="TOML"):
        serialize_document([], "toml")
    with pytest.raises(ConfigurationError, match="unsupported"):
        serialize_document({}, "ini")
    assert serialize_document({"name": "test"}, "json").startswith("{\n")
    fake_yaml = types.SimpleNamespace(safe_dump=lambda document, **_: "name: " + document["name"] + "\n")
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "yaml", fake_yaml)
        assert serialize_document({"name": "test"}, "yaml") == "name: test\n"
    with pytest.raises(ConfigurationError, match="invalid root"):
        merge_documents({}, cast(Any, 1), lambda _path, _old, _new: True)
