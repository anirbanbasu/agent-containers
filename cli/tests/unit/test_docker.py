"""Tests for direct-Docker command construction without Docker."""

from pathlib import Path

import pytest

from agent_containers.build_context import BuildContexts
from agent_containers.docker import (
    DockerCommandError,
    build_image_argv,
    build_run_argv,
    build_seed_argv,
    default_image_tag,
    shell_command,
)
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
            "no_proxy": ["localhost", "127.0.0.1"],
            "ca_file": "corp-ca.pem",
        },
        mounts=[{"source": "settings.json", "target": "/home/codex/settings.json"}],
    )
    argv = build_run_argv(profile, tmp_path, profile_path)
    assert "HTTP_PROXY=http://proxy.example.test:8080" in argv
    assert "http_proxy=http://proxy.example.test:8080" in argv
    assert "HTTPS_PROXY=https://proxy.example.test:8443" in argv
    assert "https_proxy=https://proxy.example.test:8443" in argv
    assert "NO_PROXY=localhost,127.0.0.1" in argv
    assert "no_proxy=localhost,127.0.0.1" in argv
    assert "NODE_USE_ENV_PROXY=1" in argv
    assert "SSL_CERT_FILE=/etc/ssl/certs/agent-containers-custom-ca.pem" in argv
    assert "REQUESTS_CA_BUNDLE=/etc/ssl/certs/agent-containers-custom-ca.pem" in argv
    assert "NODE_EXTRA_CA_CERTS=/etc/ssl/certs/agent-containers-custom-ca.pem" in argv
    assert "CUSTOM_API_KEY" in argv
    assert any(str(ca) in item and item.endswith(":ro") for item in argv)
    assert any(str(settings) in item and item.endswith(":ro") for item in argv)


