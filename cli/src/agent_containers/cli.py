"""CLI entry point. Runtime operations are added as verified components mature."""

import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from agent_containers.creation import ProfileCreationError, prompt_profile, write_profile
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
        typer.echo(_LOGO)
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
        typer.echo(f"agent-containers {version('agent-containers')}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_flag: Annotated[
        bool,
        typer.Option("--version", callback=show_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Display help without probing Docker or changing user configuration."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


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


@app.command()
def create(
    profile: Annotated[
        Path,
        typer.Argument(dir_okay=False, help="New TOML profile path to create interactively."),
    ],
) -> None:
    """Interactively create a validated TOML profile without contacting Docker."""
    try:
        document = prompt_profile(profile)
        write_profile(profile, document)
    except (OSError, ProfileCreationError, ValidationError, ValueError) as exc:
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
) -> None:
    """Show an offline plan without contacting Docker or changing state."""
    try:
        document = load_profile(profile)
        recorded = load_state(state) if state is not None else None
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="profile/state") from exc
    for line in build_plan(document, recorded).summary_lines():
        typer.echo(line)


@app.command()
def apply(
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
        record = apply_profile(document, profile, state, default_shortcuts_path())
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
        record = rollback_profile(document, state, default_shortcuts_path(), profile)
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
