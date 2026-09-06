"""Versioned TOML profile model and validation helpers."""

from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

_SCHEMA_VERSION = 1
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_ENV_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class AgentName(StrEnum):
    """Supported workload image adapters."""

    CLAUDE_CODE = "claude-code"
    OPENCODE = "opencode"
    CODEX = "codex"
    HERMES = "hermes"


class MountType(StrEnum):
    """Ways a profile can provide host content to a workload."""

    BIND = "bind"
    DIRECTORY = "directory"
    SEED = "seed"


class PackageSet(BaseModel):
    """Optional build-time packages separated by installation ecosystem."""

    model_config = ConfigDict(extra="forbid")

    apt: list[str] = Field(default_factory=list)
    npm: list[str] = Field(default_factory=list)
    uv_tools: list[str] = Field(default_factory=list)
    uv_libraries: list[str] = Field(default_factory=list)

    @field_validator("apt", "npm", "uv_tools", "uv_libraries")
    @classmethod
    def package_names_are_nonempty(cls, values: list[str]) -> list[str]:
        """Reject blank or multiline package-list entries while preserving order."""
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("package names must not be blank")
        if any("\n" in value or "\r" in value or "\x00" in value for value in cleaned):
            raise ValueError("package names must be single-line text")
        return cleaned


class ProviderConfig(BaseModel):
    """Provider connection details needed to construct a launch."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    endpoint: AnyHttpUrl | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key_env: str | None = None

    @field_validator("kind")
    @classmethod
    def kind_is_normalized(cls, value: str) -> str:
        """Keep provider identifiers stable in deployment records."""
        return value.strip().lower()

    @field_validator("api_key_env")
    @classmethod
    def environment_name_is_safe(cls, value: str | None) -> str | None:
        """Allow secret references but never literal secret values."""
        if value is not None and not _ENV_PATTERN.fullmatch(value):
            raise ValueError("api_key_env must be an uppercase environment variable name")
        return value


class ProxyConfig(BaseModel):
    """HTTP(S) proxy, bypass and runtime trust inputs."""

    model_config = ConfigDict(extra="forbid")

    http: AnyHttpUrl | None = None
    https: AnyHttpUrl | None = None
    no_proxy: list[str] = Field(default_factory=list)
    ca_file: str | None = Field(default=None, min_length=1)

    @field_validator("no_proxy")
    @classmethod
    def no_proxy_entries_are_nonempty(cls, values: list[str]) -> list[str]:
        """Reject accidental blank proxy bypass entries."""
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("no_proxy entries must not be blank")
        return cleaned


class EgressConfig(BaseModel):
    """Runtime egress policy and optional external gateway contract."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "allowlist"
    hosts: list[str] = Field(default_factory=list)
    gateway_host: str | None = Field(default=None, min_length=1)
    gateway_port: Annotated[int | None, Field(default=None, ge=1, le=65535)] = None

    @field_validator("mode")
    @classmethod
    def mode_is_supported(cls, value: str) -> str:
        """Accept only policy modes understood by the planner."""
        normalized = value.strip().lower()
        if normalized not in {"deny", "allowlist", "unrestricted"}:
            raise ValueError("network mode must be deny, allowlist, or unrestricted")
        return normalized

    @field_validator("hosts")
    @classmethod
    def hosts_are_nonempty(cls, values: list[str]) -> list[str]:
        """Reject accidental blank allowlist entries."""
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("egress hosts must not be blank")
        return cleaned

    @model_validator(mode="after")
    def gateway_requires_port(self) -> Self:
        """Require a complete gateway address when either part is supplied."""
        if (self.gateway_host is None) != (self.gateway_port is None):
            raise ValueError("gateway_host and gateway_port must be supplied together")
        return self


class DecantConfig(BaseModel):
    """Optional Decant session aggregation inputs."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    source_profiles: list[str] = Field(default_factory=list)
    bind_address: str = "127.0.0.1"
    port: Annotated[int, Field(default=8787, ge=1, le=65535)] = 8787

    @field_validator("source_profiles")
    @classmethod
    def source_names_are_nonempty(cls, values: list[str]) -> list[str]:
        """Reject blank profile references."""
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("Decant source profile names must not be blank")
        return cleaned


class MountConfig(BaseModel):
    """A custom file/directory input or copy-once seed."""

    model_config = ConfigDict(extra="forbid")

    type: MountType = MountType.BIND
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    read_only: bool = True

    @field_validator("source", "target")
    @classmethod
    def paths_are_trimmed(cls, value: str) -> str:
        """Reject whitespace-only paths."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("mount paths must not be blank")
        return cleaned

    @field_validator("target")
    @classmethod
    def target_is_absolute(cls, value: str) -> str:
        """Container targets must be absolute."""
        if not value.startswith("/") or value == "/":
            raise ValueError("mount target must be an absolute path other than /")
        return value


class Profile(BaseModel):
    """Complete desired configuration for one named agent deployment."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[int, Field(default=_SCHEMA_VERSION, ge=1)]
    name: str
    agent: AgentName
    packages: PackageSet = Field(default_factory=PackageSet)
    provider: ProviderConfig | None = None
    proxy: ProxyConfig | None = None
    egress: EgressConfig = Field(default_factory=EgressConfig)
    decant: DecantConfig = Field(default_factory=DecantConfig)
    mounts: list[MountConfig] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def schema_version_is_current(cls, value: int) -> int:
        """Reject profiles newer than this CLI can interpret."""
        if value != _SCHEMA_VERSION:
            raise ValueError(f"unsupported profile schema_version {value}; expected {_SCHEMA_VERSION}")
        return value

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, value: str) -> str:
        """Constrain names used in Docker resource identifiers."""
        cleaned = value.strip()
        if not _NAME_PATTERN.fullmatch(cleaned):
            raise ValueError("name must start with a lowercase letter and contain only a-z, 0-9, _ or -")
        return cleaned

    @model_validator(mode="after")
    def mounts_do_not_conflict(self) -> Self:
        """Reject duplicate or nested targets Docker would resolve ambiguously."""
        targets = sorted(mount.target.rstrip("/") for mount in self.mounts)
        for index, target in enumerate(targets):
            if index and (target == targets[index - 1] or target.startswith(f"{targets[index - 1]}/")):
                raise ValueError(f"mount targets overlap: {targets[index - 1]} and {target}")
        return self


def load_profile(path: Path) -> Profile:
    """Load and validate a TOML profile from disk."""
    with path.open("rb") as profile_file:
        return Profile.model_validate(tomllib.load(profile_file))


def resolve_mount_source(profile: Profile, mount: MountConfig, profile_path: Path) -> Path:
    """Resolve a relative mount source against the profile file directory."""
    del profile
    source = Path(mount.source).expanduser()
    return source if source.is_absolute() else (profile_path.parent / source).resolve()
