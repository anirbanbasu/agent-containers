"""Access bundled canonical image build contexts."""

from __future__ import annotations

import shutil
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


def bundled_image_root() -> Traversable:
    """Return the packaged image-context directory."""
    return files("agent_containers").joinpath("_assets", "agent-images")


def available_image_contexts() -> tuple[str, ...]:
    """List bundled image directories in stable order."""
    try:
        return tuple(sorted(item.name for item in bundled_image_root().iterdir() if item.is_dir()))
    except FileNotFoundError as exc:
        raise ValueError(
            "bundled image contexts are missing; run scripts/bundle_image_assets.py from the repository"
        ) from exc


def materialize_image_context(name: str, destination: Path) -> Path:
    """Copy one bundled context to a filesystem directory for Docker."""
    if name not in available_image_contexts():
        raise ValueError(f"image context is not bundled: {name}")
    _copy_tree(bundled_image_root().joinpath(name), destination)
    return destination


def _copy_tree(source: Traversable, destination: Path) -> None:
    """Copy a Traversable tree without relying on filesystem-only metadata."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            _copy_tree(item, target)
        else:
            with item.open("rb") as source_file, target.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)
