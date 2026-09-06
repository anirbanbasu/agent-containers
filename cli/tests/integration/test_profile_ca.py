"""Opt-in Docker integration coverage for profile-managed CA directories."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_containers.build_context import prepare_build_contexts
from agent_containers.docker import build_image_argv
from agent_containers.profile import Profile

pytestmark = pytest.mark.integration


def test_profile_ca_directory_is_installed_in_system_store(tmp_path: Path) -> None:
    """A profile certificate directory reaches the image trust store."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    if shutil.which("openssl") is None:
        pytest.skip("OpenSSL is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)
    certs = tmp_path / "certs"
    certs.mkdir()
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=agent-containers-integration",
            "-keyout",
            str(tmp_path / "temporary-key.pem"),
            "-out",
            str(certs / "integration.pem"),
        ],
        check=True,
        capture_output=True,
    )
    profile_path = tmp_path / "integration.toml"
    profile = Profile(name="integration-ca", agent="codex", proxy={"ca_dir": "certs"})
    contexts = prepare_build_contexts(profile, tmp_path / "context", profile_path)
    image = "agent-containers/integration-ca:profile"
    try:
        subprocess.run(
            build_image_argv(profile, contexts, image=image),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/run",
                "--cap-drop=ALL",
                "--user",
                "1000:1000",
                "--entrypoint",
                "/bin/sh",
                image,
                "-ceu",
                "test -s /usr/local/share/ca-certificates/custom/profile-ca-0-integration.crt && test -s /etc/ssl/certs/ca-certificates.crt",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)
