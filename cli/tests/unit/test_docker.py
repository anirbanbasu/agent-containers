"""Tests for direct-Docker command construction without Docker."""

import json
from pathlib import Path

import pytest

from agent_containers.build_context import BuildContexts
from agent_containers.docker import (
    DockerCommandError,
    build_decant_run_argv,
    build_image_argv,
    build_run_argv,
    build_seed_argv,
    default_decant_container_name,
    default_decant_data_volume,
    default_decant_image_tag,
    default_home_volume,
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


def test_resources_are_user_scoped_and_home_volume_can_be_selected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same-named profiles from different users use isolated defaults or an explicit volume."""
    monkeypatch.setattr("agent_containers.docker.getpass.getuser", lambda: "Alice Smith")
    monkeypatch.setattr("agent_containers.docker.os.getuid", lambda: 501)
    profile = make_profile()
    assert default_image_tag(profile).startswith("agent-containers/codex:alice-smith-501-work-")
    assert default_home_volume(profile) == "codex-home-alice-smith-501-work"
    default = build_run_argv(profile, tmp_path, tmp_path / "work.toml")
    assert "codex-home-alice-smith-501-work:/home/codex" in default
    selected = build_run_argv(make_profile(home_volume="existing-codex-home"), tmp_path, tmp_path / "work.toml")
    assert "existing-codex-home:/home/codex" in selected


def test_decant_direct_mount_command_is_user_scoped_and_subpath_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decant mounts only the agent collections directly, never a volume bridge."""
    monkeypatch.setattr("agent_containers.docker.getpass.getuser", lambda: "Alice Smith")
    monkeypatch.setattr("agent_containers.docker.os.getuid", lambda: 501)
    profile = make_profile(
        decant={
            "enabled": True,
            "source_profiles": ["claude", "codex"],
            "data_volume": "existing-decant-data",
            "bind_address": "127.0.0.1",
            "port": 9090,
        }
    )
    argv = build_decant_run_argv(profile, claude_volume="claude-home", codex_volume="codex-home")
    assert argv[:4] == ("docker", "run", "--rm", "-it")
    assert "type=volume,source=existing-decant-data,target=/var/lib/decant" in argv
    assert "--name" in argv
    assert "agent-containers-decant-alice-smith-501-work" in argv
    assert "type=volume,source=claude-home,target=/sources/claude,readonly,volume-subpath=.claude" in argv
    assert "type=volume,source=codex-home,target=/sources/codex,readonly,volume-subpath=.codex" in argv
    assert "volume-bridge" not in " ".join(argv)
    assert argv[-9:] == (
        "agent-containers/decant:alice-smith-501-work",
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "3000",
        "--no-fs-watch",
        "--interval-ms",
        "45000",
    )
    assert default_decant_data_volume(profile) == "decant-data-alice-smith-501-work"
    assert default_decant_image_tag(profile) == "agent-containers/decant:alice-smith-501-work"
    assert default_decant_container_name(profile) == "agent-containers-decant-alice-smith-501-work"


def test_decant_direct_mount_command_rejects_disabled_or_empty_sources() -> None:
    """The experimental launch refuses implicit or bridge-based source selection."""
    with pytest.raises(DockerCommandError, match="not enabled"):
        build_decant_run_argv(make_profile())
    profile = make_profile(decant={"enabled": True, "source_profiles": ["codex"]})
    with pytest.raises(DockerCommandError, match="at least one"):
        build_decant_run_argv(profile)


def test_decant_allows_explicit_prebuilt_image_override() -> None:
    """An operator may point an opted-in profile at a separately built image."""
    profile = make_profile(
        decant={"enabled": True, "source_profiles": ["codex"], "image": "registry.example.test/decant:matched"}
    )
    argv = build_decant_run_argv(profile, codex_volume="codex-home")
    assert "registry.example.test/decant:matched" in argv


def test_resource_names_fall_back_when_host_username_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resource isolation still has a safe namespace when user lookup fails."""

    def unavailable_username() -> str:
        raise KeyError

    monkeypatch.setattr("agent_containers.docker.getpass.getuser", unavailable_username)
    monkeypatch.setattr("agent_containers.docker.os.getuid", lambda: 501)
    profile = make_profile()
    assert default_home_volume(profile) == "codex-home-user-501-work"


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


def test_command_handles_proxy_ca_and_custom_mount(tmp_path: Path) -> None:
    """Proxy trust pointers and custom inputs are rendered safely."""
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
        configuration_mounts=[{"source": "settings.json", "target": "/home/codex/settings.json"}],
    )
    argv = build_run_argv(profile, tmp_path, profile_path)
    assert "HTTP_PROXY=http://proxy.example.test:8080" in argv
    assert "http_proxy=http://proxy.example.test:8080" in argv
    assert "HTTPS_PROXY=https://proxy.example.test:8443" in argv
    assert "https_proxy=https://proxy.example.test:8443" in argv
    assert "NO_PROXY=localhost,127.0.0.1" in argv
    assert "no_proxy=localhost,127.0.0.1" in argv
    assert "NODE_USE_ENV_PROXY=1" in argv
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in argv
    assert "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" in argv
    assert "NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt" in argv
    assert "CUSTOM_API_KEY" in argv
    assert any(str(settings) in item and item.endswith(":ro") for item in argv)


def test_command_handles_proxy_ca_directory(tmp_path: Path) -> None:
    """A certificate directory is validated as a build-time trust input."""
    ca_dir = tmp_path / "certs"
    ca_dir.mkdir()
    (ca_dir / "org.crt").write_text("CERT", encoding="utf-8")
    argv = build_run_argv(
        make_profile(proxy={"ca_dir": "certs"}),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in argv
    with pytest.raises(DockerCommandError, match="proxy CA directory does not exist"):
        build_run_argv(
            make_profile(proxy={"ca_dir": "missing-certs"}),
            tmp_path,
            tmp_path / "work.toml",
        )


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


def test_opencode_provider_uses_secret_free_per_run_config(tmp_path: Path) -> None:
    """OpenCode receives an ephemeral config without embedding credential values."""
    argv = build_run_argv(
        make_profile(
            agent="opencode",
            provider={
                "kind": "custom",
                "endpoint": "https://model.example.test/v1",
                "model": "local-model",
                "api_key_env": "MODEL_API_KEY",
            },
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    config = json.loads(
        next(
            item.removeprefix("AGENT_OPENCODE_CONFIG_JSON=")
            for item in argv
            if item.startswith("AGENT_OPENCODE_CONFIG_JSON=")
        )
    )
    assert config["model"] == "agent_containers/local-model"
    assert config["provider"]["agent_containers"]["options"] == {
        "baseURL": "https://model.example.test/v1",
        "apiKey": "{env:MODEL_API_KEY}",
    }
    assert "MODEL_API_KEY" in argv


def test_langfuse_runtime_exports_secret_references_and_requires_egress(tmp_path: Path) -> None:
    """Enabled Langfuse routing forwards only env names and requires its host allowlist entry."""
    profile = make_profile(
        agent="claude-code",
        langfuse={
            "enabled": True,
            "base_url": "https://self-hosted.langfuse.example.test",
            "environment": "development",
            "user_id": "alice",
        },
        egress={"hosts": ["self-hosted.langfuse.example.test"]},
    )
    argv = build_run_argv(profile, tmp_path, tmp_path / "work.toml")
    assert "TRACE_TO_LANGFUSE=true" in argv
    assert "LANGFUSE_PUBLIC_KEY" in argv
    assert "LANGFUSE_SECRET_KEY" in argv
    assert "AGENT_LANGFUSE_PUBLIC_KEY_ENV=LANGFUSE_PUBLIC_KEY" in argv
    assert "AGENT_LANGFUSE_SECRET_KEY_ENV=LANGFUSE_SECRET_KEY" in argv
    assert "LANGFUSE_BASE_URL=https://self-hosted.langfuse.example.test" in argv
    assert "LANGFUSE_TRACING_ENVIRONMENT=development" in argv
    assert "LANGFUSE_USER_ID=alice" in argv
    wildcard_argv = build_run_argv(
        make_profile(
            agent="claude-code",
            langfuse={"enabled": True, "base_url": "https://self-hosted.langfuse.example.test"},
            egress={"hosts": ["*", "other.example.test"]},
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert "AGENT_ALLOWED_EGRESS=*,other.example.test" in wildcard_argv
    with pytest.raises(DockerCommandError, match="allowlist entry or gateway"):
        build_run_argv(
            make_profile(
                agent="claude-code",
                langfuse={"enabled": True, "base_url": "https://self-hosted.langfuse.example.test"},
                egress={"mode": "deny"},
            ),
            tmp_path,
            tmp_path / "work.toml",
        )
    with pytest.raises(DockerCommandError, match="Langfuse host"):
        build_run_argv(
            make_profile(
                agent="claude-code",
                langfuse={
                    "enabled": True,
                    "base_url": "https://self-hosted.langfuse.example.test",
                    "environment": "development",
                    "user_id": "alice",
                },
                egress={"hosts": ["api.example.test"]},
            ),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_opencode_langfuse_config_does_not_require_provider(tmp_path: Path) -> None:
    """OpenCode-only observability still emits its per-run telemetry config."""
    argv = build_run_argv(
        make_profile(
            agent="opencode",
            langfuse={"enabled": True, "base_url": "https://langfuse.example.test"},
            egress={"hosts": ["langfuse.example.test"]},
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    config = json.loads(next(item.split("=", 1)[1] for item in argv if item.startswith("AGENT_OPENCODE_CONFIG_JSON=")))
    assert config["experimental"] == {"openTelemetry": True}
    assert config["plugin"] == ["@langfuse/opencode-observability-plugin@latest"]
    assert "LANGFUSE_BASEURL=https://langfuse.example.test" in argv


def test_codex_langfuse_enables_plugin_hooks_per_run(tmp_path: Path) -> None:
    """Codex receives the current hook and plugin settings without secrets."""
    argv = build_run_argv(
        make_profile(
            langfuse={"enabled": True, "base_url": "https://langfuse.example.test"},
            egress={"hosts": ["langfuse.example.test"]},
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert "features.hooks=true" in argv
    assert 'plugins."tracing@codex-observability-plugin".enabled=true' in argv


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
    (tmp_path / "gateway-key").write_text("private key", encoding="utf-8")
    (tmp_path / "gateway-known-hosts").write_text("gateway ssh key", encoding="utf-8")
    gateway = make_profile(
        egress={
            "gateway_host": "gateway",
            "gateway_port": 2222,
            "gateway_user": "tunnel",
            "gateway_access_hostname": "gateway.example.test",
            "gateway_bootstrap_allow": ["192.0.2.10"],
            "gateway_key_file": "gateway-key",
            "gateway_known_hosts_file": "gateway-known-hosts",
        }
    )
    argv = build_run_argv(gateway, tmp_path, tmp_path / "work.toml")
    assert "AGENT_GATEWAY_HOST=gateway" in argv
    assert "AGENT_GATEWAY_PORT=2222" in argv
    assert "AGENT_GATEWAY_USER=tunnel" in argv
    assert "AGENT_GATEWAY_ACCESS_HOSTNAME=gateway.example.test" in argv
    assert "AGENT_GATEWAY_BOOTSTRAP_ALLOW=192.0.2.10" in argv
    assert any("gateway-key:/etc/agent/gateway-key:ro" in item for item in argv)
    assert any("gateway-known-hosts:/etc/agent/gateway-known-hosts:ro" in item for item in argv)
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


def test_command_rejects_missing_proxy_ca(tmp_path: Path) -> None:
    """A generated launch cannot reference a missing CA input."""
    with pytest.raises(DockerCommandError, match="proxy CA does not exist"):
        build_run_argv(
            make_profile(proxy={"ca_file": "missing-ca.pem"}),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_command_rejects_proxy_mount_target_conflict(tmp_path: Path) -> None:
    """A custom mount cannot shadow the generated merged CA bundle path."""
    (tmp_path / "corp-ca.pem").write_text("CA", encoding="utf-8")
    with pytest.raises(DockerCommandError, match="generated mount"):
        build_run_argv(
            make_profile(
                proxy={"ca_file": "corp-ca.pem"},
                mounts=[{"source": "corp-ca.pem", "target": "/etc/ssl/certs/ca-certificates.crt"}],
            ),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_command_rejects_missing_gateway_inputs(tmp_path: Path) -> None:
    """Gateway launches reject missing SSH inputs before Docker can create directories."""
    with pytest.raises(DockerCommandError, match="gateway key does not exist"):
        build_run_argv(
            make_profile(
                egress={
                    "gateway_host": "gateway",
                    "gateway_port": 2222,
                    "gateway_key_file": "key",
                    "gateway_known_hosts_file": "hosts",
                }
            ),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_command_rejects_unconfigured_gateway_contract(tmp_path: Path) -> None:
    """Gateway mode cannot start without either dedicated or explicit key mounts."""
    with pytest.raises(DockerCommandError, match="gateway key input is required"):
        build_run_argv(
            make_profile(egress={"gateway_host": "gateway", "gateway_port": 2222}),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_command_rejects_gateway_without_known_hosts_input(tmp_path: Path) -> None:
    """A manually mounted key still requires a pinned gateway host key."""
    with pytest.raises(DockerCommandError, match="gateway known-hosts input is required"):
        build_run_argv(
            make_profile(
                egress={"gateway_host": "gateway", "gateway_port": 2222},
                mounts=[{"source": "key", "target": "/etc/agent/gateway-key"}],
            ),
            tmp_path,
            tmp_path / "work.toml",
        )


def test_command_accepts_explicit_readonly_gateway_mounts(tmp_path: Path) -> None:
    """Gateway trust inputs may be supplied as ordinary read-only mounts."""
    (tmp_path / "key").write_text("private key", encoding="utf-8")
    (tmp_path / "hosts").write_text("gateway ssh key", encoding="utf-8")
    argv = build_run_argv(
        make_profile(
            egress={"gateway_host": "gateway", "gateway_port": 2222},
            mounts=[
                {"source": "key", "target": "/etc/agent/gateway-key"},
                {"source": "hosts", "target": "/etc/agent/gateway-known-hosts"},
            ],
        ),
        tmp_path,
        tmp_path / "work.toml",
    )
    assert any("key:/etc/agent/gateway-key:ro" in item for item in argv)
    assert any("hosts:/etc/agent/gateway-known-hosts:ro" in item for item in argv)


def test_command_rejects_unsafe_gateway_mounts(tmp_path: Path) -> None:
    """Gateway key material cannot be writable or silently created as a directory."""
    with pytest.raises(DockerCommandError, match="must be read-only"):
        build_run_argv(
            make_profile(
                egress={"gateway_host": "gateway", "gateway_port": 2222},
                mounts=[
                    {"source": "key", "target": "/etc/agent/gateway-key", "read_only": False},
                    {"source": "hosts", "target": "/etc/agent/gateway-known-hosts"},
                ],
            ),
            tmp_path,
            tmp_path / "work.toml",
        )
    (tmp_path / "key").write_text("private key", encoding="utf-8")
    with pytest.raises(DockerCommandError, match="gateway known-hosts does not exist"):
        build_run_argv(
            make_profile(
                egress={"gateway_host": "gateway", "gateway_port": 2222},
                mounts=[
                    {"source": "key", "target": "/etc/agent/gateway-key"},
                    {"source": "hosts", "target": "/etc/agent/gateway-known-hosts"},
                ],
            ),
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
    assert "--cap-add=DAC_OVERRIDE" in argv
    assert "SEED_TARGET=/home/codex/.codex/settings.json" in argv
    assert "test ! -e" in argv[-1]
    assert "--no-preserve=mode,ownership,timestamps" in argv[-1]
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
