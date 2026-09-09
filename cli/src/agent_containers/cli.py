"""CLI entry point. Runtime operations are added as verified components mature."""

import json
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from agent_containers.configuration import ConfigurationError, load_import_document
from agent_containers.creation import (
    MissingProfileFields,
    ProfileCreationError,
    ProfileOptionValues,
    profile_from_options,
    prompt_profile,
    write_profile,
)
from agent_containers.docker import DockerCommandError
from agent_containers.lifecycle import (
    DoctorReport,
    LifecycleError,
    apply_profile,
    doctor_profile,
    rollback_preview,
    rollback_profile,
)
from agent_containers.planner import build_plan
from agent_containers.profile import load_profile
from agent_containers.shortcuts import ShortcutError, default_shortcuts_path
from agent_containers.state import load_state

_LOGO = """░█▀█░█▀▀░█▀▀░█▀█░▀█▀░░░█▀▀░█▀█░█▀█░▀█▀░█▀█░▀█▀░█▀█░█▀▀░█▀▄░█▀▀
░█▀█░█░█░█▀▀░█░█░░█░░░░█░░░█░█░█░█░░█░░█▀█░░█░░█░█░█▀▀░█▀▄░▀▀█
░▀░▀░▀▀▀░▀▀▀░▀░▀░░▀░░░░▀▀▀░▀▀▀░▀░▀░░▀░░▀░▀░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀"""


