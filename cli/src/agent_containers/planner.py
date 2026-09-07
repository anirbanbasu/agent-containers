"""Offline change planning for desired profiles and recorded deployments."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_containers.profile import Profile
from agent_containers.state import DeploymentState, profile_digest, profile_snapshot


class PlanAction(StrEnum):
    """Changes the apply operation may need to perform."""

    CREATE_IMAGE = "create-image"
    UPDATE_IMAGE = "update-image"
    UPDATE_LAUNCH = "update-launch"
    NOOP = "no-op"


class Plan(BaseModel):
    """A deterministic, explicitly offline description of desired changes."""

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    profile_digest: str = Field(min_length=64, max_length=64)
    actions: list[PlanAction]
    changed_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    live_state_checked: bool = False

    @property
    def is_noop(self) -> bool:
        """Whether the recorded deployment already matches the profile."""
        return self.actions == [PlanAction.NOOP]

    def summary_lines(self) -> list[str]:
        """Render stable, human-readable plan output."""
        lines = [
            f"Profile: {self.profile_name}",
            f"Live Docker state checked: {'yes' if self.live_state_checked else 'no'}",
        ]
        if self.actions:
            lines.append("Actions:")
            lines.extend(f"- {action.value}" for action in self.actions)
        if self.changed_sections:
            lines.append("Changed sections:")
            lines.extend(f"- {section}" for section in self.changed_sections)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        return lines


def build_plan(profile: Profile, state: DeploymentState | None = None, profile_path: Path | None = None) -> Plan:
    """Compare a profile with recorded state without contacting Docker."""
    snapshot = profile_snapshot(profile)
    digest = profile_digest(profile, profile_path)
    warnings = ["Live Docker state was not inspected."]
    if state is None or state.selected_deployment is None:
        return Plan(
            profile_name=profile.name,
            profile_digest=digest,
            actions=[PlanAction.CREATE_IMAGE],
            changed_sections=["initial deployment"],
            warnings=warnings + ["No selected deployment is recorded."],
        )

    selected = state.selected_deployment
    previous = selected.profile_snapshot
    image_sections = ["agent", "packages"]
    launch_sections = ["home_volume", "provider", "proxy", "egress", "decant", "configuration_mounts", "mounts"]
    changed_image = [section for section in image_sections if snapshot.get(section) != previous.get(section)]
    changed_launch = [section for section in launch_sections if snapshot.get(section) != previous.get(section)]
    langfuse_changed = snapshot.get("langfuse") != previous.get("langfuse")
    if langfuse_changed:
        changed_image.append("langfuse")
    changed = changed_image + changed_launch
    if digest != selected.profile_digest and not changed:
        if profile.proxy is not None and (profile.proxy.ca_file is not None or profile.proxy.ca_dir is not None):
            changed_image.append("proxy CA contents")
            changed.append("proxy CA contents")
        elif profile.configuration_import is not None:
            changed_launch.append("configuration import contents")
            changed.append("configuration import contents")
    if not changed:
        actions = [PlanAction.NOOP]
    else:
        actions = []
        if changed_image:
            actions.append(PlanAction.UPDATE_IMAGE)
        if changed_launch or langfuse_changed:
            actions.append(PlanAction.UPDATE_LAUNCH)
    return Plan(
        profile_name=profile.name,
        profile_digest=digest,
        actions=actions,
        changed_sections=changed,
        warnings=warnings,
    )
