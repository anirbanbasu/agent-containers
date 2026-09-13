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
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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

    def has_values(self, exclude: set[str] | None = None) -> bool:
        """Whether at least one flat option was supplied."""
        excluded = exclude or set()
        return any(key not in excluded and value is not None for key, value in self.__dict__.items())


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

_AGENT_DESCRIPTIONS = {
    AgentName.CLAUDE_CODE: "Anthropic's Claude Code CLI, the first-party template image.",
    AgentName.OPENCODE: "OpenCode, the provider-agnostic terminal coding agent.",
    AgentName.CODEX: "The OpenAI Codex CLI.",
    AgentName.HERMES: "Nous Research's self-improving, multi-provider Hermes agent.",
}

_MOUNT_TYPE_DESCRIPTIONS = {
    MountType.BIND: "live bind mount of a single host file or directory (changes are shared both ways)",
    MountType.DIRECTORY: "bind mount an entire host directory into the container",
    MountType.SEED: "copy host content into the home volume once; the agent then owns and can change it",
}

console = Console()


def _stage(step: int, total: int, title: str, body: str) -> None:
    """Announce a wizard stage with a titled panel, with breathing room on both sides."""
    console.print()
    console.print(
        Panel(
            body,
            title=f"[bold]{step}/{total} · {title}[/bold]",
            border_style="cyan",
            padding=(1, 2),
            expand=False,
        )
    )
    console.print()


def _hint(text: str) -> None:
    """Print a short description, followed by a blank line before its prompt."""
    console.print(f"  [dim]{text}[/dim]")
    console.print()


def prompt_profile(path: Path, configuration_import: Path | None = None) -> Profile:
    """Prompt for every profile section and return the validated model."""
    console.print(
        Panel(
            "This wizard walks through six short stages — "
            "[bold]identity → packages → configuration → network → integrations → mounts[/bold] — "
            "and writes a validated TOML profile at the end. Every question shows a description and, "
            "where relevant, the accepted options or range. Press Enter to accept the default shown in "
            "brackets.",
            title="[bold]Onboarding a new agent profile[/bold]",
            border_style="green",
            padding=(1, 2),
            expand=False,
        )
    )
    console.print()
    _stage(1, 6, "Identity", "Name this deployment and choose which agent CLI it runs.")
    _hint(
        "A short identifier for this deployment. It names Docker resources (image, container, volume) "
        "and is how you select this profile later, e.g. `agent-containers apply <name>.toml`.\n"
        "  Allowed: lowercase letters, digits, '_' or '-', starting with a letter."
    )
    name = typer.prompt("Profile name", default=path.stem)
    console.print()
    agent_table = Table(show_header=False, box=None, padding=(0, 2))
    for agent_choice in AgentName:
        description = _AGENT_DESCRIPTIONS[agent_choice]
        documentation_url = _CONFIGURATION_DOCS.get(agent_choice)
        cell = (
            description if documentation_url is None else f"{description}\n[dim]Config docs: {documentation_url}[/dim]"
        )
        agent_table.add_row(f"[bold]{agent_choice.value}[/bold]", cell)
    _hint("Which workload image adapter this profile builds and launches:")
    console.print(agent_table)
    console.print()
    agent = typer.prompt(
        "Agent", default=AgentName.CODEX.value, type=click.Choice([agent.value for agent in AgentName])
    )
    console.print()
    _hint(
        "Persistent Docker named volume backing the agent's home directory across restarts. Leave blank to let "
        "the CLI derive a user-scoped default."
    )
    home_volume = _optional_prompt("Home Docker volume name (blank uses a user-scoped default)")

    _stage(2, 6, "Packages", "Optional build-time software, layered by installation ecosystem.")
    _hint("System packages installed with apt-get, e.g. git, jq.")
    apt = _csv_prompt("APT packages (comma-separated)")
    console.print()
    _hint("NPM packages installed globally, e.g. typescript.")
    npm = _csv_prompt("NPM packages (comma-separated)")
    console.print()
    _hint("Isolated Python CLI tools, each installed into its own venv via `uv tool install`, e.g. ruff.")
    uv_tools = _csv_prompt("uv tools (comma-separated)")
    console.print()
    _hint("Importable Python libraries installed via `uv pip install --system`, e.g. httpx.")
    uv_libraries = _csv_prompt("uv libraries (comma-separated)")
    packages = PackageSet(apt=apt, npm=npm, uv_tools=uv_tools, uv_libraries=uv_libraries)

    _hint(
        "If enabled, provider and observability settings are supplied by mounting files you manage on "
        "the host instead of answering the provider/Langfuse questions below."
    )
    host_managed_configuration = typer.confirm(
        "Use host-managed configuration for provider and observability?", default=False
    )
    if host_managed_configuration:
        console.print()
        _hint("How many host files/directories to mount into the agent's native configuration location.")
    configuration_mounts = (
        _prompt_mounts("Number of configuration mounts", "Configuration mount") if host_managed_configuration else []
    )
    imported_configuration = (
        ConfigurationImport(source=str(configuration_import.expanduser().resolve()))
        if configuration_import is not None
        else None
    )

    _stage(3, 6, "Configuration", "Optional model provider connection details.")
    provider = None if host_managed_configuration else _prompt_provider()

    _stage(4, 6, "Network", "Proxy passthrough and outbound egress policy.")
    proxy = _prompt_proxy()
    egress = _prompt_egress()

    _stage(5, 6, "Integrations", "Optional experimental features: Decant session aggregation and Langfuse tracing.")
    decant = _prompt_decant()
    langfuse = LangfuseConfig() if host_managed_configuration else _prompt_langfuse()

    _stage(6, 6, "Mounts", "Optional extra host files or directories exposed inside the container.")
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
    missing = [name for name, field in Profile.model_fields.items() if field.is_required() and not data.get(name)]
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
    _hint("A provider tells the agent which model backend to call instead of its built-in default.")
    if not typer.confirm("Configure a model provider?", default=False):
        return None
    console.print()
    _hint("Provider identifier passed to the agent adapter, e.g. openai, anthropic, or local.")
    kind = typer.prompt("Provider kind")
    console.print()
    _hint("Base URL of the provider's API, if it differs from the adapter's default. Leave blank to use the default.")
    endpoint = _optional_prompt("Provider endpoint")
    console.print()
    _hint("Model name or tag to request, e.g. gpt-5. Leave blank to use the adapter's default.")
    model = _optional_prompt("Provider model")
    console.print()
    _hint("Name of the environment variable holding the API key — never the key value itself.")
    api_key_env = _optional_prompt("API-key environment variable")
    return ProviderConfig(kind=kind, endpoint=endpoint, model=model, api_key_env=api_key_env)


