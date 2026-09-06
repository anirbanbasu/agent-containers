"""Tests for packaged image-context access."""

from pathlib import Path

import pytest

from agent_containers.assets import _copy_tree, available_image_contexts, materialize_image_context


def test_bundled_contexts_include_supported_images() -> None:
    """The generated package snapshot contains canonical workload contexts."""
    contexts = available_image_contexts()
    assert "claude-code" in contexts
    assert "codex" in contexts
    assert "hermes" in contexts
    assert "opencode" in contexts
    assert "shared" in contexts


def test_materialize_context_preserves_files_and_mode(tmp_path: Path) -> None:
    """A bundled context can be copied to a Docker build filesystem."""
    destination = materialize_image_context("shared", tmp_path / "shared")
    script = destination / "workload-entrypoint.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o444


def test_materialize_rejects_unknown_context(tmp_path: Path) -> None:
    """Unknown names fail before creating a misleading build context."""
    with pytest.raises(ValueError, match="not bundled"):
        materialize_image_context("missing", tmp_path / "missing")


def test_materialize_copies_nested_resource_directories(tmp_path: Path) -> None:
    """The resource copier handles nested directories without filesystem metadata."""
    source = tmp_path / "source" / "nested"
    source.mkdir(parents=True)
    (source / "file.txt").write_text("content", encoding="utf-8")
    destination = tmp_path / "destination"
    _copy_tree(tmp_path / "source", destination)
    assert (destination / "nested" / "file.txt").read_text(encoding="utf-8") == "content"
