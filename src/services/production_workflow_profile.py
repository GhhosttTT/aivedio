"""Approved ComfyUI workflow profile checks for production short-drama quality."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings


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
        caps = {name: bool((capabilities or {}).get(name, True)) for name in REQUIRED_CAPABILITIES}
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
            "quality_gates": {
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
                "image_review_required": settings.GENERATION_REQUIRE_IMAGE_REVIEW,
                "video_review_required": settings.GENERATION_REQUIRE_VIDEO_REVIEW,
                "image_postprocess_required": settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS,
                "image_postprocess_command_hash": self._text_hash(settings.GENERATION_IMAGE_POSTPROCESS_COMMAND)
                if settings.GENERATION_IMAGE_POSTPROCESS_COMMAND else "",
                "width": settings.GENERATION_WIDTH,
                "height": settings.GENERATION_HEIGHT,
                "steps": settings.GENERATION_STEPS,
                "cfg": settings.GENERATION_CFG,
            },
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
        missing_capabilities = sorted(name for name in REQUIRED_CAPABILITIES if not capabilities.get(name))
        if missing_capabilities:
            missing.append("required_capabilities")
        workflow_paths = profile.get("workflow_paths") if isinstance(profile.get("workflow_paths"), dict) else {}
        workflow_hashes = profile.get("workflow_hashes") if isinstance(profile.get("workflow_hashes"), dict) else {}
        quality_gates = profile.get("quality_gates") if isinstance(profile.get("quality_gates"), dict) else {}
        current_quality_gates = self._current_quality_gates()
        for name, value in current_quality_gates.items():
            if quality_gates.get(name) != value:
                stale.append(f"quality_gate_{name}")
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
            "image_review_required": settings.GENERATION_REQUIRE_IMAGE_REVIEW,
            "video_review_required": settings.GENERATION_REQUIRE_VIDEO_REVIEW,
            "image_postprocess_required": settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS,
            "image_postprocess_command_hash": self._text_hash(settings.GENERATION_IMAGE_POSTPROCESS_COMMAND)
            if settings.GENERATION_IMAGE_POSTPROCESS_COMMAND else "",
            "width": settings.GENERATION_WIDTH,
            "height": settings.GENERATION_HEIGHT,
            "steps": settings.GENERATION_STEPS,
            "cfg": settings.GENERATION_CFG,
        }
