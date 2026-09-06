"""Prepare authoritative, profile-specific Docker build contexts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_containers.assets import materialize_image_context
from agent_containers.profile import Profile

_PACKAGE_FILES = {
    "apt": "packages-apt.txt",
    "npm": "packages-npm.txt",
    "uv_tools": "tools-uv.txt",
    "uv_libraries": "packages-uv.txt",
}


@dataclass(frozen=True)
class BuildContexts:
    """Filesystem paths passed to one isolated Docker build."""

    image: Path
    shared: Path


def prepare_build_contexts(profile: Profile, destination: Path) -> BuildContexts:
    """Materialize recipes and replace optional package lists from a profile.

    ``destination`` must not exist. This prevents an apply operation from
    silently merging generated files into user-maintained build contexts.
    """
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise ValueError(f"build-context destination already exists: {destination}")
    image = materialize_image_context(profile.agent.value, destination / "image")
    shared = materialize_image_context("shared", destination / "shared")
    for field, filename in _PACKAGE_FILES.items():
        packages = getattr(profile.packages, field)
        (image / filename).write_text(_package_file_content(packages), encoding="utf-8")
    return BuildContexts(image=image, shared=shared)


def _package_file_content(packages: list[str]) -> str:
    """Render one package per line, preserving empty-list semantics."""
    return "" if not packages else "\n".join(packages) + "\n"
