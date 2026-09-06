"""CLI entry point. Runtime operations are added as verified components mature."""

import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from agent_containers.profile import load_profile

app = typer.Typer(
    help=(
        "Onboarding and maintenance for hardened agent containers. "
        "Development foundation: profile and runtime commands are not implemented yet."
    ),
    add_completion=False,
    pretty_exceptions_enable=False,
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
