"""Video generation Celery tasks."""

import shutil
import os
import json
import subprocess
from math import gcd
from pathlib import Path
from uuid import uuid4

from src.config import settings
from src.database.database import get_db
from src.database.models import Scene, Task, TaskStatus
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.generation_provider import (
    ImageGenerationRequest, VideoGenerationRequest, GenerationProviderError,
    GenerationCancelledError, get_generation_provider, release_generation_resources,
    _seedance_api_format, _seedance_model_is_10, _seedance_model_is_25,
    _seedance_model_supports_multimodal_references,
)
from src.services.image_workflow_graph import stage_seed
from src.services.comfyui_service import ComfyUIError, ComfyUIWaitTimeout
from src.services.generation_quality_policy import video_quality_budget, video_quality_pipeline, minimum_quality_passes
from src.services.generation_review import (
    GenerationReviewService,
    ReviewError,
    attach_platform_reference_gate,
    attach_video_aesthetic_gate,
    attach_video_character_distinctiveness_gate,
    attach_video_performance_gate,
    platform_video_score,
    write_report,
)
from src.services.repair_queue import attach_repair_queue, build_repair_queue
from src.services.svd_service import SVDError, get_svd_service
from src.services.video_quality_metrics import (
    video_boundary_continuity,
    video_candidate_metrics,
    video_start_frame_reference_metrics,
    video_technical_score,
)
from src.services.visual_style_assets import VisualStyleAssetService
from src.services.video_director_service import VideoShotPlan, get_video_director_service
from src.services.sequence_plan import build_sequence_context, build_sequence_timeline
from src.services.sequence_video_service import split_sequence_video
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_video_path

logger = get_logger(__name__)


def _configured_video_provider_name(kwargs: dict | None = None) -> str:
    kwargs = kwargs or {}
    return kwargs.get("provider") or settings.GENERATION_PROVIDER


def _setting_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _native_audio_enabled(provider_name: str, override=None) -> bool:
    """Resolve per-run native audio without dropping it during postprocess."""
    if provider_name not in {"seedance_api", "http_video_api"}:
        return False
    if override is not None:
        return _setting_enabled(override)
    prefix = "SEEDANCE" if provider_name == "seedance_api" else "HTTP_VIDEO"
    return bool(getattr(settings, f"{prefix}_NATIVE_AUDIO", False))


def _preserve_generated_audio(
    provider_name: str,
    override=None,
    multimodal_refs: dict | None = None,
) -> bool:
    """Keep audio during normalization when native or reference audio is requested."""
    return _native_audio_enabled(provider_name, override) or bool(
        isinstance(multimodal_refs, dict) and multimodal_refs.get("audios")
    )


def _provider_task_state_is_ambiguous(video_generator) -> bool:
    """Prevent a draft fallback from duplicating an accepted remote job."""
    metadata = getattr(video_generator, "last_result_metadata", None)
    if not isinstance(metadata, dict) or not metadata.get("provider_task_id"):
        return False
    status = str(metadata.get("provider_status") or metadata.get("provider_task_status") or "").lower()
    return status not in {"failed", "error", "cancelled", "canceled", "expired"}


def _draft_fallback_allowed(error: Exception, video_generator) -> bool:
    """Allow placeholders only for failures before a quality decision exists."""
    if isinstance(error, (ComfyUIWaitTimeout, GenerationCancelledError, ReviewError)):
        return False
    if _provider_task_state_is_ambiguous(video_generator):
        return False
    return draft_fallback_enabled()


def _configured_reference_limit(
    provider_name: str | None,
    suffix: str,
    default: int,
    model: str | None = None,
) -> int:
    """Resolve provider reference limits, including Ark 2.5's larger defaults."""
    prefix = {
        "seedance_api": "SEEDANCE",
        "http_video_api": "HTTP_VIDEO",
    }.get(provider_name, str(provider_name or "").upper())
    setting_name = f"{prefix}_{suffix}" if prefix else suffix
    value = os.getenv(setting_name)
    if value is not None:
        return max(0, int(value))
    configured = int(getattr(settings, setting_name, default))
    if provider_name == "seedance_api":
        effective_model = str(
            model
            or os.getenv("SEEDANCE_MODEL")
            or getattr(settings, "SEEDANCE_MODEL", "")
            or ""
        ).strip()
        is_25 = _seedance_model_is_25(effective_model)
        native_defaults = {
            "SEEDANCE_MAX_REFERENCE_IMAGES": 30,
            "SEEDANCE_MAX_REFERENCE_VIDEOS": 10,
            "SEEDANCE_MAX_REFERENCE_AUDIOS": 10,
        }
        if is_25 and configured == {"SEEDANCE_MAX_REFERENCE_IMAGES": 9,
                                    "SEEDANCE_MAX_REFERENCE_VIDEOS": 3,
                                    "SEEDANCE_MAX_REFERENCE_AUDIOS": 3}.get(setting_name):
            configured = native_defaults.get(setting_name, configured)
        if _seedance_model_is_10(effective_model) and configured == {
            "SEEDANCE_MAX_REFERENCE_IMAGES": 9,
            "SEEDANCE_MAX_REFERENCE_VIDEOS": 3,
            "SEEDANCE_MAX_REFERENCE_AUDIOS": 3,
        }.get(setting_name):
            configured = {
                "SEEDANCE_MAX_REFERENCE_IMAGES": 1,
                "SEEDANCE_MAX_REFERENCE_VIDEOS": 0,
                "SEEDANCE_MAX_REFERENCE_AUDIOS": 0,
            }.get(setting_name, configured)
    return max(0, configured)


def _bounded_multi_shot_plan(sequence_context: dict | None) -> list[dict]:
    """Convert bounded continuity context into a model-facing shot plan."""
    if not isinstance(sequence_context, dict):
        return []
    sequence_shots = sequence_context.get("sequence_shots")
    if isinstance(sequence_shots, list) and sequence_shots:
        source = [("sequence", shot) for shot in sequence_shots if isinstance(shot, dict)]
    else:
        source = [(key, sequence_context.get(key)) for key in ("previous", "current", "next")]
    shots = []
    for key, shot in source:
        if not isinstance(shot, dict):
            continue
        shots.append({
            "scene_number": shot.get("scene_number"),
            "role": shot.get("role") or "story_shot",
            "character": shot.get("character_name") or "",
            "visual": str(shot.get("visual_summary") or "")[:280],
            "dialogue": str(shot.get("dialogue") or "")[:180],
            "duration_seconds": shot.get("duration_seconds"),
            "transition": "continue from previous shot" if shots else "opening shot",
        })
    return shots


def _continuity_metadata_path(video_path: str | Path) -> Path:
    return Path(video_path).with_suffix(".continuity.json")


def _provider_metadata_path(video_path: str | Path) -> Path:
    return Path(video_path).with_suffix(".provider.json")


