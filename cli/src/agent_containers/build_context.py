"""Prepare authoritative, profile-specific Docker build contexts."""

from __future__ import annotations

import shutil
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
_LANGFUSE_OPENCODE_PLUGIN = "@langfuse/opencode-observability-plugin"


@dataclass(frozen=True)
class BuildContexts:
    """Filesystem paths passed to one isolated Docker build."""

    image: Path
    shared: Path


def prepare_build_contexts(profile: Profile, destination: Path, profile_path: Path | None = None) -> BuildContexts:
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
        packages = _packages_for_profile(profile, field)
        (image / filename).write_text(_package_file_content(packages), encoding="utf-8")
    _materialize_agent_plugins(profile, image)
    _materialize_proxy_cas(profile, image / "proxy-ca.d", profile_path)
    return BuildContexts(image=image, shared=shared)


def _packages_for_profile(profile: Profile, field: str) -> list[str]:
    """Add only the package required by an explicitly enabled integration."""
    packages = list(getattr(profile.packages, field))
    required: str | None = None
    if profile.langfuse.enabled and profile.agent.value == "opencode" and field == "npm":
        required = _LANGFUSE_OPENCODE_PLUGIN
    if required is not None and required not in packages:
        packages.append(required)
    return packages


def _materialize_agent_plugins(profile: Profile, image: Path) -> None:
    """Materialize marketplace/plugin selections for profile-enabled adapters."""
    if profile.agent.value == "claude-code" and profile.langfuse.enabled:
        _append_line(image / "plugin-marketplaces.txt", "langfuse/Claude-Observability-Plugin")
        _append_line(image / "plugins.txt", "langfuse-observability@langfuse-observability")
    if profile.agent.value == "codex" and profile.langfuse.enabled:
        _append_line(image / "plugin-marketplaces.txt", "langfuse/codex-observability-plugin")
        _append_line(image / "plugins.txt", "tracing@codex-observability-plugin")


def _append_line(path: Path, value: str) -> None:
    """Append an integration entry once while preserving canonical comments."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if value not in existing.splitlines():
        path.write_text(existing.rstrip() + ("\n" if existing.strip() else "") + value + "\n", encoding="utf-8")


def _package_file_content(packages: list[str]) -> str:
    """Render one package per line, preserving empty-list semantics."""
    return "" if not packages else "\n".join(packages) + "\n"


def _materialize_proxy_cas(profile: Profile, destination: Path, profile_path: Path | None) -> None:
    """Copy profile CA inputs into the isolated image context for system trust."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in destination.iterdir():
        if item.name != ".keep":
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    if profile.proxy is None or (profile.proxy.ca_file is None and profile.proxy.ca_dir is None):
        return
    if profile_path is None:
        raise ValueError("profile_path is required when a proxy CA input is configured")
    base = profile_path.expanduser().resolve().parent
    if profile.proxy.ca_file is not None:
        source = (base / profile.proxy.ca_file).resolve()
        if not source.is_file():
            raise ValueError(f"proxy CA file does not exist: {source}")
        _copy_certificate(source, destination / "profile-ca.pem")
    if profile.proxy.ca_dir is not None:
        source = (base / profile.proxy.ca_dir).resolve()
        if not source.is_dir():
            raise ValueError(f"proxy CA directory does not exist: {source}")
        files = sorted(item for item in source.iterdir() if item.is_file())
        if not files:
            raise ValueError(f"proxy CA directory is empty: {source}")
        for index, item in enumerate(files):
            _copy_certificate(item, destination / f"profile-ca-{index}-{item.name}")


def _copy_certificate(source: Path, destination: Path) -> None:
    """Copy one non-secret certificate input while rejecting private keys."""
    contents = source.read_bytes()
    if b"PRIVATE KEY" in contents:
        raise ValueError(f"proxy CA input must not contain a private key: {source}")
    destination.write_bytes(contents)