def _prompt_proxy() -> ProxyConfig | None:
    _hint("Route the container's outbound HTTP(S) traffic through a corporate or network proxy.")
    if not typer.confirm("Configure an HTTP(S) proxy?", default=False):
        return None
    console.print()
    http = _optional_prompt("HTTP proxy URL")
    https = _optional_prompt("HTTPS proxy URL")
    console.print()
    _hint("Hosts that bypass the proxy, e.g. localhost, 127.0.0.1.")
    no_proxy = _csv_prompt("Proxy bypass hosts (comma-separated)")
    console.print()
    _hint(
        "A custom CA bundle file or a directory of CA certificates for the proxy's TLS interception. Supply at most one."
    )
    ca_file = _optional_prompt("CA file path")
    ca_dir = _optional_prompt("CA directory path")
    return ProxyConfig(http=http, https=https, no_proxy=no_proxy, ca_file=ca_file, ca_dir=ca_dir)


def _prompt_egress() -> EgressConfig:
    _hint("Outbound network policy enforced inside the container:")
    console.print(
        "  [dim]•[/dim] [bold]deny[/bold] [dim]— no outbound network access at all[/dim]\n"
        "  [dim]•[/dim] [bold]allowlist[/bold] [dim]— only the hosts you list below are reachable[/dim]\n"
        "  [dim]•[/dim] [bold]unrestricted[/bold] [dim]— no egress filtering; weakens containment[/dim]"
    )
    console.print()
    mode = typer.prompt(
        "Egress mode (deny/allowlist/unrestricted)",
        default="allowlist",
        type=click.Choice(["deny", "allowlist", "unrestricted"]),
    )
    console.print()
    if mode.strip().lower() == "allowlist":
        _hint("Hostnames the container may reach, e.g. api.anthropic.com, registry.npmjs.org.")
    hosts = _csv_prompt("Egress hosts (comma-separated)") if mode.strip().lower() == "allowlist" else []
    console.print()
    _hint(
        "Optional agent-gateway integration: tunnel all egress over SSH to a separate gateway host instead "
        "of filtering in-container. Leave blank to skip."
    )
    gateway_host = _optional_prompt("Gateway host")
    if gateway_host is not None:
        console.print()
        _hint("TCP port of the gateway's SSH endpoint. Range: 1-65535.")
    gateway_port = typer.prompt("Gateway port", type=int) if gateway_host is not None else None
    gateway_user = _optional_prompt("Gateway SSH user") if gateway_host is not None else None
    gateway_access_hostname = _optional_prompt("Gateway Access hostname") if gateway_host is not None else None
    if gateway_host:
        console.print()
        _hint("IP addresses or CIDRs allowed to reach the gateway before the tunnel is fully established.")
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
    _hint("Decant is an experimental service that aggregates sessions from several profiles for review.")
    enabled = typer.confirm("Enable Decant?", default=False)
    if not enabled:
        return DecantConfig()
    console.print()
    _hint("Names of other profiles whose sessions Decant should aggregate.")
    source_profiles = _csv_prompt("Decant source profiles (comma-separated)")
    image = _optional_prompt("Decant account-matched image override (blank uses a user-scoped default)")
    data_volume = _optional_prompt("Decant data Docker volume (blank uses a user-scoped default)")
    console.print()
    _hint("Host interface Decant's UI binds to. Keep this on loopback (127.0.0.1) unless you understand the exposure.")
    bind_address = typer.prompt("Decant bind address", default="127.0.0.1")
    console.print()
    _hint("TCP port for Decant's UI. Range: 1-65535.")
    port = typer.prompt("Decant port", default=8787, type=int)
    return DecantConfig(
        enabled=True,
        source_profiles=source_profiles,
        image=image,
        data_volume=data_volume,
        bind_address=bind_address,
        port=port,
    )


