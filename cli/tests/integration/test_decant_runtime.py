"""Opt-in runtime verification for direct named-volume Decant access."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_containers.docker import build_decant_run_argv, default_decant_image_tag
from agent_containers.profile import Profile

pytestmark = pytest.mark.integration


def _require_decant_image(profile: Profile) -> str:
    """Return an operator-built account-matched image or skip clearly."""
    if os.environ.get("AGENT_CONTAINERS_RUN_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_INTEGRATION=1 to run Docker integration tests")
    if os.environ.get("AGENT_CONTAINERS_RUN_DECANT_INTEGRATION") != "1":
        pytest.skip("set AGENT_CONTAINERS_RUN_DECANT_INTEGRATION=1 to run Decant integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    image = os.environ.get("AGENT_CONTAINERS_DECANT_IMAGE") or default_decant_image_tag(profile)
    if subprocess.run(["docker", "image", "inspect", image], check=False, capture_output=True).returncode != 0:
        pytest.skip(f"Decant image is unavailable: {image}; build/tag the account-matched image from the documentation")
    subprocess.run(["docker", "info"], check=True, capture_output=True)
    return image


def _wait_for_http(url: str) -> bytes:
    """Wait briefly for Decant's local web server and return its document."""
    last_error: Exception | None = None
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.read()
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(1)
    raise AssertionError(f"Decant did not serve {url}: {last_error}")


def test_decant_direct_mounts_start_account_matched_service(tmp_path: Path) -> None:
    """The generated direct mounts are readable and the Decant database is writable."""
    suffix = f"{os.getpid()}-{time.time_ns()}"
    claude_volume = f"agent-containers-decant-test-claude-{suffix}"
    codex_volume = f"agent-containers-decant-test-codex-{suffix}"
    data_volume = f"agent-containers-decant-test-data-{suffix}"
    container = f"agent-containers-decant-test-{suffix}"
    port = 18787
    image_override = os.environ.get("AGENT_CONTAINERS_DECANT_IMAGE")
    profile = Profile(
        name="integration-decant",
        agent="codex",
        decant={
            "enabled": True,
            "source_profiles": ["claude", "codex"],
            "image": image_override,
            "data_volume": data_volume,
            "bind_address": "127.0.0.1",
            "port": port,
        },
    )
    _require_decant_image(profile)
    for volume in (claude_volume, codex_volume, data_volume):
        subprocess.run(["docker", "volume", "create", volume], check=True, capture_output=True, text=True)
    host_uid = os.getuid()
    # macOS profile builds intentionally use image GID 1000; using the host's
    # conventional staff GID 20 would collide with Debian's dialout group in
    # the account-renumbering image.
    host_gid = 1000
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{claude_volume}:/mnt",
                "alpine",
                "sh",
                "-ceu",
                f"mkdir -p /mnt/.claude/projects; printf '{{}}\\n' > /mnt/.claude/projects/session.json; chown -R {host_uid}:{host_gid} /mnt/.claude",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{codex_volume}:/mnt",
                "alpine",
                "sh",
                "-ceu",
                f"mkdir -p /mnt/.codex/sessions; printf '{{}}\\n' > /mnt/.codex/sessions/session.json; chown -R {host_uid}:{host_gid} /mnt/.codex",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        launch = list(build_decant_run_argv(profile, claude_volume=claude_volume, codex_volume=codex_volume))
        launch.remove("-it")
        launch[launch.index("--rm")] = "--detach"
        launch[launch.index("--name") + 1] = container
        subprocess.run(launch, check=True, capture_output=True, text=True)
        page = _wait_for_http(f"http://127.0.0.1:{port}")
        assert b"Decant" in page
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
                container,
                "sh",
                "-ceu",
                f'test "$(stat -c %u /proc/1)" = "{host_uid}"',
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert identity.returncode == 0
        subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                f"{host_uid}:{host_gid}",
                container,
                "sh",
                "-ceu",
                "test -r /sources/claude/projects/session.json; test -r /sources/codex/sessions/session.json; touch /var/lib/decant/runtime-sentinel",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
        for volume in (claude_volume, codex_volume, data_volume):
            subprocess.run(["docker", "volume", "rm", "-f", volume], check=False, capture_output=True)
