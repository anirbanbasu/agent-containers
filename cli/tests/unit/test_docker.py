"""Tests for direct-Docker command construction without Docker."""

from pathlib import Path

import pytest

from agent_containers.docker import DockerCommandError, build_run_argv, shell_command
from agent_containers.profile import Profile


def make_profile(**overrides: object) -> Profile:
    """Create a minimal profile with selected field overrides."""
    payload: dict[str, object] = {"name": "work", "agent": "codex"}
    payload.update(overrides)
    return Profile.model_validate(payload)


def test_codex_command_contains_hardening_workspace_and_arguments(tmp_path: Path) -> None:
    """Codex commands preserve documented containment and argument ordering."""
    argv = build_run_argv(
        make_profile(egress={"hosts": ["api.openai.com"]}),
        tmp_path,
        tmp_path / "work.toml",
        agent_args=["--ask-for-approval", "never"],
    )
    assert argv[:4] == ("docker", "run", "-it", "--rm")
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--cap-add=NET_ADMIN" in argv
    assert "--tmpfs" in argv
    assert "AGENT_ALLOWED_EGRESS=api.openai.com" in argv
    assert argv[-3:] == ("codex", "--ask-for-approval", "never")
    assert f"{tmp_path.resolve()}:/workspace/{tmp_path.name}" in argv
    assert shell_command(argv).startswith("docker run -it")


@pytest.mark.parametrize(
    ("agent", "expected_home", "exec_tmpfs"),
    [
        ("claude-code", "/home/claude", False),
        ("opencode", "/home/opencode", True),
        ("hermes", "/opt/data", True),
    ],
)
def test_agent_specific_runtime_contracts(tmp_path: Path, agent: str, expected_home: str, exec_tmpfs: bool) -> None:
    """Each adapter uses its documented home, tmpfs and command contract."""
    argv = build_run_argv(make_profile(agent=agent), tmp_path, tmp_path / "work.toml")
    assert any(item.endswith(f":{expected_home}") for item in argv)
    assert ("/tmp:exec" in argv) is exec_tmpfs
    assert ("/run:exec" in argv) is exec_tmpfs
    if agent == "hermes":
        assert "--cap-add=CHOWN" in argv
        assert argv[-1] == "hermes:latest"
    elif agent == "claude-code":
        assert argv[-1] == "claude"
    else:
        assert argv[-1] == agent


def test_command_handles_proxy_ca_mount_and_custom_mount(tmp_path: Path) -> None:
    """Proxy and custom inputs are mounted read-only without changing contents."""
    ca = tmp_path / "corp-ca.pem"
    settings = tmp_path / "settings.json"
    ca.write_text("CA", encoding="utf-8")
    settings.write_text("{}", encoding="utf-8")
    profile_path = tmp_path / "work.toml"
    profile = make_profile(
        provider={"kind": "custom", "api_key_env": "CUSTOM_API_KEY"},
        proxy={
            "http": "http://proxy.example.test:8080",
            "https": "https://proxy.example.test:8443",
            "ca_file": "corp-ca.pem",
        },
        mounts=[{"source": "settings.json", "target": "/home/codex/settings.json"}],
    )
    argv = build_run_argv(profile, tmp_path, profile_path)
    assert "HTTP_PROXY=http://proxy.example.test:8080" in argv
    assert "HTTPS_PROXY=https://proxy.example.test:8443" in argv
    assert "CUSTOM_API_KEY" in argv
    assert any(str(ca) in item and item.endswith(":ro") for item in argv)
    assert any(str(settings) in item and item.endswith(":ro") for item in argv)


def test_command_handles_gateway_and_explicit_unrestricted_mode(tmp_path: Path) -> None:
    """Gateway variables are explicit and unrestricted mode requires consent."""
    gateway = make_profile(egress={"gateway_host": "gateway", "gateway_port": 2222})
    argv = build_run_argv(gateway, tmp_path, tmp_path / "work.toml")
    assert "AGENT_GATEWAY_HOST=gateway" in argv
    assert "AGENT_GATEWAY_PORT=2222" in argv
    with pytest.raises(DockerCommandError, match="explicit"):
        build_run_argv(make_profile(egress={"mode": "unrestricted"}), tmp_path, tmp_path / "work.toml")
    allowed = build_run_argv(
        make_profile(egress={"mode": "unrestricted"}),
        tmp_path,
        tmp_path / "work.toml",
        permit_unrestricted=True,
    )
    assert "docker" in allowed


def test_command_rejects_workspace_and_seed_conflicts(tmp_path: Path) -> None:
    """Run refuses missing workspaces and copy-once seeds."""
    missing = tmp_path / "missing"
    with pytest.raises(DockerCommandError, match="workspace"):
        build_run_argv(make_profile(), missing, tmp_path / "work.toml")
    with pytest.raises(DockerCommandError, match="seed"):
        build_run_argv(
            make_profile(mounts=[{"type": "seed", "source": "settings", "target": "/home/codex/settings"}]),
            tmp_path,
            tmp_path / "work.toml",
        )
    with pytest.raises(DockerCommandError, match="generated mount"):
        build_run_argv(
            make_profile(
                proxy={"ca_file": "corp-ca.pem"},
                mounts=[
                    {
                        "source": "settings",
                        "target": "/etc/ssl/certs/agent-containers-custom-ca.pem",
                    }
                ],
            ),
            tmp_path,
            tmp_path / "work.toml",
        )
