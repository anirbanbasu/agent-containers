"""Interactive creation of validated TOML profiles."""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import tomlkit
import typer

from agent_containers.profile import (
    AgentName,
    ConfigurationImport,
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


class MissingProfileFields(ProfileCreationError):
    """Raised when non-interactive profile inputs omit required fields."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__("missing: " + ", ".join(fields))
        self.fields = fields


@dataclass(frozen=True)
class ProfileOptionValues:
    """Flat CLI options that can be reused by create and future edit commands."""

    name: str | None = None
    agent: str | None = None
    home_volume: str | None = None
    apt: tuple[str, ...] | None = None
    npm: tuple[str, ...] | None = None
    uv_tools: tuple[str, ...] | None = None
    uv_libraries: tuple[str, ...] | None = None
    egress_mode: str | None = None
    egress_hosts: tuple[str, ...] | None = None
    gateway_host: str | None = None
    gateway_port: int | None = None
    gateway_user: str | None = None
    gateway_access_hostname: str | None = None
    gateway_bootstrap_allow: tuple[str, ...] | None = None
    gateway_key_file: str | None = None
    gateway_known_hosts_file: str | None = None
    configuration_import: Path | None = None

    def has_values(self) -> bool:
        """Whether at least one flat option was supplied."""
        return any(value is not None for value in self.__dict__.values())


_PARTIAL_NESTED_MODELS: dict[str, set[str]] = {
    "packages": set(PackageSet.model_fields),
    "provider": set(ProviderConfig.model_fields),
    "proxy": set(ProxyConfig.model_fields),
    "egress": set(EgressConfig.model_fields),
    "decant": set(DecantConfig.model_fields),
    "langfuse": set(LangfuseConfig.model_fields),
    "configuration_import": set(ConfigurationImport.model_fields),
    "configuration_mounts": set(MountConfig.model_fields),
    "mounts": set(MountConfig.model_fields),
}


_CONFIGURATION_DOCS = {
    AgentName.CLAUDE_CODE: "https://code.claude.com/docs/en/settings",
    AgentName.CODEX: "https://developers.openai.com/codex/config-basic/",
    AgentName.OPENCODE: "https://opencode.ai/v2/docs/config",
    AgentName.HERMES: "https://hermes-agent.nousresearch.com/docs/user-guide/configuration/",
}


def prompt_profile(path: Path, configuration_import: Path | None = None) -> Profile:
    """Prompt for every profile section and return the validated model."""
    typer.echo("Onboarding roadmap: identity → packages → configuration → network → integrations → mounts")
    typer.echo("Progress: 1/6 identity")
    name = typer.prompt("Profile name", default=path.stem)
    agent = typer.prompt(
        "Agent", default=AgentName.CODEX.value, type=click.Choice([agent.value for agent in AgentName])
    )
    documentation_url = _CONFIGURATION_DOCS.get(agent.strip().lower())
    if documentation_url is not None:
        typer.echo(f"Optional native configuration guide: {documentation_url}")
    home_volume = _optional_prompt("Home Docker volume name (blank uses a user-scoped default)")
    typer.echo("Progress: 2/6 packages")
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
    imported_configuration = (
        ConfigurationImport(source=str(configuration_import.expanduser().resolve()))
        if configuration_import is not None
        else None
    )
    typer.echo("Progress: 3/6 configuration")
    provider = None if host_managed_configuration else _prompt_provider()
    typer.echo("Progress: 4/6 network")
    proxy = _prompt_proxy()
    egress = _prompt_egress()
    typer.echo("Progress: 5/6 integrations")
    decant = _prompt_decant()
    langfuse = LangfuseConfig() if host_managed_configuration else _prompt_langfuse()
    typer.echo("Progress: 6/6 mounts")
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
        configuration_import=imported_configuration,
        configuration_mounts=configuration_mounts,
        mounts=mounts,
    )


def profile_from_options(
    path: Path,
    options: ProfileOptionValues,
    config_path: Path | None = None,
    *,
    non_interactive: bool = False,
) -> Profile:
    """Build a profile from a partial TOML and flat options with safe precedence."""
    data: dict[str, Any] = {}
    if config_path is not None:
        try:
            with config_path.expanduser().resolve().open("rb") as config_file:
                loaded = tomllib.load(config_file)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ProfileCreationError(f"invalid --config {config_path}: {exc}") from exc
        _validate_partial_keys(loaded, config_path)
        data = loaded
    _apply_options(data, options)
    if options.name is None and "name" not in data and not non_interactive:
        data["name"] = path.stem
    missing = _missing_noninteractive_fields(data) if non_interactive else []
    if missing:
        raise MissingProfileFields(missing)
    try:
        return Profile.model_validate(data)
    except ValueError as exc:
        raise ProfileCreationError(str(exc)) from exc


def _validate_partial_keys(value: object, config_path: Path, model_name: str = "Profile") -> None:
    """Reject unknown keys in a partial config before defaults are merged."""
    if not isinstance(value, dict):
        raise ProfileCreationError(f"--config {config_path}: root must be a TOML table")
    allowed = set(Profile.model_fields) if model_name == "Profile" else _PARTIAL_NESTED_MODELS[model_name]
    for key, nested in value.items():
        if key not in allowed:
            raise ProfileCreationError(f"--config {config_path}: unknown key {model_name}.{key}")
        nested_model = key if model_name == "Profile" and key in _PARTIAL_NESTED_MODELS else None
        if nested_model is None:
            continue
        if isinstance(nested, dict):
            _validate_partial_keys(nested, config_path, nested_model)
        elif isinstance(nested, list) and nested_model in {"mounts", "configuration_mounts"}:
            for item in nested:
                _validate_partial_keys(item, config_path, nested_model)
        elif nested is not None:
            raise ProfileCreationError(f"--config {config_path}: {nested_model} must be a TOML table")


def _apply_options(data: dict[str, Any], options: ProfileOptionValues) -> None:
    """Apply explicit flags over config values, replacing repeated lists."""
    for field in ("name", "agent", "home_volume"):
        value = getattr(options, field)
        if value is not None:
            data[field] = value
    packages = data.setdefault("packages", {})
    if not isinstance(packages, dict):
        raise ProfileCreationError("--config packages must be a TOML table")
    for option, field in (("apt", "apt"), ("npm", "npm"), ("uv_tools", "uv_tools"), ("uv_libraries", "uv_libraries")):
        value = getattr(options, option)
        if value is not None:
            packages[field] = list(value)
    egress = data.setdefault("egress", {})
    if not isinstance(egress, dict):
        raise ProfileCreationError("--config egress must be a TOML table")
    for option, field in (
        ("egress_mode", "mode"),
        ("egress_hosts", "hosts"),
        ("gateway_host", "gateway_host"),
        ("gateway_port", "gateway_port"),
        ("gateway_user", "gateway_user"),
        ("gateway_access_hostname", "gateway_access_hostname"),
        ("gateway_bootstrap_allow", "gateway_bootstrap_allow"),
        ("gateway_key_file", "gateway_key_file"),
        ("gateway_known_hosts_file", "gateway_known_hosts_file"),
    ):
        value = getattr(options, option)
        if value is not None:
            egress[field] = list(value) if isinstance(value, tuple) else value
    if options.configuration_import is not None:
        imported = data.setdefault("configuration_import", {})
        if not isinstance(imported, dict):
            raise ProfileCreationError("--config configuration_import must be a TOML table")
        imported["source"] = str(options.configuration_import.expanduser().resolve())


def _missing_noninteractive_fields(data: dict[str, Any]) -> list[str]:
    """Return stable dotted paths for required values absent from CLI input."""
    missing = [field for field in ("name", "agent") if not data.get(field)]
    provider = data.get("provider")
    if isinstance(provider, dict) and provider and not provider.get("api_key_env"):
        missing.append("provider.api_key_env")
    return missing


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
    mode = typer.prompt(
        "Egress mode (deny/allowlist/unrestricted)",
        default="allowlist",
        type=click.Choice(["deny", "allowlist", "unrestricted"]),
    )
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