def _write_json_sidecar(path: Path, data: dict) -> None:
    """Publish a JSON sidecar atomically so recovery never reads half a file."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_provider_metadata(video_path: str | Path, metadata: dict | None) -> str | None:
    if not isinstance(metadata, dict) or not metadata:
        return None
    path = _provider_metadata_path(video_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_sidecar(path, metadata)
    return str(path)


def _normalization_duration_for_provider(
    provider_name: str,
    request_mode: str | None,
    multi_shot: bool | None,
    shot_plan: VideoShotPlan,
    quality_report: dict | None,
    sequence_level_multi_shot: bool = False,
    source_path: str | Path | None = None,
) -> float:
    """Preserve provider-selected long-form duration for multi-shot/extend jobs."""
    requested_mode = str(request_mode or "").strip().lower()
    long_form = bool(multi_shot) or requested_mode in {"multi_shot", "seedance_2_5", "2.5", "extend"}
    if provider_name == "seedance_api" and long_form and source_path:
        metrics = video_candidate_metrics(source_path)
        actual_duration = metrics.get("duration_seconds") if isinstance(metrics, dict) else None
        if isinstance(actual_duration, (int, float)) and float(actual_duration) > 0:
            return max(1.0, min(30.0, float(actual_duration)))
    if provider_name == "seedance_api" and long_form and isinstance(quality_report, dict):
        metadata = quality_report.get("selected_provider_metadata")
        if isinstance(metadata, dict):
            try:
                duration = float(
                    metadata.get("provider_duration_seconds")
                    or metadata.get("requested_duration_seconds")
                    or 0
                )
                if duration > 0:
                    return max(1.0, min(30.0, duration))
            except (TypeError, ValueError):
                pass
    if provider_name == "seedance_api" and sequence_level_multi_shot:
        return max(
            shot_plan.target_duration_seconds,
            min(30.0, float(getattr(settings, "SEEDANCE_MULTI_SHOT_DURATION_SECONDS", 30))),
        )
    return float(shot_plan.target_duration_seconds)


def _write_scene_continuity_metadata(video_path: str | Path, metadata: dict | None) -> str | None:
    """Persist a provider's public last-frame anchor beside the accepted clip."""
    if not isinstance(metadata, dict):
        return None
    last_frame = metadata.get("last_frame_url")
    last_frame_path = metadata.get("last_frame_path")
    if not (
        isinstance(last_frame, str) and last_frame.strip()
    ) and not (
        isinstance(last_frame_path, str) and Path(last_frame_path).is_file()
    ):
        return None
    path = _continuity_metadata_path(video_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_sidecar(path, {
        "last_frame_url": last_frame.strip() if isinstance(last_frame, str) and last_frame.strip() else None,
        "last_frame_path": last_frame_path if isinstance(last_frame_path, str) and Path(last_frame_path).is_file() else None,
        "source": metadata.get("endpoint"),
    })
    return str(path)


def _read_scene_continuity_reference(video_path: str | Path) -> str | None:
    path = _continuity_metadata_path(video_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    local_path = data.get("last_frame_path")
    if isinstance(local_path, str) and Path(local_path).is_file():
        return local_path
    value = data.get("last_frame_url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _extract_video_last_frame(video_path: str | Path) -> str | None:
    """Extract a local continuity anchor so Ark does not need an undocumented response field."""
    source = Path(video_path)
    if not source.is_file() or not shutil.which("ffmpeg"):
        return None
    output = source.with_name(f"{source.stem}.last_frame.png")
    temporary = output.with_name(f".{output.name}.part.png")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-sseof", "-0.08", "-i", str(source),
             "-frames:v", "1", str(temporary)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            return None
        temporary.replace(output)
        return str(output)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        temporary.unlink(missing_ok=True)


def _uses_configured_video_provider(provider_name: str) -> bool:
    return provider_name != "local_comfyui" or bool(settings.COMFYUI_VIDEO_WORKFLOW_PATH)


def _build_video_generator(
    scene: Scene,
    shot_plan: VideoShotPlan,
    provider_name: str,
    end_image: str | None,
    provider_options: dict | None = None,
    character_reference_bindings: list[dict] | None = None,
):
    if _uses_configured_video_provider(provider_name):
        return _ComfyVideoGenerator(
            scene,
            provider=get_generation_provider(provider_name),
            shot_plan=shot_plan,
            provider_options=provider_options,
            character_reference_bindings=character_reference_bindings,
        ).with_end_image(end_image)
    return get_svd_service()


def _aspect_ratio_for_size(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unknown"
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _append_terms(text: str | None, addition: str | None) -> str:
    parts = []
    seen = set()
    for value in (text, addition):
        for term in str(value or "").split(","):
            clean = term.strip()
            key = clean.lower()
            if clean and key not in seen:
                parts.append(clean)
                seen.add(key)
    return ", ".join(parts)


def _project_video_negative_prompt(scene: Scene, base_negative: str | None) -> str:
    project_id = getattr(scene, "project_id", None)
    if project_id is None:
        return base_negative or ""
    try:
        style_negative = VisualStyleAssetService().generation_negative_for_project(project_id)
    except Exception:
        style_negative = ""
    return _append_terms(base_negative, style_negative)


VIDEO_REPAIR_PROMPT_DIRECTIVES = {
    "lower_motion_and_regenerate_video": (
        "Keep the action controlled and cinematic: stable face, stable wardrobe, smooth continuous motion, "
        "no sudden camera jump, no identity drift, no body warping."
    ),
    "increase_motion_and_regenerate_video": (
        "Add a readable short-drama motion beat: clear body movement, visible reaction timing, subtle camera life, "
        "and no frozen still-image feeling."
    ),
    "regenerate_video_with_performance_direction": (
        "Strengthen short-drama acting performance: clear facial emotion readable on a phone screen, intentional eye line, "
        "visible reaction to dialogue, expressive but natural body language, and one readable action intent. "
        "When a locked scene keyframe is supplied, preserve its face, wardrobe, framing, lighting and opening composition exactly before motion begins."
    ),
    "refine_video_commercial_aesthetic": (
        "Repair the platform-reference gap against a premium Seed Dance-style vertical short-drama clip: "
        "make the first second scroll-stopping, keep the actor face intentionally cast and attractive, "
        "raise phone-frame value, improve set dressing and wardrobe polish, preserve premium lighting and clean color grade, "
        "stabilize temporal skin texture and micro-expression continuity, and keep the full motion commercially publishable."
    ),
    "refine_final_composition_finish": (
        "Unify the final episode finish: consistent exposure, skin tone, color grade, sharpness, subtitle integration, "
        "and one polished mobile short-drama look across all cuts."
    ),
}

VIDEO_REPAIR_NEGATIVE_DIRECTIVES = {
    "lower_motion_and_regenerate_video": (
        "identity drift, face morphing, body warping, flicker, random camera jump, unstable wardrobe"
    ),
    "increase_motion_and_regenerate_video": (
        "frozen still image, static pose only, lifeless motion, no body movement, slideshow"
    ),
    "regenerate_video_with_performance_direction": (
        "flat acting, dead eyes, unreadable emotion, no reaction to dialogue, stiff body language, random gesture"
    ),
    "refine_video_commercial_aesthetic": (
        "cheap filter, low-budget set, muddy lighting, washed-out color grade, cluttered frame, "
        "generic face casting, weak first impression, low mobile frame value, unfinished production design, "
        "unreadable face on phone screen, commercial aesthetic drop, waxy skin in motion, AI gloss, face morphing"
    ),
    "refine_final_composition_finish": (
        "exposure jump between cuts, skin tone mismatch, mixed color grade, sharpness mismatch, "
        "subtitle covering faces, unfinished generated-clip collage"
    ),
}


def _append_prompt_directive(text: str | None, directive: str | None) -> str:
    base = str(text or "").strip()
    addition = str(directive or "").strip()
    if not addition:
        return base
    if addition.lower() in base.lower():
        return base
    if not base:
        return addition
    return f"{base}. {addition}"


def _append_end_frame_target(prompt: str | None, end_frame_prompt: str | None) -> str:
    target = str(end_frame_prompt or "").strip()
    if not target:
        return prompt or ""
    return _append_prompt_directive(prompt, f"End frame target: {target}")


def _apply_video_repair_prompt(
    prompt: str | None,
    negative_prompt: str | None,
    repair_action: str | None,
) -> tuple[str, str]:
    if not repair_action:
        return prompt or "", negative_prompt or ""
    return (
        _append_prompt_directive(prompt, VIDEO_REPAIR_PROMPT_DIRECTIVES.get(repair_action)),
        _append_terms(negative_prompt, VIDEO_REPAIR_NEGATIVE_DIRECTIVES.get(repair_action)),
    )


class _ComfyVideoGenerator:
    def __init__(
        self,
        scene: Scene,
        provider=None,
        shot_plan: VideoShotPlan | None = None,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audios: list[str] | None = None,
        provider_options: dict | None = None,
        character_reference_bindings: list[dict] | None = None,
    ):
        self.scene = scene
        self.provider = provider or get_generation_provider("local_comfyui")
        self.provider_options = dict(provider_options or {})
        self.shot_plan = shot_plan
        self.reference_images = list(reference_images or [])
        self.continuity_reference_image: str | None = None
        self.reference_videos = list(reference_videos or [])
        self.reference_audios = list(reference_audios or [])
        self.sequence_context: dict | None = None
        self.character_reference_bindings = [
            dict(item) for item in (character_reference_bindings or []) if isinstance(item, dict)
        ]

    def generate_video(
        self,
        image_path: str,
        output_path: str,
        num_frames: int,
        fps: int,
        motion_bucket_id: int,
        noise_aug_strength: float,
    ) -> str:
        duration = (
            self.shot_plan.target_duration_seconds
            if self.shot_plan
            else max(1.0, num_frames / max(fps, 1))
        )
        duration_override = self._provider_setting("DURATION_SECONDS", "")
        has_duration_override = bool(str(duration_override).strip())
        try:
            if has_duration_override:
                duration = max(1.0, min(30.0, float(duration_override)))
        except (TypeError, ValueError):
            raise GenerationProviderError("DURATION_SECONDS must be a number between 1 and 30")
        request_mode = str(self._provider_setting("REQUEST_MODE", "reference_to_video")).strip().lower()
        # A per-run value must override the provider default. This distinction
        # matters when the environment enables Seedance 2.5 multi-shot but a
        # caller explicitly selects ordinary reference-to-video for one shot.
        explicit_multi_shot = self.provider_options.get("MULTI_SHOT")
        mode_requests_multi_shot = request_mode in {"multi_shot", "seedance_2_5", "2.5"}
        multi_shot = (
            _setting_enabled(explicit_multi_shot)
            if explicit_multi_shot is not None
            else mode_requests_multi_shot
        )
        # The UI exposes the checkbox as an explicit per-run control. Do not
        # silently ignore it just because the mode selector still says
        # ``reference``; normalize only reference-like modes and preserve the
        # meaning of edit/extend requests.
        if multi_shot and request_mode not in {"edit", "extend", "auto"}:
            request_mode = "multi_shot"
        if multi_shot and not has_duration_override:
            sequence_level_multi_shot = _setting_enabled(
                self._provider_setting("SEQUENCE_LEVEL_MULTI_SHOT", False)
            )
            if sequence_level_multi_shot:
                duration = max(
                    duration,
                    min(30.0, float(self._provider_setting("MULTI_SHOT_DURATION_SECONDS", 30))),
                )
        else:
            sequence_level_multi_shot = _setting_enabled(
                self._provider_setting("SEQUENCE_LEVEL_MULTI_SHOT", False)
            )
        prompt = (
            self.shot_plan.director_prompt
            if self.shot_plan
            else self.scene.image_prompt or self.scene.visual_description
        )
        if self.shot_plan:
            prompt = _append_end_frame_target(prompt, self.shot_plan.end_frame_prompt)
        negative_prompt = (
            self.shot_plan.negative_prompt
            if self.shot_plan
            else settings.GENERATION_QUALITY_NEGATIVE_APPEND
        )
        pipeline = video_quality_pipeline(
            self.shot_plan.as_dict() if self.shot_plan else None,
            getattr(self, "repair_action", None),
        )
        prompt = _append_prompt_directive(prompt, pipeline.prompt_directive)
        negative_prompt = _append_terms(negative_prompt, pipeline.negative_directive)
        prompt, negative_prompt = _apply_video_repair_prompt(
            prompt,
            negative_prompt,
            getattr(self, "repair_action", None),
        )
        negative_prompt = _project_video_negative_prompt(self.scene, negative_prompt)
        seed = stage_seed(
            self.scene.id,
            f"video:{Path(output_path).name}:{motion_bucket_id}:{noise_aug_strength:.4f}",
        )
        self.last_seed = seed
        shot_plan_payload = self.shot_plan.as_dict() if self.shot_plan else None
        if shot_plan_payload is not None and self.sequence_context:
            shot_plan_payload = {**shot_plan_payload, "sequence_context": self.sequence_context}
        if shot_plan_payload is not None and self.character_reference_bindings:
            shot_plan_payload = {
                **shot_plan_payload,
                "character_reference_bindings": self.character_reference_bindings,
            }
        if multi_shot and sequence_level_multi_shot and shot_plan_payload is not None:
            sequence_timeline = self.provider_options.get("SEQUENCE_TIMELINE")
            shot_plan_payload = {
                **shot_plan_payload,
                "multi_shot": True,
                "sequence_level": True,
                "shots": _bounded_multi_shot_plan(self.sequence_context),
            }
            if isinstance(sequence_timeline, list) and sequence_timeline:
                normalized_timeline = [
                    {
                        "scene_number": item.get("scene_number"),
                        "start_seconds": round(float(item.get("start_seconds", 0.0)), 3),
                        "end_seconds": round(float(item.get("end_seconds", 0.0)), 3),
                        "duration_seconds": round(float(item.get("duration_seconds", 0.0)), 3),
                    }
                    for item in sequence_timeline
                    if isinstance(item, dict)
                ]
                if normalized_timeline:
                    shot_plan_payload["sequence_timeline"] = normalized_timeline
                    timing_text = "; ".join(
                        f"scene {item['scene_number']} {item['start_seconds']:.3f}-{item['end_seconds']:.3f}s"
                        for item in normalized_timeline
                    )
                    prompt = (
                        f"{prompt}. Follow this exact sequence timing contract and make each scene a readable continuous beat: "
                        f"{timing_text}."
                    )
        elif multi_shot and shot_plan_payload is not None:
            shot_plan_payload = {
                **shot_plan_payload,
                "multi_shot": False,
                "sequence_level": False,
                "continuity_mode": "bounded_previous_current_next",
            }
        result = self.provider.generate_video(VideoGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            reference_image=image_path,
            end_image=getattr(self, "end_image", None),
            reference_images=self.reference_images or None,
            continuity_reference_image=self.continuity_reference_image,
            reference_videos=(None if request_mode == "extend" else self.reference_videos or None),
            extend_video=(self.reference_videos[0] if request_mode == "extend" and self.reference_videos else None),
            reference_audios=self.reference_audios or None,
            audio_path=self.reference_audios[0] if self.reference_audios else None,
            generate_audio=_setting_enabled(self._provider_setting("NATIVE_AUDIO", False)),
            return_last_frame=_setting_enabled(self._provider_setting("RETURN_LAST_FRAME", True)),
            camera_fixed=_setting_enabled(self._provider_setting("CAMERA_FIXED", False)),
            watermark=_setting_enabled(self._provider_setting("WATERMARK", False)),
            output_format=self._provider_setting("OUTPUT_FORMAT", "") or None,
            resolution=self._provider_setting("RESOLUTION", "") or None,
            model=self._provider_setting("MODEL", "") or None,
            request_mode=request_mode,
            draft=_setting_enabled(self._provider_setting("DRAFT", False)),
            draft_task_id=self._provider_setting("DRAFT_TASK_ID", "") or None,
            multi_shot=multi_shot,
            shot_plan=shot_plan_payload,
            output_path=output_path,
            duration_seconds=duration,
            width=settings.GENERATION_WIDTH,
            height=settings.GENERATION_HEIGHT,
            aspect_ratio=_aspect_ratio_for_size(settings.GENERATION_WIDTH, settings.GENERATION_HEIGHT),
            fps=fps,
            seed=seed,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            quality_mode=settings.GENERATION_QUALITY_PROFILE,
            repair_action=getattr(self, "repair_action", None),
            quality_pipeline=pipeline.as_dict(),
            local_task_id=self.provider_options.get("LOCAL_TASK_ID"),
            progress_callback=self.provider_options.get("PROGRESS_CALLBACK"),
            cancellation_check=self.provider_options.get("CANCELLATION_CHECK"),
        ))
        self.last_result_metadata = dict(result.metadata or {})
        return result.output_path

    def with_end_image(self, end_image: str | None):
        self.end_image = end_image
        return self

    def with_repair_action(self, repair_action: str | None):
        self.repair_action = repair_action
        return self

    def with_multimodal_references(
        self,
        *,
        images: list[str] | None = None,
        videos: list[str] | None = None,
        audios: list[str] | None = None,
        continuity_image: str | None = None,
    ):
        """Attach Seedance-style references without changing local workflows."""
        self.reference_images = list(images or [])
        self.reference_videos = list(videos or [])
        self.reference_audios = list(audios or [])
        self.continuity_reference_image = continuity_image
        return self

    def with_continuity_reference(self, image: str | None):
        self.continuity_reference_image = image
        return self

    def with_sequence_context(self, context: dict | None):
        self.sequence_context = context
        return self

    def with_character_reference_bindings(self, bindings: list[dict] | None):
        self.character_reference_bindings = [
            dict(item) for item in (bindings or []) if isinstance(item, dict)
        ]
        return self

    def _provider_setting(self, suffix: str, default):
        if suffix.lower() in {key.lower() for key in self.provider_options}:
            for key, value in self.provider_options.items():
                if key.lower() == suffix.lower():
                    return value
        provider_name = getattr(getattr(self.provider, "name", None), "value", "")
        prefix = "SEEDANCE" if provider_name == "seedance_api" else "HTTP_VIDEO"
        environment_name = f"{prefix}_{suffix}"
        if environment_name in os.environ:
            return os.environ[environment_name]
        return getattr(settings, f"{prefix}_{suffix}", default)

    def release_generation_resources(self):
        release_generation_resources(self.provider)


def _candidate_video_path(final_path: str | Path, index: int) -> str:
    path = Path(final_path)
    return str(path.with_name(f"{path.stem}.candidate_{index:02d}{path.suffix}"))


def _video_variant_params(base_motion: int, base_noise: float, index: int) -> tuple[int, float]:
    motion_offsets = [0, -12, 12, -24, 24, -36, 36, -48]
    noise_offsets = [0.0, 0.01, -0.005, 0.02, -0.01, 0.03, -0.015, 0.04]
    offset_index = (index - 1) % len(motion_offsets)
    motion = max(1, min(255, base_motion + motion_offsets[offset_index]))
    noise = max(0.0, min(1.0, base_noise + noise_offsets[offset_index]))
    return motion, noise


def _refined_video_base_params(motion: int, noise: float) -> tuple[int, float]:
    return max(1, int(motion * 0.72)), max(0.0, round(noise * 0.6, 4))


def _apply_video_repair_action(
    motion_bucket_id: int,
    noise_aug_strength: float,
    repair_action: str | None,
) -> tuple[int, float]:
    if repair_action == "lower_motion_and_regenerate_video":
        return (
            max(1, min(255, int(motion_bucket_id * 0.58))),
            max(0.0, min(1.0, round(noise_aug_strength * 0.45, 4))),
        )
    if repair_action == "increase_motion_and_regenerate_video":
        return (
            max(1, min(255, int(motion_bucket_id * 1.22))),
            max(0.0, min(1.0, round(max(noise_aug_strength * 1.15, noise_aug_strength + 0.006), 4))),
        )
    if repair_action == "regenerate_video_with_performance_direction":
        return (
            max(1, min(255, int(motion_bucket_id * 1.08))),
            max(0.0, min(1.0, round(max(noise_aug_strength * 1.08, noise_aug_strength + 0.004), 4))),
        )
    if repair_action == "refine_video_commercial_aesthetic":
        return (
            max(1, min(255, int(motion_bucket_id * 0.86))),
            max(0.0, min(1.0, round(max(noise_aug_strength * 0.65, noise_aug_strength - 0.008), 4))),
        )
    if repair_action == "refine_final_composition_finish":
        return (
            max(1, min(255, int(motion_bucket_id * 0.88))),
            max(0.0, min(1.0, round(max(noise_aug_strength * 0.78, noise_aug_strength - 0.003), 4))),
        )
    return motion_bucket_id, noise_aug_strength


def _scene_review_payload(scene: Scene, project_id: int | None = None, db=None) -> dict:
    visible_characters = []
    character_sheet_contract = {"prompt": "", "negative": "", "references": [], "identity_contrast_matrix": {}}
    style_service = VisualStyleAssetService()
    if project_id is not None and db is not None:
        from src.tasks.image_tasks import _character_sheet_generation_contract, _visible_character_payload
        visible_characters = _visible_character_payload(scene, project_id, db)
        character_sheet_contract = _character_sheet_generation_contract(visible_characters)
    shot_aesthetic_profile = style_service.shot_aesthetic_profile(
        scene,
        visible_count=len(visible_characters),
    )
    return {
        "scene_number": scene.scene_number,
        "description": scene.visual_description,
        "dialogue": scene.dialogue,
        "image_prompt": scene.image_prompt,
        "expected_image": scene.image_path,
        "visible_characters": visible_characters,
        "character_sheet_contract": character_sheet_contract["prompt"],
        "character_sheet_references": character_sheet_contract["references"],
        "identity_contrast_matrix": character_sheet_contract["identity_contrast_matrix"],
        "platform_aesthetic_contract": style_service.platform_aesthetic_contract(project_id),
        "shot_aesthetic_profile": shot_aesthetic_profile,
    }


def _visible_characters_for_scene(scene: Scene, project_id: int, db) -> list[dict]:
    from src.tasks.image_tasks import _visible_character_payload
    return _visible_character_payload(scene, project_id, db)


def _multimodal_references_for_scene(
    scene: Scene,
    project_id: int,
    db,
    provider_name: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    """Build deterministic references for providers that support multimodality.

    The approved keyframe is always first. Frozen character-sheet views follow
    it, so an external provider can bind the scene layout as ``Image1`` and
    identity anchors as ``Image2...``. The previous accepted shot is supplied
    as a motion/continuity reference when available; local providers simply
    ignore the extra fields.
    """
    scene_payload = _scene_review_payload(scene, project_id, db)
    supports_multimodal = (
        provider_name != "seedance_api"
        or _seedance_model_supports_multimodal_references(model)
    )
    images = [str(scene.image_path)] if scene.image_path else []
    for item in scene_payload.get("character_sheet_references", []):
        path = item.get("path") if isinstance(item, dict) else None
        if path and path not in images and Path(path).is_file():
            images.append(path)

    previous = db.query(Scene).filter(
        Scene.project_id == project_id,
        Scene.scene_number < scene.scene_number,
        Scene.video_path.isnot(None),
    ).order_by(Scene.scene_number.desc()).first()
    videos = []
    if supports_multimodal and previous and previous.video_path:
        previous_video = str(previous.video_path)
        local_video = Path(previous_video).is_file()
        media_template = str(
            os.getenv("SEEDANCE_MEDIA_URL_TEMPLATE")
            or getattr(settings, "SEEDANCE_MEDIA_URL_TEMPLATE", "")
            or ""
        ).strip()
        seedance_endpoint = str(
            os.getenv("SEEDANCE_ENDPOINT")
            or getattr(settings, "SEEDANCE_ENDPOINT", "")
            or ""
        ).strip()
        native_ark = (
            provider_name == "seedance_api"
            and _seedance_api_format(seedance_endpoint) in {
                "ark", "ark_v3", "volcengine", "volcengine_v3",
            }
        )
        if (
            native_ark
            and local_video
            and not media_template
        ):
            logger.warning(
                "Skipping local previous-shot video reference for native Seedance; "
                "configure SEEDANCE_MEDIA_URL_TEMPLATE to send motion references"
            )
        elif local_video or previous_video.startswith(("http://", "https://", "asset://")):
            videos = [previous_video]
    continuity_image = (
        _read_scene_continuity_reference(previous.video_path)
        if supports_multimodal and previous and previous.video_path
        else None
    )
    # Older clips and non-Ark providers may not have persisted a continuity
    # sidecar. Extract the accepted clip's actual tail frame on demand so a
    # later shot does not silently lose its visual anchor after a restart.
    if supports_multimodal and not continuity_image and previous and previous.video_path and Path(previous.video_path).is_file():
        continuity_image = _extract_video_last_frame(previous.video_path)
        if continuity_image:
            _write_scene_continuity_metadata(
                previous.video_path,
                {"last_frame_path": continuity_image, "source": "local_ffmpeg_fallback"},
            )
    audios = (
        [str(scene.audio_path)]
        if supports_multimodal and scene.audio_path and Path(scene.audio_path).is_file()
        else []
    )
    if not supports_multimodal:
        # Seedance 1.0 accepts a single image/frame contract, not the
        # 2.x omni-reference roles. It can still follow multi-shot narrative
        # instructions in the prompt, so keep that control surface while
        # retaining only the approved keyframe for the native input contract.
        images = images[:1]
    return {
        "images": images[: max(1, _configured_reference_limit(provider_name, "MAX_REFERENCE_IMAGES", 9, model))],
        "continuity_image": continuity_image,
        "videos": videos[: _configured_reference_limit(provider_name, "MAX_REFERENCE_VIDEOS", 3, model)],
        "audios": audios[: _configured_reference_limit(provider_name, "MAX_REFERENCE_AUDIOS", 3, model)],
    }


def _character_reference_bindings_for_scene(
    scene: Scene,
    project_id: int,
    db,
    multimodal_refs: dict[str, object],
) -> list[dict]:
    """Bind approved character-sheet files to the exact provider image index."""
    return _character_reference_bindings_for_scenes(
        [scene], project_id, db, multimodal_refs,
    )


def _character_reference_bindings_for_scenes(
    scenes: list[Scene],
    project_id: int,
    db,
    multimodal_refs: dict[str, object],
) -> list[dict]:
    """Bind all sequence character-sheet files to exact provider image indexes."""
    image_paths = [str(path) for path in (multimodal_refs.get("images") or [])]
    if len(image_paths) < 2:
        return []
    bindings = []
    seen: set[tuple[int, str]] = set()
    for scene in scenes:
        payload = _scene_review_payload(scene, project_id, db)
        for item in payload.get("character_sheet_references", []):
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not path or str(path) not in image_paths:
                continue
            expected = item.get("expected_features")
            image_index = image_paths.index(str(path)) + 1
            name = str(item.get("name") or "character").strip()
            key = (image_index, name)
            if key in seen:
                continue
            seen.add(key)
            binding = {
                "image_index": image_index,
                "character_name": name,
                "view": str(item.get("view") or "front").strip(),
            }
            if isinstance(expected, dict):
                binding["expected_features"] = {
                    str(key): str(value) for key, value in expected.items() if str(value or "").strip()
                }
            bindings.append(binding)
    return bindings


def _multimodal_references_for_sequence(
    scenes: list[Scene],
    project_id: int,
    db,
    provider_name: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    """Bind the complete sequence asset pack to one provider request.

    A sequence-level request must not silently fall back to the first scene's
    references. The provider still receives bounded lists, but every atomic
    shot gets a chance to contribute its approved keyframe and dialogue audio.
    """
    supports_multimodal = (
        provider_name != "seedance_api"
        or _seedance_model_supports_multimodal_references(model)
    )
    shot_images: list[str] = []
    identity_images: list[str] = []
    audios: list[str] = []
    for scene in scenes:
        if scene.image_path and Path(scene.image_path).is_file() and scene.image_path not in shot_images:
            shot_images.append(str(scene.image_path))
        payload = _scene_review_payload(scene, project_id, db)
        for item in payload.get("character_sheet_references", []):
            path = item.get("path") if isinstance(item, dict) else None
            if path and Path(path).is_file() and path not in shot_images and path not in identity_images:
                identity_images.append(path)
        if supports_multimodal and scene.audio_path and Path(scene.audio_path).is_file():
            audios.append(str(scene.audio_path))

    if not supports_multimodal:
        shot_images = shot_images[:1]
        identity_images = []

    return {
        "images": (shot_images + identity_images)[: max(1, _configured_reference_limit(provider_name, "MAX_REFERENCE_IMAGES", 9, model))],
        "continuity_image": None,
        "videos": [],
        "audios": audios[: _configured_reference_limit(provider_name, "MAX_REFERENCE_AUDIOS", 3, model)] if supports_multimodal else [],
    }


def _sequence_context_for_scene(scene: Scene, project_id: int, db) -> dict:
    scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
    return build_sequence_context(
        scenes,
        scene.scene_number,
        sequence_id=f"project-{project_id}",
    ).as_dict()


def _scene_end_frame_path(project_id: int, scene_id: int) -> str:
    from src.utils.storage import storage_manager
    path = storage_manager.get_image_path(project_id, scene_id, f"scene_{scene_id}_end.png")
    return str(path)


def _generate_end_frame(
    scene: Scene, project_id: int, shot_plan: VideoShotPlan, provider=None,
    scene_payload: dict | None = None,
) -> str:
    provider = provider or get_generation_provider("local_comfyui")
    output_path = _scene_end_frame_path(project_id, scene.id)
    payload = {
        **(scene_payload or {}),
        "scene_number": scene.scene_number,
        "visual_description": shot_plan.end_frame_prompt,
        "dialogue": scene.dialogue,
        "stage": "end_frame",
    }
    references = payload.get("character_sheet_references") or []
    request = ImageGenerationRequest(
        prompt=shot_plan.end_frame_prompt,
        negative_prompt=shot_plan.negative_prompt,
        output_path=output_path,
        width=settings.GENERATION_WIDTH,
        height=settings.GENERATION_HEIGHT,
        steps=settings.GENERATION_STEPS,
        cfg_scale=settings.GENERATION_CFG,
        seed=stage_seed(scene.id, f"end_frame:{shot_plan.shot_role}"),
        reference_image=scene.image_path,
        use_ipadapter=bool(scene.image_path and settings.COMFYUI_REFERENCE_WORKFLOW_PATH),
        quality_mode=settings.GENERATION_QUALITY_PROFILE,
        character_references=references if len(references) > 1 else None,
    )
    from src.tasks.image_tasks import _generate_quality_candidates
    path, _quality = _generate_quality_candidates(provider, request, payload, scene.image_path)
    return path


def _reference_for_scene(scene: Scene, project_id: int, db) -> str | None:
    from src.tasks.image_tasks import _get_reference_image, _visual_character
    character = _visual_character(scene, project_id, db)
    if not character:
        return None
    return _get_reference_image(character, project_id) or scene.image_path


def _sequence_segment_quality_report(
    scene: Scene,
    segment_path: str,
    project_id: int,
    db,
    provider_metadata: dict,
) -> dict:
    """Review each atomic clip published from a sequence-level generation.

    Sequence generation has one provider request, but composition consumes
    atomic scene files. Each published file therefore needs its own technical
    metrics and final VLM review; otherwise a bad cut can inherit the
    sequence-level pass for the first scene.
    """
    base_report = {
        "kind": "video_candidate_selection",
        "status": "passed",
        "selected_provider_metadata": dict(provider_metadata or {}),
    }
    if settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return _review_final_video_after_postprocess(
            segment_path,
            scene,
            project_id,
            db,
            quality_report=base_report,
            reference=_reference_for_scene(scene, project_id, db),
        )

    metrics = video_candidate_metrics(segment_path)
    metrics["start_frame_reference"] = video_start_frame_reference_metrics(
        segment_path,
        scene.image_path,
    )
    _apply_audio_quality_contract(metrics, provider_metadata)
    error = None
    if metrics.get("status") != "available":
        error = "sequence segment technical metrics are unavailable"
    elif (
        isinstance(metrics.get("max_black_run_seconds"), (int, float))
        and metrics["max_black_run_seconds"] > settings.GENERATION_VIDEO_MAX_BLACK_SECONDS
    ):
        error = "sequence segment contains an excessive black-frame run"
    elif (
        metrics.get("audio_expected") is True
        and metrics.get("audio_quality_status") != "passed"
    ):
        error = "sequence segment native-audio contract did not pass"
    elif (
        isinstance(metrics.get("start_frame_reference"), dict)
        and metrics["start_frame_reference"].get("status") == "available"
        and metrics["start_frame_reference"].get("score", 5.0)
        < settings.GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE
    ):
        error = "sequence segment opening frame reference did not pass"
    report = {
        **base_report,
        "status": "needs_review" if error else "passed",
        "technical_metrics": metrics,
        "error": error,
    }
    write_report(Path(segment_path).with_suffix(".quality.json"), report)
    return report


def _promote_sequence_sidecar(staging_path: Path, output_path: Path, suffix: str) -> None:
    """Move a staged quality sidecar and update its published media paths."""
    source = staging_path.with_suffix(suffix)
    if not source.is_file():
        return
    destination = output_path.with_suffix(suffix)
    source.replace(destination)
    if suffix not in {".quality.json", ".final_review.json"}:
        return
    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("path", "review_path"):
                value = payload.get(key)
                if value == str(staging_path):
                    payload[key] = str(output_path)
                elif value == str(staging_path.with_suffix(".final_review.json")):
                    payload[key] = str(output_path.with_suffix(".final_review.json"))
            _write_json_sidecar(destination, payload)
    except (OSError, TypeError, ValueError):
        logger.warning("Could not update promoted sequence quality sidecar: {}", destination)


def _publish_sequence_artifacts_atomically(
    staging_paths: list[Path],
    output_paths: list[Path],
) -> None:
    """Publish sequence clips and their reports as one recoverable batch."""
    if len(staging_paths) != len(output_paths):
        raise ValueError("Sequence staging and output batches must have equal sizes")
    pairs: list[tuple[Path, Path]] = []
    for staging_path, output_path in zip(staging_paths, output_paths):
        if not staging_path.is_file():
            raise FileNotFoundError(f"Missing staged sequence clip: {staging_path}")
        pairs.append((staging_path, output_path))
        for suffix in (".quality.json", ".final_review.json"):
            source = staging_path.with_suffix(suffix)
            if not source.is_file():
                continue
            destination = output_path.with_suffix(suffix)
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for key in ("path", "review_path"):
                        value = payload.get(key)
                        if value == str(staging_path):
                            payload[key] = str(output_path)
                        elif value == str(staging_path.with_suffix(".final_review.json")):
                            payload[key] = str(output_path.with_suffix(".final_review.json"))
                    _write_json_sidecar(source, payload)
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid staged sequence sidecar: {source}") from exc
            pairs.append((source, destination))

    backups: list[tuple[Path, Path]] = []
    promoted: list[Path] = []
    try:
        for source, destination in pairs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = destination.with_name(f".{destination.name}.{uuid4().hex}.bak")
                destination.replace(backup)
                backups.append((backup, destination))
            source.replace(destination)
            promoted.append(destination)
    except Exception as exc:
        for destination in reversed(promoted):
            destination.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            if backup.exists():
                backup.replace(destination)
        raise RuntimeError(f"Could not publish the complete sequence batch: {exc}") from exc
    finally:
        for backup, destination in backups:
            if backup.exists() and destination.exists():
                backup.unlink(missing_ok=True)


def _review_score_from_batch(batch: dict, key: str) -> float | None:
    value = (batch.get("review") or {}).get(key)
    if isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
        return float(value["score"])
    return None


def _video_gate_scores(review_report: dict) -> dict[str, float]:
    batches = review_report.get("batches") or []
    scores: dict[str, list[float]] = {
        "facial_identity": [],
        "identity_consistency": [],
        "temporal_consistency": [],
    }
    for batch in batches:
        for key in scores:
            score = _review_score_from_batch(batch, key)
            if score is not None:
                scores[key].append(score)
    return {key: min(values) for key, values in scores.items() if values}


def _video_gate_evidence_complete(review_report: dict) -> bool:
    """Require identity and temporal evidence in every VLM review batch."""
    batches = review_report.get("batches") or []
    if not batches:
        return False
    required = {"facial_identity", "identity_consistency", "temporal_consistency"}
    for batch in batches:
        review = batch.get("review") if isinstance(batch, dict) else None
        if not isinstance(review, dict) or not required.issubset(review):
            return False
        for key in required:
            value = review.get(key)
            if not isinstance(value, dict) or not isinstance(value.get("score"), (int, float)):
                return False
    return True


def _video_platform_score(review_report: dict) -> float | None:
    scores = []
    for batch in review_report.get("batches") or []:
        attach_video_aesthetic_gate(batch)
        attach_platform_reference_gate(batch)
        if isinstance(batch.get("platform_score"), (int, float)):
            scores.append(float(batch["platform_score"]))
            continue
        review = batch.get("review") if isinstance(batch.get("review"), dict) else {}
        score = platform_video_score(review)
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return round(min(scores), 2)


def _video_aesthetic_gate_summary(review_report: dict) -> dict | None:
    gates = [
        batch.get("video_aesthetic_gate")
        for batch in review_report.get("batches") or []
        if isinstance(batch.get("video_aesthetic_gate"), dict)
    ]
    if not gates:
        return None
    failed = [gate for gate in gates if gate.get("status") != "passed"]
    selected = failed[0] if failed else min(gates, key=lambda item: item.get("average", 5))
    return {
        "status": "needs_review" if failed else "passed",
        "min_score": selected.get("min_score"),
        "average": selected.get("average"),
        "low": selected.get("low", {}),
        "missing": selected.get("missing", []),
    }


def _platform_reference_gate_summary(review_report: dict) -> dict | None:
    for batch in review_report.get("batches") or []:
        if isinstance(batch, dict) and "platform_reference_gate" not in batch:
            attach_platform_reference_gate(batch)
    gates = [
        batch.get("platform_reference_gate")
        for batch in review_report.get("batches") or []
        if isinstance(batch.get("platform_reference_gate"), dict)
    ]
    if not gates:
        return None
    failed = [gate for gate in gates if gate.get("status") != "passed"]
    selected = failed[0] if failed else min(gates, key=lambda item: item.get("average", 5))
    return {
        "status": "needs_review" if failed else "passed",
        "min_score": selected.get("min_score"),
        "average": selected.get("average"),
        "low": selected.get("low", {}),
        "missing": selected.get("missing", []),
    }


def _video_character_distinctiveness_gate_summary(review_report: dict, scene: dict | None = None) -> dict | None:
    scene = scene or review_report.get("scene") or {}
    for batch in review_report.get("batches") or []:
        if isinstance(batch, dict) and "character_distinctiveness_gate" not in batch:
            attach_video_character_distinctiveness_gate(batch, scene)
    gates = [
        batch.get("character_distinctiveness_gate")
        for batch in review_report.get("batches") or []
        if isinstance(batch.get("character_distinctiveness_gate"), dict)
    ]
    if not gates:
        return None
    failed = [gate for gate in gates if gate.get("status") != "passed"]
    selected = failed[0] if failed else min(gates, key=lambda item: item.get("average", 5))
    return {
        "status": "needs_review" if failed else "passed",
        "min_score": selected.get("min_score"),
        "average": selected.get("average"),
        "low": selected.get("low", {}),
        "missing": selected.get("missing", []),
    }


def _video_performance_gate_summary(review_report: dict, scene: dict | None = None) -> dict | None:
    scene = scene or review_report.get("scene") or {}
    for batch in review_report.get("batches") or []:
        if isinstance(batch, dict) and "video_performance_gate" not in batch:
            attach_video_performance_gate(batch, scene)
    gates = [
        batch.get("video_performance_gate")
        for batch in review_report.get("batches") or []
        if isinstance(batch.get("video_performance_gate"), dict)
    ]
    if not gates:
        return None
    failed = [gate for gate in gates if gate.get("status") != "passed"]
    selected = failed[0] if failed else min(gates, key=lambda item: item.get("average", 5))
    return {
        "status": "needs_review" if failed else "passed",
        "min_score": selected.get("min_score"),
        "average": selected.get("average"),
        "low": selected.get("low", {}),
        "missing": selected.get("missing", []),
    }


def _video_aesthetic_gate_passes(candidate: dict) -> bool:
    gate = candidate.get("video_aesthetic_gate")
    if not isinstance(gate, dict):
        return not settings.GENERATION_REQUIRE_VIDEO_REVIEW
    return gate.get("status") == "passed"


def _platform_reference_gate_passes(candidate: dict) -> bool:
    gate = candidate.get("platform_reference_gate")
    if not isinstance(gate, dict):
        return not settings.GENERATION_REQUIRE_VIDEO_REVIEW
    return gate.get("status") == "passed"


def _video_character_distinctiveness_gate_passes(candidate: dict) -> bool:
    gate = candidate.get("character_distinctiveness_gate")
    if not isinstance(gate, dict):
        return True
    return gate.get("status") == "passed"


def _video_performance_gate_passes(candidate: dict) -> bool:
    gate = candidate.get("video_performance_gate")
    if not isinstance(gate, dict):
        return True
    return gate.get("status") == "passed"


def _video_gate_passes(candidate: dict) -> tuple[bool, dict[str, float]]:
    scores = candidate.get("gate_scores") or {}
    if not scores:
        return (not settings.GENERATION_REQUIRE_VIDEO_REVIEW), {}
    if settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        if candidate.get("gate_evidence_complete") is False:
            return False, scores
        required = {"facial_identity", "identity_consistency", "temporal_consistency"}
        if not required.issubset(scores):
            return False, scores
    identity_min = settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE
    temporal_min = settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE
    identity_ok = all(
        scores.get(key, identity_min) >= identity_min
        for key in ("facial_identity", "identity_consistency")
    )
    temporal_ok = scores.get("temporal_consistency", temporal_min) >= temporal_min
    return identity_ok and temporal_ok, scores


def _attach_video_technical_metrics(candidate: dict) -> None:
    if not candidate.get("path"):
        return
    metrics = (
        candidate.get("technical_metrics")
        if isinstance(candidate.get("technical_metrics"), dict)
        else video_candidate_metrics(candidate["path"])
    )
    request = candidate.get("request") if isinstance(candidate.get("request"), dict) else {}
    reference_image = request.get("image_path") or request.get("reference_image")
    if reference_image and "start_frame_reference" not in metrics:
        metrics["start_frame_reference"] = video_start_frame_reference_metrics(
            candidate["path"], reference_image,
        )
    if _is_long_form_shot_plan(candidate.get("shot_plan")) and metrics.get("status") == "available":
        metrics["technical_score"] = video_technical_score(
            metrics,
            duration_low=4.0,
            duration_high=30.0,
            duration_soft_low=2.0,
            duration_soft_high=32.0,
        )
    _apply_audio_quality_contract(metrics, candidate.get("provider_metadata"))
    candidate["technical_metrics"] = metrics
    if isinstance(metrics.get("technical_score"), (int, float)):
        candidate["technical_score"] = float(metrics["technical_score"])


def _apply_audio_quality_contract(metrics: dict, provider_metadata: dict | None) -> dict:
    """Score presence and duration alignment when the provider requested audio."""
    audio_expected = bool(
        isinstance(provider_metadata, dict)
        and (
            provider_metadata.get("requested_generate_audio") is True
            or provider_metadata.get("requested_reference_audio") is True
        )
    )
    if not audio_expected:
        return metrics
    metrics["audio_expected"] = True
    if not metrics.get("audio_present"):
        metrics["audio_quality_status"] = "missing"
        metrics["audio_sync_score"] = 0.0
    elif not isinstance(metrics.get("audio_duration_delta_seconds"), (int, float)):
        # A present stream with no measurable duration cannot prove sync.
        # Do not turn an ffprobe blind spot into a false production pass.
        metrics["audio_quality_status"] = "unavailable"
        metrics["audio_sync_score"] = 0.0
    else:
        delta = float(metrics["audio_duration_delta_seconds"])
        metrics["audio_quality_status"] = "passed" if delta <= 0.35 else "needs_review"
        metrics["audio_sync_score"] = round(max(0.0, 5.0 - min(delta / 0.35, 5.0)), 2)
    start_delta = metrics.get("audio_video_start_delta_seconds")
    if isinstance(start_delta, (int, float)):
        start_delta = abs(float(start_delta))
        metrics["audio_video_start_delta_seconds"] = round(start_delta, 3)
        if start_delta > 0.35:
            metrics["audio_quality_status"] = "needs_review"
            metrics["audio_sync_score"] = 0.0
            metrics["audio_sync_error"] = (
                "audio/video stream start offset exceeds 0.350s: "
                f"{start_delta:.3f}s"
            )
        elif isinstance(metrics.get("audio_sync_score"), (int, float)):
            metrics["audio_sync_score"] = round(min(
                float(metrics["audio_sync_score"]),
                max(0.0, 5.0 - start_delta / 0.35 * 5.0),
            ), 2)
    signal_status = metrics.get("audio_signal_status")
    if signal_status == "near_silent":
        metrics["audio_quality_status"] = "needs_review"
        metrics["audio_signal_error"] = (
            "audio stream is present but contains near-silence; generated dialogue/audio cannot be trusted"
        )
        metrics["audio_sync_score"] = 0.0
    elif signal_status == "unavailable":
        metrics["audio_quality_status"] = "unavailable"
        metrics["audio_sync_score"] = 0.0
    if isinstance(metrics.get("technical_score"), (int, float)):
        metrics["technical_score"] = round(min(
            float(metrics["technical_score"]),
            float(metrics["audio_sync_score"]),
        ), 2)
    return metrics


def _is_long_form_shot_plan(shot_plan) -> bool:
    return isinstance(shot_plan, dict) and shot_plan.get("multi_shot") is True


def _quality_report_has_long_form(quality_report: dict) -> bool:
    candidates = quality_report.get("candidates") if isinstance(quality_report, dict) else None
    return any(
        _is_long_form_shot_plan(candidate.get("shot_plan"))
        for candidate in (candidates or [])
        if isinstance(candidate, dict)
    )


def _candidate_gate_average(candidate: dict, key: str) -> float | None:
    gate = candidate.get(key)
    if isinstance(gate, dict) and isinstance(gate.get("average"), (int, float)):
        return float(gate["average"])
    return None


def _video_critical_floor_score(candidate: dict) -> float | None:
    scores: list[float] = []
    gate_scores = candidate.get("gate_scores") if isinstance(candidate.get("gate_scores"), dict) else {}
    for key in ("facial_identity", "identity_consistency", "temporal_consistency"):
        value = gate_scores.get(key)
        if isinstance(value, (int, float)):
            scores.append(float(value))
    for key in ("video_aesthetic_gate", "platform_reference_gate", "character_distinctiveness_gate", "video_performance_gate"):
        value = _candidate_gate_average(candidate, key)
        if value is not None:
            scores.append(value)
    platform_score = candidate.get("platform_score")
    if isinstance(platform_score, (int, float)):
        scores.append(float(platform_score))
    if not scores:
        return None
    return min(scores)


def _video_selection_score(candidate: dict) -> float:
    platform_score = candidate.get("platform_score")
    average = candidate.get("average")
    technical_score = candidate.get("technical_score")
    distinctiveness_score = candidate.get("character_distinctiveness_score")
    performance_score = candidate.get("video_performance_score")
    aesthetic_score = _candidate_gate_average(candidate, "video_aesthetic_gate")
    reference_score = _candidate_gate_average(candidate, "platform_reference_gate")
    critical_floor_score = _video_critical_floor_score(candidate)
    if not isinstance(platform_score, (int, float)):
        platform_score = average if isinstance(average, (int, float)) else 0.0
    if not isinstance(average, (int, float)):
        average = platform_score
    if not isinstance(technical_score, (int, float)):
        technical_score = platform_score
    if not isinstance(distinctiveness_score, (int, float)):
        distinctiveness_score = platform_score
    if not isinstance(performance_score, (int, float)):
        performance_score = platform_score
    if not isinstance(aesthetic_score, (int, float)):
        aesthetic_score = platform_score
    if not isinstance(reference_score, (int, float)):
        reference_score = platform_score
    if not isinstance(critical_floor_score, (int, float)):
        critical_floor_score = min(
            float(value)
            for value in (platform_score, average, technical_score, distinctiveness_score, performance_score)
            if isinstance(value, (int, float))
        )
    return round(
        max(0.0, min(
            5.0,
            float(platform_score) * 0.16
            + float(average) * 0.10
            + float(technical_score) * 0.07
            + float(distinctiveness_score) * 0.14
            + float(performance_score) * 0.14
            + float(aesthetic_score) * 0.04
            + float(reference_score) * 0.15
            + float(critical_floor_score) * 0.20,
        )),
        2,
    )


def _review_final_video_after_postprocess(
    video_path: str,
    scene: Scene,
    project_id: int,
    db,
    *,
    quality_report: dict,
    reference: str | None = None,
    shot_plan: VideoShotPlan | None = None,
) -> dict:
    """Review the final normalized clip before accepting it for composition."""
    reviewer = GenerationReviewService()
    scene_payload = _scene_review_payload(scene, project_id, db)
    shot_plan_payload = shot_plan.as_dict() if shot_plan else None
    review_scene_payload = {**scene_payload, "shot_plan": shot_plan_payload}
    review_path = Path(video_path).with_suffix(".final_review.json")
    technical_metrics = video_candidate_metrics(video_path)
    technical_metrics["start_frame_reference"] = video_start_frame_reference_metrics(
        video_path, scene.image_path,
    )
    _apply_audio_quality_contract(
        technical_metrics,
        quality_report.get("selected_provider_metadata"),
    )
    if _quality_report_has_long_form(quality_report) and technical_metrics.get("status") == "available":
        technical_metrics["technical_score"] = video_technical_score(
            technical_metrics,
            duration_low=4.0,
            duration_high=30.0,
            duration_soft_low=2.0,
            duration_soft_high=32.0,
        )
    review = reviewer.review_video(
        video_path,
        {
            **review_scene_payload,
            "shot_plan": shot_plan_payload,
            "final_stage": "postprocess_normalized_clip",
            "technical_metrics": technical_metrics,
        },
        review_path,
        reference,
    )
    final_review = {
        "path": video_path,
        "status": review.get("status"),
        "average": review.get("average", 0),
        "review_path": str(review_path),
        "scene": {"scene_number": scene.scene_number},
        "provider_metadata": quality_report.get("selected_provider_metadata", {})
        if isinstance(quality_report.get("selected_provider_metadata"), dict) else {},
    }
    gate_scores = _video_gate_scores(review)
    if gate_scores:
        final_review["gate_scores"] = gate_scores
    final_review["gate_evidence_complete"] = _video_gate_evidence_complete(review)
    platform_score = _video_platform_score(review)
    if platform_score is not None:
        final_review["platform_score"] = platform_score
    aesthetic_gate = _video_aesthetic_gate_summary(review)
    if aesthetic_gate:
        final_review["video_aesthetic_gate"] = aesthetic_gate
    reference_gate = _platform_reference_gate_summary(review)
    if reference_gate:
        final_review["platform_reference_gate"] = reference_gate
        final_review["platform_reference_score"] = reference_gate.get("average", 0)
    distinctiveness_gate = _video_character_distinctiveness_gate_summary(review, review_scene_payload)
    if distinctiveness_gate:
        final_review["character_distinctiveness_gate"] = distinctiveness_gate
        final_review["character_distinctiveness_score"] = distinctiveness_gate.get("average", 0)
    performance_gate = _video_performance_gate_summary(review, review_scene_payload)
    if performance_gate:
        final_review["video_performance_gate"] = performance_gate
        final_review["video_performance_score"] = performance_gate.get("average", 0)
    final_review["technical_metrics"] = technical_metrics
    if isinstance(technical_metrics.get("technical_score"), (int, float)):
        final_review["technical_score"] = technical_metrics["technical_score"]
    if review.get("error"):
        final_review["error"] = review["error"]
    quality_report["final_video_review"] = final_review
    gate_ok, gate_scores = _video_gate_passes(final_review)
    aesthetic_ok = _video_aesthetic_gate_passes(final_review)
    reference_ok = _platform_reference_gate_passes(final_review)
    distinctiveness_ok = _video_character_distinctiveness_gate_passes(final_review)
    performance_ok = _video_performance_gate_passes(final_review)
    platform_score = final_review.get("platform_score")
    acceptance_error = _final_video_acceptance_error(
        final_review,
        gate_ok,
        aesthetic_ok,
        reference_ok,
        distinctiveness_ok,
        performance_ok,
        platform_score,
        final_review.get("technical_score"),
    )
    if (
        settings.GENERATION_REQUIRE_VIDEO_REVIEW
        and acceptance_error
    ):
        final_review["error"] = acceptance_error
        quality_report["status"] = "needs_review"
        quality_report["error"] = acceptance_error
        quality_report["repair_queue"] = build_repair_queue(
            {"status": "needs_review", "candidates": [final_review]},
            "video",
        )
        write_report(Path(video_path).with_suffix(".quality.json"), quality_report)
        raise ReviewError(quality_report["error"])
    write_report(Path(video_path).with_suffix(".quality.json"), quality_report)
    return quality_report


def _final_video_acceptance_error(
    final_review: dict,
    gate_ok: bool,
    aesthetic_ok: bool,
    reference_ok: bool,
    distinctiveness_ok: bool,
    performance_ok: bool,
    platform_score,
    technical_score=None,
) -> str | None:
    technical_metrics = (
        final_review.get("technical_metrics")
        if isinstance(final_review.get("technical_metrics"), dict)
        else {}
    )
    if technical_metrics.get("audio_expected") is True and technical_metrics.get("audio_quality_status") != "passed":
        return (
            "Final normalized video native-audio check failed: "
            f"{technical_metrics.get('audio_quality_status') or 'audio stream unavailable'}"
        )
    max_black_run_seconds = technical_metrics.get("max_black_run_seconds")
    if (
        isinstance(max_black_run_seconds, (int, float))
        and max_black_run_seconds > settings.GENERATION_VIDEO_MAX_BLACK_SECONDS
    ):
        return (
            "Final normalized video contains a black-frame run of "
            f"{max_black_run_seconds:.3f}s, above "
            f"{settings.GENERATION_VIDEO_MAX_BLACK_SECONDS}s"
        )
    max_static_run_seconds = technical_metrics.get("max_static_run_seconds")
    motion_energy = technical_metrics.get("motion_energy")
    if (
        isinstance(max_static_run_seconds, (int, float))
        and max_static_run_seconds > settings.GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS
        and isinstance(motion_energy, (int, float))
        and motion_energy < 0.4
    ):
        return (
            "Final normalized video contains a frozen/static run of "
            f"{max_static_run_seconds:.3f}s with motion_energy={motion_energy:.3f}"
        )
    brightness_step_p95 = technical_metrics.get("brightness_step_p95")
    if (
        isinstance(brightness_step_p95, (int, float))
        and brightness_step_p95 > settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95
    ):
        return (
            "video temporal exposure jumps: brightness_step_p95="
            f"{brightness_step_p95:.3f}, limit={settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95:.3f}"
        )
    motion_jitter_ratio = technical_metrics.get("motion_jitter_ratio")
    if (
        isinstance(motion_jitter_ratio, (int, float))
        and motion_jitter_ratio > settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO
    ):
        return (
            "video motion cadence is unstable: motion_jitter_ratio="
            f"{motion_jitter_ratio:.3f}, limit={settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO:.3f}"
        )
    start_frame_reference = technical_metrics.get("start_frame_reference")
    if isinstance(start_frame_reference, dict) and start_frame_reference.get("status") == "available":
        start_frame_score = start_frame_reference.get("score")
        if (
            isinstance(start_frame_score, (int, float))
            and start_frame_score < settings.GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE
        ):
            return (
                "Final normalized video opening frame reference score "
                f"{start_frame_score} is below "
                f"{settings.GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE}"
            )
    provider_metadata = final_review.get("provider_metadata")
    requested_resolution = (
        str(provider_metadata.get("requested_resolution") or "").lower()
        if isinstance(provider_metadata, dict) else ""
    )
    if (
        isinstance(provider_metadata, dict)
        and provider_metadata.get("provider_name") == "seedance_api"
        and requested_resolution in {"1080p", "4k"}
    ):
        provider_pixel_format = str(provider_metadata.get("video_pixel_format") or "").lower()
        final_pixel_format = str(technical_metrics.get("pixel_format") or "").lower()
        provider_high_bit_depth = provider_metadata.get("video_high_bit_depth") is True
        if provider_high_bit_depth and technical_metrics.get("high_bit_depth") is not True:
            return (
                "Final normalized Seedance video lost the provider high-bit-depth format "
                f"for {requested_resolution} (provider={provider_pixel_format or 'unknown'}, "
                f"final={final_pixel_format or 'unknown'})"
            )
        provider_chroma_rank = _pixel_format_chroma_rank(provider_pixel_format)
        final_chroma_rank = _pixel_format_chroma_rank(final_pixel_format)
        if provider_chroma_rank and final_chroma_rank < provider_chroma_rank:
            return (
                "Final normalized Seedance video lost provider chroma fidelity "
                f"for {requested_resolution} (provider={provider_pixel_format}, "
                f"final={final_pixel_format or 'unknown'})"
            )
    if final_review.get("status") != "passed":
        return f"Final normalized video review status={final_review.get('status') or 'unknown'}"
    if final_review.get("average", 0) < settings.GENERATION_VIDEO_MIN_SCORE:
        return (
            f"Final normalized video score {final_review.get('average', 0)} is below "
            f"{settings.GENERATION_VIDEO_MIN_SCORE}"
        )
    if not gate_ok:
        return f"Final normalized video gate scores are below threshold: {final_review.get('gate_scores') or {}}"
    if settings.GENERATION_REQUIRE_VIDEO_REVIEW and not isinstance(final_review.get("video_aesthetic_gate"), dict):
        return "Final normalized video is missing video aesthetic feature scores from local VLM review"
    if not aesthetic_ok:
        return "Final normalized video aesthetic feature gate did not pass"
    if settings.GENERATION_REQUIRE_VIDEO_REVIEW and not isinstance(final_review.get("platform_reference_gate"), dict):
        return "Final normalized video is missing platform reference feature scores from local VLM review"
    if not reference_ok:
        return "Final normalized video platform reference gate did not pass"
    if not distinctiveness_ok:
        return "Final normalized video character distinctiveness gate did not pass"
    if not performance_ok:
        return "Final normalized video performance gate did not pass"
    if isinstance(platform_score, (int, float)) and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
        return (
            f"Final normalized video platform score {platform_score} is below "
            f"{settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE}"
        )
    if isinstance(technical_score, (int, float)) and technical_score < settings.GENERATION_VIDEO_TECHNICAL_MIN_SCORE:
        return (
            f"Final normalized video technical score {technical_score} is below "
            f"{settings.GENERATION_VIDEO_TECHNICAL_MIN_SCORE}"
        )
    return None


def _pixel_format_chroma_rank(pixel_format: str) -> int:
    """Return a comparable chroma-fidelity rank for common YUV formats."""
    normalized = str(pixel_format or "").lower()
    if "444" in normalized:
        return 3
    if "422" in normalized:
        return 2
    if "420" in normalized:
        return 1
    return 0


def _video_repair_action_from_candidates(candidates: list[dict]) -> str | None:
    """Infer the next automatic video repair action from failed candidate reviews."""
    if not candidates:
        return None
    queue = build_repair_queue(
        {"status": "needs_review", "candidates": sorted(candidates, key=_video_candidate_rank, reverse=True)[:1]},
        "video",
    )
    for item in queue:
        if item.get("execution") == "auto" and item.get("action") in {
            "lower_motion_and_regenerate_video",
            "increase_motion_and_regenerate_video",
            "regenerate_video_with_performance_direction",
            "refine_video_commercial_aesthetic",
            "refine_final_composition_finish",
        }:
            return str(item["action"])
    return None


def _video_candidate_passes(candidate: dict) -> bool:
    return _final_video_acceptance_error(
        candidate,
        _video_gate_passes(candidate)[0],
        _video_aesthetic_gate_passes(candidate),
        _platform_reference_gate_passes(candidate),
        _video_character_distinctiveness_gate_passes(candidate),
        _video_performance_gate_passes(candidate),
        candidate.get("platform_score"),
        candidate.get("technical_score"),
    ) is None


def _video_candidate_rank(candidate: dict) -> tuple:
    return (
        _video_candidate_passes(candidate),
        _video_gate_passes(candidate)[0],
        _video_aesthetic_gate_passes(candidate),
        _platform_reference_gate_passes(candidate),
        _video_character_distinctiveness_gate_passes(candidate),
        _video_performance_gate_passes(candidate),
        _video_critical_floor_score(candidate) or 0,
        _video_selection_score(candidate),
        candidate.get("average", 0),
    )


def _select_best_video_candidate(
    candidates: list[dict],
    final_path: str,
    report_path: Path,
    quality_budget: dict | None = None,
) -> tuple[str, dict]:
    if not candidates:
        raise ReviewError("No video candidates were generated")
    for candidate in candidates:
        _attach_video_technical_metrics(candidate)
        candidate["critical_floor_score"] = _video_critical_floor_score(candidate)
        candidate["selection_score"] = _video_selection_score(candidate)
    ranked = sorted(
        candidates,
        key=_video_candidate_rank,
        reverse=True,
    )
    best = ranked[0]
    gate_ok, gate_scores = _video_gate_passes(best)
    aesthetic_gate_ok = _video_aesthetic_gate_passes(best)
    aesthetic_gate = best.get("video_aesthetic_gate")
    reference_gate_ok = _platform_reference_gate_passes(best)
    reference_gate = best.get("platform_reference_gate")
    distinctiveness_gate_ok = _video_character_distinctiveness_gate_passes(best)
    distinctiveness_gate = best.get("character_distinctiveness_gate")
    performance_gate_ok = _video_performance_gate_passes(best)
    performance_gate = best.get("video_performance_gate")
    platform_score = best.get("platform_score")
    report = {
        "kind": "video_candidate_selection",
        "status": "passed" if _video_candidate_passes(best) else "needs_review",
        "selected_path": best["path"],
        "selected_average": best.get("average", 0),
        "selected_platform_score": platform_score,
        "selected_technical_score": best.get("technical_score"),
        "selected_critical_floor_score": best.get("critical_floor_score"),
        "selected_selection_score": best.get("selection_score"),
        "selected_provider_metadata": best.get("provider_metadata", {}),
        "min_average": settings.GENERATION_VIDEO_MIN_SCORE,
        "min_identity_score": settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE,
        "min_temporal_score": settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE,
        "min_platform_score": settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE,
        "selected_gate_scores": gate_scores,
        "selected_video_aesthetic_gate": aesthetic_gate,
        "selected_platform_reference_gate": reference_gate,
        "selected_character_distinctiveness_gate": distinctiveness_gate,
        "selected_video_performance_gate": performance_gate,
        "candidates": ranked,
    }
    if quality_budget:
        report["quality_budget"] = quality_budget
    if best.get("status") != "passed":
        report["error"] = f"Selected video review status={best.get('status') or 'unknown'}"
    elif not gate_ok:
        report["error"] = f"Selected video gate scores are below threshold: {gate_scores}"
    elif platform_score is not None and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
        report["error"] = (
            f"Best video platform score {platform_score} is below "
            f"{settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE}"
        )
    elif best.get("average", 0) < settings.GENERATION_VIDEO_MIN_SCORE:
        report["error"] = (
            f"Best video score {best.get('average', 0)} is below "
            f"{settings.GENERATION_VIDEO_MIN_SCORE}"
        )
    elif (
        isinstance(best.get("technical_score"), (int, float))
        and best["technical_score"] < settings.GENERATION_VIDEO_TECHNICAL_MIN_SCORE
    ):
        report["error"] = (
            f"Best video technical score {best['technical_score']} is below "
            f"{settings.GENERATION_VIDEO_TECHNICAL_MIN_SCORE}"
        )
    elif settings.GENERATION_REQUIRE_VIDEO_REVIEW and not isinstance(aesthetic_gate, dict):
        report["error"] = "Selected video is missing video aesthetic feature scores from local VLM review"
    elif settings.GENERATION_REQUIRE_VIDEO_REVIEW and not isinstance(reference_gate, dict):
        report["error"] = "Selected video is missing platform reference feature scores from local VLM review"
    elif isinstance(aesthetic_gate, dict) and aesthetic_gate.get("status") != "passed":
        report["error"] = "Selected video aesthetic feature gate did not pass"
    elif isinstance(reference_gate, dict) and reference_gate.get("status") != "passed":
        report["error"] = "Selected video platform reference gate did not pass"
    elif isinstance(distinctiveness_gate, dict) and distinctiveness_gate.get("status") != "passed":
        report["error"] = "Selected video character distinctiveness gate did not pass"
    elif isinstance(performance_gate, dict) and performance_gate.get("status") != "passed":
        report["error"] = "Selected video performance gate did not pass"
    if report["status"] != "passed" and settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        attach_repair_queue(report, "video")
        write_report(report_path, report)
        raise ReviewError(
            f"Video candidates failed quality gate: average={best.get('average', 0)}, "
            f"required={settings.GENERATION_VIDEO_MIN_SCORE}, gates={gate_scores}, "
            f"reason={report.get('error')}, report={report_path}"
        )
    Path(final_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best["path"], final_path)
    report["promoted_path"] = final_path
    if report["status"] != "passed":
        attach_repair_queue(report, "video")
    write_report(report_path, report)
    return final_path, report


def _generate_quality_video_candidates(
    svd_service,
    scene: Scene,
    project_id: int,
    output_path: str,
    db,
    *,
    num_frames: int,
    fps: int,
    motion_bucket_id: int,
    noise_aug_strength: float,
    shot_plan: VideoShotPlan | None = None,
    repair_action: str | None = None,
) -> tuple[str, dict]:
    budget = video_quality_budget(repair_action)
    max_refinement_passes = max(0, min(budget.refinement_passes, 4))
    strongest_budget = budget
    reviewer = GenerationReviewService()
    reference = _reference_for_scene(scene, project_id, db)
    scene_payload = _scene_review_payload(scene, project_id, db)
    shot_plan_payload = shot_plan.as_dict() if shot_plan else None
    base_quality_pipeline = video_quality_pipeline(shot_plan_payload, repair_action)
    candidate_scene = {
        "scene_number": scene.scene_number,
        "description": scene.visual_description,
        "dialogue": scene.dialogue,
        "repair_action": repair_action,
        "visible_characters": scene_payload.get("visible_characters", []),
        "identity_contrast_matrix": scene_payload.get("identity_contrast_matrix", {}),
        "quality_pipeline": base_quality_pipeline.as_dict(),
    }
    candidates = []
    from src.services.svd_service import cleanup_svd_service
    current_motion = motion_bucket_id
    current_noise = noise_aug_strength
    pass_index = 0
    next_candidate_index = 1
    while pass_index <= max_refinement_passes:
        generated = []
        current_repair_action = repair_action or (
            _video_repair_action_from_candidates(candidates) if pass_index else None
        )
        pass_budget = video_quality_budget(current_repair_action)
        if pass_budget.candidate_count >= strongest_budget.candidate_count:
            strongest_budget = pass_budget
        max_refinement_passes = max(max_refinement_passes, max(0, min(pass_budget.refinement_passes, 4)))
        quality_pipeline = video_quality_pipeline(shot_plan_payload, current_repair_action)
        pass_scene = {
            **candidate_scene,
            "repair_action": current_repair_action,
            "quality_pipeline": quality_pipeline.as_dict(),
        }
        pass_motion, pass_noise = _apply_video_repair_action(
            current_motion,
            current_noise,
            current_repair_action,
        )
        if hasattr(svd_service, "with_repair_action"):
            svd_service.with_repair_action(current_repair_action)
        try:
            for offset in range(1, pass_budget.candidate_count + 1):
                index = next_candidate_index
                next_candidate_index += 1
                candidate_path = _candidate_video_path(output_path, index)
                motion, noise = _video_variant_params(pass_motion, pass_noise, offset)
                try:
                    generated_path = svd_service.generate_video(
                        image_path=scene.image_path,
                        output_path=candidate_path,
                        num_frames=num_frames,
                        fps=fps,
                        motion_bucket_id=motion,
                        noise_aug_strength=noise,
                    )
                except ComfyUIWaitTimeout:
                    raise
                except (ComfyUIError, GenerationProviderError, SVDError, OSError) as exc:
                    candidates.append({
                        "index": index, "pass": pass_index, "path": candidate_path,
                        "status": "error", "average": 0, "error": str(exc),
                        "stage": "generation", "scene": dict(pass_scene),
                    })
                    continue
                generated.append({
                    "index": index,
                    "pass": pass_index,
                    "path": generated_path,
                    "provider_metadata": {
                        **dict(getattr(svd_service, "last_result_metadata", {}) or {}),
                        **({
                            "provider_name": getattr(
                                getattr(getattr(svd_service, "provider", None), "name", None),
                                "value", None,
                            )
                        } if getattr(getattr(svd_service, "provider", None), "name", None) is not None else {}),
                    },
                    "motion_bucket_id": motion,
                    "noise_aug_strength": noise,
                    "scene": dict(pass_scene),
                    "request": {
                        "image_path": scene.image_path,
                        "num_frames": num_frames,
                        "fps": fps,
                        "motion_bucket_id": motion,
                        "noise_aug_strength": noise,
                        "reference_image": reference,
                        "reference_images": list(getattr(svd_service, "reference_images", []) or []),
                        "reference_videos": list(getattr(svd_service, "reference_videos", []) or []),
                        "reference_audios": list(getattr(svd_service, "reference_audios", []) or []),
                        "continuity_reference_image": getattr(svd_service, "continuity_reference_image", None),
                        "sequence_context": getattr(svd_service, "sequence_context", None),
                        "provider": getattr(getattr(svd_service, "provider", None), "name", None).value
                        if getattr(getattr(svd_service, "provider", None), "name", None) is not None
                        and hasattr(getattr(svd_service, "provider", None).name, "value")
                        else None,
                        "character_sheet_references": scene_payload.get("character_sheet_references", []),
                        "identity_contrast_matrix": scene_payload.get("identity_contrast_matrix", {}),
                        "platform_aesthetic_contract": scene_payload.get("platform_aesthetic_contract", {}),
                        "repair_action": current_repair_action,
                        "quality_budget": pass_budget.as_dict(),
                        "quality_pipeline": quality_pipeline.as_dict(),
                    },
                    "shot_plan": shot_plan_payload,
                    "quality_pipeline": quality_pipeline.as_dict(),
                    "repair_action": current_repair_action,
                })
        finally:
            release_generation_resources(svd_service)
            cleanup_svd_service()

        pass_candidates = []
        for generated_candidate in generated:
            index = generated_candidate["index"]
            generated_path = generated_candidate["path"]
            review_path = Path(generated_path).with_suffix(".review.json")
            candidate_technical_metrics = video_candidate_metrics(generated_path)
            candidate_technical_metrics["start_frame_reference"] = video_start_frame_reference_metrics(
                generated_path, scene.image_path,
            )
            _apply_audio_quality_contract(
                candidate_technical_metrics,
                generated_candidate.get("provider_metadata"),
            )
            if _is_long_form_shot_plan(shot_plan_payload) and candidate_technical_metrics.get("status") == "available":
                candidate_technical_metrics["technical_score"] = video_technical_score(
                    candidate_technical_metrics,
                    duration_low=4.0,
                    duration_high=30.0,
                    duration_soft_low=2.0,
                    duration_soft_high=32.0,
                )
            review = reviewer.review_video(
                generated_path,
                {
                    **scene_payload,
                    "shot_plan": shot_plan_payload,
                    "candidate_index": index,
                    "refinement_pass": generated_candidate["pass"],
                    "motion_bucket_id": generated_candidate["motion_bucket_id"],
                    "noise_aug_strength": generated_candidate["noise_aug_strength"],
                    "repair_action": current_repair_action,
                    "quality_pipeline": quality_pipeline.as_dict(),
                    "technical_metrics": candidate_technical_metrics,
                },
                review_path,
                reference,
            )
            candidate = {
                "index": index,
                "pass": generated_candidate["pass"],
                "path": generated_path,
                "status": review.get("status"),
                "average": review.get("average", 0),
                "review_path": str(review_path),
                "motion_bucket_id": generated_candidate["motion_bucket_id"],
                "noise_aug_strength": generated_candidate["noise_aug_strength"],
                "scene": generated_candidate["scene"],
                "request": generated_candidate["request"],
                "provider_metadata": generated_candidate.get("provider_metadata", {}),
                "technical_metrics": candidate_technical_metrics,
            }
            gate_scores = _video_gate_scores(review)
            if gate_scores:
                candidate["gate_scores"] = gate_scores
            candidate["gate_evidence_complete"] = _video_gate_evidence_complete(review)
            platform_score = _video_platform_score(review)
            if platform_score is not None:
                candidate["platform_score"] = platform_score
            aesthetic_gate = _video_aesthetic_gate_summary(review)
            if aesthetic_gate:
                candidate["video_aesthetic_gate"] = aesthetic_gate
            reference_gate = _platform_reference_gate_summary(review)
            if reference_gate:
                candidate["platform_reference_gate"] = reference_gate
                candidate["platform_reference_score"] = reference_gate.get("average", 0)
            distinctiveness_gate = _video_character_distinctiveness_gate_summary(review, scene_payload)
            if distinctiveness_gate:
                candidate["character_distinctiveness_gate"] = distinctiveness_gate
                candidate["character_distinctiveness_score"] = distinctiveness_gate.get("average", 0)
            performance_gate = _video_performance_gate_summary(review, {
                **scene_payload,
                "shot_plan": shot_plan_payload,
            })
            if performance_gate:
                candidate["video_performance_gate"] = performance_gate
                candidate["video_performance_score"] = performance_gate.get("average", 0)
            if current_repair_action:
                candidate["repair_action"] = current_repair_action
            if shot_plan_payload:
                candidate["shot_plan"] = shot_plan_payload
            candidate["quality_pipeline"] = quality_pipeline.as_dict()
            if review.get("error"):
                candidate["error"] = review["error"]
            _attach_video_technical_metrics(candidate)
            candidate["selection_score"] = _video_selection_score(candidate)
            candidates.append(candidate)
            pass_candidates.append(candidate)
        if any(_video_candidate_passes(candidate) for candidate in candidates) and pass_index + 1 >= minimum_quality_passes(pass_budget):
            break
        if all(candidate.get("status") == "error" for candidate in pass_candidates):
            break
        if pass_index >= max_refinement_passes and max_refinement_passes < 4:
            next_repair_action = repair_action or _video_repair_action_from_candidates(candidates)
            if next_repair_action:
                max_refinement_passes = pass_index + 1
        current_motion, current_noise = _refined_video_base_params(pass_motion, pass_noise)
        pass_index += 1
    if all(candidate.get("status") == "error" for candidate in candidates):
        report = {
            "kind": "video_candidate_selection",
            "status": "review_unavailable",
            "selected_path": candidates[0]["path"],
            "candidates": candidates,
            "quality_budget": strongest_budget.as_dict(),
        }
        attach_repair_queue(report, "video")
        write_report(Path(output_path).with_suffix(".quality.json"), report)
        raise ReviewError("All video candidate reviews failed")
    return _select_best_video_candidate(
        candidates,
        output_path,
        Path(output_path).with_suffix(".quality.json"),
        quality_budget=strongest_budget.as_dict(),
    )


@celery_app.task(bind=True, name="generate_video")
def generate_video_task(
    self,
    scene_id: int,
    project_id: int,
    task_id: int,
    **kwargs,
):
    """Generate a video clip for one scene."""
    logger.info("Start video generation: scene_id={}", scene_id)
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "video_generation"})

    db = next(get_db())
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene or scene.project_id != project_id:
            raise ValueError(f"Scene not found: {scene_id}")
        if not scene.image_path or not Path(scene.image_path).is_file():
            raise ValueError(f"Scene image file is missing: {scene_id}: {scene.image_path or '<empty>'}")

        video_path = str(kwargs.get("output_path") or get_scene_video_path(project_id, scene_id))
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "svd_generation"})

        try:
            try:
                from src.services.comfyui_service import get_comfyui_service
                get_comfyui_service().free_memory()
            except Exception as exc:
                logger.warning("Could not ask ComfyUI to free memory before video generation; continuing: {}", exc)
            visible_characters = _visible_characters_for_scene(scene, project_id, db)
            shot_plan = get_video_director_service().plan_scene(scene, project_id, visible_characters)
            num_frames = max(kwargs.get("num_frames", settings.SVD_NUM_FRAMES), shot_plan.num_frames)
            fps = kwargs.get("fps", shot_plan.fps)
            motion_bucket_id = kwargs.get("motion_bucket_id", shot_plan.motion_bucket_id)
            noise_aug_strength = kwargs.get("noise_aug_strength", shot_plan.noise_aug_strength)
            repair_action = kwargs.get("repair_action")
            motion_bucket_id, noise_aug_strength = _apply_video_repair_action(
                motion_bucket_id,
                noise_aug_strength,
                repair_action,
            )
            provider_name = _configured_video_provider_name(kwargs)
            end_image = None
            sequence_level_requested = _setting_enabled(
                kwargs.get("sequence_level_multi_shot", kwargs.get("SEQUENCE_LEVEL_MULTI_SHOT", False))
            )
            if (
                settings.GENERATION_VIDEO_END_FRAME_ENABLED
                and _uses_configured_video_provider(provider_name)
                and not sequence_level_requested
            ):
                end_image = _generate_end_frame(
                    scene, project_id, shot_plan, scene_payload=_scene_review_payload(scene, project_id, db),
                )
            def option(name: str):
                return kwargs.get(name.lower(), kwargs.get(name))

            provider_options = {
                key: value for key, value in {
                    "REQUEST_MODE": option("REQUEST_MODE"),
                    "MULTI_SHOT": option("MULTI_SHOT"),
                    "NATIVE_AUDIO": option("NATIVE_AUDIO"),
                    "SEQUENCE_LEVEL_MULTI_SHOT": option("SEQUENCE_LEVEL_MULTI_SHOT"),
                    "DRAFT": option("DRAFT"),
                    "DRAFT_TASK_ID": option("DRAFT_TASK_ID"),
                    "RESOLUTION": option("RESOLUTION"),
                    "OUTPUT_FORMAT": option("OUTPUT_FORMAT"),
                    "RETURN_LAST_FRAME": option("RETURN_LAST_FRAME"),
                    "CAMERA_FIXED": option("CAMERA_FIXED"),
                    "WATERMARK": option("WATERMARK"),
                    "MODEL": option("MODEL"),
                    "LOCAL_TASK_ID": task_id,
                "DURATION_SECONDS": option("DURATION_SECONDS"),
                "SEQUENCE_TIMELINE": option("SEQUENCE_TIMELINE"),
                }.items() if value is not None
            }
            provider_ref = {}
            external_progress_callback = kwargs.get("PROVIDER_PROGRESS_CALLBACK")
            def report_provider_progress(progress, state):
                generator = provider_ref.get("generator")
                metadata = getattr(generator, "last_result_metadata", {}) if generator else {}
                if callable(external_progress_callback):
                    external_progress_callback(progress, state, metadata)
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "current": progress,
                        "total": 100,
                        "step": f"provider_{state}",
                        "provider_task_id": metadata.get("provider_task_id"),
                        "provider_status": metadata.get("provider_status") or metadata.get("provider_task_status"),
                    },
                )
            provider_options["PROGRESS_CALLBACK"] = report_provider_progress
            provider_options["CANCELLATION_CHECK"] = lambda: (
                db.query(Task.status).filter(Task.id == task_id).scalar() == TaskStatus.CANCELLED
            )
            video_generator = _build_video_generator(
                scene, shot_plan, provider_name, end_image, provider_options=provider_options,
            )
            provider_ref["generator"] = video_generator
            sequence_scenes = None
            if _setting_enabled(kwargs.get("sequence_level_multi_shot")):
                sequence_scenes = db.query(Scene).filter(
                    Scene.project_id == project_id,
                ).order_by(Scene.scene_number).all()
                multimodal_refs = _multimodal_references_for_sequence(
                    sequence_scenes, project_id, db, provider_name, option("MODEL"),
                )
            else:
                multimodal_refs = _multimodal_references_for_scene(
                    scene, project_id, db, provider_name, option("MODEL"),
                )
            if isinstance(video_generator, _ComfyVideoGenerator):
                video_generator.with_multimodal_references(**multimodal_refs)
                video_generator.with_sequence_context(_sequence_context_for_scene(scene, project_id, db))
                binding_scenes = sequence_scenes or [scene]
                video_generator.with_character_reference_bindings(
                    _character_reference_bindings_for_scenes(
                        binding_scenes, project_id, db, multimodal_refs,
                    )
                )
            result_path, quality_report = _generate_quality_video_candidates(
                video_generator,
                scene,
                project_id,
                video_path,
                db,
                num_frames=num_frames,
                fps=fps,
                motion_bucket_id=motion_bucket_id,
                noise_aug_strength=noise_aug_strength,
                shot_plan=shot_plan,
                repair_action=repair_action,
            )
            normalized_path = str(Path(video_path).with_name(f"{Path(video_path).stem}.normalized.mp4"))
            normalized = get_video_director_service().normalize_clip(
                result_path,
                normalized_path,
                _normalization_duration_for_provider(
                    provider_name,
                    kwargs.get("request_mode"),
                    kwargs.get("multi_shot"),
                    shot_plan,
                    quality_report,
                    sequence_level_multi_shot=_setting_enabled(
                        kwargs.get("sequence_level_multi_shot", kwargs.get("SEQUENCE_LEVEL_MULTI_SHOT", False))
                    ),
                    source_path=result_path,
                ),
                preserve_audio=_preserve_generated_audio(
                    provider_name,
                    kwargs.get("native_audio"),
                    multimodal_refs,
                ),
                preserve_provider_quality=provider_name == "seedance_api",
            )
            quality_report = _review_final_video_after_postprocess(
                normalized,
                scene,
                project_id,
                db,
                quality_report=quality_report,
                reference=_reference_for_scene(scene, project_id, db),
                shot_plan=shot_plan,
            )
            if normalized != result_path:
                shutil.copyfile(normalized, video_path)
                result_path = video_path
            continuity_metadata_path = _write_scene_continuity_metadata(
                result_path,
                {
                    **(quality_report.get("selected_provider_metadata") or {} if isinstance(quality_report, dict) else {}),
                    "last_frame_path": _extract_video_last_frame(result_path),
                },
            )
            if continuity_metadata_path:
                quality_report["continuity_metadata_path"] = continuity_metadata_path
            selected_provider_metadata = dict(
                quality_report.get("selected_provider_metadata")
                if isinstance(quality_report, dict)
                and isinstance(quality_report.get("selected_provider_metadata"), dict)
                else {}
            )
            selected_provider_metadata.update({
                "provider_name": provider_name,
                "native_audio_requested": _native_audio_enabled(
                    provider_name, kwargs.get("native_audio")
                ),
            })
            provider_metadata_path = _write_provider_metadata(
                result_path,
                selected_provider_metadata,
            )
            if provider_metadata_path:
                quality_report["provider_metadata_path"] = provider_metadata_path
            logger.info("Video candidate selection completed: scene_id={}, report={}", scene_id, quality_report)
        except Exception as exc:
            if not _draft_fallback_allowed(exc, locals().get("video_generator")):
                raise
            duration = get_draft_media_service().estimate_dialogue_duration(scene.dialogue or "")
            logger.warning(
                "Real video generation failed; using draft still-video fallback: scene_id={}, duration={}, error={}",
                scene_id,
                duration,
                exc,
            )
            result_path = get_draft_media_service().generate_video_from_image(
                image_path=scene.image_path,
                output_path=video_path,
                duration=duration,
                fps=kwargs.get("fps", 24),
            )

        scene.video_path = result_path
        db.commit()

        logger.info("Video generation completed: scene_id={}, path={}", scene_id, result_path)
        return {"scene_id": scene_id, "video_path": result_path, "status": "completed"}
    except Exception as exc:
        logger.error("Video generation failed: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_sequence_video")
