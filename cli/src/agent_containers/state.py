"""Machine-managed deployment state stored separately from user TOML."""

from __future__ import annotations

import hashlib
import json
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


def profile_digest(profile: Profile) -> str:
    """Return the canonical digest of a desired profile."""
    return digest_snapshot(profile_snapshot(profile))


def load_state(path: Path) -> DeploymentState:
    """Load machine-managed deployment state from JSON."""
    with path.open(encoding="utf-8") as state_file:
        return DeploymentState.model_validate_json(state_file.read())


def save_state(path: Path, state: DeploymentState) -> None:
    """Write state as formatted JSON, creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        state.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def new_deployment_id(profile: Profile) -> str:
    """Create a timestamp-plus-digest identifier without using a secret."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{profile.name}-{timestamp}-{profile_digest(profile)[:12]}"