class LogoGroup(TyperGroup):
    """Render the required banner before Click dispatches any CLI invocation."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        """Print once for normal commands, help, version and parser errors."""
        typer.echo(_LOGO, err=True)
        return super().parse_args(ctx, args)


app = typer.Typer(
    help=(
        "Onboarding and maintenance for hardened agent containers. "
        "Profiles can be validated, planned, and applied with direct Docker commands."
    ),
    add_completion=False,
    pretty_exceptions_enable=False,
    cls=LogoGroup,
)


def show_version(value: bool) -> None:
    """Read installed distribution metadata, avoiding a second version constant."""
    if value:
        typer.echo(f"agent-containers {version('agent-containers-cli')}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_flag: Annotated[
        bool,
        typer.Option("--version", callback=show_version, is_eager=True, help="Show version and exit."),
    ] = False,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Never prompt; reject underspecified input."),
    ] = False,
) -> None:
    """Display help without probing Docker or changing user configuration."""
    ctx.ensure_object(dict)
    ctx.obj["non_interactive"] = non_interactive
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def _is_non_interactive(ctx: typer.Context) -> bool:
    """Read the global no-prompt contract from a subcommand context."""
    ctx.ensure_object(dict)
    return bool(ctx.obj.get("non_interactive"))


@app.command()
def validate(
    profile: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="TOML profile to validate."),
    ],
) -> None:
    """Validate a TOML profile without contacting Docker or changing state."""
    try:
        document = load_profile(profile)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile") from exc
    typer.echo(f"Valid profile: {document.name} ({document.agent.value})")
    if document.decant.enabled and not document.decant.bind_address_is_loopback:
        typer.echo("Warning: Decant is bound to a non-loopback address.", err=True)


@app.command()
def create(
    ctx: typer.Context,
    profile: Annotated[
        Path,
        typer.Argument(dir_okay=False, help="New TOML profile path to create interactively."),
    ],
    configuration_import: Annotated[
        Path | None,
        typer.Option(
            "--configuration-import",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional agent-native JSON/JSONC/TOML/YAML configuration to validate and import on apply.",
        ),
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Profile name.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Agent adapter.")] = None,
    home_volume: Annotated[str | None, typer.Option("--home-volume", help="Persistent Docker volume name.")] = None,
    apt: Annotated[list[str] | None, typer.Option("--apt", help="APT package; repeatable.")] = None,
    npm: Annotated[list[str] | None, typer.Option("--npm", help="NPM package; repeatable.")] = None,
    uv_tool: Annotated[list[str] | None, typer.Option("--uv-tool", help="uv CLI tool; repeatable.")] = None,
    uv_package: Annotated[
        list[str] | None, typer.Option("--uv-package", help="Importable uv package; repeatable.")
    ] = None,
    egress_mode: Annotated[str | None, typer.Option("--egress-mode", help="deny, allowlist, or unrestricted.")] = None,
    egress_host: Annotated[
        list[str] | None, typer.Option("--egress-host", help="Allowlisted host; repeatable.")
    ] = None,
    gateway_host: Annotated[str | None, typer.Option("--gateway-host")] = None,
    gateway_port: Annotated[int | None, typer.Option("--gateway-port")] = None,
    gateway_user: Annotated[str | None, typer.Option("--gateway-user")] = None,
    gateway_access_hostname: Annotated[str | None, typer.Option("--gateway-access-hostname")] = None,
    gateway_bootstrap_allow: Annotated[
        list[str] | None, typer.Option("--gateway-bootstrap-allow", help="Gateway IP/CIDR; repeatable.")
    ] = None,
    gateway_key_file: Annotated[str | None, typer.Option("--gateway-key-file")] = None,
    gateway_known_hosts_file: Annotated[str | None, typer.Option("--gateway-known-hosts-file")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True, help="Partial TOML input."),
    ] = None,
) -> None:
    """Create a validated TOML profile interactively or from typed options."""
    option_values = ProfileOptionValues(
        name=name,
        agent=agent,
        home_volume=home_volume,
        apt=tuple(apt) if apt is not None else None,
        npm=tuple(npm) if npm is not None else None,
        uv_tools=tuple(uv_tool) if uv_tool is not None else None,
        uv_libraries=tuple(uv_package) if uv_package is not None else None,
        egress_mode=egress_mode,
        egress_hosts=tuple(egress_host) if egress_host is not None else None,
        gateway_host=gateway_host,
        gateway_port=gateway_port,
        gateway_user=gateway_user,
        gateway_access_hostname=gateway_access_hostname,
        gateway_bootstrap_allow=tuple(gateway_bootstrap_allow) if gateway_bootstrap_allow is not None else None,
        gateway_key_file=gateway_key_file,
        gateway_known_hosts_file=gateway_known_hosts_file,
        configuration_import=configuration_import,
    )
    non_interactive = _is_non_interactive(ctx)
    try:
        direct_options = (
            non_interactive or config is not None or option_values.has_values(exclude={"configuration_import"})
        )
        document = (
            profile_from_options(profile, option_values, config, non_interactive=non_interactive)
            if direct_options
            else prompt_profile(profile, configuration_import)
        )
        if document.configuration_import is not None:
            load_import_document(document, profile)
        write_profile(profile, document)
    except MissingProfileFields as exc:
        for field in exc.fields:
            typer.echo(f"missing: {field}", err=True)
        raise typer.Exit(2) from exc
    except (ConfigurationError, OSError, ProfileCreationError, ValidationError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile") from exc
    typer.echo(f"Created profile: {profile.expanduser().resolve()} ({document.name}/{document.agent.value})")


@app.command()
def plan(
    profile: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="TOML profile to plan."),
    ],
    state: Annotated[
        Path | None,
        typer.Option("--state", exists=True, dir_okay=False, readable=True, help="Recorded deployment JSON."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit the versioned machine-readable plan.")] = False,
) -> None:
    """Show an offline plan without contacting Docker or changing state."""
    try:
        document = load_profile(profile)
        recorded = load_state(state) if state is not None else None
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile/state") from exc
    result = build_plan(document, recorded, profile)
    if json_output:
        typer.echo(json.dumps(result.json_payload(), separators=(",", ":")))
    else:
        for line in result.summary_lines():
            typer.echo(line)


@app.command()
def apply(
    ctx: typer.Context,
    profile: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="TOML profile to build and select."),
    ],
    state: Annotated[
        Path | None,
        typer.Option("--state", dir_okay=False, help="Override the XDG deployment-state JSON path."),
    ] = None,
) -> None:
    """Build, safely seed, and select a profile deployment without launching it."""
    try:
        document = load_profile(profile)
        if sys.platform == "darwin":
            typer.echo(
                "Note: macOS Docker Desktop builds retain the host UID and use image GID 1000 to avoid collisions."
            )
        record = apply_profile(
            document,
            profile,
            state,
            default_shortcuts_path(),
        )
    except (
        DockerCommandError,
        LifecycleError,
        ShortcutError,
        OSError,
        subprocess.CalledProcessError,
        tomllib.TOMLDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile/state") from exc
    typer.echo(f"Selected deployment: {record.deployment_id} ({record.image})")


@app.command()
def rollback(
    ctx: typer.Context,
    profile: Annotated[
        Path,
        typer.Argument(
            exists=True, dir_okay=False, readable=True, help="TOML profile whose selected deployment is restored."
        ),
    ],
    state: Annotated[
        Path | None,
        typer.Option(
            "--state", exists=True, dir_okay=False, readable=True, help="Override the XDG deployment-state JSON path."
        ),
    ] = None,
) -> None:
    """Restore the immediately previous retained image and managed launch record."""
    try:
        document = load_profile(profile)
        record = rollback_profile(document, state, default_shortcuts_path(), profile_path=profile)
    except (
        LifecycleError,
        ShortcutError,
        OSError,
        subprocess.CalledProcessError,
        tomllib.TOMLDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile/state") from exc
    for line in rollback_preview(record):
        typer.echo(line)


@app.command()
def doctor(
    profile: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="TOML profile whose deployment is inspected."),
    ],
    state: Annotated[
        Path | None,
        typer.Option("--state", dir_okay=False, help="Override the XDG deployment-state JSON path."),
    ] = None,
) -> None:
    """Check Docker, recorded deployment state, and the selected image without mutating them."""
    try:
        document = load_profile(profile)
        report: DoctorReport = doctor_profile(document, state)
    except (LifecycleError, OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile/state") from exc
    for line in report.lines:
        typer.echo(line)
    if not report.healthy:
        raise typer.Exit(1)
