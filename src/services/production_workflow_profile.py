"""Approved ComfyUI workflow profile checks for production short-drama quality."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.services.generation_quality_policy import (
    SHOT_PIPELINE_STAGES,
    image_quality_budget,
    video_quality_budget,
)
from src.services.video_engine_preflight import scan_placeholders
from src.utils.atomic_json import write_json_atomic


REQUIRED_CAPABILITIES = {
    "character_identity",
    "spatial_control",
    "pose_control",
    "depth_control",
    "first_last_frame_video",
    "motion_control",
    "face_repair",
    "upscale",
    "candidate_review",
}
REQUIRED_WORKFLOWS = {"image", "reference", "video"}
REQUIRED_IMAGE_PIPELINE_STAGES = sorted({
    stage
    for profile in SHOT_PIPELINE_STAGES.values()
    for stage in profile["stages"]
})
MIN_QUALITY_BUDGET = {
    "image_candidates": 5,
    "image_refinement_passes": 2,
    "video_candidates": 4,
    "video_refinement_passes": 2,
    "steps": 40,
}
APPROVED_QUALITY_PROFILES = {"hongguo_reference", "seed_dance_reference", "ultra", "high_quality"}
CAPABILITY_KEYWORDS = {
    "character_identity": ("ipadapter", "faceid", "instantid"),
    "spatial_control": ("controlnet", "depth", "openpose", "dwpose", "pose", "seg", "mask"),
    "pose_control": ("openpose", "dwpose", "pose"),
    "depth_control": ("depth", "zoe", "midas"),
    "motion_control": ("svd", "animatediff", "video", "motion", "ltx", "wan"),
    "face_repair": ("facedetailer", "face detailer", "gfpgan", "codeformer", "facerestore"),
    "upscale": ("upscale", "ultrascale", "supir", "esrgan"),
    "candidate_review": ("saveimage", "save_image", "savevideo", "video combine", "vhs_videocombine"),
}
VIDEO_OUTPUT_KEYWORDS = ("vhs_videocombine", "savevideo", "createvideo", "video combine")
VIDEO_WORKFLOW_PLACEHOLDER_GROUPS = {
    "reference": {"reference_image", "image"},
    "end_frame": {"end_image", "last_frame"},
    "prompt": {"prompt", "positive_prompt"},
    "quality_profile": {"quality_mode", "quality_profile"},
    "repair_action": {"repair_action"},
    "quality_pipeline": {
        "quality_pipeline", "quality_pipeline_json", "quality_pipeline_stages",
        "quality_pipeline_prompt", "quality_pipeline_negative",
    },
    "spatial_plan": {"spatial_plan_json"},
    "spatial_control_references": {"spatial_control_references_json"},
    "spatial_asset_contract": {"spatial_asset_pack_json", "spatial_scene_contract_hash"},
    "continuity_reference": {"continuity_reference_image", "continuity_image", "previous_last_frame"},
    "reference_images": {"reference_images_json"},
}
IMAGE_WORKFLOW_PLACEHOLDER_GROUPS = {
    "spatial_plan": {"spatial_plan_json"},
    "spatial_control_references": {"spatial_control_references_json"},
    "spatial_asset_contract": {"spatial_asset_pack_json", "spatial_scene_contract_hash"},
}


class ProductionWorkflowProfileService:
    """Freeze and validate the local ComfyUI workflow contract."""

    def freeze_profile(
        self,
        profile_path: str | None = None,
        capabilities: dict | None = None,
        notes: str = "",
    ) -> dict:
        profile_file = self._profile_path(profile_path)
        workflow_paths = self._current_workflow_paths()
        missing_paths = [
            name for name, path in workflow_paths.items()
            if (name in REQUIRED_WORKFLOWS and not path) or (path and not Path(path).is_file())
        ]
        if missing_paths:
            raise ValueError("workflow files are missing: " + ", ".join(missing_paths))
        budget_issues = self._quality_budget_issues(self._current_quality_gates())
        if budget_issues:
            raise ValueError("generation quality budget is below production minimum: " + ", ".join(budget_issues))
        detected_capabilities = self._detect_workflow_capabilities(workflow_paths)
        caps = {
            name: bool((detected_capabilities.get(name) or {}).get("present")) and bool((capabilities or {}).get(name, True))
            for name in REQUIRED_CAPABILITIES
        }
        missing_capabilities = sorted(name for name in REQUIRED_CAPABILITIES if not caps.get(name))
        if missing_capabilities:
            raise ValueError("workflow capabilities are missing: " + ", ".join(missing_capabilities))
        video_contract = self._video_workflow_contract(workflow_paths.get("video", ""))
        if video_contract["missing_groups"]:
            raise ValueError(
                "video workflow quality placeholders are missing: "
                + ", ".join(video_contract["missing_groups"])
            )
        image_contract = self._image_workflow_contract(workflow_paths.get("image", ""))
        if image_contract["missing_groups"]:
            raise ValueError(
                "image workflow spatial placeholders are missing: "
                + ", ".join(image_contract["missing_groups"])
            )
        manifest = {
            "version": 1,
            "status": "approved",
            "name": "local_short_drama_high_quality",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "workflow_paths": workflow_paths,
            "workflow_hashes": {
                name: self._file_hash(Path(path))
                for name, path in workflow_paths.items()
                if path
            },
            "required_capabilities": sorted(REQUIRED_CAPABILITIES),
            "required_workflows": sorted(REQUIRED_WORKFLOWS),
            "required_image_pipeline_stages": REQUIRED_IMAGE_PIPELINE_STAGES,
            "required_video_workflow_placeholders": {
                name: sorted(values)
                for name, values in VIDEO_WORKFLOW_PLACEHOLDER_GROUPS.items()
            },
            "video_workflow_contract": video_contract,
            "required_image_workflow_placeholders": {
                name: sorted(values)
                for name, values in IMAGE_WORKFLOW_PLACEHOLDER_GROUPS.items()
            },
            "image_workflow_contract": image_contract,
            "capabilities": caps,
            "capability_evidence": detected_capabilities,
            "quality_gates": self._current_quality_gates(),
            "notes": notes,
        }
        write_json_atomic(profile_file, manifest)
        return manifest

    def validate_profile(self, profile_path: str | None = None) -> dict:
        profile_file = self._profile_path(profile_path)
        if not profile_file.is_file():
            return {
                "status": "missing",
                "path": str(profile_file),
                "missing": ["profile_file"],
                "required_capabilities": sorted(REQUIRED_CAPABILITIES),
                "required_workflows": sorted(REQUIRED_WORKFLOWS),
            }
        try:
            profile = json.loads(profile_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "invalid", "path": str(profile_file), "error": str(exc)}
        missing = []
        stale = []
        if profile.get("status") != "approved":
            missing.append("approved_status")
        if profile.get("required_image_pipeline_stages") != REQUIRED_IMAGE_PIPELINE_STAGES:
            stale.append("required_image_pipeline_stages")
        required_video_placeholders = {
            name: sorted(values)
            for name, values in VIDEO_WORKFLOW_PLACEHOLDER_GROUPS.items()
        }
        if profile.get("required_video_workflow_placeholders") != required_video_placeholders:
            stale.append("required_video_workflow_placeholders")
        required_image_placeholders = {
            name: sorted(values)
            for name, values in IMAGE_WORKFLOW_PLACEHOLDER_GROUPS.items()
        }
        if profile.get("required_image_workflow_placeholders") != required_image_placeholders:
            stale.append("required_image_workflow_placeholders")
        capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
        capability_evidence = profile.get("capability_evidence") if isinstance(profile.get("capability_evidence"), dict) else {}
        missing_capabilities = sorted(name for name in REQUIRED_CAPABILITIES if not capabilities.get(name))
        if missing_capabilities:
            missing.append("required_capabilities")
        current_workflow_capabilities = self._detect_workflow_capabilities(self._current_workflow_paths())
        for name in REQUIRED_CAPABILITIES:
            if not (current_workflow_capabilities.get(name) or {}).get("present"):
                if name not in missing_capabilities:
                    missing_capabilities.append(name)
                missing.append("required_workflow_capability_evidence")
            elif capability_evidence.get(name) != current_workflow_capabilities.get(name):
                stale.append(f"capability_evidence_{name}")
        workflow_paths = profile.get("workflow_paths") if isinstance(profile.get("workflow_paths"), dict) else {}
        workflow_hashes = profile.get("workflow_hashes") if isinstance(profile.get("workflow_hashes"), dict) else {}
        quality_gates = profile.get("quality_gates") if isinstance(profile.get("quality_gates"), dict) else {}
        current_quality_gates = self._current_quality_gates()
        for name, value in current_quality_gates.items():
            if quality_gates.get(name) != value:
                stale.append(f"quality_gate_{name}")
        low_budget = self._quality_budget_issues(quality_gates)
        if low_budget:
            missing.append("production_quality_budget")
        current_paths = self._current_workflow_paths()
        if workflow_paths.get("multi_reference") and not current_paths.get("multi_reference"):
            stale.append("multi_reference_path")
        current_video_contract = self._video_workflow_contract(current_paths.get("video", ""))
        stored_video_contract = profile.get("video_workflow_contract") if isinstance(profile.get("video_workflow_contract"), dict) else {}
        if current_video_contract.get("missing_groups"):
            missing.append("video_workflow_quality_placeholders")
        if stored_video_contract and stored_video_contract != current_video_contract:
            stale.append("video_workflow_contract")
        current_image_contract = self._image_workflow_contract(current_paths.get("image", ""))
        stored_image_contract = profile.get("image_workflow_contract") if isinstance(profile.get("image_workflow_contract"), dict) else {}
        if current_image_contract.get("missing_groups"):
            missing.append("image_workflow_spatial_placeholders")
        if stored_image_contract and stored_image_contract != current_image_contract:
            stale.append("image_workflow_contract")
        for name, current_path in current_paths.items():
            if name in REQUIRED_WORKFLOWS and not current_path:
                missing.append(f"{name}_workflow_path")
                continue
            stored_path = workflow_paths.get(name)
            if current_path != stored_path:
                stale.append(f"{name}_path")
            if current_path:
                path = Path(current_path)
                if not path.is_file():
                    missing.append(f"{name}_workflow_file")
                elif workflow_hashes.get(name) != self._file_hash(path):
                    stale.append(f"{name}_workflow_hash")
        status = "valid" if not missing and not stale else "blocked"
        return {
            "status": status,
            "path": str(profile_file),
            "missing": sorted(set(missing)),
            "stale": sorted(set(stale)),
            "missing_capabilities": missing_capabilities,
            "quality_budget_issues": low_budget,
            "video_workflow_contract": current_video_contract,
            "image_workflow_contract": current_image_contract,
            "minimum_quality_budget": {
                **MIN_QUALITY_BUDGET,
                "approved_quality_profiles": sorted(APPROVED_QUALITY_PROFILES),
                "video_end_frame_enabled": True,
                "required_image_pipeline_stages": REQUIRED_IMAGE_PIPELINE_STAGES,
                "required_video_workflow_placeholders": required_video_placeholders,
                "required_image_workflow_placeholders": required_image_placeholders,
            },
            "profile": profile,
        }

    def _current_workflow_paths(self) -> dict[str, str]:
        paths = {
            "image": self._resolve_path(settings.COMFYUI_WORKFLOW_PATH),
            "reference": self._resolve_path(settings.COMFYUI_REFERENCE_WORKFLOW_PATH),
            "video": self._resolve_path(settings.COMFYUI_VIDEO_WORKFLOW_PATH),
        }
        if settings.COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH:
            paths["multi_reference"] = self._resolve_path(settings.COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH)
        return paths

    def _profile_path(self, profile_path: str | None = None) -> Path:
        path = profile_path or settings.COMFYUI_PRODUCTION_PROFILE_PATH
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        return resolved

    def _resolve_path(self, path: str) -> str:
        if not path:
            return ""
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        return str(resolved)

    def _file_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _text_hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _current_quality_gates(self) -> dict:
        image_budget = image_quality_budget()
        video_budget = video_quality_budget()
        return {
            "image_min_score": settings.GENERATION_IMAGE_MIN_SCORE,
            "image_identity_min_score": settings.GENERATION_IMAGE_IDENTITY_MIN_SCORE,
            "image_platform_min_score": settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE,
            "image_aesthetic_feature_min_score": settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE,
            "turnaround_feature_min_score": settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE,
            "video_min_score": settings.GENERATION_VIDEO_MIN_SCORE,
            "video_identity_min_score": settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE,
            "character_identity_min_score": settings.GENERATION_CHARACTER_IDENTITY_MIN_SCORE,
            "character_identity_max_score_spread": settings.GENERATION_CHARACTER_IDENTITY_MAX_SCORE_SPREAD,
            "character_identity_min_observations": settings.GENERATION_CHARACTER_IDENTITY_MIN_OBSERVATIONS,
            "episode_style_brightness_warning": settings.GENERATION_EPISODE_STYLE_BRIGHTNESS_WARNING,
            "episode_style_brightness_blocker": settings.GENERATION_EPISODE_STYLE_BRIGHTNESS_BLOCKER,
            "episode_style_saturation_warning": settings.GENERATION_EPISODE_STYLE_SATURATION_WARNING,
            "episode_style_saturation_blocker": settings.GENERATION_EPISODE_STYLE_SATURATION_BLOCKER,
            "episode_style_contrast_warning": settings.GENERATION_EPISODE_STYLE_CONTRAST_WARNING,
            "episode_style_contrast_blocker": settings.GENERATION_EPISODE_STYLE_CONTRAST_BLOCKER,
            "episode_style_sharpness_ratio_warning": settings.GENERATION_EPISODE_STYLE_SHARPNESS_RATIO_WARNING,
            "episode_style_sharpness_ratio_blocker": settings.GENERATION_EPISODE_STYLE_SHARPNESS_RATIO_BLOCKER,
            "episode_style_aspect_ratio_warning": settings.GENERATION_EPISODE_STYLE_ASPECT_RATIO_WARNING,
            "episode_style_aspect_ratio_blocker": settings.GENERATION_EPISODE_STYLE_ASPECT_RATIO_BLOCKER,
            "rhythm_min_shot_seconds": settings.GENERATION_RHYTHM_MIN_SHOT_SECONDS,
            "rhythm_max_silent_shot_seconds": settings.GENERATION_RHYTHM_MAX_SILENT_SHOT_SECONDS,
            "rhythm_max_dialogue_margin_seconds": settings.GENERATION_RHYTHM_MAX_DIALOGUE_MARGIN_SECONDS,
            "rhythm_same_role_warning_run": settings.GENERATION_RHYTHM_SAME_ROLE_WARNING_RUN,
            "rhythm_max_hook_latency_seconds": settings.GENERATION_RHYTHM_MAX_HOOK_LATENCY_SECONDS,
            "video_temporal_min_score": settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE,
            "video_max_static_run_seconds": settings.GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS,
            "video_max_temporal_jump_ratio": settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO,
            "video_platform_min_score": settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE,
            "video_character_distinctiveness_min_score": settings.GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE,
            "video_aesthetic_feature_min_score": settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE,
            "video_performance_min_score": settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE,
            "video_audio_visual_alignment_min_score": settings.GENERATION_VIDEO_AUDIO_VISUAL_ALIGNMENT_MIN_SCORE,
            "seed_dance_baseline_regression_tolerance": settings.GENERATION_SEED_DANCE_BASELINE_REGRESSION_TOLERANCE,
            "image_review_required": settings.GENERATION_REQUIRE_IMAGE_REVIEW,
            "video_review_required": settings.GENERATION_REQUIRE_VIDEO_REVIEW,
            "image_postprocess_required": settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS,
            "image_postprocess_command_hash": self._text_hash(settings.GENERATION_IMAGE_POSTPROCESS_COMMAND)
            if settings.GENERATION_IMAGE_POSTPROCESS_COMMAND else "",
            "quality_profile": settings.GENERATION_QUALITY_PROFILE,
            "image_candidates": settings.GENERATION_IMAGE_CANDIDATES,
            "image_refinement_passes": settings.GENERATION_IMAGE_REFINEMENT_PASSES,
            "max_image_candidates": settings.GENERATION_MAX_IMAGE_CANDIDATES,
            "minimum_quality_passes": settings.GENERATION_MIN_QUALITY_PASSES,
            "repair_image_candidate_multiplier": settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER,
            "repair_extra_refinement_passes": settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES,
            "video_candidates": settings.GENERATION_VIDEO_CANDIDATES,
            "video_refinement_passes": settings.GENERATION_VIDEO_REFINEMENT_PASSES,
            "max_video_candidates": settings.GENERATION_MAX_VIDEO_CANDIDATES,
            "repair_video_candidate_multiplier": settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER,
            "effective_image_candidates": image_budget.candidate_count,
            "effective_image_refinement_passes": image_budget.refinement_passes,
            "effective_video_candidates": video_budget.candidate_count,
            "effective_video_refinement_passes": video_budget.refinement_passes,
            "video_end_frame_enabled": settings.GENERATION_VIDEO_END_FRAME_ENABLED,
            "video_output_node": settings.COMFYUI_VIDEO_OUTPUT_NODE,
            "video_target_seconds": settings.GENERATION_VIDEO_TARGET_SECONDS,
            "video_max_frames": settings.GENERATION_VIDEO_MAX_FRAMES,
            "video_max_freeze_seconds": settings.GENERATION_VIDEO_MAX_FREEZE_SECONDS,
            "video_model_fps": settings.GENERATION_VIDEO_MODEL_FPS,
            "video_output_fps": settings.GENERATION_VIDEO_OUTPUT_FPS,
            "width": settings.GENERATION_WIDTH,
            "height": settings.GENERATION_HEIGHT,
            "steps": settings.GENERATION_STEPS,
            "cfg": settings.GENERATION_CFG,
        }

    def _quality_budget_issues(self, quality_gates: dict) -> list[str]:
        issues = []
        for name, minimum in MIN_QUALITY_BUDGET.items():
            value = quality_gates.get(name)
            if not isinstance(value, (int, float)) or value < minimum:
                issues.append(f"{name}_below_{minimum}")
        if quality_gates.get("quality_profile") not in APPROVED_QUALITY_PROFILES:
            issues.append("quality_profile_not_production_approved")
        if quality_gates.get("video_end_frame_enabled") is not True:
            issues.append("video_end_frame_disabled")
        return issues

    def _detect_workflow_capabilities(self, workflow_paths: dict[str, str]) -> dict[str, dict]:
        class_names = []
        class_names_by_workflow = {}
        load_image_counts = {}
        for workflow_name, workflow_path in workflow_paths.items():
            classes = self._workflow_class_names(workflow_path)
            class_names_by_workflow[workflow_name] = classes
            class_names.extend(classes)
            load_image_counts[workflow_name] = sum(1 for class_name in classes if class_name.lower() == "loadimage")
        lower_classes = [class_name.lower() for class_name in class_names]
        evidence = {
            capability: self._capability_match(capability, lower_classes, class_names)
            for capability in REQUIRED_CAPABILITIES
        }
        video_classes = [class_name.lower() for class_name in class_names_by_workflow.get("video", [])]
        has_video_output = any(any(keyword in class_name for keyword in VIDEO_OUTPUT_KEYWORDS) for class_name in video_classes)
        first_last_ok = bool(
            has_video_output
            and settings.GENERATION_VIDEO_END_FRAME_ENABLED
            and load_image_counts.get("video", 0) >= 2
        )
        evidence["first_last_frame_video"] = {
            "present": first_last_ok,
            "matched_nodes": [
                class_name for class_name in class_names_by_workflow.get("video", [])
                if class_name.lower() == "loadimage" or any(keyword in class_name.lower() for keyword in VIDEO_OUTPUT_KEYWORDS)
            ],
            "requirement": "video workflow must load first and last frame images and emit video",
        }
        command = settings.GENERATION_IMAGE_POSTPROCESS_COMMAND.lower()
        if settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS and command:
            if any(term in command for term in ("face", "gfpgan", "codeformer")):
                evidence["face_repair"] = {
                    "present": True,
                    "matched_nodes": ["GENERATION_IMAGE_POSTPROCESS_COMMAND"],
                    "requirement": "face repair can be provided by a required postprocess command",
                }
            if any(term in command for term in ("upscale", "supir", "esrgan", "vsr")):
                evidence["upscale"] = {
                    "present": True,
                    "matched_nodes": ["GENERATION_IMAGE_POSTPROCESS_COMMAND"],
                    "requirement": "upscale can be provided by a required postprocess command",
                }
        return evidence

    def _workflow_class_names(self, workflow_path: str) -> list[str]:
        if not workflow_path:
            return []
        path = Path(workflow_path)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        nodes = data.get("nodes") if isinstance(data, dict) and isinstance(data.get("nodes"), dict) else data
        if not isinstance(nodes, dict):
            return []
        classes = []
        for node in nodes.values():
            if isinstance(node, dict) and node.get("class_type"):
                classes.append(str(node["class_type"]))
        return classes

    def _video_workflow_contract(self, workflow_path: str) -> dict:
        placeholders = sorted(self._workflow_placeholders(workflow_path))
        placeholder_set = set(placeholders)
        group_status = {
            name: bool(values & placeholder_set)
            for name, values in VIDEO_WORKFLOW_PLACEHOLDER_GROUPS.items()
        }
        return {
            "placeholders": placeholders,
            "groups": group_status,
            "missing_groups": sorted(name for name, present in group_status.items() if not present),
        }

    def _image_workflow_contract(self, workflow_path: str) -> dict:
        placeholders = sorted(self._workflow_placeholders(workflow_path))
        placeholder_set = set(placeholders)
        group_status = {
            name: bool(values & placeholder_set)
            for name, values in IMAGE_WORKFLOW_PLACEHOLDER_GROUPS.items()
        }
        return {
            "placeholders": placeholders,
            "groups": group_status,
            "missing_groups": sorted(name for name, present in group_status.items() if not present),
        }

    def _workflow_placeholders(self, workflow_path: str) -> set[str]:
        if not workflow_path:
            return set()
        path = Path(workflow_path)
        if not path.is_file():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return scan_placeholders(data)

    def _capability_match(self, capability: str, lower_classes: list[str], class_names: list[str]) -> dict:
        keywords = CAPABILITY_KEYWORDS.get(capability, ())
        matched = [
            class_names[index]
            for index, class_name in enumerate(lower_classes)
            if any(keyword in class_name for keyword in keywords)
        ]
        return {
            "present": bool(matched),
            "matched_nodes": sorted(set(matched)),
            "requirement": " or ".join(keywords),
        }
