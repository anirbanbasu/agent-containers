"""Interactive creation of validated TOML profiles."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import tomlkit
import typer

from agent_containers.profile import (
    AgentName,
    DecantConfig,
    EgressConfig,
    MountConfig,
    MountType,
    PackageSet,
    Profile,
    ProviderConfig,
    ProxyConfig,
)


class ProfileCreationError(ValueError):
    """Raised when an interactive profile cannot be written safely."""


def prompt_profile(path: Path) -> Profile:
    """Prompt for every profile section and return the validated model."""
    name = typer.prompt("Profile name", default=path.stem)
    agent = typer.prompt("Agent", default=AgentName.CODEX.value)
    packages = PackageSet(
        apt=_csv_prompt("APT packages (comma-separated)"),
        npm=_csv_prompt("NPM packages (comma-separated)"),
        uv_tools=_csv_prompt("uv tools (comma-separated)"),
        uv_libraries=_csv_prompt("uv libraries (comma-separated)"),
    )
    provider = _prompt_provider()
    proxy = _prompt_proxy()
    egress = _prompt_egress()
    decant = _prompt_decant()
    mounts = _prompt_mounts()
    return Profile(
        name=name,
        agent=agent,
        packages=packages,
        provider=provider,
        proxy=proxy,
        egress=egress,
        decant=decant,
        mounts=mounts,
    )


def write_profile(path: Path, profile: Profile) -> None:
    """Write a new profile atomically and refuse to replace an existing file."""
    path = path.expanduser().resolve()
    if path.exists():
        raise ProfileCreationError(f"profile already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = tomlkit.dumps(profile.model_dump(mode="json", exclude_none=True))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as profile_file:
            profile_file.write(document)
            profile_file.flush()
            os.fsync(profile_file.fileno())
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _prompt_provider() -> ProviderConfig | None:
    if not typer.confirm("Configure a model provider?", default=False):
        return None
    return ProviderConfig(
        kind=typer.prompt("Provider kind"),
        endpoint=_optional_prompt("Provider endpoint"),
        model=_optional_prompt("Provider model"),
        api_key_env=_optional_prompt("API-key environment variable"),
    )


def _prompt_proxy() -> ProxyConfig | None:
    if not typer.confirm("Configure an HTTP(S) proxy?", default=False):
        return None
    return ProxyConfig(
        http=_optional_prompt("HTTP proxy URL"),
        https=_optional_prompt("HTTPS proxy URL"),
        ca_file=_optional_prompt("CA file path"),
    )


def _prompt_egress() -> EgressConfig:
    mode = typer.prompt("Egress mode (deny/allowlist/unrestricted)", default="allowlist")
    hosts = _csv_prompt("Egress hosts (comma-separated)") if mode.strip().lower() == "allowlist" else []
    gateway_host = _optional_prompt("Gateway host")
    gateway_port = typer.prompt("Gateway port", type=int) if gateway_host is not None else None
    return EgressConfig(mode=mode, hosts=hosts, gateway_host=gateway_host, gateway_port=gateway_port)


def _prompt_decant() -> DecantConfig:
    enabled = typer.confirm("Enable Decant?", default=False)
    if not enabled:
        return DecantConfig()
    return DecantConfig(
        enabled=True,
        source_profiles=_csv_prompt("Decant source profiles (comma-separated)"),
        bind_address=typer.prompt("Decant bind address", default="127.0.0.1"),
        port=typer.prompt("Decant port", default=8787, type=int),
    )


def _prompt_mounts() -> list[MountConfig]:
    count = typer.prompt("Number of custom mounts", default=0, type=int)
    mounts: list[MountConfig] = []
    for index in range(count):
        typer.echo(f"Mount {index + 1} of {count}")
        mounts.append(
            MountConfig(
                type=typer.prompt("Mount type (bind/directory/seed)", default=MountType.BIND.value),
                source=typer.prompt("Mount source"),
                target=typer.prompt("Mount target"),
                read_only=typer.confirm("Mount read-only?", default=True),
            )
        )
    return mounts


def _csv_prompt(label: str) -> list[str]:
    value = typer.prompt(label, default="")
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_prompt(label: str) -> str | None:
    value = typer.prompt(label, default="")
    return value.strip() or None
