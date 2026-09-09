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


def test_opencode_provider_package_loads_without_registry_access(tmp_path: Path) -> None:
    """A configured OpenCode provider does not need npm access at first launch."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    profile_path = tmp_path / "integration-opencode-provider-load.toml"
    profile = Profile(
        name="integration-opencode-provider-load",
        agent="opencode",
        provider={
            "kind": "custom",
            "endpoint": "https://model.example.test/v1",
            "model": "local-model",
        },
    )
    contexts = prepare_build_contexts(profile, tmp_path / "context", profile_path)
    image = "agent-containers/integration-opencode-provider-load:provider"
    launch = list(build_run_argv(profile, tmp_path, profile_path, image=image))
    launch.remove("-it")
    launch.insert(2, "--network=none")
    image_index = launch.index(image)
    launch[image_index:] = [image, "opencode", "run", "--model", "agent_containers/local-model", "probe"]
    try:
        subprocess.run(
            ["docker", "build", "--build-context", f"shared={contexts.shared}", "--tag", image, str(contexts.image)],
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
                "--entrypoint",
                "/bin/sh",
                image,
                "-ceu",
                "find /opt/agent-tools/npm -path '*/@ai-sdk/openai-compatible' -type d -print -quit | grep -q .",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(launch, check=False, capture_output=True, text=True)
        assert result.returncode != 0
        stderr = result.stderr.lower()
        assert "cannot find package" not in stderr
        assert "module not found" not in stderr
        assert "npm install" not in stderr
        assert "registry.npmjs.org" not in stderr
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)


def test_opencode_langfuse_plugin_is_profile_opt_in(tmp_path: Path) -> None:
    """An opted-in Langfuse profile installs its plugin without credentials."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    subprocess.run(["docker", "info"], check=True, capture_output=True)

    profile_path = tmp_path / "integration-langfuse.toml"
    profile = Profile(
        name="integration-opencode-langfuse",
        agent="opencode",
        langfuse={"enabled": True, "base_url": "https://langfuse.example.test"},
        egress={"hosts": ["langfuse.example.test"]},
    )
    contexts = prepare_build_contexts(profile, tmp_path / "context", profile_path)
    image = "agent-containers/integration-opencode-langfuse:profile"
    launch = list(build_run_argv(profile, tmp_path, profile_path, image=image))
    assert "LANGFUSE_PUBLIC_KEY" in launch
    assert "LANGFUSE_SECRET_KEY" in launch
    image_index = launch.index(image)
    launch[image_index:] = [
        image,
        "sh",
        "-ceu",
        (
            "test -s /tmp/agent-containers-opencode.json\n"
            "find /opt/agent-tools/npm -path '*langfuse*' -print -quit | grep -q .\n"
            "grep -F '@langfuse/opencode-observability-plugin' /tmp/agent-containers-opencode.json\n"
            "opencode --version"
        ),
    ]
    launch.remove("-it")
    launch.insert(2, "--network=none")
    try:
        subprocess.run(
            ["docker", "build", "--build-context", f"shared={contexts.shared}", "--tag", image, str(contexts.image)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(launch, check=True, capture_output=True, text=True)
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], check=False, capture_output=True)
