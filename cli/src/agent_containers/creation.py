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
    LangfuseConfig,
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
    home_volume = _optional_prompt("Home Docker volume name (blank uses a user-scoped default)")
    packages = PackageSet(
        apt=_csv_prompt("APT packages (comma-separated)"),
        npm=_csv_prompt("NPM packages (comma-separated)"),
        uv_tools=_csv_prompt("uv tools (comma-separated)"),
        uv_libraries=_csv_prompt("uv libraries (comma-separated)"),
    )
    host_managed_configuration = typer.confirm(
        "Use host-managed configuration for provider and observability?", default=False
    )
    configuration_mounts = (
        _prompt_mounts("Number of configuration mounts", "Configuration mount") if host_managed_configuration else []
    )
    provider = None if host_managed_configuration else _prompt_provider()
    proxy = _prompt_proxy()
    egress = _prompt_egress()
    decant = _prompt_decant()
    langfuse = LangfuseConfig() if host_managed_configuration else _prompt_langfuse()
    mounts = _prompt_mounts()
    return Profile(
        name=name,
        agent=agent,
        home_volume=home_volume,
        packages=packages,
        provider=provider,
        proxy=proxy,
        egress=egress,
        decant=decant,
        langfuse=langfuse,
        configuration_mounts=configuration_mounts,
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
        no_proxy=_csv_prompt("Proxy bypass hosts (comma-separated)"),
        ca_file=_optional_prompt("CA file path"),
        ca_dir=_optional_prompt("CA directory path"),
    )


def _prompt_egress() -> EgressConfig:
    mode = typer.prompt("Egress mode (deny/allowlist/unrestricted)", default="allowlist")
    hosts = _csv_prompt("Egress hosts (comma-separated)") if mode.strip().lower() == "allowlist" else []
    gateway_host = _optional_prompt("Gateway host")
    gateway_port = typer.prompt("Gateway port", type=int) if gateway_host is not None else None
    gateway_user = _optional_prompt("Gateway SSH user") if gateway_host is not None else None
    gateway_access_hostname = _optional_prompt("Gateway Access hostname") if gateway_host is not None else None
    gateway_bootstrap_allow = _csv_prompt("Gateway bootstrap IPs/CIDRs (comma-separated)") if gateway_host else []
    gateway_key_file = _optional_prompt("Gateway SSH key path") if gateway_host is not None else None
    gateway_known_hosts_file = _optional_prompt("Gateway known-hosts path") if gateway_host is not None else None
    return EgressConfig(
        mode=mode,
        hosts=hosts,
        gateway_host=gateway_host,
        gateway_port=gateway_port,
        gateway_user=gateway_user,
        gateway_access_hostname=gateway_access_hostname,
        gateway_bootstrap_allow=gateway_bootstrap_allow,
        gateway_key_file=gateway_key_file,
        gateway_known_hosts_file=gateway_known_hosts_file,
    )


def _prompt_decant() -> DecantConfig:
    enabled = typer.confirm("Enable Decant?", default=False)
    if not enabled:
        return DecantConfig()
    return DecantConfig(
        enabled=True,
        source_profiles=_csv_prompt("Decant source profiles (comma-separated)"),
        image=_optional_prompt("Decant account-matched image override (blank uses a user-scoped default)"),
        data_volume=_optional_prompt("Decant data Docker volume (blank uses a user-scoped default)"),
        bind_address=typer.prompt("Decant bind address", default="127.0.0.1"),
        port=typer.prompt("Decant port", default=8787, type=int),
    )


def _prompt_langfuse() -> LangfuseConfig:
    if not typer.confirm("Enable experimental Langfuse observability?", default=False):
        return LangfuseConfig()
    return LangfuseConfig(
        enabled=True,
        base_url=typer.prompt("Langfuse base URL"),
        public_key_env=typer.prompt("Langfuse public-key environment variable", default="LANGFUSE_PUBLIC_KEY"),
        secret_key_env=typer.prompt("Langfuse secret-key environment variable", default="LANGFUSE_SECRET_KEY"),
        environment=_optional_prompt("Langfuse environment label"),
        user_id=_optional_prompt("Langfuse user ID"),
    )


def _prompt_mounts(count_label: str = "Number of custom mounts", item_label: str = "Mount") -> list[MountConfig]:
    count = typer.prompt(count_label, default=0, type=int)
    mounts: list[MountConfig] = []
    for index in range(count):
        typer.echo(f"{item_label} {index + 1} of {count}")
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
