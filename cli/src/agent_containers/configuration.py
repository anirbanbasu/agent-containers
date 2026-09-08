"""Native configuration import, validation, and conservative merging."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import tomlkit

from agent_containers.profile import AgentName, Profile, resolve_mount_source

ConfigurationDocument = dict[str, Any] | list[Any]
ConflictResolver = Callable[[str, Any, Any], bool]

_TARGETS = {
    AgentName.CLAUDE_CODE: ("/home/claude", "/home/claude/.claude/settings.json", "json"),
    AgentName.CODEX: ("/home/codex", "/home/codex/.codex/config.toml", "toml"),
    AgentName.OPENCODE: ("/home/opencode", "/home/opencode/.config/opencode/opencode.json", "jsonc"),
    AgentName.HERMES: ("/opt/data", "/opt/data/config.yaml", "yaml"),
}
_ALLOWED_FORMATS = {
    AgentName.CLAUDE_CODE: {"json", "jsonc"},
    AgentName.CODEX: {"toml"},
    AgentName.OPENCODE: {"json", "jsonc"},
    AgentName.HERMES: {"yaml"},
}


class ConfigurationError(ValueError):
    """Raised when an imported configuration cannot be safely processed."""


class ConfigurationConflict(ConfigurationError):
    """Raised when a non-interactive merge encounters differing values."""

    def __init__(self, path: str, existing: Any, incoming: Any) -> None:
        super().__init__(f"configuration conflict at {path or '<root>'}; rerun interactively to resolve")
        self.path = path
        self.existing = existing
        self.incoming = incoming


def configuration_target(profile: Profile) -> tuple[str, str, str]:
    """Return home path, native target, and format for an agent adapter."""
    home, default_target, default_format = _TARGETS[profile.agent]
    imported = profile.configuration_import
    target = imported.target if imported and imported.target else default_target
    if not target.startswith(f"{home}/"):
        raise ConfigurationError(f"configuration target must be inside {home}: {target}")
    format_name = imported.format if imported and imported.format else default_format
    if format_name == "json" and target.endswith(".jsonc"):
        format_name = "jsonc"
    if format_name not in _ALLOWED_FORMATS[profile.agent]:
        allowed = ", ".join(sorted(_ALLOWED_FORMATS[profile.agent]))
        raise ConfigurationError(f"{profile.agent.value} configuration imports must use {allowed}")
    return home, target, format_name


def load_import_document(profile: Profile, profile_path: Path) -> tuple[ConfigurationDocument, str]:
    """Read and parse an import source without executing any configuration content."""
    imported = profile.configuration_import
    if imported is None:
        raise ConfigurationError("profile has no configuration import")
    source = resolve_mount_source(imported.source, profile_path)
    if not source.is_file():
        raise ConfigurationError(f"configuration import source does not exist: {source}")
    _, target, default_format = configuration_target(profile)
    format_name = imported.format or default_format
    if imported.format is None:
        suffix = source.suffix.lower()
        if suffix in {".json", ".jsonc"}:
            format_name = "jsonc" if suffix == ".jsonc" else "json"
        elif suffix == ".toml":
            format_name = "toml"
        elif suffix in {".yaml", ".yml"}:
            format_name = "yaml"
    try:
        text = source.read_text(encoding="utf-8")
        return parse_document(text, format_name), target
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError, ConfigurationError) as exc:
        raise ConfigurationError(f"invalid {format_name} configuration in {source}: {exc}") from exc


def parse_document(text: str, format_name: str) -> ConfigurationDocument:
    """Parse one of the supported native formats."""
    if format_name == "jsonc":
        text = _strip_json_comments(text)
        format_name = "json"
    if format_name == "json":
        document = json.loads(text)
    elif format_name == "toml":
        document = tomllib.loads(text)
    elif format_name == "yaml":
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - exercised in packaging environments
            raise ConfigurationError("YAML imports require the PyYAML CLI dependency") from exc
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"invalid YAML document: {exc}") from exc
    else:  # pragma: no cover - profile validation prevents this branch
        raise ConfigurationError(f"unsupported configuration format: {format_name}")
    if not isinstance(document, (dict, list)):
        raise ConfigurationError("configuration document must contain an object or array at its root")
    return document


def serialize_document(document: ConfigurationDocument, format_name: str) -> str:
    """Serialize a merged document for atomic installation in the home volume."""
    if format_name in {"json", "jsonc"}:
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if format_name == "toml":
        if not isinstance(document, dict):
            raise ConfigurationError("TOML configuration root must be an object")
        return tomlkit.dumps(document)
    if format_name == "yaml":
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - exercised in packaging environments
            raise ConfigurationError("YAML imports require the PyYAML CLI dependency") from exc
        return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    raise ConfigurationError(f"unsupported configuration format: {format_name}")


def merge_documents(
    existing: ConfigurationDocument | None,
    incoming: ConfigurationDocument,
    resolver: ConflictResolver | None = None,
) -> ConfigurationDocument:
    """Merge incoming keys while preserving unspecified existing settings."""
    if existing is None:
        return incoming
    merged = _merge_value(existing, incoming, "", resolver)
    if not isinstance(merged, (dict, list)):
        raise ConfigurationError("merged configuration has an invalid root")
    return merged


def _merge_value(existing: Any, incoming: Any, path: str, resolver: ConflictResolver | None) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        result = dict(existing)
        for key, value in incoming.items():
            child_path = f"{path}.{key}" if path else str(key)
            result[key] = _merge_value(result[key], value, child_path, resolver) if key in result else value
        return result
    if existing == incoming:
        return existing
    if resolver is None:
        raise ConfigurationConflict(path, existing, incoming)
    return incoming if resolver(path, existing, incoming) else existing


def _strip_json_comments(text: str) -> str:
    """Remove JSONC comments while respecting quoted strings."""
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
        elif character == '"':
            in_string = True
            output.append(character)
            index += 1
        elif character == "/" and following == "/":
            index = text.find("\n", index)
            if index == -1:
                break
        elif character == "/" and following == "*":
            end = text.find("*/", index + 2)
            if end == -1:
                break
            index = end + 2
        else:
            output.append(character)
            index += 1
    return "".join(output)
