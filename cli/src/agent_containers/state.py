"""Machine-managed deployment state stored separately from user TOML."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_containers.profile import Profile


class DeploymentRecord(BaseModel):
    """One retained image and managed launch configuration."""

    model_config = ConfigDict(extra="forbid")

    deployment_id: str = Field(min_length=1)
    image: str = Field(min_length=1)
    profile_digest: str = Field(min_length=64, max_length=64)
    profile_snapshot: dict[str, Any]
    launch_digest: str = Field(min_length=64, max_length=64)
    created_at: datetime
    selected: bool = False

    @field_validator("created_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        """Keep state timestamps unambiguous across hosts."""
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value


class DeploymentState(BaseModel):
    """Current and retained deployment records for one profile."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    profile_name: str = Field(min_length=1)
    deployments: list[DeploymentRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_at_most_one_selected(self) -> Self:
        """Prevent ambiguous active deployment selection."""
        if sum(record.selected for record in self.deployments) > 1:
            raise ValueError("deployment state may select at most one deployment")
        return self

    @property
    def selected_deployment(self) -> DeploymentRecord | None:
        """Return the active record, if one has been applied."""
        return next((record for record in self.deployments if record.selected), None)


def profile_snapshot(profile: Profile) -> dict[str, Any]:
    """Produce a JSON-compatible desired profile snapshot."""
    return profile.model_dump(mode="json")


def digest_snapshot(snapshot: dict[str, Any]) -> str:
    """Hash a canonical snapshot for change detection."""
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def profile_digest(profile: Profile, profile_path: Path | None = None) -> str:
    """Return the canonical digest, including deployment CA input contents."""
    snapshot = profile_snapshot(profile)
    if profile_path is not None and profile.proxy is not None:
        snapshot["_proxy_ca_digest"] = _proxy_ca_digest(profile, profile_path)
    return digest_snapshot(snapshot)


def load_state(path: Path) -> DeploymentState:
    """Load machine-managed deployment state from JSON."""
    with path.open(encoding="utf-8") as state_file:
        return DeploymentState.model_validate_json(state_file.read())


def default_state_path(profile: Profile) -> Path:
    """Return the XDG-style per-user state path for one named profile."""
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return (root / "agent-containers" / f"{profile.name}.json").resolve()


def save_state(path: Path, state: DeploymentState) -> None:
    """Atomically write formatted JSON, creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
            state_file.write(state.model_dump_json(indent=2) + "\n")
            state_file.flush()
            os.fsync(state_file.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def new_deployment_id(profile: Profile, profile_path: Path | None = None) -> str:
    """Create a timestamp-plus-digest identifier without using a secret."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{profile.name}-{timestamp}-{profile_digest(profile, profile_path)[:12]}"


def _proxy_ca_digest(profile: Profile, profile_path: Path) -> str:
    """Hash profile CA inputs so certificate rotation triggers an image update."""
    assert profile.proxy is not None
    hasher = hashlib.sha256()
    base = profile_path.expanduser().resolve().parent
    if profile.proxy.ca_file is not None:
        source = (base / profile.proxy.ca_file).resolve()
        if not source.is_file():
            raise ValueError(f"proxy CA file does not exist: {source}")
        hasher.update(source.name.encode())
        hasher.update(source.read_bytes())
    if profile.proxy.ca_dir is not None:
        source = (base / profile.proxy.ca_dir).resolve()
        if not source.is_dir():
            raise ValueError(f"proxy CA directory does not exist: {source}")
        files = sorted(item for item in source.iterdir() if item.is_file())
        if not files:
            raise ValueError(f"proxy CA directory is empty: {source}")
        for item in files:
            hasher.update(item.name.encode())
            hasher.update(item.read_bytes())
    return hasher.hexdigest()
