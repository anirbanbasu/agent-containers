"""Tests for profile-owned temporary Docker build contexts."""

from pathlib import Path

import pytest

from agent_containers.build_context import prepare_build_contexts
from agent_containers.profile import Profile


def make_profile(**overrides: object) -> Profile:
    """Create a profile with selected values changed for one test."""
    payload: dict[str, object] = {"name": "work", "agent": "codex"}
    payload.update(overrides)
    return Profile.model_validate(payload)


def test_prepare_contexts_replaces_all_optional_package_lists(tmp_path: Path) -> None:
    """Profile lists are authoritative rather than merged with recipe defaults."""
    contexts = prepare_build_contexts(
        make_profile(
            packages={
                "apt": ["ffmpeg"],
                "npm": ["typescript@5"],
                "uv_tools": ["ruff==0.16.6"],
                "uv_libraries": ["httpx>=0.28"],
            }
        ),
        tmp_path / "context",
    )
    assert (contexts.image / "Dockerfile").is_file()
    assert (contexts.shared / "workload-entrypoint.sh").is_file()
    assert (contexts.image / "packages-apt.txt").read_text(encoding="utf-8") == "ffmpeg\n"
    assert (contexts.image / "packages-npm.txt").read_text(encoding="utf-8") == "typescript@5\n"
    assert (contexts.image / "tools-uv.txt").read_text(encoding="utf-8") == "ruff==0.16.6\n"
    assert (contexts.image / "packages-uv.txt").read_text(encoding="utf-8") == "httpx>=0.28\n"


def test_prepare_contexts_writes_empty_lists_and_refuses_existing_destination(tmp_path: Path) -> None:
    """Empty profiles install no optional packages and never merge into a directory."""
    destination = tmp_path / "context"
    contexts = prepare_build_contexts(make_profile(), destination)
    for filename in ("packages-apt.txt", "packages-npm.txt", "tools-uv.txt", "packages-uv.txt"):
        assert (contexts.image / filename).read_text(encoding="utf-8") == ""
    with pytest.raises(ValueError, match="already exists"):
        prepare_build_contexts(make_profile(), destination)
