"""Opt-in Docker integration coverage for the OpenCode provider adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_containers.build_context import prepare_build_contexts
from agent_containers.docker import build_image_argv, build_run_argv
from agent_containers.profile import Profile

pytestmark = pytest.mark.integration


def test_opencode_provider_config_is_ephemeral(tmp_path: Path) -> None:
    """The adapter starts OpenCode with a temporary config and no secret value."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    profile_path = tmp_path / "integration.toml"
    profile = Profile(
        name="integration-opencode",
        agent="opencode",
        provider={
            "kind": "custom",
            "endpoint": "https://model.example.test/v1",
            "model": "local-model",
            "api_key_env": "MODEL_API_KEY",
        },
    )
    contexts = prepare_build_contexts(profile, tmp_path / "context", profile_path)
    image = "agent-containers/integration-opencode:provider"
    launch = build_run_argv(profile, tmp_path, profile_path, image=image)
    config = next(item.split("=", 1)[1] for item in launch if item.startswith("AGENT_OPENCODE_CONFIG_JSON="))
    parsed = json.loads(config)
    assert parsed["model"] == "agent_containers/local-model"
    assert parsed["provider"]["agent_containers"]["options"]["apiKey"] == "{env:MODEL_API_KEY}"
    try:
        subprocess.run(
            [*build_image_argv(profile, contexts, image=image)],
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
                "/tmp:exec",
                "--tmpfs",
                "/run",
                "--tmpfs",
                "/home/opencode:uid=1000,gid=1000",
                "--cap-drop=ALL",
                "--cap-add=NET_ADMIN",
                "--cap-add=NET_RAW",
                "--cap-add=SETUID",
                "--cap-add=SETGID",
                "-e",
                "AGENT_ALLOWED_EGRESS=*",
                "-e",
                f"AGENT_OPENCODE_CONFIG_JSON={config}",
                image,
                "sh",
                "-ceu",
                "test -s /tmp/agent-containers-opencode.json && grep -F 'agent_containers/local-model' /tmp/agent-containers-opencode.json && opencode --version",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)