def test_provider_overrides_use_agent_surfaces(tmp_path: Path) -> None:
    """Claude receives env settings while Codex receives one-run config overrides."""
    claude = build_run_argv(
        make_profile(
            agent="claude-code",
            provider={"kind": "anthropic", "endpoint": "https://proxy.example.test/v1", "model": "sonnet"},
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert "ANTHROPIC_BASE_URL=https://proxy.example.test/v1" in claude
    assert "ANTHROPIC_MODEL=sonnet" in claude
    codex = build_run_argv(
        make_profile(provider={"kind": "local", "endpoint": "http://model.example.test/v1", "model": "local-model"}),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert codex[-10:] == (
        "--model",
        "local-model",
        "--config",
        'model_provider="agent_containers"',
        "--config",
        'model_providers.agent_containers.name="local"',
        "--config",
        'model_providers.agent_containers.base_url="http://model.example.test/v1"',
        "--config",
        'model_providers.agent_containers.wire_api="responses"',
    )


def test_provider_endpoint_mapping_rejects_unimplemented_agents(tmp_path: Path) -> None:
    """A provider field never disappears silently for OpenCode."""
    with pytest.raises(DockerCommandError, match="not implemented"):
        build_run_argv(
            make_profile(agent="opencode", provider={"kind": "custom", "endpoint": "https://model.example.test"}),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_hermes_provider_uses_per_run_flags_and_endpoint_environment(tmp_path: Path) -> None:
    """Hermes provider selection does not rewrite its persistent config file."""
    argv = build_run_argv(
        make_profile(
            agent="hermes",
            provider={"kind": "custom", "endpoint": "http://model.example.test/v1", "model": "local-model"},
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert "OPENAI_BASE_URL=http://model.example.test/v1" in argv
    assert argv[-4:] == ("--provider", "custom", "--model", "local-model")


def test_hermes_rejects_unknown_endpoint_provider_mapping(tmp_path: Path) -> None:
    """Unknown Hermes endpoint conventions fail rather than route incorrectly."""
    with pytest.raises(DockerCommandError, match="Hermes provider"):
        build_run_argv(
            make_profile(agent="hermes", provider={"kind": "openrouter", "endpoint": "https://router.example.test/v1"}),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_codex_builtin_provider_and_empty_unsupported_provider(tmp_path: Path) -> None:
    """Built-in OpenAI routing uses its dedicated key and empty metadata is a no-op."""
    builtin = build_run_argv(
        make_profile(provider={"kind": "openai", "endpoint": "https://api.openai.com/v1"}),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert 'openai_base_url="https://api.openai.com/v1"' in builtin
    empty = build_run_argv(
        make_profile(agent="opencode", provider={"kind": "custom"}), tmp_path, tmp_path / "work.toml"
    )
    assert empty[-1] == "opencode"


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
    (tmp_path / "corp-ca.pem").write_text("CA", encoding="utf-8")
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


def test_command_rejects_missing_proxy_ca(tmp_path: Path) -> None:
    """A generated launch cannot reference a missing CA input."""
    with pytest.raises(DockerCommandError, match="CA file does not exist"):
        build_run_argv(
            make_profile(proxy={"ca_file": "missing-ca.pem"}),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_build_command_uses_profile_tag_contexts_and_first_party_ids(tmp_path: Path) -> None:
    """Build commands connect the generated shared context and host IDs safely."""
    contexts = BuildContexts(image=tmp_path / "image", shared=tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    profile = make_profile(packages={"npm": ["typescript"]})
    argv = build_image_argv(profile, contexts, uid=501, gid=20)
    assert argv[:3] == ("docker", "build", "--build-context")
    assert f"shared={contexts.shared}" in argv
    assert default_image_tag(profile) in argv
    assert "UID=501" in argv
    assert "GID=20" in argv
    assert argv[-1] == str(contexts.image)


def test_build_command_omits_uid_arguments_for_hermes_and_rejects_bad_inputs(tmp_path: Path) -> None:
    """Hermes retains its upstream fixed identity and contexts must be complete."""
    contexts = BuildContexts(image=tmp_path / "image", shared=tmp_path / "shared")
    contexts.image.mkdir()
    contexts.shared.mkdir()
    assert "UID=501" not in build_image_argv(make_profile(agent="hermes"), contexts, uid=501, gid=20)
    with pytest.raises(DockerCommandError, match="together"):
        build_image_argv(make_profile(), contexts, uid=501)
    with pytest.raises(DockerCommandError, match="positive"):
        build_image_argv(make_profile(), contexts, uid=0, gid=20)
    with pytest.raises(DockerCommandError, match="directories"):
        build_image_argv(make_profile(), BuildContexts(tmp_path / "missing", contexts.shared))


def test_seed_command_is_networkless_create_only_and_home_scoped(tmp_path: Path) -> None:
    """Seed helpers cannot overwrite arbitrary container locations or use egress."""
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    profile = make_profile(
        mounts=[{"type": "seed", "source": "settings.json", "target": "/home/codex/.codex/settings.json"}]
    )
    argv = build_seed_argv(profile, "/home/codex/.codex/settings.json", tmp_path / "work.toml", image="image")
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-add=CHOWN" in argv
    assert "SEED_TARGET=/home/codex/.codex/settings.json" in argv
    assert "test ! -e" in argv[-1]
    with pytest.raises(DockerCommandError, match="not configured"):
        build_seed_argv(profile, "/home/codex/.codex/other.json", tmp_path / "work.toml", image="image")
    with pytest.raises(DockerCommandError, match="persistent home"):
        build_seed_argv(
            make_profile(mounts=[{"type": "seed", "source": "settings.json", "target": "/etc/settings.json"}]),
            "/etc/settings.json",
            tmp_path / "work.toml",
            image="image",
        )
    with pytest.raises(DockerCommandError, match="does not exist"):
        build_seed_argv(
            make_profile(mounts=[{"type": "seed", "source": "missing", "target": "/home/codex/.codex/settings.json"}]),
            "/home/codex/.codex/settings.json",
            tmp_path / "work.toml",
            image="image",
        )
