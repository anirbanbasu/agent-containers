"""Opt-in runtime checks for the Claude Code and Codex Langfuse adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_containers.build_context import prepare_build_contexts
from agent_containers.docker import build_image_argv, build_run_argv
from agent_containers.profile import Profile

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_langfuse_profile_builds_and_launches_without_credentials(tmp_path: Path, agent: str) -> None:
    """The profile-enabled plugin is installed and the CLI still starts networkless."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)
    profile = Profile(
        name=f"integration-{agent}-langfuse",
        agent=agent,
        langfuse={"enabled": True, "base_url": "https://langfuse.example.test"},
        egress={"hosts": ["langfuse.example.test"]},
    )
    profile_path = tmp_path / f"{agent}.toml"
    contexts = prepare_build_contexts(profile, tmp_path / "context", profile_path)
    image = f"agent-containers/integration-{agent}-langfuse:runtime"
    try:
        subprocess.run(
            build_image_argv(profile, contexts, image=image, uid=os.getuid(), gid=1000),
            check=True,
            capture_output=True,
            text=True,
        )
        launch = list(build_run_argv(profile, tmp_path, profile_path, image=image, agent_args=["--version"]))
        assert "TRACE_TO_LANGFUSE=true" in launch
        assert "LANGFUSE_BASE_URL=https://langfuse.example.test" in launch
        assert "AGENT_LANGFUSE_PUBLIC_KEY_ENV=LANGFUSE_PUBLIC_KEY" in launch
        launch.remove("-it")
        launch.insert(2, "--network=none")
        subprocess.run(launch, check=True, capture_output=True, text=True)
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)
