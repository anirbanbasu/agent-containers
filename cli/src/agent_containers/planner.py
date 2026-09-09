"""Offline change planning for desired profiles and recorded deployments."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_containers.profile import Profile
from agent_containers.state import DeploymentState, profile_content_digests, profile_digest, profile_snapshot


class PlanAction(StrEnum):
    """Changes the apply operation may need to perform."""

    CREATE_IMAGE = "create-image"
    UPDATE_IMAGE = "update-image"
    UPDATE_LAUNCH = "update-launch"
    NOOP = "no-op"


class PlanWarning(BaseModel):
    """Stable machine-readable warning with human-facing text."""

    code: str
    message: str


class Plan(BaseModel):
    """A deterministic, explicitly offline description of desired changes."""

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    profile_digest: str = Field(min_length=64, max_length=64)
    actions: list[PlanAction]
    changed_sections: list[str] = Field(default_factory=list)
    changed_image: list[str] = Field(default_factory=list)
    changed_launch: list[str] = Field(default_factory=list)
    warnings: list[PlanWarning] = Field(default_factory=list)
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
            lines.extend(f"- {warning.message}" for warning in self.warnings)
        return lines

    def json_payload(self) -> dict[str, object]:
        """Return the versioned machine-readable plan interface."""
        return {
            "schema_version": 1,
            "profile_name": self.profile_name,
            "actions": [
                {"kind": action.value, "reason": reason}
                for action, reason in _action_reasons(self.actions, self.changed_image, self.changed_launch)
            ],
            "warnings": [warning.model_dump() for warning in self.warnings],
        }


def _action_reasons(
    actions: list[PlanAction], changed_image: list[str], changed_launch: list[str]
) -> list[tuple[PlanAction, str]]:
    """Associate each existing plan action with a stable reason string."""
    if actions == [PlanAction.NOOP]:
        return [(PlanAction.NOOP, "profile matches selected deployment")]
    reasons: list[tuple[PlanAction, str]] = []
    for action in actions:
        if action == PlanAction.CREATE_IMAGE:
            reason = "initial deployment"
        elif action == PlanAction.UPDATE_IMAGE:
            reason = ", ".join(changed_image) or "profile image changed"
        elif action == PlanAction.UPDATE_LAUNCH:
            reason = ", ".join(changed_launch) or "profile launch changed"
        else:
            reason = "profile changed"
        reasons.append((action, reason))
    return reasons


def build_plan(profile: Profile, state: DeploymentState | None = None, profile_path: Path | None = None) -> Plan:
    """Compare a profile with recorded state without contacting Docker."""
    snapshot = profile_snapshot(profile)
    digest = profile_digest(profile, profile_path)
    warnings = [PlanWarning(code="live_state_unchecked", message="Live Docker state was not inspected.")]
    if profile.egress.mode == "unrestricted":
        warnings.append(PlanWarning(code="unrestricted_egress", message="Unrestricted egress is enabled."))
    if profile.decant.enabled and not profile.decant.bind_address_is_loopback:
        warnings.append(
            PlanWarning(code="decant_non_loopback_bind", message="Decant is bound to a non-loopback address.")
        )
    if state is None or state.selected_deployment is None:
        return Plan(
            profile_name=profile.name,
            profile_digest=digest,
            actions=[PlanAction.CREATE_IMAGE],
            changed_sections=["initial deployment"],
            warnings=warnings
            + [PlanWarning(code="no_selected_deployment", message="No selected deployment is recorded.")],
        )

    selected = state.selected_deployment
    previous = selected.profile_snapshot
    image_sections = ["agent", "packages"]
    launch_sections = [
        "home_volume",
        "provider",
        "proxy",
        "egress",
        "decant",
        "configuration_import",
        "configuration_mounts",
        "mounts",
    ]
    changed_image = [section for section in image_sections if snapshot.get(section) != previous.get(section)]
    changed_launch = [section for section in launch_sections if snapshot.get(section) != previous.get(section)]
    langfuse_changed = snapshot.get("langfuse") != previous.get("langfuse")
    if langfuse_changed:
        changed_image.append("langfuse")
    changed = changed_image + changed_launch
    if digest != selected.profile_digest and not changed:
        current_content = profile_content_digests(profile, profile_path) if profile_path is not None else {}
        previous_proxy_ca = previous.get("_proxy_ca_digest")
        if (
            "_proxy_ca_digest" in current_content
            and previous_proxy_ca is not None
            and current_content["_proxy_ca_digest"] != previous_proxy_ca
        ):
            changed_image.append("proxy CA contents")
            changed.append("proxy CA contents")
        previous_import = previous.get("_configuration_import_digest")
        if (
            "_configuration_import_digest" in current_content
            and previous_import is not None
            and current_content["_configuration_import_digest"] != previous_import
        ):
            changed_launch.append("configuration import contents")
            changed.append("configuration import contents")
        if "_proxy_ca_digest" in current_content and previous_proxy_ca is None and profile.configuration_import is None:
            changed_image.append("proxy CA contents")
            changed.append("proxy CA contents")
        if "_configuration_import_digest" in current_content and previous_import is None and profile.proxy is None:
            changed_launch.append("configuration import contents")
            changed.append("configuration import contents")
        if not changed:
            changed_image.append("profile inputs changed")
            changed_launch.append("profile inputs changed")
            changed.append("profile inputs changed")
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
        changed_image=changed_image,
        changed_launch=changed_launch,
        warnings=warnings,
    )