def generate_sequence_video_task(
    self,
    scene_ids: list[int],
    project_id: int,
    task_id: int,
    **kwargs,
):
    """Generate one provider-level sequence, then publish atomic scene clips."""
    if not scene_ids:
        raise ValueError("A sequence requires at least one scene")
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "sequence_planning"})
    db = next(get_db())
    sequence_path: Path | None = None
    previous_video_paths: dict[int, str | None] = {}
    staging_paths: list[Path] = []
    try:
        scenes = db.query(Scene).filter(
            Scene.project_id == project_id,
            Scene.id.in_(scene_ids),
        ).order_by(Scene.scene_number).all()
        if len(scenes) != len(scene_ids):
            raise ValueError("One or more sequence scenes are missing")
        if any(not scene.image_path or not Path(scene.image_path).is_file() for scene in scenes):
            raise ValueError("Every sequence scene needs a generated keyframe")
        previous_video_paths = {scene.id: scene.video_path for scene in scenes}

        segments = build_sequence_timeline(scenes, max_duration_seconds=30.0)
        first_scene = scenes[0]
        provider_kwargs = dict(kwargs)
        requested_sequence_path = provider_kwargs.get("sequence_output_path") or provider_kwargs.get(
            "SEQUENCE_OUTPUT_PATH"
        )
        sequence_path = Path(requested_sequence_path) if requested_sequence_path else Path(
            get_scene_video_path(project_id, first_scene.id)
        ).with_name(f"sequence_{task_id}.mp4")
        provider_kwargs.update({
            "multi_shot": True,
            "sequence_level_multi_shot": True,
            "request_mode": kwargs.get("request_mode") or "multi_shot",
            "output_path": str(sequence_path),
            "sequence_timeline": [segment.as_dict() for segment in segments],
        })
        def report_sequence_provider_progress(progress, state, metadata=None):
            metadata = metadata if isinstance(metadata, dict) else {}
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": progress,
                    "total": 100,
                    "step": f"provider_{state}",
                    "provider_task_id": metadata.get("provider_task_id"),
                    "provider_status": metadata.get("provider_status") or metadata.get("provider_task_status"),
                },
            )
        provider_kwargs["PROVIDER_PROGRESS_CALLBACK"] = report_sequence_provider_progress
        self.update_state(state="PROGRESS", meta={"current": 10, "total": 100, "step": "sequence_generation"})
        generated = generate_video_task.run(first_scene.id, project_id, task_id, **provider_kwargs)
        source = Path(generated["video_path"])
        if not source.is_file() or source.stat().st_size <= 0:
            raise ValueError("The provider returned an empty sequence video")

        output_paths = [Path(get_scene_video_path(project_id, scene.id)) for scene in scenes]
        staging_paths = [
            output_path.with_name(
                f".{output_path.stem}.sequence-{task_id}.part{output_path.suffix}"
            )
            for output_path in output_paths
        ]
        self.update_state(state="PROGRESS", meta={"current": 70, "total": 100, "step": "sequence_splitting"})
        split_sequence_video(source, segments, staging_paths)
        sequence_provider_metadata = {}
        provider_metadata_path = _provider_metadata_path(source)
        if provider_metadata_path.is_file():
            try:
                loaded = json.loads(provider_metadata_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    sequence_provider_metadata = loaded
            except (OSError, ValueError):
                logger.warning("Could not read sequence provider metadata: {}", provider_metadata_path)
        boundary_report = video_boundary_continuity([str(path) for path in staging_paths])
        boundary_report_path = sequence_path.with_suffix(".boundary.json")
        write_report(boundary_report_path, boundary_report)
        if boundary_report.get("status") == "available":
            severe_count = int(boundary_report.get("severe_transition_count") or 0)
            geometry_count = int(boundary_report.get("geometry_mismatch_count") or 0)
            if severe_count or geometry_count:
                raise ReviewError(
                    "Sequence boundary quality gate failed: "
                    f"severe_transitions={severe_count}, geometry_mismatches={geometry_count}; "
                    f"report={boundary_report_path}"
                )
        for scene, staging_path in zip(scenes, staging_paths):
            segment_report = _sequence_segment_quality_report(
                scene,
                str(staging_path),
                project_id,
                db,
                sequence_provider_metadata,
            )
            if segment_report.get("status") != "passed":
                raise ReviewError(
                    f"Sequence segment scene {scene.scene_number} is not production-ready: "
                    f"{segment_report.get('error') or 'quality review failed'}"
                )
        # Publish only after every derived scene has passed its own review.
        _publish_sequence_artifacts_atomically(staging_paths, output_paths)

        for scene, output_path in zip(scenes, output_paths):
            scene.video_path = str(output_path)
            last_frame_path = _extract_video_last_frame(output_path)
            if last_frame_path:
                _write_scene_continuity_metadata(
                    output_path,
                    {**sequence_provider_metadata, "last_frame_path": last_frame_path},
                )
            _write_provider_metadata(output_path, sequence_provider_metadata)
        db.commit()
        self.update_state(state="PROGRESS", meta={"current": 100, "total": 100, "step": "sequence_completed"})
        return {
            "project_id": project_id,
            "scene_ids": scene_ids,
            "video_paths": [str(path) for path in output_paths],
            "segments": [segment.as_dict() for segment in segments],
            "status": "completed",
        }
    except Exception:
        db.rollback()
        if previous_video_paths:
            for scene_id, video_path in previous_video_paths.items():
                scene = db.query(Scene).filter(Scene.id == scene_id).first()
                if scene:
                    scene.video_path = video_path
            db.commit()
        raise
    finally:
        for staging_path in staging_paths:
            for artifact in staging_path.parent.glob(f"{staging_path.stem}*"):
                if artifact.is_file():
                    artifact.unlink(missing_ok=True)
        if sequence_path and sequence_path.exists():
            for artifact in sequence_path.parent.glob(f"{sequence_path.stem}*"):
                if artifact.name.endswith(".provider.pending.json"):
                    continue
                if artifact.is_file():
                    artifact.unlink(missing_ok=True)
        db.close()
