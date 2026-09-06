"""Tests for profile-owned temporary Docker build contexts."""

from pathlib import Path

import pytest

from agent_containers.build_context import _materialize_proxy_cas, prepare_build_contexts
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


def test_prepare_contexts_copies_single_ca_file(tmp_path: Path) -> None:
    """A single certificate is injected into the isolated image context."""
    (tmp_path / "corp-ca.pem").write_text("CERTIFICATE", encoding="utf-8")
    contexts = prepare_build_contexts(
        make_profile(proxy={"ca_file": "corp-ca.pem"}),
        tmp_path / "context",
        tmp_path / "work.toml",
    )
    assert (contexts.image / "proxy-ca.d/profile-ca.pem").read_text(encoding="utf-8") == "CERTIFICATE"


def test_prepare_contexts_copies_ca_directory_and_rejects_private_keys(tmp_path: Path) -> None:
    """All directory inputs are copied while private-key material is refused."""
    ca_dir = tmp_path / "certs"
    ca_dir.mkdir()
    (ca_dir / "first.crt").write_text("FIRST", encoding="utf-8")
    (ca_dir / "second.pem").write_text("SECOND", encoding="utf-8")
    contexts = prepare_build_contexts(
        make_profile(proxy={"ca_dir": "certs"}),
        tmp_path / "context",
        tmp_path / "work.toml",
    )
    copied = sorted(item.read_text(encoding="utf-8") for item in (contexts.image / "proxy-ca.d").glob("profile-ca-*"))
    assert copied == ["FIRST", "SECOND"]
    (ca_dir / "private.pem").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    with pytest.raises(ValueError, match="private key"):
        prepare_build_contexts(
            make_profile(proxy={"ca_dir": "certs"}),
            tmp_path / "private-context",
            tmp_path / "work.toml",
        )


def test_prepare_contexts_rejects_missing_or_empty_ca_inputs(tmp_path: Path) -> None:
    """Missing and empty certificate inputs fail before a Docker build."""
    with pytest.raises(ValueError, match="CA file does not exist"):
        prepare_build_contexts(
            make_profile(proxy={"ca_file": "missing.pem"}),
            tmp_path / "missing-context",
            tmp_path / "work.toml",
        )
    (tmp_path / "empty-certs").mkdir()
    with pytest.raises(ValueError, match="CA directory is empty"):
        prepare_build_contexts(
            make_profile(proxy={"ca_dir": "empty-certs"}),
            tmp_path / "empty-context",
            tmp_path / "work.toml",
        )
    with pytest.raises(ValueError, match="CA directory does not exist"):
        prepare_build_contexts(
            make_profile(proxy={"ca_dir": "missing-certs"}),
            tmp_path / "missing-dir-context",
            tmp_path / "work.toml",
        )


def test_materialize_proxy_cas_cleans_stale_entries_and_requires_profile_path(tmp_path: Path) -> None:
    """Context preparation removes stale files and requires source provenance."""
    destination = tmp_path / "proxy-ca.d"
    destination.mkdir()
    (destination / "stale.txt").write_text("stale", encoding="utf-8")
    (destination / "stale-dir").mkdir()
    _materialize_proxy_cas(make_profile(), destination, None)
    assert not (destination / "stale.txt").exists()
    assert not (destination / "stale-dir").exists()
    with pytest.raises(ValueError, match="profile_path is required"):
        _materialize_proxy_cas(make_profile(proxy={"ca_file": "ca.pem"}), destination, None)