def _prompt_langfuse() -> LangfuseConfig:
    _hint("Langfuse is an experimental integration for sending trace/observability data to a Langfuse instance.")
    if not typer.confirm("Enable experimental Langfuse observability?", default=False):
        return LangfuseConfig()
    console.print()
    base_url = typer.prompt("Langfuse base URL")
    console.print()
    _hint("Names of the environment variables holding your Langfuse keys — never the key values themselves.")
    public_key_env = typer.prompt("Langfuse public-key environment variable", default="LANGFUSE_PUBLIC_KEY")
    secret_key_env = typer.prompt("Langfuse secret-key environment variable", default="LANGFUSE_SECRET_KEY")
    environment = _optional_prompt("Langfuse environment label")
    user_id = _optional_prompt("Langfuse user ID")
    return LangfuseConfig(
        enabled=True,
        base_url=base_url,
        public_key_env=public_key_env,
        secret_key_env=secret_key_env,
        environment=environment,
        user_id=user_id,
    )


def _prompt_mounts(count_label: str = "Number of custom mounts", item_label: str = "Mount") -> list[MountConfig]:
    _hint("How many extra host files or directories to expose inside the container.")
    count = typer.prompt(count_label, default=0, type=int)
    mounts: list[MountConfig] = []
    for index in range(count):
        console.print()
        console.print(f"[bold]{item_label} {index + 1} of {count}[/bold]")
        for mount_type, description in _MOUNT_TYPE_DESCRIPTIONS.items():
            console.print(f"  [dim]•[/dim] [bold]{mount_type.value}[/bold] [dim]— {description}[/dim]")
        console.print()
        mount_type_value = typer.prompt("Mount type (bind/directory/seed)", default=MountType.BIND.value)
        console.print()
        _hint("Path on the host to mount.")
        source = typer.prompt("Mount source")
        console.print()
        _hint("Absolute path inside the container where the source is mounted.")
        target = typer.prompt("Mount target")
        read_only = typer.confirm("Mount read-only?", default=True)
        mounts.append(MountConfig(type=mount_type_value, source=source, target=target, read_only=read_only))
    return mounts


def _csv_prompt(label: str) -> list[str]:
    value = typer.prompt(label, default="")
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_prompt(label: str) -> str | None:
    value = typer.prompt(label, default="")
    return value.strip() or None
