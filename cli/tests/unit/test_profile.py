"""Validation tests for the Docker-independent profile schema."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_containers.profile import Profile, load_profile, resolve_mount_source


def test_profile_accepts_complete_work_configuration(tmp_path: Path) -> None:
    """A comprehensive profile combines packages, integrations and mounts."""
    profile_path = tmp_path / "work.toml"
    profile_path.write_text(
        """
schema_version = 1
name = "work"
agent = "claude-code"

[packages]
apt = ["ffmpeg"]
npm = ["typescript"]
uv_tools = ["ruff"]
uv_libraries = ["httpx"]

[provider]
kind = "anthropic"
endpoint = "https://api.anthropic.com"
model = "claude-sonnet"
api_key_env = "ANTHROPIC_API_KEY"

[proxy]
https = "https://proxy.example.test:8443"
no_proxy = ["localhost", " 127.0.0.1 "]
ca_file = "./corp-ca.pem"

[egress]
mode = "allowlist"
hosts = ["api.anthropic.com", "registry.npmjs.org"]
gateway_host = "gateway.example.test"
gateway_port = 22
gateway_user = "tunnel"
gateway_access_hostname = "gateway-access.example.test"
gateway_bootstrap_allow = ["192.0.2.10"]
gateway_key_file = "./gateway-key"
gateway_known_hosts_file = "./gateway-known-hosts"

[decant]
enabled = true
source_profiles = ["claude", "codex"]
port = 8787

[[mounts]]
type = "bind"
source = "./claude-settings.json"
target = "/home/claude/.claude/settings.json"
read_only = true
""",
        encoding="utf-8",
    )
    profile = load_profile(profile_path)
    assert profile.agent.value == "claude-code"
    assert profile.packages.uv_tools == ["ruff"]
    assert profile.proxy is not None
    assert profile.proxy.no_proxy == ["localhost", "127.0.0.1"]
    assert resolve_mount_source(profile, profile.mounts[0], profile_path) == tmp_path / "claude-settings.json"


def test_unknown_profile_fields_are_rejected() -> None:
    """Typos in a profile fail instead of silently changing behavior."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Profile.model_validate({"name": "work", "agent": "codex", "unknown": True})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": "Work", "agent": "codex"}, "name"),
        ({"name": "work", "agent": "codex", "home_volume": "../shared"}, "home_volume"),
        ({"name": "work", "agent": "codex", "home_volume": "  "}, "home_volume"),
        ({"name": "work", "agent": "codex", "schema_version": 2}, "unsupported"),
        ({"name": "work", "agent": "codex", "packages": {"apt": ["  "]}}, "package names"),
        ({"name": "work", "agent": "codex", "packages": {"npm": ["one\ntwo"]}}, "single-line"),
        ({"name": "work", "agent": "codex", "egress": {"mode": "open"}}, "network mode"),
        ({"name": "work", "agent": "codex", "egress": {"hosts": ["  "]}}, "egress hosts"),
        ({"name": "work", "agent": "codex", "decant": {"source_profiles": ["  "]}}, "Decant"),
        ({"name": "work", "agent": "codex", "mounts": [{"source": "  ", "target": "/x"}]}, "mount paths"),
        ({"name": "work", "agent": "codex", "mounts": [{"source": "x", "target": "settings.json"}]}, "absolute"),
        (
            {
                "name": "work",
                "agent": "codex",
                "mounts": [
                    {"source": "a", "target": "/home/codex"},
                    {"source": "b", "target": "/home/codex/settings.json"},
                ],
            },
            "overlap",
        ),
        ({"name": "work", "agent": "codex", "egress": {"gateway_host": "gateway"}}, "together"),
        ({"name": "work", "agent": "codex", "provider": {"api_key_env": "secret-value"}}, "uppercase"),
        ({"name": "work", "agent": "codex", "proxy": {"no_proxy": ["localhost", "  "]}}, "no_proxy entries"),
        (
            {"name": "work", "agent": "codex", "proxy": {"ca_file": "ca.pem", "ca_dir": "certs"}},
            "ca_file and ca_dir",
        ),
        ({"name": "work", "agent": "codex", "egress": {"gateway_user": "tunnel"}}, "gateway options"),
        (
            {
                "name": "work",
                "agent": "codex",
                "egress": {"gateway_host": "gateway", "gateway_port": 2222, "gateway_key_file": "key"},
            },
            "gateway_key_file and gateway_known_hosts_file",
        ),
        (
            {
                "name": "work",
                "agent": "codex",
                "egress": {"gateway_host": "gateway", "gateway_bootstrap_allow": ["  "]},
            },
            "gateway bootstrap entries",
        ),
        (
            {"name": "work", "agent": "codex", "egress": {"gateway_bootstrap_allow": ["gateway.example.test"]}},
            "IP addresses or CIDRs",
        ),
        ({"name": "work", "agent": "hermes", "decant": {"enabled": True}}, "Decant support"),
        (
            {"name": "work", "agent": "hermes", "langfuse": {"enabled": True, "base_url": "https://lf.example"}},
            "Langfuse support",
        ),
        ({"name": "work", "agent": "codex", "langfuse": {"enabled": True}}, "base_url is required"),
        (
            {
                "name": "work",
                "agent": "codex",
                "langfuse": {"enabled": True, "base_url": "https://lf.example", "public_key_env": "secret"},
            },
            "uppercase environment variable names",
        ),
        (
            {
                "name": "work",
                "agent": "codex",
                "langfuse": {
                    "enabled": True,
                    "base_url": "https://lf.example",
                    "public_key_env": "SAME",
                    "secret_key_env": "SAME",
                },
            },
            "must differ",
        ),
    ],
)
def test_profile_rejects_unsafe_values(payload: dict[str, object], message: str) -> None:
    """Invalid names, paths, overlaps and secret literals produce clear errors."""
    with pytest.raises(ValidationError, match=message):
        Profile.model_validate(payload)


def test_seed_mount_is_explicitly_distinct() -> None:
    """Copy-once seeds remain distinguishable from bind mounts."""
    profile = Profile.model_validate(
        {
            "name": "local",
            "agent": "hermes",
            "mounts": [{"type": "seed", "source": "settings", "target": "/opt/data/config"}],
        }
    )
    assert profile.mounts[0].type.value == "seed"
