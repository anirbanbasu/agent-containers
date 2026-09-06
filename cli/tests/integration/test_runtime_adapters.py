"""Opt-in Docker runtime coverage for the remaining agent adapters."""

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


def _require_docker() -> None:
    """Skip unless the caller explicitly enabled disposable Docker tests."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)


@pytest.mark.parametrize("agent", ["claude-code", "hermes"])
def test_remaining_agent_adapters_launch_without_credentials(tmp_path: Path, agent: str) -> None:
    """Claude and Hermes start through their hardened profile-generated argv."""
    _require_docker()
    profile = Profile(name=f"integration-{agent}", agent=agent, egress={"hosts": ["127.0.0.1"]})
    profile_path = tmp_path / f"{agent}.toml"
    contexts = prepare_build_contexts(profile, tmp_path / "context", profile_path)
    image = f"agent-containers/integration-{agent}:runtime"
    try:
        subprocess.run(
            build_image_argv(profile, contexts, image=image, uid=os.getuid(), gid=1000),
            check=True,
            capture_output=True,
            text=True,
        )
        launch = list(build_run_argv(profile, tmp_path, profile_path, image=image, agent_args=["--version"]))
        launch.remove("-it")
        launch.insert(2, "--network=none")
        if agent == "claude-code":
            subprocess.run(launch, check=True, capture_output=True, text=True)
        else:
            # Hermes owns an s6 service tree and deliberately stays alive;
            # launch detached, then inspect the unprivileged service process.
            container = f"agent-containers-integration-{agent}"
            launch[launch.index("--rm")] = "--detach"
            image_index = launch.index(image)
            launch[image_index:image_index] = ["--name", container]
            try:
                subprocess.run(launch, check=True, capture_output=True, text=True)
                status = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", container],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                assert status == "running"
                identity = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "--user",
                        "10000:10000",
                        container,
                        "sh",
                        "-ceu",
                        'test "$(id -u)" = 10000; test "$(id -g)" = 10000',
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                assert identity.returncode == 0
            finally:
                subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)
