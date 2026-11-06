"""Editable shot direction shared by scripts, APIs, and video planning."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Intensity = Literal["low", "medium", "high"]
ContinuityAssetKind = Literal["prop", "wardrobe", "injury", "environment", "blocking", "other"]
ShotRole = Literal["establishing", "dialogue_reaction", "emotion_reaction", "action", "prop_interaction"]
EngineCapability = Literal[
    "identity_reference",
    "performance_control",
    "multi_character",
    "motion_control",
    "temporal_keyframes",
]


class ShotCharacterState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    character_name: str = Field(min_length=1, max_length=100)
    emotion: str = Field(default="", max_length=200)
    action: str = Field(default="", max_length=500)
    start_state: str = Field(default="", max_length=500)
    end_state: str = Field(default="", max_length=500)


class ShotContinuityAsset(BaseModel):
    """A named physical or spatial fact that may cross a shot boundary.

    Free-form continuity notes remain useful for creative direction. This model
    provides the small, deterministic subset that the planner can compare
    without pretending to understand arbitrary natural language.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    asset_id: str = Field(min_length=1, max_length=100)
    kind: ContinuityAssetKind = "other"
    start_state: dict[str, Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]] = Field(default_factory=dict, max_length=12)
    end_state: dict[str, Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]] = Field(default_factory=dict, max_length=12)
    inherits_previous: bool = True
    transition_note: str = Field(default="", max_length=500)


class ShotSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    purpose: str = Field(default="", max_length=500)
    emotion: str = Field(default="", max_length=200)
    shot_role: ShotRole | None = None
    required_engine_capabilities: list[EngineCapability] = Field(default_factory=list, max_length=5)
    duration_seconds: float | None = Field(default=None, gt=0, le=120, allow_inf_nan=False)
    camera_movement: str = Field(default="", max_length=500)
    camera_intensity: Intensity | None = None
    action_intensity: Intensity | None = None
    performance_intensity: int | None = Field(default=None, ge=1, le=5, strict=True)
    motion_reference_video: str = Field(default="", max_length=1000)
    performance_reference_audio: str = Field(default="", max_length=1000)
    continuity_constraints: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]] = Field(default_factory=list, max_length=30)
    character_states: list[ShotCharacterState] = Field(default_factory=list, max_length=10)
    continuity_assets: list[ShotContinuityAsset] = Field(default_factory=list, max_length=20)

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def validate_duration(cls, value):
        if isinstance(value, bool):
            raise ValueError("Shot duration cannot be a boolean")
        return value

    @field_validator("character_states")
    @classmethod
    def unique_characters(cls, states):
        names = [state.character_name for state in states]
        if len(set(names)) != len(names):
            raise ValueError("Shot character states must have unique names")
        return states

    @field_validator("continuity_assets")
    @classmethod
    def unique_continuity_assets(cls, assets):
        asset_ids = [asset.asset_id for asset in assets]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("Shot continuity assets must have unique asset IDs")
        return assets

    @field_validator("required_engine_capabilities")
    @classmethod
    def unique_engine_capabilities(cls, capabilities):
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("Required engine capabilities must be unique")
        return capabilities

    def direction_text(self) -> str:
        parts = []
        for label, value in (("Narrative purpose", self.purpose), ("Emotion", self.emotion)):
            if value:
                parts.append(f"{label}: {value}")
        if self.performance_intensity is not None:
            parts.append(f"Performance intensity: {self.performance_intensity}/5")
        if self.motion_reference_video:
            parts.append("Use the approved motion-driving video")
        if self.performance_reference_audio:
            parts.append("Use the approved performance-driving audio")
        for state in self.character_states:
            details = "; ".join(
                f"{label}: {value}" for label, value in (
                    ("emotion", state.emotion), ("action", state.action),
                    ("start state", state.start_state), ("end state", state.end_state),
                ) if value
            )
            parts.append(f"{state.character_name}: {details}")
        if self.continuity_constraints:
            parts.append("Locked continuity: " + "; ".join(self.continuity_constraints))
        for asset in self.continuity_assets:
            start = ", ".join(f"{key}={value}" for key, value in asset.start_state.items())
            end = ", ".join(f"{key}={value}" for key, value in asset.end_state.items())
            details = "; ".join(part for part in (start and f"start {start}", end and f"end {end}", asset.transition_note) if part)
            if details:
                parts.append(f"Continuity asset {asset.asset_id} ({asset.kind}): {details}")
        return ". ".join(parts)

    def keyframe_contract(self) -> dict:
        return {
            "phase": "opening_frame",
            "emotion": self.emotion,
            "character_states": [
                {"character_name": state.character_name, "emotion": state.emotion,
                 "state": state.start_state}
                for state in self.character_states if state.start_state or state.emotion
            ],
            "continuity_constraints": list(self.continuity_constraints),
            "continuity_assets": [
                {
                    "asset_id": asset.asset_id,
                    "kind": asset.kind,
                    "start_state": asset.start_state,
                    "inherits_previous": asset.inherits_previous,
                }
                for asset in self.continuity_assets
            ],
        }

    def temporal_state_directive(self, progress: float) -> str:
        """Compile approved state transitions for an internal temporal anchor."""
        progress = max(0.0, min(1.0, float(progress)))
        phase = "early development" if progress < 0.5 else "late development"
        parts = [f"Temporal state at {round(progress * 100)}% ({phase})"]
        for state in self.character_states:
            details = []
            if state.start_state and state.end_state:
                relation = "begins moving toward" if progress < 0.5 else "is close to"
                details.append(
                    f"starts from '{state.start_state}' and {relation} the approved end state "
                    f"'{state.end_state}' without introducing any unlisted state"
                )
            elif state.start_state:
                details.append(f"preserves '{state.start_state}'")
            elif state.end_state:
                details.append(f"moves toward the approved end state '{state.end_state}'")
            if state.emotion:
                details.append(f"emotion remains {state.emotion}")
            if state.action:
                details.append(f"action remains {state.action}")
            if details:
                parts.append(f"{state.character_name}: " + "; ".join(details))
        for asset in self.continuity_assets:
            start = ", ".join(f"{key}={value}" for key, value in asset.start_state.items())
            end = ", ".join(f"{key}={value}" for key, value in asset.end_state.items())
            if start and end and start != end:
                relation = "still closer to its start state" if progress < 0.5 else "now closer to its end state"
                details = f"transitions from ({start}) toward ({end}) and is {relation}"
            elif start or end:
                details = f"stays locked as ({start or end})"
            else:
                details = "keeps the same established ownership, orientation and appearance"
            if asset.transition_note:
                details += f"; transition rule: {asset.transition_note}"
            parts.append(f"Continuity asset {asset.asset_id}: {details}")
        if self.continuity_constraints:
            parts.append("Locked continuity: " + "; ".join(self.continuity_constraints))
        return ". ".join(parts) + "."
