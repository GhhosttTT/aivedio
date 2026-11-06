"""Preflight checks for production-grade short-drama video generation."""

from __future__ import annotations

import json
import math
import ipaddress
import os
import shutil
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from src.config import settings
from src.services.comfyui_service import ComfyUIService
from src.services.local_video_engine_router import (
    evaluate_local_video_engine_fleet,
    LocalVideoEngineRoutingError,
    LOCAL_VIDEO_MODEL_CAPABILITY_POLICY,
    load_local_video_engine_registry,
)
from src.services.motion_reference_library import (
    load_motion_reference_library,
    MotionReferenceLibraryError,
)
from src.services.video_workflow_binding import (
    VideoWorkflowBindingError,
    apply_video_workflow_bindings,
    binding_has_control,
    load_video_workflow_bindings,
    validate_video_workflow_bindings,
)
from src.services.generation_provider import (
    _seedance_model,
    _seedance_model_is_10,
    _seedance_model_is_25,
    _seedance_model_supports_first_last_frame,
    _seedance_model_supports_multimodal_references,
    _seedance_model_supports_reference_audio,
    _seedance_duration_bounds,
    _seedance_supported_resolutions,
)


VIDEO_WORKFLOW_PLACEHOLDERS = {
    "prompt", "positive_prompt", "negative_prompt", "reference_image", "image",
    "start_image", "first_frame", "end_image", "last_frame",
    "width", "height", "duration_seconds", "fps", "seed", "output_prefix",
    "num_frames", "video_frames", "frame_count",
    "motion_bucket_id", "noise_aug_strength",
    "quality_mode", "quality_profile", "repair_action", "quality_pipeline",
    "quality_pipeline_json", "quality_pipeline_stages", "quality_pipeline_prompt",
    "quality_pipeline_negative",
    "shot_plan_json", "spatial_plan_json", "spatial_control_references_json",
    "spatial_asset_pack_json", "spatial_scene_contract_hash",
    "continuity_reference_image", "continuity_image", "previous_last_frame",
    "continuity_reference_fallback",
    "reference_images_json", "reference_image_count",
    "reference_videos_json", "reference_audios_json",
    "driving_video", "performance_audio",
    "reference_video_count", "reference_audio_count",
    "keyframe_images", "keyframe_indices", "keyframe_strengths", "keyframe_roles",
    "keyframe_images_json", "keyframe_count",
}

# Keep the selectable catalog next to the provider contract so the UI and
# preflight cannot silently drift apart when a model variant is added.
SEEDANCE_MODEL_CATALOG = [
    {"id": "doubao-seedance-2-5-260628", "label": "Seedance 2.5"},
    {"id": "doubao-seedance-2-0-260128", "label": "Seedance 2.0"},
    {"id": "doubao-seedance-2-0-fast-260128", "label": "Seedance 2.0 Fast"},
    {"id": "doubao-seedance-2-0-mini-260128", "label": "Seedance 2.0 Mini"},
    {"id": "doubao-seedance-1-0-pro-250528", "label": "Seedance 1.0 Pro"},
    {"id": "doubao-seedance-1-0-pro-fast-251015", "label": "Seedance 1.0 Pro Fast"},
]


LOCAL_VIDEO_MODEL_PROFILES = {
    "svd_legacy": {
        "label": "Stable Video Diffusion",
        "production_ready": False,
        "minimum_model_fps": 0,
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["svd_legacy"]),
        "reason": "SVD is retained for draft motion checks only; it is not approved for final short-drama video.",
    },
    "wan_2_2_ti2v_5b": {
        "label": "Wan 2.2 TI2V-5B",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": 24,
        "quality_tier": "local_candidate",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["wan_2_2_ti2v_5b"]),
        "reason": "Official 720P/24fps local candidate; 12GB quantized/offload deployments require measured sample validation.",
    },
    "wan_2_2_i2v_14b": {
        "label": "Wan 2.2 I2V-A14B",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": 80,
        "quality_tier": "high_quality_candidate",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["wan_2_2_i2v_14b"]),
        "reason": "Higher-capacity I2V candidate; official full-precision single-GPU inference uses an 80GB-class GPU.",
    },
    "wan_2_2": {
        "label": "Wan 2.2 (variant unknown)",
        "production_ready": False,
        "minimum_model_fps": 24,
        "official_min_vram_gb": None,
        "quality_tier": "unknown",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["wan_2_2"]),
        "reason": "The workflow mentions Wan 2.2 but does not identify a 5B or 14B I2V model variant.",
    },
    "hunyuanvideo_i2v": {
        "label": "HunyuanVideo I2V",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": None,
        "quality_tier": "local_candidate",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["hunyuanvideo_i2v"]),
        "reason": "Use atomic 3-6 second shots and retain character, continuity, and lip-sync quality gates.",
    },
    "hunyuanvideo_1_5_keyframes": {
        "label": "HunyuanVideo 1.5 Keyframes",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": None,
        "quality_tier": "high_quality_candidate",
        "supports_temporal_keyframes": True,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["hunyuanvideo_1_5_keyframes"]),
        "reason": "Keyframe-aware HunyuanVideo 1.5 candidate; the workflow must expose real frame-indexed conditioning.",
    },
    "ltx_2_keyframes": {
        "label": "LTX-2 Keyframes",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": None,
        "quality_tier": "high_quality_candidate",
        "supports_temporal_keyframes": True,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["ltx_2_keyframes"]),
        "reason": "Native multi-keyframe candidate; validate identity, motion and final-resolution samples on the target GPU.",
    },
    "hunyuan_custom": {
        "label": "HunyuanCustom",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": None,
        "quality_tier": "specialized_candidate",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["hunyuan_custom"]),
        "reason": "Subject-consistent image/audio/video-conditioned candidate; multi-subject release support must be proven separately.",
    },
    "hunyuanvideo_avatar": {
        "label": "HunyuanVideo-Avatar",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": 24,
        "quality_tier": "specialized_candidate",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["hunyuanvideo_avatar"]),
        "reason": "Audio-driven emotional and multi-character dialogue candidate; target-GPU speed and dialogue samples remain mandatory.",
    },
    "wan_2_2_animate": {
        "label": "Wan 2.2 Animate",
        "production_ready": True,
        "minimum_model_fps": 24,
        "official_min_vram_gb": None,
        "quality_tier": "specialized_candidate",
        "supports_temporal_keyframes": False,
        "native_capabilities": list(LOCAL_VIDEO_MODEL_CAPABILITY_POLICY["wan_2_2_animate"]),
        "reason": "Reference-character plus driving-video candidate for controlled body motion and expression transfer.",
    },
    "unknown": {
        "label": "Unknown local video model",
        "production_ready": False,
        "minimum_model_fps": 0,
        "official_min_vram_gb": None,
        "quality_tier": "draft_only",
        "supports_temporal_keyframes": False,
        "native_capabilities": [],
        "reason": "The workflow does not expose a verified production video model family.",
    },
}


