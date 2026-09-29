"""Approved ComfyUI workflow profile checks for production short-drama quality."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.services.generation_quality_policy import image_quality_budget, video_quality_budget


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
            "capabilities": caps,
            "capability_evidence": detected_capabilities,
            "quality_gates": self._current_quality_gates(),
            "notes": notes,
        }
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
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
            "minimum_quality_budget": {
                **MIN_QUALITY_BUDGET,
                "approved_quality_profiles": sorted(APPROVED_QUALITY_PROFILES),
                "video_end_frame_enabled": True,
            },
            "profile": profile,
        }

    def _current_workflow_paths(self) -> dict[str, str]:
        return {
            "image": self._resolve_path(settings.COMFYUI_WORKFLOW_PATH),
            "reference": self._resolve_path(settings.COMFYUI_REFERENCE_WORKFLOW_PATH),
            "video": self._resolve_path(settings.COMFYUI_VIDEO_WORKFLOW_PATH),
        }

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
            "video_temporal_min_score": settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE,
            "video_platform_min_score": settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE,
            "video_aesthetic_feature_min_score": settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE,
            "video_performance_min_score": settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE,
            "image_review_required": settings.GENERATION_REQUIRE_IMAGE_REVIEW,
            "video_review_required": settings.GENERATION_REQUIRE_VIDEO_REVIEW,
            "image_postprocess_required": settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS,
            "image_postprocess_command_hash": self._text_hash(settings.GENERATION_IMAGE_POSTPROCESS_COMMAND)
            if settings.GENERATION_IMAGE_POSTPROCESS_COMMAND else "",
            "quality_profile": settings.GENERATION_QUALITY_PROFILE,
            "image_candidates": settings.GENERATION_IMAGE_CANDIDATES,
            "image_refinement_passes": settings.GENERATION_IMAGE_REFINEMENT_PASSES,
            "max_image_candidates": settings.GENERATION_MAX_IMAGE_CANDIDATES,
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
            "video_target_seconds": settings.GENERATION_VIDEO_TARGET_SECONDS,
            "video_max_frames": settings.GENERATION_VIDEO_MAX_FRAMES,
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
