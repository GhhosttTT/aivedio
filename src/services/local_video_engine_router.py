"""Select a local ComfyUI video workflow from explicit shot capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOCAL_VIDEO_ENGINE_CAPABILITIES = frozenset({
    "identity_reference",
    "performance_control",
    "multi_character",
    "motion_control",
    "temporal_keyframes",
})

LOCAL_VIDEO_PRECISIONS = frozenset({"bf16", "fp16", "fp8", "fp6", "fp4", "int8"})

# Keep runtime routing conservative even when an operator skips the production
# preflight command. A generic I2V profile cannot become a dialogue, multi-cast,
# or driven-motion engine merely by setting booleans in the registry.
LOCAL_VIDEO_MODEL_CAPABILITY_POLICY = {
    "svd_legacy": (),
    "wan_2_2_ti2v_5b": ("identity_reference",),
    "wan_2_2_i2v_14b": ("identity_reference",),
    "wan_2_2": (),
    "hunyuanvideo_i2v": ("identity_reference",),
    "hunyuanvideo_1_5_keyframes": (
        "identity_reference", "motion_control", "temporal_keyframes",
    ),
    "ltx_2_keyframes": (
        "identity_reference", "motion_control", "temporal_keyframes",
    ),
    "hunyuan_custom": (
        "identity_reference", "performance_control", "multi_character", "motion_control",
    ),
    "hunyuanvideo_avatar": (
        "identity_reference", "performance_control", "multi_character",
    ),
    "wan_2_2_animate": (
        "identity_reference", "performance_control", "motion_control",
    ),
}

LOCAL_VIDEO_SPECIALIST_ROLE_POLICY = {
    "hunyuanvideo_avatar": frozenset({
        "dialogue", "emotion", "dialogue_reaction", "emotion_reaction",
    }),
    "wan_2_2_animate": frozenset({
        "action", "prop_interaction", "dialogue", "emotion",
        "dialogue_reaction", "emotion_reaction",
    }),
}

SHORT_DRAMA_ENGINE_PROFILES = (
    {
        "profile": "single_character_performance",
        "capabilities": ("identity_reference", "performance_control"),
    },
    {
        "profile": "multi_character_dialogue",
        "capabilities": ("identity_reference", "performance_control", "multi_character"),
    },
    {
        "profile": "character_motion",
        "capabilities": ("identity_reference", "motion_control"),
    },
)


class LocalVideoEngineRoutingError(ValueError):
    """Raised when a configured engine registry cannot satisfy a shot."""


@dataclass(frozen=True)
class LocalVideoEngineRoute:
    engine_id: str
    model_profile: str
    workflow_path: str
    bindings_path: str | None
    capabilities: dict[str, bool]
    selection_reasons: tuple[str, ...]
    requested_capabilities: tuple[str, ...]
    unmet_preferences: tuple[str, ...]
    runtime: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "model_profile": self.model_profile,
            "workflow_path": self.workflow_path,
            "bindings_path": self.bindings_path,
            "capabilities": dict(self.capabilities),
            "selection_reasons": list(self.selection_reasons),
            "requested_capabilities": list(self.requested_capabilities),
            "unmet_preferences": list(self.unmet_preferences),
            "runtime": dict(self.runtime),
        }


def _resolved_file(raw_path: object, *, base_dir: Path, label: str) -> str:
    value = str(raw_path or "").strip()
    if not value:
        raise LocalVideoEngineRoutingError(f"Local video engine {label} is required")
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if not path.is_file():
        raise LocalVideoEngineRoutingError(f"Local video engine {label} does not exist: {path}")
    return str(path)


def load_local_video_engine_registry(path: str | Path) -> list[dict[str, Any]]:
    registry_path = Path(path)
    if not registry_path.is_absolute():
        registry_path = Path.cwd() / registry_path
    registry_path = registry_path.resolve()
    if not registry_path.is_file():
        raise LocalVideoEngineRoutingError(f"Local video engine registry does not exist: {registry_path}")
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalVideoEngineRoutingError(f"Invalid local video engine registry: {exc}") from exc
    engines = payload.get("engines") if isinstance(payload, dict) else None
    if not isinstance(engines, list) or not engines:
        raise LocalVideoEngineRoutingError("Local video engine registry must contain a non-empty engines list")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(engines, start=1):
        if not isinstance(item, dict):
            raise LocalVideoEngineRoutingError(f"Local video engine #{index} must be an object")
        engine_id = str(item.get("id") or "").strip()
        if not engine_id or engine_id in seen_ids:
            raise LocalVideoEngineRoutingError(f"Local video engine #{index} needs a unique non-empty id")
        seen_ids.add(engine_id)
        capabilities = item.get("capabilities") or {}
        if not isinstance(capabilities, dict):
            raise LocalVideoEngineRoutingError(f"Local video engine {engine_id} capabilities must be an object")
        unknown_capabilities = sorted(set(map(str, capabilities)) - LOCAL_VIDEO_ENGINE_CAPABILITIES)
        if unknown_capabilities:
            raise LocalVideoEngineRoutingError(
                f"Local video engine {engine_id} has unknown capabilities: "
                + ", ".join(unknown_capabilities)
            )
        invalid_capability_types = sorted(
            str(key) for key, value in capabilities.items() if not isinstance(value, bool)
        )
        if invalid_capability_types:
            raise LocalVideoEngineRoutingError(
                f"Local video engine {engine_id} capabilities must use JSON booleans: "
                + ", ".join(invalid_capability_types)
            )
        model_profile = str(item.get("model_profile") or "").strip().lower()
        if model_profile not in LOCAL_VIDEO_MODEL_CAPABILITY_POLICY:
            raise LocalVideoEngineRoutingError(
                f"Local video engine {engine_id} must use a supported explicit model_profile; "
                f"got {model_profile or '<empty>'}"
            )
        allowed_capabilities = set(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY[model_profile])
        unsupported_claims = sorted(
            str(key) for key, enabled in capabilities.items()
            if enabled and key not in allowed_capabilities
        )
        if unsupported_claims:
            raise LocalVideoEngineRoutingError(
                f"Local video engine {engine_id} profile {model_profile} cannot declare: "
                + ", ".join(unsupported_claims)
            )
        bindings_path = item.get("bindings_path")
        runtime = item.get("runtime") or {}
        if not isinstance(runtime, dict):
            raise LocalVideoEngineRoutingError(
                f"Local video engine {engine_id} runtime must be an object"
            )
        minimum_vram_gb = runtime.get("minimum_vram_gb")
        if minimum_vram_gb is not None:
            try:
                minimum_vram_gb = float(minimum_vram_gb)
            except (TypeError, ValueError) as exc:
                raise LocalVideoEngineRoutingError(
                    f"Local video engine {engine_id} runtime.minimum_vram_gb must be numeric"
                ) from exc
            if minimum_vram_gb <= 0:
                raise LocalVideoEngineRoutingError(
                    f"Local video engine {engine_id} runtime.minimum_vram_gb must be greater than zero"
                )
        precision = str(runtime.get("precision") or "").strip().lower()
        if precision and precision not in LOCAL_VIDEO_PRECISIONS:
            raise LocalVideoEngineRoutingError(
                f"Local video engine {engine_id} runtime.precision must be one of: "
                + ", ".join(sorted(LOCAL_VIDEO_PRECISIONS))
            )
        for field in ("cpu_offload", "sequential_only"):
            if field in runtime and not isinstance(runtime[field], bool):
                raise LocalVideoEngineRoutingError(
                    f"Local video engine {engine_id} runtime.{field} must be a JSON boolean"
                )
        normalized_runtime = {
            "minimum_vram_gb": minimum_vram_gb,
            "precision": precision or None,
            "cpu_offload": bool(runtime.get("cpu_offload", False)),
            "sequential_only": bool(runtime.get("sequential_only", False)),
        }
        normalized.append({
            "id": engine_id,
            "model_profile": model_profile,
            "workflow_path": _resolved_file(
                item.get("workflow_path"), base_dir=registry_path.parent, label=f"{engine_id} workflow_path",
            ),
            "bindings_path": (
                _resolved_file(bindings_path, base_dir=registry_path.parent, label=f"{engine_id} bindings_path")
                if str(bindings_path or "").strip() else None
            ),
            "capabilities": {str(key): value for key, value in capabilities.items()},
            "priority": int(item.get("priority") or 0),
            "runtime": normalized_runtime,
        })
    return normalized


def _shot_preferences(shot_plan: dict | None) -> tuple[str, ...]:
    plan = shot_plan if isinstance(shot_plan, dict) else {}
    role = str(plan.get("shot_role") or "").strip().lower()
    intensity = str(plan.get("action_intensity") or "").strip().lower()
    try:
        visible_count = max(0, int(plan.get("visible_character_count") or 0))
    except (TypeError, ValueError):
        visible_count = 0
    explicit = plan.get("required_engine_capabilities") or []
    if not isinstance(explicit, list):
        raise LocalVideoEngineRoutingError("Shot required_engine_capabilities must be a list")
    unknown = sorted(set(map(str, explicit)) - LOCAL_VIDEO_ENGINE_CAPABILITIES)
    if unknown:
        raise LocalVideoEngineRoutingError(
            "Shot has unknown required engine capabilities: " + ", ".join(unknown)
        )
    preferences = []
    for capability in explicit:
        name = str(capability)
        if name not in preferences:
            preferences.append(name)

    def require(capability: str) -> None:
        if capability not in preferences:
            preferences.append(capability)

    if visible_count > 0:
        require("identity_reference")
    if role in {"action", "prop_interaction"} or intensity == "high":
        require("motion_control")
    if role in {"dialogue", "emotion", "dialogue_reaction", "emotion_reaction"}:
        require("performance_control")
    if visible_count > 1:
        require("multi_character")
    return tuple(preferences)


def _engine_missing_conditioning_inputs(
    engine: dict[str, Any],
    required: list[str],
    shot_plan: dict | None,
) -> list[str]:
    """Return native conditioning inputs unavailable for this exact shot."""
    plan = shot_plan if isinstance(shot_plan, dict) else {}
    profile = str(engine.get("model_profile") or "").strip().lower()
    has_audio = bool(
        plan.get("has_performance_audio")
        or str(plan.get("performance_reference_audio") or "").strip()
    )
    has_driving_video = bool(
        plan.get("has_motion_reference_video")
        or str(plan.get("motion_reference_video") or "").strip()
    )
    missing = []
    if profile == "hunyuanvideo_avatar" and "performance_control" in required and not has_audio:
        missing.append("performance_audio")
    if (
        profile == "wan_2_2_animate"
        and ({"performance_control", "motion_control"} & set(required))
        and not has_driving_video
    ):
        missing.append("driving_video")
    if profile == "hunyuan_custom" and "visible_character_count" in plan:
        if "motion_control" in required and not has_driving_video:
            missing.append("driving_video")
        if "performance_control" in required and not (has_audio or has_driving_video):
            missing.append("performance_audio_or_driving_video")
    return missing


def _engine_role_mismatch(engine: dict[str, Any], shot_plan: dict | None) -> str | None:
    """Keep narrow specialist models away from unrelated cinematic shots."""
    plan = shot_plan if isinstance(shot_plan, dict) else {}
    role = str(plan.get("shot_role") or "").strip().lower()
    if not role:
        return None
    profile = str(engine.get("model_profile") or "").strip().lower()
    allowed_roles = LOCAL_VIDEO_SPECIALIST_ROLE_POLICY.get(profile)
    if allowed_roles is not None and role not in allowed_roles:
        return f"model profile {profile} does not support shot role {role}"
    if profile == "hunyuan_custom":
        try:
            visible_count = max(0, int(plan.get("visible_character_count") or 0))
        except (TypeError, ValueError):
            visible_count = 0
        if visible_count == 0:
            return "model profile hunyuan_custom requires a visible customized subject"
    return None


def evaluate_local_video_engine_fleet(
    engines: list[dict[str, Any]],
    *,
    temporal_keyframes_required: bool,
) -> dict[str, Any]:
    """Check that one engine can satisfy each core short-drama shot profile."""
    profiles = list(SHORT_DRAMA_ENGINE_PROFILES)
    if temporal_keyframes_required:
        profiles.append({
            "profile": "temporal_character_motion",
            "capabilities": ("identity_reference", "motion_control", "temporal_keyframes"),
        })
    results = []
    for profile in profiles:
        required = tuple(profile["capabilities"])
        matching = sorted(
            str(engine.get("id") or "")
            for engine in engines
            if all(bool((engine.get("capabilities") or {}).get(name)) for name in required)
        )
        results.append({
            "profile": profile["profile"],
            "required_capabilities": list(required),
            "matching_engines": matching,
            "passed": bool(matching),
        })
    missing = [item["profile"] for item in results if not item["passed"]]
    return {
        "profiles": results,
        "missing_profiles": missing,
        "passed": not missing,
    }


def select_local_video_engine(
    engines: list[dict[str, Any]],
    *,
    shot_plan: dict | None,
    has_temporal_keyframes: bool,
    available_vram_gb: float | None = None,
) -> LocalVideoEngineRoute:
    """Choose a workflow that can satisfy the complete shot contract.

    Short-drama identity, performance, motion, and multi-character controls are
    generation requirements. Falling back to an engine without one of them
    produces a valid file with a predictably invalid shot, so routing fails
    before GPU work starts instead of treating these controls as soft hints.
    """
    return rank_local_video_engine_routes(
        engines,
        shot_plan=shot_plan,
        has_temporal_keyframes=has_temporal_keyframes,
        available_vram_gb=available_vram_gb,
    )[0]


def rank_local_video_engine_routes(
    engines: list[dict[str, Any]],
    *,
    shot_plan: dict | None,
    has_temporal_keyframes: bool,
    available_vram_gb: float | None = None,
) -> tuple[LocalVideoEngineRoute, ...]:
    """Return every executable route in deterministic quality-search order."""
    if not engines:
        raise LocalVideoEngineRoutingError("No local video engines are available")
    required = list(_shot_preferences(shot_plan))
    if has_temporal_keyframes and "temporal_keyframes" not in required:
        required.insert(0, "temporal_keyframes")
    capability_eligible = [
        item for item in engines
        if all(bool((item.get("capabilities") or {}).get(name)) for name in required)
        and not _engine_missing_conditioning_inputs(item, required, shot_plan)
        and not _engine_role_mismatch(item, shot_plan)
    ]
    eligible = [
        item for item in capability_eligible
        if (
            available_vram_gb is None
            or not (item.get("runtime") or {}).get("minimum_vram_gb")
            or float((item.get("runtime") or {})["minimum_vram_gb"]) <= float(available_vram_gb)
        )
    ]
    if not eligible:
        coverage = []
        for item in engines:
            capabilities = item.get("capabilities") or {}
            missing = [name for name in required if not capabilities.get(name)]
            missing_inputs = _engine_missing_conditioning_inputs(item, required, shot_plan)
            role_mismatch = _engine_role_mismatch(item, shot_plan)
            details = []
            if missing:
                details.append("capabilities " + ", ".join(missing))
            if missing_inputs:
                details.append("inputs " + ", ".join(missing_inputs))
            if role_mismatch:
                details.append(role_mismatch)
            minimum_vram = (item.get("runtime") or {}).get("minimum_vram_gb")
            if (
                available_vram_gb is not None
                and minimum_vram
                and float(minimum_vram) > float(available_vram_gb)
            ):
                details.append(
                    f"VRAM {minimum_vram:g}GB required, {float(available_vram_gb):g}GB available"
                )
            coverage.append(f"{item.get('id')}: missing {'; '.join(details) if details else 'none'}")
        raise LocalVideoEngineRoutingError(
            "No local video engine satisfies this shot's required capabilities "
            f"({', '.join(required) if required else 'none'}). "
            + "; ".join(coverage)
        )

    reasons = [f"required:{name}" for name in required]
    if not reasons:
        reasons.append("fallback:priority")
    ranked = sorted(
        eligible,
        key=lambda item: (-int(item.get("priority") or 0), str(item.get("id") or "")),
    )
    return tuple(
        LocalVideoEngineRoute(
            engine_id=str(selected["id"]),
            model_profile=str(selected.get("model_profile") or "unknown"),
            workflow_path=str(selected["workflow_path"]),
            bindings_path=(str(selected["bindings_path"]) if selected.get("bindings_path") else None),
            capabilities=dict(selected.get("capabilities") or {}),
            selection_reasons=tuple(reasons),
            requested_capabilities=tuple(required),
            unmet_preferences=(),
            runtime=dict(selected.get("runtime") or {}),
        )
        for selected in ranked
    )


def resolve_local_video_engine_route(
    registry_path: str | Path | None,
    *,
    shot_plan: dict | None,
    has_temporal_keyframes: bool,
    available_vram_gb: float | None = None,
) -> LocalVideoEngineRoute | None:
    if not str(registry_path or "").strip():
        return None
    return select_local_video_engine(
        load_local_video_engine_registry(str(registry_path)),
        shot_plan=shot_plan,
        has_temporal_keyframes=has_temporal_keyframes,
        available_vram_gb=available_vram_gb,
    )


def resolve_local_video_engine_routes(
    registry_path: str | Path | None,
    *,
    shot_plan: dict | None,
    has_temporal_keyframes: bool,
    available_vram_gb: float | None = None,
) -> tuple[LocalVideoEngineRoute, ...]:
    if not str(registry_path or "").strip():
        return ()
    return rank_local_video_engine_routes(
        load_local_video_engine_registry(str(registry_path)),
        shot_plan=shot_plan,
        has_temporal_keyframes=has_temporal_keyframes,
        available_vram_gb=available_vram_gb,
    )