def inspect_local_video_model(
    workflow_path: str | None = None,
    configured_profile_override: str | None = None,
) -> dict:
    """Classify the model referenced by a local ComfyUI video workflow."""
    configured_profile = str(
        configured_profile_override
        if configured_profile_override is not None
        else getattr(settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto") or "auto"
    ).strip().lower()
    path_value = workflow_path or settings.COMFYUI_VIDEO_WORKFLOW_PATH
    path = Path(path_value) if path_value else None
    if path and not path.is_absolute():
        path = Path.cwd() / path
    report = {
        "status": "blocked",
        "profile": "unknown",
        "configured_profile": configured_profile,
        "workflow_path": str(path) if path else "",
        "evidence": [],
        "action_items": [],
    }
    if not path or not path.is_file():
        report["action_items"].append("Configure a local ComfyUI video workflow before selecting a production model profile.")
        return report
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report["action_items"].append(f"Read the local video workflow failed: {exc}")
        return report

    raw = json.dumps(workflow, ensure_ascii=False).lower()
    detected = "unknown"
    wan_marker = "wan2.2" in raw or "wan_2_2" in raw or "wan2_2" in raw
    if any(marker in raw for marker in ("wan2.2-animate", "wan2_2_animate", "wan_2_2_animate", "wan-animate", "wan_animate", "wananimate")):
        detected = "wan_2_2_animate"
    elif any(marker in raw for marker in ("hunyuanvideo-avatar", "hunyuanvideo_avatar", "hunyuanvideoavatar")):
        detected = "hunyuanvideo_avatar"
    elif any(marker in raw for marker in ("hunyuan-custom", "hunyuan_custom", "hunyuancustom")):
        detected = "hunyuan_custom"
    elif any(marker in raw for marker in ("ltx-2", "ltx_2", "ltx2", "ltxvideo2")):
        detected = "ltx_2_keyframes"
    elif (
        any(marker in raw for marker in ("hunyuanvideo-1.5", "hunyuanvideo_1_5", "hunyuanvideo1.5"))
        and any(marker in raw for marker in ("keyframe", "key_frame", "conditioning_indices"))
    ):
        detected = "hunyuanvideo_1_5_keyframes"
    elif wan_marker and ("ti2v" in raw and "5b" in raw):
        detected = "wan_2_2_ti2v_5b"
    elif wan_marker and ("i2v" in raw and "14b" in raw):
        detected = "wan_2_2_i2v_14b"
    elif wan_marker:
        detected = "wan_2_2"
    elif "hunyuanvideo" in raw or "hunyuan_video" in raw:
        detected = "hunyuanvideo_i2v"
    elif "stable-video-diffusion" in raw or "stable_video_diffusion" in raw or "svd_" in raw or "svd" in raw:
        detected = "svd_legacy"

    requested = configured_profile if configured_profile != "auto" else detected
    aliases = {
        "wan2.2": "wan_2_2",
        "wan2_2": "wan_2_2",
        "wan_2_2_ti2v_5b": "wan_2_2_ti2v_5b",
        "wan2.2-ti2v-5b": "wan_2_2_ti2v_5b",
        "wan2.2-i2v-14b": "wan_2_2_i2v_14b",
        "hunyuanvideo": "hunyuanvideo_i2v",
        "hunyuanvideo-i2v": "hunyuanvideo_i2v",
        "hunyuanvideo-1.5-keyframes": "hunyuanvideo_1_5_keyframes",
        "hunyuanvideo_1_5_keyframes": "hunyuanvideo_1_5_keyframes",
        "ltx-2": "ltx_2_keyframes",
        "ltx2": "ltx_2_keyframes",
        "ltx_2_keyframes": "ltx_2_keyframes",
        "hunyuan-custom": "hunyuan_custom",
        "hunyuancustom": "hunyuan_custom",
        "hunyuanvideo-avatar": "hunyuanvideo_avatar",
        "hunyuanvideo_avatar": "hunyuanvideo_avatar",
        "wan2.2-animate": "wan_2_2_animate",
        "wan-animate": "wan_2_2_animate",
        "svd": "svd_legacy",
    }
    requested = aliases.get(requested, requested)
    if requested not in LOCAL_VIDEO_MODEL_PROFILES:
        requested = "unknown"
    profile = LOCAL_VIDEO_MODEL_PROFILES[requested]
    report.update({
        "profile": requested,
        "detected_profile": detected,
        "label": profile["label"],
        "production_ready": profile["production_ready"],
        "reason": profile["reason"],
        "model_fps": int(getattr(settings, "GENERATION_VIDEO_MODEL_FPS", 0) or 0),
        "minimum_model_fps": profile["minimum_model_fps"],
        "official_min_vram_gb": profile.get("official_min_vram_gb"),
        "quality_tier": profile.get("quality_tier", "unknown"),
        "supports_temporal_keyframes": bool(profile.get("supports_temporal_keyframes")),
        "native_capabilities": list(profile.get("native_capabilities") or []),
        "target_duration_seconds": float(getattr(settings, "GENERATION_VIDEO_TARGET_SECONDS", 0) or 0),
        "max_frames": int(getattr(settings, "GENERATION_VIDEO_MAX_FRAMES", 0) or 0),
        "evidence": [f"workflow_detection={detected}", f"configured_profile={configured_profile}"],
    })
    if configured_profile != "auto" and detected != "unknown" and requested != detected:
        report["action_items"].append(
            f"LOCAL_VIDEO_MODEL_PROFILE={requested} conflicts with workflow detection={detected}; align the setting and graph."
        )
        return report
    if not profile["production_ready"]:
        report["action_items"].append(profile["reason"])
        report["action_items"].append(
            "Use a verified Wan 2.2 or HunyuanVideo-I2V workflow for single-frame conditioning, or an "
            "LTX-2/HunyuanVideo 1.5 keyframe workflow when temporal anchors are enabled; then run real-GPU samples."
        )
        return report
    if (
        settings.GENERATION_VIDEO_MID_KEYFRAME_ENABLED
        and not report["supports_temporal_keyframes"]
    ):
        report["action_items"].append(
            f"{profile['label']} does not natively support the frame-indexed temporal keyframes required by "
            "GENERATION_VIDEO_MID_KEYFRAME_ENABLED. Use LTX-2 Keyframes or a verified HunyuanVideo 1.5 "
            "keyframe workflow, or disable temporal anchors."
        )
        return report
    if report["model_fps"] < report["minimum_model_fps"]:
        report["action_items"].append(
            f"GENERATION_VIDEO_MODEL_FPS={report['model_fps']} is below the {report['minimum_model_fps']} fps "
            f"required for {profile['label']} production sampling; output interpolation does not replace model motion samples."
        )
        return report
    required_frames = math.ceil(report["target_duration_seconds"] * report["model_fps"])
    report["required_target_frames"] = required_frames
    if report["max_frames"] < required_frames:
        report["action_items"].append(
            f"GENERATION_VIDEO_MAX_FRAMES={report['max_frames']} cannot hold the configured "
            f"{report['target_duration_seconds']:.2f}s target at {report['model_fps']} fps "
            f"({required_frames} frames required). Increase the workflow frame capacity before production."
        )
        return report
    report["status"] = "ready"
    return report


def local_video_model_fingerprint(workflow_path: str | None = None) -> dict:
    """Return the reproducible local-video configuration validated by a sample run.

    A validation score only applies to the graph and native sampling settings
    that produced it. Keep the fingerprint intentionally independent from the
    graph's absolute location so GPU machines can share an acceptance package.
    """
    inspection = inspect_local_video_model(workflow_path)
    path_value = inspection.get("workflow_path")
    path = Path(path_value) if path_value else None
    workflow_sha256 = ""
    if path and path.is_file():
        workflow_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    binding_sha256 = ""
    if path and path.is_file():
        try:
            binding_sha256 = load_video_workflow_bindings(
                path,
                getattr(settings, "COMFYUI_VIDEO_BINDINGS_PATH", ""),
            ).get("sha256", "")
        except VideoWorkflowBindingError:
            binding_sha256 = "invalid"
    identity = {
        "profile": inspection.get("profile", "unknown"),
        "detected_profile": inspection.get("detected_profile", "unknown"),
        "workflow_sha256": workflow_sha256,
        "binding_sha256": binding_sha256,
        "model_fps": inspection.get("model_fps", 0),
        "max_frames": inspection.get("max_frames", 0),
        "target_duration_seconds": inspection.get("target_duration_seconds", 0),
        "required_target_frames": inspection.get("required_target_frames", 0),
        "mid_keyframe_enabled": bool(settings.GENERATION_VIDEO_MID_KEYFRAME_ENABLED),
        "mid_keyframe_position": settings.GENERATION_VIDEO_MID_KEYFRAME_POSITION,
        "mid_keyframe_min_seconds": settings.GENERATION_VIDEO_MID_KEYFRAME_MIN_SECONDS,
        "max_mid_keyframes": settings.GENERATION_VIDEO_MAX_MID_KEYFRAMES,
        "keyframe_reference_min_score": settings.GENERATION_VIDEO_KEYFRAME_REFERENCE_MIN_SCORE,
        "supports_temporal_keyframes": inspection.get("supports_temporal_keyframes", False),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return {
        **identity,
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "model_status": inspection.get("status", "blocked"),
    }


def local_video_engine_registry_fingerprint(registry_path: str | None = None) -> dict:
    """Bind sample evidence to every workflow that the local router may select."""
    configured_path = str(
        registry_path
        if registry_path is not None
        else getattr(settings, "COMFYUI_VIDEO_ENGINE_REGISTRY_PATH", "") or ""
    ).strip()
    try:
        engines = load_local_video_engine_registry(configured_path)
    except LocalVideoEngineRoutingError as exc:
        return {
            "profile": "engine_registry",
            "fingerprint": "",
            "model_status": "blocked",
            "error": str(exc),
            "engines": [],
        }
    engine_identities = []
    statuses = []
    for engine in engines:
        workflow = Path(str(engine["workflow_path"]))
        bindings = Path(str(engine["bindings_path"])) if engine.get("bindings_path") else None
        inspection = inspect_local_video_model(
            str(workflow),
            configured_profile_override=str(engine.get("model_profile") or "auto"),
        )
        statuses.append(inspection.get("status"))
        engine_identities.append({
            "engine_id": engine["id"],
            "model_profile": engine.get("model_profile"),
            "detected_profile": inspection.get("detected_profile", "unknown"),
            "workflow_sha256": hashlib.sha256(workflow.read_bytes()).hexdigest(),
            "binding_sha256": (
                hashlib.sha256(bindings.read_bytes()).hexdigest()
                if bindings and bindings.is_file() else ""
            ),
            "capabilities": dict(engine.get("capabilities") or {}),
            "priority": int(engine.get("priority") or 0),
        })
    identity = {
        "profile": "engine_registry",
        "engines": engine_identities,
        "model_fps": int(settings.GENERATION_VIDEO_MODEL_FPS),
        "max_frames": int(settings.GENERATION_VIDEO_MAX_FRAMES),
        "target_duration_seconds": float(settings.GENERATION_VIDEO_TARGET_SECONDS),
        "mid_keyframe_enabled": bool(settings.GENERATION_VIDEO_MID_KEYFRAME_ENABLED),
        "max_mid_keyframes": int(settings.GENERATION_VIDEO_MAX_MID_KEYFRAMES),
        "keyframe_reference_min_score": float(settings.GENERATION_VIDEO_KEYFRAME_REFERENCE_MIN_SCORE),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **identity,
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "model_status": "ready" if statuses and all(status == "ready" for status in statuses) else "blocked",
    }


def local_video_configuration_fingerprint(workflow_path: str | None = None) -> dict:
    """Return the active single-workflow or routed-workflow evidence identity."""
    if workflow_path is None and str(
        getattr(settings, "COMFYUI_VIDEO_ENGINE_REGISTRY_PATH", "") or ""
    ).strip():
        return local_video_engine_registry_fingerprint()
    return local_video_model_fingerprint(workflow_path)


def scan_placeholders(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(scan_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            found.update(scan_placeholders(item))
    elif isinstance(value, str):
        for name in VIDEO_WORKFLOW_PLACEHOLDERS:
            if "{" + name + "}" in value:
                found.add(name)
    return found


def likely_video_outputs(workflow: dict) -> list[dict]:
    output_keywords = ("vhs", "webm", "gif", "animated")
    output_markers = ("save", "combine", "output", "export", "preview")
    matches = []
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", ""))
        lower_class = class_type.lower()
        if any(keyword in lower_class for keyword in output_keywords) or (
            "video" in lower_class and any(marker in lower_class for marker in output_markers)
        ):
            matches.append({"node_id": node_id, "class_type": class_type})
    return matches


def preflight_video_workflow(
    base_url: str | None = None,
    workflow_path: str | None = None,
    bindings_path: str | None = None,
) -> dict:
    path = workflow_path or settings.COMFYUI_VIDEO_WORKFLOW_PATH
    report = {"status": "blocked", "workflow_path": path, "checks": {}, "action_items": []}
    checks = report["checks"]
    if not path:
        checks["configured"] = False
        report["status"] = "skipped"
        report["message"] = "COMFYUI_VIDEO_WORKFLOW_PATH is empty; video generation will use SVD"
        report["action_items"].append("Set COMFYUI_VIDEO_WORKFLOW_PATH to a production ComfyUI video API workflow.")
        return report
    checks["configured"] = True
    workflow_file = Path(path)
    if not workflow_file.is_absolute():
        workflow_file = Path.cwd() / workflow_file
    checks["workflow_file"] = workflow_file.is_file()
    report["resolved_workflow_path"] = str(workflow_file)
    if not workflow_file.is_file():
        report["error"] = f"workflow file does not exist: {workflow_file}"
        report["action_items"].append(report["error"])
        return report
    try:
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            raise ValueError("workflow JSON root must be an object")
        binding_manifest = load_video_workflow_bindings(
            workflow_file,
            bindings_path if bindings_path is not None else getattr(settings, "COMFYUI_VIDEO_BINDINGS_PATH", ""),
        )
        binding_validation = (
            validate_video_workflow_bindings(workflow, binding_manifest)
            if binding_manifest.get("status") == "configured"
            else {
                "status": "missing",
                "controls": [],
                "derived_controls": [],
                "errors": [],
                "path": "",
                "sha256": "",
            }
        )
        report["binding_manifest"] = binding_validation
        if binding_validation["status"] == "invalid":
            checks["binding_manifest_valid"] = False
            report["action_items"].extend(binding_validation["errors"])
            return report
        checks["binding_manifest_valid"] = binding_validation["status"] in {"valid", "missing"}
        placeholders = sorted(scan_placeholders(workflow))
        placeholder_set = set(placeholders)

        def has_control(names: set[str]) -> bool:
            return bool(names & placeholder_set) or binding_has_control(binding_manifest, names)

        outputs = likely_video_outputs(workflow)
        report["placeholders"] = placeholders
        report["recognized_placeholders"] = sorted(VIDEO_WORKFLOW_PLACEHOLDERS)
        report["likely_output_nodes"] = outputs
        checks["has_reference_placeholder"] = has_control(
            {"reference_image", "image", "start_image", "first_frame"}
        )
        checks["has_native_end_frame_control"] = has_control({"end_image", "last_frame"})
        checks["has_prompt_placeholder"] = has_control({"prompt", "positive_prompt"})
        checks["has_negative_prompt_control"] = has_control({"negative_prompt"})
        checks["has_dimensions_control"] = (
            has_control({"width"}) and has_control({"height"})
        )
        checks["has_frame_count_control"] = has_control({"num_frames", "video_frames", "frame_count"})
        checks["has_fps_control"] = has_control({"fps"})
        checks["has_seed_control"] = has_control({"seed"})
        checks["has_output_prefix_control"] = has_control({"output_prefix"})
        checks["has_quality_profile_placeholder"] = has_control({"quality_mode", "quality_profile"})
        checks["has_repair_action_placeholder"] = has_control({"repair_action"})
        checks["has_quality_pipeline_placeholder"] = has_control({
            "quality_pipeline", "quality_pipeline_json", "quality_pipeline_stages",
            "quality_pipeline_prompt", "quality_pipeline_negative",
        })
        checks["has_spatial_plan_placeholder"] = has_control({"spatial_plan_json"})
        checks["has_spatial_control_references_placeholder"] = has_control({"spatial_control_references_json"})
        checks["has_spatial_asset_contract_placeholder"] = has_control({
            "spatial_asset_pack_json", "spatial_scene_contract_hash",
        })
        checks["has_continuity_reference_placeholder"] = has_control({
            "continuity_reference_image", "continuity_image", "previous_last_frame",
        })
        checks["has_reference_images_placeholder"] = has_control({"reference_images_json"})
        checks["has_driving_video_control"] = has_control({"driving_video"})
        checks["has_performance_audio_control"] = has_control({"performance_audio"})
        checks["has_temporal_keyframe_control"] = bool(
            has_control({"keyframe_images_json"})
            or (
                has_control({"keyframe_images"})
                and has_control({"keyframe_indices"})
            )
        )
        checks["has_end_frame_placeholder"] = bool(
            checks["has_native_end_frame_control"]
            or checks["has_temporal_keyframe_control"]
        )
        # The director and quality pipeline are compiled into the positive and
        # negative prompts before this graph is called. Standard Wan nodes do
        # not parse application JSON, so prompt bindings are valid model-facing
        # delivery for these controls. Explicit JSON remains an optional native
        # capability for custom pose/depth/multi-reference workflows.
        checks["quality_controls_effective"] = bool(
            checks["has_prompt_placeholder"] and checks["has_negative_prompt_control"]
        )
        checks["spatial_prompt_fallback_effective"] = checks["has_prompt_placeholder"]
        checks["has_likely_video_output"] = bool(outputs)
        contract_required = [
            "workflow_file", "has_reference_placeholder", "has_prompt_placeholder",
            "has_negative_prompt_control", "has_dimensions_control",
            "has_frame_count_control", "has_fps_control", "has_seed_control",
            "has_output_prefix_control", "quality_controls_effective",
            "spatial_prompt_fallback_effective", "has_likely_video_output",
        ]
        if settings.GENERATION_VIDEO_END_FRAME_ENABLED:
            contract_required.append("has_end_frame_placeholder")
        if settings.GENERATION_VIDEO_MID_KEYFRAME_ENABLED:
            contract_required.append("has_temporal_keyframe_control")
        report["required_checks"] = list(contract_required)
        if not all(checks.get(key) for key in contract_required):
            checks["comfyui_preflight"] = False
            report["status"] = "blocked"
            report["action_items"].extend(_video_workflow_action_items(checks))
            return report
        service = ComfyUIService(base_url=base_url, timeout=15)
        try:
            quality_pipeline = {
                "stages": ["platform_reference_gap_repair", "commercial_lighting_pass"],
                "prompt_directive": "premium short-drama video quality validation",
                "negative_directive": "cheap filter, low-budget lighting, unstable face",
            }
            resolved = service._replace_workflow_placeholders(workflow, {
                "prompt": "validation cinematic short-drama shot",
                "positive_prompt": "validation cinematic short-drama shot",
                "negative_prompt": "flicker, warped face, bad motion",
                "reference_image": "validation_reference.png",
                "image": "validation_reference.png",
                "start_image": "validation_reference.png",
                "first_frame": "validation_reference.png",
                "end_image": "validation_end.png",
                "last_frame": "validation_end.png",
                "reference_images_json": json.dumps(["validation_reference.png"]),
                "reference_image_count": 1,
                "reference_videos_json": "[]",
                "reference_audios_json": "[]",
                "driving_video": "validation_driving.mp4",
                "performance_audio": "validation_performance.wav",
                "reference_video_count": 0,
                "reference_audio_count": 0,
                "keyframe_images": ["validation_mid.png"],
                "keyframe_indices": [max(1, math.ceil(
                    settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                ) // 2)],
                "keyframe_strengths": [0.85],
                "keyframe_roles": ["performance_peak"],
                "keyframe_images_json": json.dumps([{
                    "path": "validation_mid.png",
                    "frame_index": max(1, math.ceil(
                        settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                    ) // 2),
                    "strength": 0.85,
                    "role": "performance_peak",
                }]),
                "keyframe_count": 1,
                "width": settings.GENERATION_WIDTH,
                "height": settings.GENERATION_HEIGHT,
                "duration_seconds": settings.GENERATION_VIDEO_TARGET_SECONDS,
                "num_frames": math.ceil(settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS),
                "video_frames": math.ceil(settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS),
                "frame_count": math.ceil(settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS),
                "fps": settings.GENERATION_VIDEO_MODEL_FPS,
                "seed": 31001,
                "output_prefix": "validation_video",
                "motion_bucket_id": 127,
                "noise_aug_strength": 0.02,
                "quality_mode": "seed_dance_reference",
                "quality_profile": "seed_dance_reference",
                "repair_action": "refine_video_commercial_aesthetic",
                "quality_pipeline": quality_pipeline,
                "quality_pipeline_json": json.dumps(quality_pipeline, ensure_ascii=False),
                "quality_pipeline_stages": ", ".join(quality_pipeline["stages"]),
                "quality_pipeline_prompt": quality_pipeline["prompt_directive"],
                "quality_pipeline_negative": quality_pipeline["negative_directive"],
                "shot_plan_json": json.dumps({"spatial_plan": {"camera_angle": "validation"}}, ensure_ascii=False),
                "spatial_plan_json": json.dumps({"camera_angle": "validation"}, ensure_ascii=False),
                "spatial_control_references_json": json.dumps(
                    {"pose_reference_prompt": "validation"}, ensure_ascii=False,
                ),
                "spatial_asset_pack_json": json.dumps({"scene_contract_hash": "validation"}, ensure_ascii=False),
                "spatial_scene_contract_hash": "validation",
                "continuity_reference_image": "validation_previous_last_frame.png",
                "continuity_image": "validation_previous_last_frame.png",
                "previous_last_frame": "validation_previous_last_frame.png",
                "continuity_reference_fallback": "",
            })
            if binding_manifest.get("status") == "configured":
                resolved = apply_video_workflow_bindings(resolved, binding_manifest, {
                    "prompt": "validation cinematic short-drama shot",
                    "positive_prompt": "validation cinematic short-drama shot",
                    "negative_prompt": "flicker, warped face, bad motion",
                    "reference_image": "validation_reference.png",
                    "image": "validation_reference.png",
                    "start_image": "validation_reference.png",
                    "first_frame": "validation_reference.png",
                    "end_image": "validation_end.png",
                    "last_frame": "validation_end.png",
                    "continuity_reference_image": "validation_previous_last_frame.png",
                    "continuity_image": "validation_previous_last_frame.png",
                    "previous_last_frame": "validation_previous_last_frame.png",
                    "reference_images_json": json.dumps(["validation_reference.png"]),
                    "driving_video": "validation_driving.mp4",
                    "performance_audio": "validation_performance.wav",
                    "keyframe_images": ["validation_mid.png"],
                    "keyframe_indices": [max(1, math.ceil(
                        settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                    ) // 2)],
                    "keyframe_strengths": [0.85],
                    "keyframe_roles": ["performance_peak"],
                    "keyframe_images_json": json.dumps([{
                        "path": "validation_mid.png",
                        "frame_index": max(1, math.ceil(
                            settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                        ) // 2),
                        "strength": 0.85,
                        "role": "performance_peak",
                    }]),
                    "keyframe_count": 1,
                    "width": settings.GENERATION_WIDTH,
                    "height": settings.GENERATION_HEIGHT,
                    "num_frames": math.ceil(
                        settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                    ),
                    "video_frames": math.ceil(
                        settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                    ),
                    "frame_count": math.ceil(
                        settings.GENERATION_VIDEO_TARGET_SECONDS * settings.GENERATION_VIDEO_MODEL_FPS
                    ),
                    "fps": settings.GENERATION_VIDEO_MODEL_FPS,
                    "seed": 31001,
                    "output_prefix": "validation_video",
                })
            service.preflight(resolved)
            checks["comfyui_preflight"] = True
            stats = service.client.get(service.base_url + "/system_stats")
            stats.raise_for_status()
            report["comfyui_devices"] = stats.json().get("devices", [])
        finally:
            service.client.close()
    except Exception as exc:
        checks["comfyui_preflight"] = False
        report["error"] = str(exc)
        report["action_items"].append(str(exc))
        return report
    required = ("workflow_file", "comfyui_preflight")
    report["status"] = "ready_for_live_test" if all(checks.get(key) for key in required) else "blocked"
    if report["status"] == "blocked":
        report["action_items"].extend(_video_workflow_action_items(checks))
    return report


def preflight_end_frame_workflow(provider: str | None = None) -> dict:
    """Validate the local image workflows used to create provider-neutral end frames.

    Remote video providers still need a locally generated final-frame image for the
    first/last-frame contract. Keep this check separate from the video workflow so
    a configured Ark endpoint cannot make an otherwise incomplete run look ready.
    """
    enabled = bool(settings.GENERATION_VIDEO_END_FRAME_ENABLED)
    provider_name = str(provider or getattr(settings, "GENERATION_PROVIDER", "") or "").strip().lower()
    report = {
        "status": "skipped",
        "provider": provider_name,
        "enabled": enabled,
        "checks": {},
        "action_items": [],
    }
    if not enabled or provider_name == "local_comfyui":
        report["message"] = "End-frame generation is disabled or the run uses the local video path."
        return report

    def resolve(path_value: str) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else Path.cwd() / path

    image_path = resolve(str(getattr(settings, "COMFYUI_WORKFLOW_PATH", "") or ""))
    reference_path = resolve(str(getattr(settings, "COMFYUI_REFERENCE_WORKFLOW_PATH", "") or ""))
    checks = report["checks"]
    checks["image_workflow_configured"] = bool(str(getattr(settings, "COMFYUI_WORKFLOW_PATH", "") or "").strip())
    checks["image_workflow_file"] = image_path.is_file() if checks["image_workflow_configured"] else False
    checks["reference_workflow_configured"] = bool(str(getattr(settings, "COMFYUI_REFERENCE_WORKFLOW_PATH", "") or "").strip())
    checks["reference_workflow_file"] = reference_path.is_file() if checks["reference_workflow_configured"] else False
    report["resolved_paths"] = {"image": str(image_path), "reference": str(reference_path)}
    missing = []
    if not checks["image_workflow_file"]:
        missing.append(f"COMFYUI_WORKFLOW_PATH is missing or does not exist: {image_path}")
    if not checks["reference_workflow_file"]:
        missing.append(f"COMFYUI_REFERENCE_WORKFLOW_PATH is missing or does not exist: {reference_path}")
    image_contract = _inspect_image_workflow(image_path, require_reference=False)
    reference_contract = _inspect_image_workflow(reference_path, require_reference=True)
    report["image_workflow"] = image_contract
    report["reference_workflow"] = reference_contract
    if not image_contract["valid"]:
        missing.extend(f"Image workflow: {item}" for item in image_contract["errors"])
    if not reference_contract["valid"]:
        missing.extend(f"Reference workflow: {item}" for item in reference_contract["errors"])
    if missing:
        report["status"] = "blocked"
        report["action_items"] = [
            "Configure both local ComfyUI image workflows before using a remote video provider with end-frame generation."
        ] + missing
        return report
    report["status"] = "ready"
    return report


def preflight_local_video_engine_registry(
    base_url: str | None = None,
    registry_path: str | None = None,
) -> dict:
    """Validate every routable local workflow before production starts."""
    configured_path = str(
        registry_path
        if registry_path is not None
        else getattr(settings, "COMFYUI_VIDEO_ENGINE_REGISTRY_PATH", "") or ""
    ).strip()
    report = {
        "status": "skipped",
        "registry_path": configured_path,
        "engines": [],
        "action_items": [],
    }
    if not configured_path:
        report["message"] = "COMFYUI_VIDEO_ENGINE_REGISTRY_PATH is empty"
        return report
    try:
        engines = load_local_video_engine_registry(configured_path)
    except LocalVideoEngineRoutingError as exc:
        report["status"] = "blocked"
        report["action_items"].append(str(exc))
        return report

    for engine in engines:
        workflow_report = preflight_video_workflow(
            base_url,
            str(engine["workflow_path"]),
            str(engine["bindings_path"]) if engine.get("bindings_path") else None,
        )
        model_report = inspect_local_video_model(
            str(engine["workflow_path"]),
            configured_profile_override=str(engine.get("model_profile") or "auto"),
        )
        declared = dict(engine.get("capabilities") or {})
        capability_issues = []
        native_capabilities = set(model_report.get("native_capabilities") or [])
        unsupported_claims = sorted(
            name for name, enabled in declared.items()
            if enabled and name not in native_capabilities
        )
        if unsupported_claims:
            capability_issues.append(
                "declares capabilities not supported by the selected model profile: "
                + ", ".join(unsupported_claims)
            )
        if declared.get("temporal_keyframes") and not (
            workflow_report.get("checks", {}).get("has_temporal_keyframe_control")
            and model_report.get("supports_temporal_keyframes")
        ):
            capability_issues.append(
                "declares temporal_keyframes but the workflow/model does not prove frame-indexed conditioning"
            )
        workflow_checks = workflow_report.get("checks", {})
        profile = str(model_report.get("profile") or engine.get("model_profile") or "").strip().lower()
        if (
            profile == "hunyuanvideo_avatar"
            and declared.get("performance_control")
            and not workflow_checks.get("has_performance_audio_control")
        ):
            capability_issues.append(
                "declares performance_control but the Avatar workflow has no performance_audio binding"
            )
        if (
            profile in {"wan_2_2_animate", "hunyuan_custom"}
            and declared.get("motion_control")
            and not workflow_checks.get("has_driving_video_control")
        ):
            capability_issues.append(
                "declares motion_control but the driven workflow has no driving_video binding"
            )
        if (
            profile == "hunyuan_custom"
            and declared.get("performance_control")
            and not (
                workflow_checks.get("has_performance_audio_control")
                or workflow_checks.get("has_driving_video_control")
            )
        ):
            capability_issues.append(
                "declares performance_control but HunyuanCustom has neither performance_audio nor driving_video binding"
            )
        status = "ready" if (
            workflow_report.get("status") == "ready_for_live_test"
            and model_report.get("status") == "ready"
            and not capability_issues
        ) else "blocked"
        engine_report = {
            "engine_id": engine["id"],
            "status": status,
            "declared_capabilities": declared,
            "workflow": workflow_report,
            "model": model_report,
            "capability_issues": capability_issues,
        }
        report["engines"].append(engine_report)
        if status != "ready":
            reasons = capability_issues or workflow_report.get("action_items") or model_report.get("action_items")
            report["action_items"].extend(
                f"{engine['id']}: {reason}" for reason in reasons
            )
    ready_engine_ids = {
        item["engine_id"] for item in report["engines"] if item["status"] == "ready"
    }
    fleet_coverage = evaluate_local_video_engine_fleet(
        [engine for engine in engines if engine["id"] in ready_engine_ids],
        temporal_keyframes_required=bool(settings.GENERATION_VIDEO_MID_KEYFRAME_ENABLED),
    )
    if not fleet_coverage["passed"]:
        report["action_items"].append(
            "Local video engine registry does not cover required short-drama profiles: "
            + ", ".join(fleet_coverage["missing_profiles"])
        )
    all_engines_ready = bool(report["engines"]) and all(
        item["status"] == "ready" for item in report["engines"]
    )
    report["status"] = (
        "ready_for_live_test"
        if all_engines_ready and fleet_coverage["passed"]
        else "blocked"
    )
    report["fleet_coverage"] = fleet_coverage
    report["checks"] = {
        "registry_loaded": True,
        "engine_count": len(report["engines"]),
        "all_engines_ready": all_engines_ready,
        "short_drama_profiles_covered": fleet_coverage["passed"],
    }
    return report


def preflight_motion_reference_library(library_path: str | None = None) -> dict:
    """Validate configured action-driving assets before a GPU task needs them."""
    configured_path = str(
        library_path
        if library_path is not None
        else getattr(settings, "LOCAL_MOTION_REFERENCE_LIBRARY_PATH", "") or ""
    ).strip()
    report = {
        "status": "skipped",
        "library_path": configured_path,
        "assets": [],
        "action_items": [],
    }
    if not configured_path:
        report["message"] = "LOCAL_MOTION_REFERENCE_LIBRARY_PATH is empty"
        return report
    try:
        assets = load_motion_reference_library(configured_path)
    except MotionReferenceLibraryError as exc:
        report["status"] = "blocked"
        report["action_items"].append(str(exc))
        return report
    report["status"] = "ready"
    report["assets"] = [
        {
            "asset_id": asset["id"],
            "path": asset["path"],
            "sha256": asset["sha256"],
            "tags": list(asset["tags"]),
            "shot_roles": list(asset["shot_roles"]),
            "action_intensities": list(asset["action_intensities"]),
            "character_range": [asset["min_characters"], asset["max_characters"]],
        }
        for asset in assets
    ]
    return report


def _inspect_image_workflow(path: Path, *, require_reference: bool) -> dict:
    """Validate the offline contract required by ComfyUI image generation."""
    result = {"valid": False, "classes": [], "errors": []}
    if not path.is_file():
        result["errors"].append(f"workflow file does not exist: {path}")
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["errors"].append(f"workflow JSON is invalid: {exc}")
        return result
    nodes = data.get("nodes") if isinstance(data, dict) and isinstance(data.get("nodes"), dict) else data
    if not isinstance(nodes, dict) or not nodes:
        result["errors"].append("workflow must contain a non-empty nodes object")
        return result
    classes = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or not node.get("class_type"):
            result["errors"].append(f"node {node_id} is missing class_type")
            continue
        if not isinstance(node.get("inputs", {}), dict):
            result["errors"].append(f"node {node_id} inputs must be an object")
        classes.append(str(node["class_type"]))
    result["classes"] = sorted(set(classes))
    required = {"CheckpointLoaderSimple", "KSampler", "VAEDecode", "SaveImage"}
    missing_classes = sorted(required - set(classes))
    if missing_classes:
        result["errors"].append("missing required nodes: " + ", ".join(missing_classes))
    if require_reference:
        if "LoadImage" not in classes:
            result["errors"].append("reference workflow must contain LoadImage")
        if not any("ipadapter" in class_name.lower() for class_name in classes):
            result["errors"].append("reference workflow must contain an IP-Adapter node")
    result["valid"] = not result["errors"]
    return result


def _video_workflow_action_items(checks: dict) -> list[str]:
    items = []
    if not checks.get("has_reference_placeholder"):
        items.append("Add {reference_image} or {image} to the workflow input image node.")
    if not checks.get("has_prompt_placeholder"):
        items.append("Bind prompt/positive_prompt to the real positive CLIP text node.")
    if not checks.get("has_negative_prompt_control"):
        items.append("Bind negative_prompt to the real negative CLIP text node so repair constraints affect sampling.")
    if not checks.get("has_dimensions_control"):
        items.append("Bind width and height to the latent/video conditioning node.")
    if not checks.get("has_frame_count_control"):
        items.append("Bind num_frames, video_frames, or frame_count to the native video length input.")
    if not checks.get("has_fps_control"):
        items.append("Bind fps to the video output node.")
    if not checks.get("has_seed_control"):
        items.append("Bind seed to every active Wan sampling stage.")
    if not checks.get("has_output_prefix_control"):
        items.append("Bind output_prefix to the video save node so candidates cannot overwrite each other.")
    if not checks.get("has_end_frame_placeholder"):
        items.append("Add {end_image} or {last_frame} so the workflow can honor an approved shot ending.")
    if settings.GENERATION_VIDEO_MID_KEYFRAME_ENABLED and not checks.get("has_temporal_keyframe_control"):
        items.append(
            "Bind keyframe_images_json, or bind both keyframe_images and keyframe_indices, "
            "before enabling middle-frame performance anchors."
        )
    if not checks.get("quality_controls_effective"):
        items.append("Bind both positive and negative prompts; quality and repair directives are compiled into them upstream.")
    if not checks.get("has_likely_video_output"):
        items.append("Add a video output node such as VHS_VideoCombine, WebM/GIF export, or another video save node.")
    if not checks.get("comfyui_preflight"):
        items.append("Fix ComfyUI node/model preflight errors before running production video generation.")
    return items


def preflight_production_video_engine(
    base_url: str | None = None,
    workflow_path: str | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    request_mode_override: str | None = None,
    resolution_override: str | None = None,
    output_format_override: str | None = None,
    duration_override: float | None = None,
) -> dict:
    workflow_report = preflight_video_workflow(base_url, workflow_path)
    if any(
        value is not None and value != ""
        for value in (
            provider_override,
            model_override,
            request_mode_override,
            resolution_override,
            output_format_override,
        )
    ) or duration_override is not None:
        provider_kwargs = {"provider_override": provider_override}
        if model_override:
            provider_kwargs["model_override"] = model_override
        if request_mode_override:
            provider_kwargs["request_mode_override"] = request_mode_override
        if resolution_override:
            provider_kwargs["resolution_override"] = resolution_override
        if output_format_override:
            provider_kwargs["output_format_override"] = output_format_override
        if duration_override is not None:
            provider_kwargs["duration_override"] = duration_override
        provider_report = preflight_video_provider(**provider_kwargs)
    else:
        provider_report = preflight_video_provider()
    report = {
        "status": "production_not_ready",
        "engine": "director_pipeline",
        "workflow": workflow_report,
        "provider": provider_report,
        "requirements": [
            "A configured ComfyUI image-to-video workflow or production HTTP video provider",
            "Reference image placeholder for each scene keyframe",
            "Prompt placeholders for the director motion contract",
            "Quality profile, repair action, and quality-pipeline placeholders for commercial repair passes",
            "A continuity-reference placeholder for verified adjacent-shot tail frames",
            "A real video output node",
            "ComfyUI preflight passing against installed nodes and models, or API endpoint/key configured",
        ],
        "action_items": [],
    }
    local_provider = str(provider_report.get("provider") or "").strip().lower() == "local_comfyui"
    registry_report = (
        preflight_local_video_engine_registry(base_url)
        if local_provider and workflow_path is None
        else {"status": "skipped", "engines": [], "action_items": []}
    )
    if registry_report.get("status") != "skipped":
        workflow_report = registry_report
        report["workflow"] = workflow_report
        report["engine_registry"] = registry_report
        model_reports = [
            item.get("model") for item in registry_report.get("engines", [])
            if isinstance(item, dict) and isinstance(item.get("model"), dict)
        ]
        local_model_report = {
            "status": "ready" if model_reports and all(
                item.get("status") == "ready" for item in model_reports
            ) else "blocked",
            "profiles": [item.get("profile") for item in model_reports],
            "engines": model_reports,
            "action_items": list(registry_report.get("action_items") or []),
        }
    else:
        local_model_report = inspect_local_video_model(workflow_path) if local_provider else {
            "status": "not_applicable",
            "reason": "The selected video provider is not the local ComfyUI path.",
        }
    report["local_model"] = local_model_report
    motion_library_report = preflight_motion_reference_library()
    report["motion_reference_library"] = motion_library_report
    end_frame_report = preflight_end_frame_workflow(provider_report.get("provider"))
    report["end_frame"] = end_frame_report
    provider_warnings = provider_report.get("warnings") or []
    if provider_warnings:
        report["warnings"] = list(provider_warnings)
    provider_blocked = provider_report.get("status") == "blocked"
    end_frame_blocked = end_frame_report.get("status") == "blocked"
    workflow_ready = workflow_report.get("status") == "ready_for_live_test"
    provider_ready = provider_report.get("status") == "configured"
    provider_requires_output_validation = str(provider_report.get("provider") or "").strip().lower() == "seedance_api"
    provider_capabilities = provider_report.get("capabilities")
    provider_output_validation_ready = (
        not provider_requires_output_validation
        or not isinstance(provider_capabilities, dict)
        or "output_artifact_validation" not in provider_capabilities
        or provider_capabilities.get("output_artifact_validation") is True
    )
    if workflow_ready or provider_ready:
        report["status"] = "ready_for_production_video_test"
        report["action_items"].append("Run one full project with video review enabled and compare against the Seed Dance baseline.")
        report["action_items"].extend(provider_warnings)
        if local_provider and local_model_report.get("status") != "ready":
            report["status"] = "production_not_ready"
            report["action_items"] = local_model_report.get("action_items") or [
                "Configure a verified local production video model before final generation."
            ]
        if local_provider and motion_library_report.get("status") == "blocked":
            report["status"] = "production_not_ready"
            report["action_items"] = motion_library_report.get("action_items") or [
                "Fix the configured motion reference library before action generation."
            ]
        if provider_ready and not provider_output_validation_ready:
            report["status"] = "production_not_ready"
            report["action_items"] = [
                "Install ffprobe and keep SEEDANCE_VALIDATE_OUTPUT=true before accepting remote video output for production."
            ]
        if end_frame_blocked:
            report["status"] = "production_not_ready"
            report["action_items"] = end_frame_report.get("action_items") or [
                "Fix the end-frame image workflow before using a remote video provider."
            ]
    elif provider_blocked and workflow_report.get("status") == "skipped":
        report["action_items"].extend(
            provider_report.get("action_items")
            or [provider_report.get("message") or "Fix the configured video provider before production."]
        )
    elif workflow_report.get("status") == "skipped":
        report["action_items"].append(
            "Configure COMFYUI_VIDEO_WORKFLOW_PATH with a verified local workflow. Use LTX-2 or "
            "HunyuanVideo 1.5 keyframe conditioning when temporal anchors are enabled."
        )
    elif workflow_report.get("error"):
        report["action_items"].append(workflow_report["error"])
    else:
        report["action_items"].extend(
            workflow_report.get("action_items") or ["Fix the blocked video workflow checks before using production generation."]
        )
    return report


def preflight_video_provider(
    provider_override: str | None = None,
    model_override: str | None = None,
    request_mode_override: str | None = None,
    resolution_override: str | None = None,
    output_format_override: str | None = None,
    duration_override: float | None = None,
) -> dict:
    def runtime_value(name: str, default=""):
        value = os.getenv(name)
        if value is not None:
            return value
        return getattr(settings, name, default)

    def runtime_bool(name: str, default: bool = False) -> bool:
        return str(runtime_value(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}

    provider = str(provider_override or os.getenv("GENERATION_PROVIDER") or settings.GENERATION_PROVIDER).strip().lower()
    if provider == "hybrid":
        provider = os.getenv("GENERATION_PRIMARY_PROVIDER") or settings.GENERATION_PRIMARY_PROVIDER
    prefix_by_provider = {
        "jimeng_api": "JIMENG",
        "kling_api": "KLING",
        "hailuo_api": "HAILUO",
        "http_video_api": "HTTP_VIDEO",
        "seedance_api": "SEEDANCE",
    }
    prefix = prefix_by_provider.get(provider)
    report = {"provider": provider, "status": "skipped", "checks": {}}
    if not prefix:
        report["message"] = "GENERATION_PROVIDER is local; production readiness depends on ComfyUI video workflow"
        return report
    endpoint = os.getenv(f"{prefix}_ENDPOINT") or str(getattr(settings, f"{prefix}_ENDPOINT", "") or "")
    api_key = os.getenv(f"{prefix}_API_KEY") or str(getattr(settings, f"{prefix}_API_KEY", "") or "")
    status_endpoint = os.getenv(f"{prefix}_STATUS_ENDPOINT") or str(getattr(settings, f"{prefix}_STATUS_ENDPOINT", "") or "")
    result_endpoint = os.getenv(f"{prefix}_RESULT_ENDPOINT") or str(getattr(settings, f"{prefix}_RESULT_ENDPOINT", "") or "")
    cancel_endpoint = os.getenv(f"{prefix}_CANCEL_ENDPOINT") or str(getattr(settings, f"{prefix}_CANCEL_ENDPOINT", "") or "")
    endpoint_host = (urlparse(endpoint).hostname or "").lower() if endpoint else ""
    endpoint_path = urlparse(endpoint).path if endpoint else ""
    looks_like_ark_endpoint = (
        endpoint_host in {"ark.cn-beijing.volcengine.com", "ark.cn-beijing.volces.com"}
        or endpoint_host.endswith(".volcengine.com")
        or endpoint_host.endswith(".volces.com")
    )
    if provider == "seedance_api":
        configured_api_format = str(runtime_value("SEEDANCE_API_FORMAT", "legacy")).strip().lower() or "legacy"
        api_format = configured_api_format
        if (
            ("SEEDANCE_API_FORMAT" not in os.environ or not str(os.environ.get("SEEDANCE_API_FORMAT", "")).strip())
            and configured_api_format.strip().lower() == "legacy"
            and looks_like_ark_endpoint
        ):
            api_format = "ark_v3"
        model = str(model_override or runtime_value("SEEDANCE_MODEL", "") or "").strip()
        if not model:
            model = _seedance_model()
        resolution = str(resolution_override or runtime_value("SEEDANCE_RESOLUTION", "1080p"))
        output_format = str(output_format_override or runtime_value("SEEDANCE_OUTPUT_FORMAT", "mp4"))
        request_mode = str(request_mode_override or runtime_value("SEEDANCE_REQUEST_MODE", "reference_to_video"))
        report["configuration"] = {
            "api_format": api_format,
            "model": model,
            "request_mode": request_mode,
            "resolution": resolution,
            "output_format": output_format,
            "duration_seconds": duration_override,
        }
        report["capabilities"] = {
            "multimodal_references": True,
            "native_audio": runtime_bool("SEEDANCE_NATIVE_AUDIO", True),
            "multi_shot": runtime_bool("SEEDANCE_MULTI_SHOT", True),
            "continuity_last_frame": runtime_bool("SEEDANCE_RETURN_LAST_FRAME", True),
            "first_last_frame": True,
            "first_frame": True,
            "edit_and_extend": True,
        }
    ark_native = (
        provider == "seedance_api"
        and report.get("configuration", {}).get("api_format", "").strip().lower()
        in {"ark", "ark_v3", "volcengine", "volcengine_v3"}
    )
    if ark_native and endpoint and not status_endpoint:
        status_endpoint = endpoint.rstrip("/") + "/{job_id}"
    report["checks"] = {
        "endpoint_configured": bool(endpoint),
        "api_key_configured": bool(api_key),
        "status_endpoint_configured": bool(status_endpoint),
        "result_endpoint_configured": bool(result_endpoint),
        "result_endpoint_required": not ark_native,
        "native_ark_format": ark_native,
        "ark_endpoint_detected": looks_like_ark_endpoint,
        "remote_cancel_endpoint_configured": bool(cancel_endpoint),
        "remote_cancel_endpoint_valid": (
            not cancel_endpoint
            or "{job_id}" in cancel_endpoint
            or "{request_id}" in cancel_endpoint
        ),
    }
    checks = report["checks"]
    configuration_ok = True
    if cancel_endpoint and not checks["remote_cancel_endpoint_valid"]:
        configuration_ok = False
        report.setdefault("action_items", []).append(
            f"{prefix}_CANCEL_ENDPOINT must contain {{job_id}} or {{request_id}}."
        )
    if provider == "seedance_api":
        callback_url = str(runtime_value("SEEDANCE_CALLBACK_URL", "") or "").strip()
        callback_secret = str(runtime_value("SEEDANCE_CALLBACK_SECRET", "") or "").strip()
        checks["callback_url_configured"] = bool(callback_url)
        checks["callback_secret_configured"] = bool(callback_secret)
        if callback_url and not callback_secret:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "SEEDANCE_CALLBACK_URL requires SEEDANCE_CALLBACK_SECRET; configure both or disable callbacks."
            )
        api_format = report["configuration"]["api_format"].strip().lower()
        resolution = report["configuration"]["resolution"].strip().lower()
        output_format = report["configuration"]["output_format"].strip().lower()
        valid_formats = {"legacy", "generic", "compatible", "ark", "ark_v3", "volcengine", "volcengine_v3"}
        model_name = report["configuration"]["model"].strip().lower()
        model_is_10 = _seedance_model_is_10(model_name)
        model_is_25 = _seedance_model_is_25(model_name)
        valid_resolutions = (
            _seedance_supported_resolutions(model_name)
            if ark_native
            else {"480p", "720p", "1080p", "4k"}
        )
        checks["api_format_valid"] = api_format in valid_formats
        checks["resolution_valid"] = resolution in valid_resolutions
        checks["output_format_valid"] = output_format in {"mp4", "mov"}
        if ark_native and output_format == "mov" and not model_is_25:
            checks["output_format_valid"] = False
        checks["request_mode_valid"] = request_mode.strip().lower() in {
            "reference", "reference_to_video", "auto", "multi_shot", "seedance_2_5", "2.5",
            "first_frame", "first_last_frame", "edit", "extend",
        }
        configuration_ok = configuration_ok and all(
            checks[key] for key in (
                "api_format_valid", "resolution_valid", "output_format_valid", "request_mode_valid",
            )
        )
        if not checks["request_mode_valid"]:
            report.setdefault("action_items", []).append(
                "SEEDANCE_REQUEST_MODE must be reference, reference_to_video, auto, multi_shot, seedance_2_5, 2.5, first_frame, first_last_frame, edit, or extend."
            )
        normalized_mode = request_mode.strip().lower()
        if ark_native and normalized_mode == "first_frame":
            first_frame_supported = model_is_10 or model_is_25
            checks["first_frame_mode_supported"] = first_frame_supported
            report["capabilities"]["first_frame"] = first_frame_supported
            if not first_frame_supported:
                configuration_ok = False
                report.setdefault("action_items", []).append(
                    f"Native Seedance explicit first_frame mode requires Seedance 1.0 or 2.5; current model is {model_name}."
                )
        elif ark_native:
            checks["first_frame_mode_supported"] = True
        if ark_native and normalized_mode == "first_last_frame":
            first_last_frame_supported = _seedance_model_supports_first_last_frame(model_name)
            checks["first_last_frame_mode_supported"] = first_last_frame_supported
            report["capabilities"]["first_last_frame"] = first_last_frame_supported
            if not first_last_frame_supported:
                configuration_ok = False
                report.setdefault("action_items", []).append(
                    f"Native Seedance first_last_frame mode is not supported by model {model_name}."
                )
        if duration_override is not None:
            try:
                requested_duration = float(duration_override)
            except (TypeError, ValueError):
                requested_duration = 0
            minimum_duration, maximum_duration = _seedance_duration_bounds(model_name, request_mode)
            duration_valid = minimum_duration <= requested_duration <= maximum_duration
            if model_is_25 and request_mode.strip().lower() in {"edit", "extend"}:
                duration_valid = False
            checks["duration_valid"] = duration_valid
            if not duration_valid:
                configuration_ok = False
                if model_is_25 and request_mode.strip().lower() in {"edit", "extend"}:
                    report.setdefault("action_items", []).append(
                        "Native Seedance 2.5 edit/extend tasks require automatic duration (-1); clear the per-run duration."
                    )
                else:
                    report.setdefault("action_items", []).append(
                        f"Native Seedance model {model_name} duration must be between {minimum_duration} and {maximum_duration} seconds; configured {requested_duration:g}."
                    )
        if ark_native and request_mode.strip().lower() in {"multi_shot", "seedance_2_5", "2.5"}:
            try:
                configured_sequence_duration = float(runtime_value("SEEDANCE_MULTI_SHOT_DURATION_SECONDS", "30"))
            except (TypeError, ValueError):
                configured_sequence_duration = 0
            minimum_duration, maximum_duration = _seedance_duration_bounds(model_name, request_mode)
            checks["multi_shot_duration_valid"] = minimum_duration <= configured_sequence_duration <= maximum_duration
            if not checks["multi_shot_duration_valid"]:
                configuration_ok = False
                report.setdefault("action_items", []).append(
                    f"Native Seedance model {model_name} multi-shot duration must be between "
                    f"{minimum_duration} and {maximum_duration} seconds; configured {configured_sequence_duration:g}."
                )
        if (
            ark_native
            and model_is_10
            and request_mode.strip().lower() in {"edit", "extend"}
        ):
            configuration_ok = False
            report.setdefault("action_items", []).append(
                f"Native Seedance model {model_name} does not support {request_mode.strip().lower()} tasks; use Seedance 2.0 or 2.5."
            )
        if ark_native and request_mode.strip().lower() == "auto" and not model_is_25:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                f"Native Seedance model {model_name} does not support omni_reference_task_type=auto; use Seedance 2.5."
            )
        if not checks["resolution_valid"]:
            report.setdefault("action_items", []).append(
                f"{report['configuration']['model']} does not support {resolution}; use one of "
                f"{', '.join(sorted(valid_resolutions))}."
            )
        if ark_native and output_format == "mov" and not model_is_25:
            report.setdefault("action_items", []).append(
                "Native Ark MOV output requires Seedance 2.5; use MP4 for Seedance 2.0/1.0."
            )
        if looks_like_ark_endpoint and not ark_native:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "The configured endpoint is a Volcano Ark endpoint but the effective format is legacy; configure a compatible gateway or set SEEDANCE_API_FORMAT=ark_v3 explicitly."
            )
        elif ark_native and endpoint and not looks_like_ark_endpoint:
            report.setdefault("warnings", []).append(
                "SEEDANCE_API_FORMAT=ark_v3 is enabled but the endpoint host is not Volcano Ark; verify the gateway contract."
            )
        if looks_like_ark_endpoint and ark_native and endpoint_path and "/api/v3/contents/generations/tasks" not in endpoint_path:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "Native Ark endpoint should use /api/v3/contents/generations/tasks."
            )
        checks["model_configured"] = bool(report["configuration"]["model"].strip())
        checks["model_is_25"] = model_is_25
        if ark_native:
            report["capabilities"]["available_models"] = [dict(item) for item in SEEDANCE_MODEL_CATALOG]
            report["capabilities"]["multimodal_references"] = _seedance_model_supports_multimodal_references(model_name)
            report["capabilities"]["first_last_frame"] = _seedance_model_supports_first_last_frame(model_name)
            report["capabilities"]["edit_and_extend"] = not model_is_10
            minimum_duration, maximum_duration = _seedance_duration_bounds(model_name, request_mode)
            report["capabilities"].update({
                "supported_resolutions": sorted(valid_resolutions),
                "duration_min_seconds": minimum_duration,
                "duration_max_seconds": maximum_duration,
                "supports_draft": model_is_25,
                "supports_auto_mode": model_is_25,
                "supports_edit": not model_is_10,
                "supports_extend": not model_is_10,
                "supports_mov": model_is_25,
                "supports_first_frame_mode": model_is_10 or model_is_25,
            })
        report["capabilities"]["reference_item_limit"] = (
            50 if model_is_25 and ark_native else (15 if ark_native else None)
        )
        report["capabilities"]["reference_category_limits"] = (
            {"images": 30, "videos": 10, "audios": 10}
            if model_is_25 and ark_native
            else (
                {"images": 2 if _seedance_model_supports_first_last_frame(model_name) else 1, "videos": 0, "audios": 0}
                if model_is_10 and ark_native
                else {"images": 9, "videos": 3, "audios": 3}
            )
        )
        if model_is_10 and ark_native:
            report["capabilities"]["reference_item_limit"] = 2 if _seedance_model_supports_first_last_frame(model_name) else 1
        # Ark's reference-audio support is model-specific: 2.0 accepts it
        # alongside image/video references, 2.5 accepts it directly, while
        # 1.0 does not advertise the capability.
        report["capabilities"]["reference_audio_supported"] = bool(
            ark_native and _seedance_model_supports_reference_audio(model_name)
        )
        checks["production_resolution"] = resolution in {"1080p", "4k"}
        if not checks["model_configured"]:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "Set SEEDANCE_MODEL to a real provider model id before submitting generation tasks."
            )
        if not checks["production_resolution"]:
            report.setdefault("warnings", []).append(
                f"Seedance production output is configured as {resolution}; use 1080p or 4k for final delivery."
            )
        if not model_is_25:
            report.setdefault("warnings", []).append(
                "The configured Seedance model is not identified as 2.5; 2.5 multimodal limits and Draft promotion are unavailable."
            )
        if not report["capabilities"]["native_audio"]:
            report.setdefault("warnings", []).append(
                "Native audio is disabled; dialogue will use the separate audio pipeline and cannot use Ark audio generation."
            )
        output_validation_enabled = runtime_bool("SEEDANCE_VALIDATE_OUTPUT", True)
        checks["output_validation_enabled"] = output_validation_enabled
        checks["ffprobe_available"] = bool(shutil.which("ffprobe"))
        report["capabilities"]["output_artifact_validation"] = bool(
            output_validation_enabled and checks["ffprobe_available"]
        )
        if not output_validation_enabled:
            report.setdefault("warnings", []).append(
                "SEEDANCE_VALIDATE_OUTPUT=false disables native Ark artifact validation and is not allowed for production runs."
            )
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "Set SEEDANCE_VALIDATE_OUTPUT=true before submitting native Ark production generation tasks."
            )
        elif not checks["ffprobe_available"]:
            report.setdefault("warnings", []).append(
                "SEEDANCE_VALIDATE_OUTPUT is enabled but ffprobe is unavailable; returned Ark artifacts cannot be validated immediately."
            )
            report.setdefault("action_items", []).append(
                "Install ffprobe before submitting native Ark production generation tasks."
            )
        if not report["capabilities"]["continuity_last_frame"]:
            report.setdefault("warnings", []).append(
                "return_last_frame is disabled; cross-shot continuity will fall back to local video-frame extraction."
            )
        if ark_native:
            media_template = str(runtime_value("SEEDANCE_MEDIA_URL_TEMPLATE", "") or "")
            mode = str(report["configuration"]["request_mode"]).strip().lower()
            requires_video_transport = mode in {"edit", "extend"}
            media_template_valid = False
            if media_template:
                try:
                    sample_url = media_template.format(filename="preflight.mp4", path="preflight/preflight.mp4")
                    parsed = urlparse(sample_url)
                    hostname = parsed.hostname or ""
                    private_host = hostname.lower() in {"localhost", "localhost.localdomain"}
                    try:
                        address = ipaddress.ip_address(hostname)
                        private_host = private_host or any(
                            (
                                address.is_private,
                                address.is_loopback,
                                address.is_link_local,
                                address.is_reserved,
                            )
                        )
                    except ValueError:
                        pass
                    media_template_valid = (
                        ("{filename}" in media_template or "{path}" in media_template)
                        and parsed.scheme == "https"
                        and bool(parsed.netloc)
                        and not private_host
                    )
                except (KeyError, ValueError):
                    media_template_valid = False
            checks["local_video_reference_transport_configured"] = media_template_valid
            report["capabilities"]["local_video_audio_references"] = media_template_valid
            if not media_template_valid:
                message = (
                    "Native Ark image references and small local audio files can use Base64; local video and "
                    "oversized audio references require a valid HTTP(S) SEEDANCE_MEDIA_URL_TEMPLATE with "
                    "{filename}/{path}, or pre-ingested public asset IDs."
                )
                report.setdefault("warnings", []).append(message)
                if requires_video_transport:
                    configuration_ok = False
                    report.setdefault("action_items", []).append(message)
    report["status"] = "configured" if endpoint and api_key and configuration_ok else "blocked"
    if report["status"] == "blocked":
        if not endpoint or not api_key:
            report["message"] = f"Set {prefix}_ENDPOINT and {prefix}_API_KEY"
        else:
            report["message"] = "Fix Seedance API format, resolution, or output format settings"
    return report
