"""Generation provider abstraction.

The system can use local ComfyUI for low-cost drafts and API providers for
high-quality production shots. API providers are intentionally strict: without
real integration settings they fail clearly instead of returning fake assets.
"""

from __future__ import annotations

import os
import ipaddress
import base64
import hashlib
from io import BytesIO
import json
import math
import shutil
import subprocess
from string import Formatter
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol
from urllib.parse import quote, urlparse
from uuid import uuid4

import httpx

from src.config import settings
from src.utils.logger import get_logger
from src.services.video_quality_metrics import temporal_sample_evidence_error, video_candidate_metrics
from src.services.seedance_callback_store import claim_early_callback

logger = get_logger(__name__)


COMFYUI_QUALITY_MODE_ALIASES = {
    "seed_dance_reference": "ultra",
    "hongguo_reference": "high_quality",
}
COMFYUI_HIGH_QUALITY_MODES = {"high_quality", "ultra"}


def _provider_setting(name: str, default: str = "") -> str:
    """Read an explicit environment override, then the loaded Settings/.env value."""
    value = os.getenv(name)
    if value is not None:
        return value
    configured = getattr(settings, name, default)
    return default if configured is None else str(configured)


def _provider_bool(name: str, default: bool = False) -> bool:
    return _provider_setting(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _provider_bool_value(value: bool | None, name: str, default: bool = False) -> bool:
    """Resolve an optional per-request boolean before the environment default."""
    return bool(value) if value is not None else _provider_bool(name, default)


def _seedance_model(default: str = "doubao-seedance-2-5-260628", model: str | None = None) -> str:
    """Resolve an empty copied .env model back to the production default."""
    if model is not None:
        return str(model).strip() or default
    return _provider_setting("SEEDANCE_MODEL", default).strip() or default


def _seedance_model_is_25(model: str | None = None) -> bool:
    """Recognize the documented Seedance 2.5 model naming variants."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return "2.5" in normalized or "2-5" in normalized


def _seedance_model_is_10(model: str | None = None) -> bool:
    """Recognize Seedance 1.0 Pro and Pro Fast model ids."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return "1.0" in normalized or "1-0" in normalized


def _seedance_model_is_20(model: str | None = None) -> bool:
    """Recognize the Seedance 2.0 model family, including Fast and Mini."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return "2.0" in normalized or "2-0" in normalized


def _seedance_model_is_20_limited(model: str | None = None) -> bool:
    """Return whether a 2.0 Fast/Mini model has the reduced output contract."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return _seedance_model_is_20(normalized) and ("fast" in normalized or "mini" in normalized)


def _seedance_supported_resolutions(model: str | None = None) -> set[str]:
    """Return native Ark resolution values for the selected Seedance model."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    if _seedance_model_is_25(normalized):
        return {"480p", "720p", "1080p"}
    if _seedance_model_is_20_limited(normalized):
        return {"480p", "720p"}
    if _seedance_model_is_20(normalized):
        return {"480p", "720p", "1080p", "4k"}
    if _seedance_model_is_10(normalized):
        return {"480p", "720p", "1080p"}
    return {"480p", "720p", "1080p", "4k"}


def _seedance_duration_bounds(
    model: str | None = None,
    request_mode: str | None = None,
) -> tuple[int, int]:
    """Return the documented native Ark duration range for a model/task.

    Seedance 2.5 has a different lower bound for ordinary generation versus
    video editing/extension. Keeping the task mode here prevents a short
    reaction beat from being silently expanded and breaking the local timeline.
    """
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    mode = str(request_mode or "").strip().lower().replace("_", "-")
    if _seedance_model_is_25(normalized):
        return (4, 30) if mode in {"edit", "extend"} else (2, 30)
    if _seedance_model_is_10(normalized):
        return 2, 12
    if _seedance_model_is_20(normalized):
        # The current Ark 2.0 generation contract is 4-15 seconds. The
        # provider's 2-second bound applies to reference-video inputs, not
        # to the requested generated output duration.
        return 4, 15
    return 4, 15


def _seedance_model_supports_multimodal_references(model: str | None = None) -> bool:
    """Return whether ``reference_image/video/audio`` roles are supported."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return _seedance_model_is_25(normalized) or "2.0" in normalized or "2-0" in normalized


def _seedance_model_supports_first_last_frame(model: str | None = None) -> bool:
    """Return whether the model supports explicit first/last frame roles."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    if _seedance_model_is_25(normalized) or "2.0" in normalized or "2-0" in normalized:
        return True
    return _seedance_model_is_10(normalized) and "fast" not in normalized


def _seedance_model_supports_reference_audio(model: str | None = None) -> bool:
    """Return whether the Ark model accepts reference_audio content items."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return _seedance_model_supports_multimodal_references(normalized)


def _seedance_model_supports_seed_camera(model: str | None = None) -> bool:
    """Seed and fixed-camera controls are limited to Seedance 1.0 models."""
    normalized = str(model if model is not None else _seedance_model()).strip().lower().replace("_", "-")
    return "1.0" in normalized or "1-0" in normalized


def _seedance_api_format(endpoint: str | None = None) -> str:
    """Resolve the Seedance wire format, auto-detecting the official Ark host."""
    env_configured = os.getenv("SEEDANCE_API_FORMAT")
    configured = str(
        env_configured if env_configured is not None and env_configured.strip()
        else getattr(settings, "SEEDANCE_API_FORMAT", "legacy") or "legacy"
    ).strip().lower()
    # An empty value in a copied .env file means "auto", rather than an
    # invalid wire format. Non-empty environment values remain authoritative.
    if env_configured is not None and env_configured.strip():
        return configured
    host = (urlparse(str(endpoint or "")).hostname or "").lower()
    if configured == "legacy" and (
        host.endswith(".volcengine.com") or host.endswith(".volces.com")
    ):
        return "ark_v3"
    return configured


def _extract_workflow_image_metadata(output_path: str) -> dict[str, object]:
    workflow_path = Path(output_path).with_suffix(".workflow.json")
    if not workflow_path.is_file():
        return {}
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"workflow_path": str(workflow_path), "workflow_error": str(exc)}
    if not isinstance(workflow, dict) or not all(
        isinstance(node, dict) and isinstance(node.get("inputs", {}), dict)
        and isinstance(node.get("class_type"), str) for node in workflow.values()
    ):
        return {"workflow_path": str(workflow_path), "workflow_error": "Invalid workflow node structure"}
    from src.services.image_workflow_graph import ImageWorkflowGraph, ImageWorkflowGraphError
    graph = ImageWorkflowGraph(workflow)
    metadata: dict[str, object] = {"workflow_path": str(workflow_path)}
    active = set(workflow)
    try:
        preferred = None
        job_path = Path(output_path).with_suffix(".job.json")
        if job_path.is_file():
            try:
                from src.services.generation_review import fingerprint
                job = json.loads(job_path.read_text(encoding="utf-8"))
                if isinstance(job, dict) and job.get("workflow_sha256") == fingerprint(workflow):
                    preferred = job.get("output_node") if isinstance(job.get("output_node"), str) else None
            except (OSError, ValueError):
                pass
        output_node = graph.output_node(preferred)
        base_sampler = graph.base_sampler(output_node)
        active = graph.ancestors(output_node)
        metadata["output_node"] = output_node
        metadata["samplers"] = [
            {"node_id": node_id, "stage": "base" if node_id == base_sampler else "detail",
             **{key: node["inputs"][key] for key in ("seed", "steps", "cfg", "denoise", "sampler_name", "scheduler")
                if key in node.get("inputs", {})}}
            for node_id, node in workflow.items()
            if node_id in active and node.get("class_type") in {"KSampler", "FaceDetailer"}
        ]
        metadata["identity_bindings"] = [
            {"node_id": node_id, "class_type": node["class_type"],
             "image_node": graph.link(node["inputs"].get("image")),
             "regional_mask": graph.link(node["inputs"].get("attn_mask")) is not None}
            for node_id, node in workflow.items()
            if node_id in graph.model_ancestors(base_sampler)
            and node.get("class_type") in {"IPAdapterFaceID", "IPAdapterAdvanced"}
        ]
        sampler = workflow[base_sampler]
    except ImageWorkflowGraphError as exc:
        metadata["workflow_error"] = str(exc)
        samplers = [node for node in workflow.values()
                    if isinstance(node, dict) and node.get("class_type") == "KSampler"]
        sampler = samplers[0] if len(samplers) == 1 else {}
    latent = next(
        (node for node_id, node in workflow.items() if node_id in active and isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage"),
        {},
    )
    sampler_inputs = sampler.get("inputs") if isinstance(sampler.get("inputs"), dict) else {}
    latent_inputs = latent.get("inputs") if isinstance(latent.get("inputs"), dict) else {}
    for key in ("steps", "cfg", "seed", "sampler_name", "scheduler"):
        if key in sampler_inputs:
            metadata[key] = sampler_inputs[key]
    for key in ("width", "height", "batch_size"):
        if key in latent_inputs:
            metadata[f"latent_{key}"] = latent_inputs[key]
    return metadata


class GenerationProviderError(Exception):
    """Raised when a generation provider cannot fulfill a request."""


class GenerationCancelledError(GenerationProviderError):
    """Raised when an in-flight provider request is cancelled by the user."""


class GenerationProviderName(str, Enum):
    LOCAL_COMFYUI = "local_comfyui"
    JIMENG_API = "jimeng_api"
    KLING_API = "kling_api"
    HAILUO_API = "hailuo_api"
    HTTP_VIDEO_API = "http_video_api"
    SEEDANCE_API = "seedance_api"
    HYBRID = "hybrid"


@dataclass
class ImageGenerationRequest:
    prompt: str
    output_path: str
    negative_prompt: Optional[str] = None
    width: int = 1024
    height: int = 576
    steps: int = 28
    cfg_scale: float = 6.0
    seed: int = -1
    reference_image: Optional[str] = None
    use_ipadapter: bool = False
    scene_type: Optional[str] = None
    quality_mode: Optional[str] = None
    optimization_mode: Optional[str] = None
    character_references: Optional[list[dict]] = None
    spatial_plan: Optional[dict] = None
    spatial_control_references: Optional[dict] = None
    spatial_asset_pack: Optional[dict] = None


@dataclass
class VideoGenerationRequest:
    prompt: str
    output_path: str
    negative_prompt: Optional[str] = None
    reference_image: Optional[str] = None
    end_image: Optional[str] = None
    # Seedance-style multimodal references. ``reference_image`` remains as a
    # backwards-compatible shortcut for local ComfyUI/SVD workflows.
    reference_images: Optional[list[str]] = None
    continuity_reference_image: Optional[str] = None
    reference_videos: Optional[list[str]] = None
    reference_audios: Optional[list[str]] = None
    audio_path: Optional[str] = None
    generate_audio: bool = False
    return_last_frame: Optional[bool] = None
    camera_fixed: Optional[bool] = None
    watermark: Optional[bool] = None
    output_format: Optional[str] = None
    resolution: Optional[str] = None
    model: Optional[str] = None
    request_mode: Optional[str] = None
    draft: Optional[bool] = None
    draft_task_id: Optional[str] = None
    multi_shot: bool = False
    extend_video: Optional[str] = None
    shot_plan: Optional[dict] = None
    duration_seconds: float = 5.0
    # The product target is mobile short-drama delivery. Callers can still
    # explicitly request landscape or square output for other workflows.
    aspect_ratio: str = "9:16"
    width: int = 768
    height: int = 1344
    fps: int = 8
    seed: int = -1
    motion_bucket_id: int = 127
    noise_aug_strength: float = 0.02
    quality_mode: Optional[str] = None
    repair_action: Optional[str] = None
    quality_pipeline: Optional[dict] = None
    local_task_id: Optional[int | str] = None
    progress_callback: Optional[Callable[[int, str], None]] = None
    cancellation_check: Optional[Callable[[], bool]] = None


@dataclass
class GenerationResult:
    provider: str
    output_path: str
    asset_type: str
    metadata: Dict[str, object]


class GenerationProvider(Protocol):
    name: GenerationProviderName

    def generate_image(self, request: ImageGenerationRequest) -> GenerationResult:
        ...

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        ...


class LocalComfyUIProvider:
    name = GenerationProviderName.LOCAL_COMFYUI

    def __init__(self, comfyui_service=None):
        self._comfyui_service = comfyui_service

    @property
    def comfyui_service(self):
        if self._comfyui_service is None:
            from src.services.comfyui_service import get_comfyui_service

            self._comfyui_service = get_comfyui_service()
        return self._comfyui_service

    def generate_image(self, request: ImageGenerationRequest) -> GenerationResult:
        requested_quality_mode = str(request.quality_mode or "").lower().strip()
        effective_quality_mode = COMFYUI_QUALITY_MODE_ALIASES.get(
            requested_quality_mode,
            request.quality_mode,
        )
        high_quality_request = str(effective_quality_mode or "").lower() in COMFYUI_HIGH_QUALITY_MODES
        enable_prompt_optimization = bool(
            settings.GENERATION_ENABLE_PROMPT_OPTIMIZATION
            and (high_quality_request or request.optimization_mode)
        )
        enable_parameter_optimization = bool(
            settings.GENERATION_ENABLE_PARAMETER_OPTIMIZATION
            and high_quality_request
        )
        reference_options = {}
        if request.character_references:
            reference_options["character_references"] = request.character_references
        output_path = self.comfyui_service.generate_image(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            output_path=request.output_path,
            width=request.width,
            height=request.height,
            steps=request.steps,
            cfg_scale=request.cfg_scale,
            seed=request.seed,
            reference_image=request.reference_image,
            use_ipadapter=request.use_ipadapter,
            scene_type=request.scene_type,
            quality_mode=effective_quality_mode,
            optimization_mode=request.optimization_mode,
            enable_realism=False,
            enable_prompt_optimization=enable_prompt_optimization,
            enable_parameter_optimization=enable_parameter_optimization,
            spatial_plan=request.spatial_plan,
            spatial_control_references=request.spatial_control_references,
            spatial_asset_pack=request.spatial_asset_pack,
            **reference_options,
        )
        return GenerationResult(
            provider=self.name.value,
            output_path=output_path,
            asset_type="image",
            metadata={
                "width": request.width,
                "height": request.height,
                "quality_mode": request.quality_mode,
                "effective_quality_mode": effective_quality_mode,
                "optimization_mode": request.optimization_mode,
                "prompt_optimization": enable_prompt_optimization,
                "parameter_optimization": enable_parameter_optimization,
                "workflow": _extract_workflow_image_metadata(output_path),
            },
        )

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        output_path = self.comfyui_service.generate_video(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt or "",
            reference_image=request.reference_image,
            end_image=request.end_image,
            continuity_reference_image=request.continuity_reference_image,
            reference_images=request.reference_images,
            reference_videos=request.reference_videos,
            reference_audios=request.reference_audios,
            output_path=request.output_path,
            width=request.width,
            height=request.height,
            duration_seconds=request.duration_seconds,
            fps=request.fps,
            seed=request.seed,
            motion_bucket_id=request.motion_bucket_id,
            noise_aug_strength=request.noise_aug_strength,
            quality_mode=request.quality_mode,
            repair_action=request.repair_action,
            quality_pipeline=request.quality_pipeline,
            shot_plan=request.shot_plan,
        )
        return GenerationResult(
            provider=self.name.value,
            output_path=output_path,
            asset_type="video",
            metadata={
                "duration_seconds": request.duration_seconds,
                "aspect_ratio": request.aspect_ratio,
                "width": request.width,
                "height": request.height,
                "fps": request.fps,
                "end_image": request.end_image,
                "continuity_reference_image": request.continuity_reference_image,
                "reference_images": list(request.reference_images or []),
                "reference_videos": list(request.reference_videos or []),
                "reference_audios": list(request.reference_audios or []),
                "motion_bucket_id": request.motion_bucket_id,
                "noise_aug_strength": request.noise_aug_strength,
                "quality_mode": request.quality_mode,
                "repair_action": request.repair_action,
                "quality_pipeline": request.quality_pipeline,
                "shot_plan": request.shot_plan,
                "spatial_asset_pack": (
                    request.shot_plan.get("spatial_asset_pack")
                    if isinstance(request.shot_plan, dict)
                    else None
                ),
            },
        )

    def release_generation_resources(self) -> None:
        self.comfyui_service.free_memory()


def release_generation_resources(provider) -> None:
    release = getattr(provider, "release_generation_resources", None)
    if callable(release):
        try:
            release()
        except Exception as exc:
            logger.warning("Could not release generation GPU resources before review: {}", exc)


class ApiVideoProvider:
    """Base class for external image/video generation providers."""

    name: GenerationProviderName
    env_prefix: str

    def __init__(self, endpoint: Optional[str] = None, api_key: Optional[str] = None):
        self.endpoint = endpoint or _provider_setting(f"{self.env_prefix}_ENDPOINT")
        self.api_key = api_key or _provider_setting(f"{self.env_prefix}_API_KEY")
        self.status_endpoint = _provider_setting(f"{self.env_prefix}_STATUS_ENDPOINT")
        self.result_endpoint = _provider_setting(f"{self.env_prefix}_RESULT_ENDPOINT")
        if (
            not self.status_endpoint
            and self.name == GenerationProviderName.SEEDANCE_API
            and _seedance_api_format(self.endpoint) in {"ark", "ark_v3", "volcengine", "volcengine_v3"}
            and self.endpoint
        ):
            # Ark uses GET on the create-task collection with the task id.
            self.status_endpoint = self.endpoint.rstrip("/") + "/{job_id}"
        self.timeout = int(_provider_setting(f"{self.env_prefix}_TIMEOUT_SECONDS", "1800"))
        self.poll_interval = float(_provider_setting(f"{self.env_prefix}_POLL_INTERVAL_SECONDS", "5"))
        self.max_polls = int(_provider_setting(f"{self.env_prefix}_MAX_POLLS", "240"))
        self.max_retries = max(0, int(_provider_setting(f"{self.env_prefix}_MAX_RETRIES", "2")))
        self.retry_backoff = max(0.0, float(_provider_setting(f"{self.env_prefix}_RETRY_BACKOFF_SECONDS", "1.0")))
        self.auth_header = _provider_setting(f"{self.env_prefix}_AUTH_HEADER", "Authorization")
        self.auth_scheme = _provider_setting(f"{self.env_prefix}_AUTH_SCHEME", "Bearer")
        self.last_result_metadata: dict[str, object] = {}

    def _ensure_configured(self) -> None:
        if not self.endpoint or not self.api_key:
            raise GenerationProviderError(
                f"{self.name.value} is not configured. Set {self.env_prefix}_ENDPOINT and {self.env_prefix}_API_KEY"
            )

    def generate_image(self, request: ImageGenerationRequest) -> GenerationResult:
        self._ensure_configured()
        raise GenerationProviderError(f"{self.name.value} image generation is not supported by this provider")

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        self._ensure_configured()
        self.last_result_metadata = {}
        self.last_result_metadata["requested_draft"] = bool(request.draft)
        self.last_result_metadata["requested_generate_audio"] = bool(request.generate_audio)
        self.last_result_metadata["requested_reference_audio"] = bool(
            request.audio_path or request.reference_audios
        )
        expected_duration = self._expected_provider_duration(request)
        try:
            requested_duration = float(request.duration_seconds)
            if requested_duration > 0:
                self.last_result_metadata["requested_duration_seconds"] = requested_duration
        except (TypeError, ValueError):
            pass
        if request.draft_task_id:
            self.last_result_metadata["promoted_draft_task_id"] = request.draft_task_id
        self._check_cancelled(request.cancellation_check)
        self._report_progress(request.progress_callback, 5, "queued")
        pending = self._load_pending_task(request.output_path, request)
        payload = None if pending else self._video_payload(request)
        headers = self._headers()
        if not pending:
            idempotency_key = self._idempotency_key(request)
            if idempotency_key:
                headers[idempotency_key[0]] = idempotency_key[1]
                self.last_result_metadata["idempotency_key_hash"] = hashlib.sha256(
                    idempotency_key[1].encode("utf-8")
                ).hexdigest()
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            self._check_cancelled(request.cancellation_check)
            if pending:
                self.last_result_metadata["provider_request_submitted"] = True
                task_id = str(pending["provider_task_id"])
                pending_status_endpoint = str(
                    pending.get("status_endpoint") or self.status_endpoint or ""
                ).strip()
                self.last_result_metadata["provider_task_id"] = task_id
                self.last_result_metadata["resumed_pending_task"] = True
                self._report_progress(request.progress_callback, 10, "resuming")
                data = {"job_id": task_id}
            else:
                pending_status_endpoint = self.status_endpoint
                # A transport error after the gateway accepted a POST is
                # ambiguous. Never blindly resubmit a paid generation request;
                # callers can inspect the provider/task state and retry manually.
                self.last_result_metadata["provider_request_submitted"] = True
                response = self._request_with_retry(
                    client,
                    "post",
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    retry_transport_errors=False,
                    retry_status_errors=False,
                )
                content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
                if content_type.startswith("video/") or content_type in {"application/octet-stream", "binary/octet-stream"}:
                    self._check_cancelled(request.cancellation_check)
                    final_path = self._write_video_bytes(response.content, request.output_path)
                    self._validate_provider_video(
                        final_path,
                        require_audio=_request_requires_audio(request),
                        expected_duration=expected_duration,
                        request=request,
                    )
                    self._record_output_hash(final_path)
                    self._report_progress(request.progress_callback, 100, "downloaded")
                    return GenerationResult(
                        provider=self.name.value,
                        output_path=final_path,
                        asset_type="video",
                        metadata={"endpoint": self.endpoint, "response_mode": "binary", **self.last_result_metadata},
                    )
                data = self._parse_json_response(response, "task creation")
                self._remember_result_metadata(data)
                if self.last_result_metadata.get("provider_task_id"):
                    self._write_pending_task(
                        request.output_path,
                        str(self.last_result_metadata["provider_task_id"]),
                        request,
                    )
            try:
                final_path = self._resolve_video_result(
                    client,
                    data,
                    request.output_path,
                    headers,
                    request.progress_callback,
                    request.cancellation_check,
                    status_endpoint=pending_status_endpoint,
                )
            except GenerationCancelledError:
                self._cancel_remote_task_if_supported(client, headers)
                if self.last_result_metadata.get("remote_cancel_requested"):
                    self._clear_pending_task(request.output_path)
                raise
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                if pending and status_code in {400, 404, 410}:
                    self._clear_pending_task(request.output_path)
                raise GenerationProviderError(
                    f"{self.name.value} provider returned HTTP {status_code} while polling "
                    f"task {self.last_result_metadata.get('provider_task_id') or '<unknown>'}"
                ) from exc
            except GenerationProviderError:
                if str(self.last_result_metadata.get("provider_status", "")).lower() in {
                    "failed", "error", "cancelled", "canceled", "expired",
                }:
                    self._clear_pending_task(request.output_path)
                raise
            self._validate_provider_video(
                final_path,
                require_audio=_request_requires_audio(request),
                expected_duration=expected_duration,
                request=request,
            )
            self._record_output_hash(final_path)
            # Ark's returned last-frame URL is intentionally short-lived. Save
            # it beside the accepted clip while it is still valid so a later
            # shot, retry, or project resume does not depend on the remote
            # URL remaining downloadable for 24 hours.
            self._persist_last_frame(client, request.output_path, headers)
            self._clear_pending_task(request.output_path)
            self._report_progress(request.progress_callback, 100, "downloaded")
        return GenerationResult(
            provider=self.name.value,
            output_path=final_path,
            asset_type="video",
            metadata={"endpoint": self.endpoint, "status_endpoint": self.status_endpoint or None, **self.last_result_metadata},
        )

    def _expected_provider_duration(self, request: VideoGenerationRequest) -> float | None:
        """Return a fixed duration only when the provider contract fixes it."""
        try:
            requested = float(request.duration_seconds)
        except (TypeError, ValueError):
            return None
        if requested <= 0 or request.draft_task_id:
            return None
        if self.name != GenerationProviderName.SEEDANCE_API:
            return requested
        mode = str(
            request.request_mode or _provider_setting("SEEDANCE_REQUEST_MODE", "reference")
        ).strip().lower()
        model = _seedance_model(model=request.model).lower()
        is_25 = _seedance_model_is_25(model)
        if is_25 and mode in {"edit", "extend"}:
            return None
        return requested

    def _record_output_hash(self, output_path: str) -> None:
        """Bind provider metadata to the exact accepted artifact bytes."""
        digest = hashlib.sha256()
        with Path(output_path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        self.last_result_metadata["video_sha256"] = digest.hexdigest()

    def _write_video_bytes(self, content: bytes, output_path: str) -> str:
        if not content:
            raise GenerationProviderError("Video response is empty")
        return _atomic_write_video(content, output_path)

    def _pending_task_path(self, output_path: str) -> Path:
        return Path(output_path).with_suffix(".provider.pending.json")

    def _provider_callback_path(self, output_path: str) -> Path:
        return Path(output_path).with_suffix(".provider.callback.json")

    def _load_provider_callback(self, output_path: str, task_id: str) -> dict | None:
        """Read a terminal webhook result written by the callback route."""
        path = self._provider_callback_path(output_path)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        callback_id = str(
            payload.get("draft_task_id")
            or payload.get("draft_id")
            or payload.get("id")
            or payload.get("task_id")
            or payload.get("job_id")
            or ""
        )
        state = str(payload.get("status") or payload.get("state") or "").strip().lower()
        if callback_id != str(task_id) or state not in {
            "completed", "complete", "succeeded", "success", "done",
            "failed", "error", "cancelled", "canceled", "expired",
        }:
            return None
        return payload

    def _load_pending_task(
        self, output_path: str, request: VideoGenerationRequest | None = None,
    ) -> dict[str, str] | None:
        path = self._pending_task_path(output_path)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._clear_pending_task(output_path)
            return None
        if not isinstance(data, dict) or not data.get("provider_task_id"):
            self._clear_pending_task(output_path)
            return None
        if data.get("provider") not in {None, self.name.value}:
            return None
        if data.get("endpoint") not in {None, self.endpoint}:
            return None
        stored_fingerprint = data.get("request_fingerprint")
        if stored_fingerprint and request is not None:
            expected_fingerprint = _video_request_fingerprint(
                request, provider_prefix=self.env_prefix,
            )
            if stored_fingerprint != expected_fingerprint:
                raise GenerationProviderError(
                    "A pending provider task belongs to a different video request; "
                    "use a new output path or clear the pending task only after checking the remote task."
                )
        pending = {"provider_task_id": str(data["provider_task_id"])}
        stored_status_endpoint = data.get("status_endpoint")
        if isinstance(stored_status_endpoint, str) and stored_status_endpoint.strip():
            pending["status_endpoint"] = stored_status_endpoint.strip()
        return pending

    def _write_pending_task(
        self, output_path: str, task_id: str, request: VideoGenerationRequest | None = None,
    ) -> None:
        path = self._pending_task_path(output_path)
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._provider_callback_path(output_path).unlink(missing_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
            temporary.write_text(json.dumps({
                "provider": self.name.value,
                "endpoint": self.endpoint,
                "status_endpoint": self.status_endpoint,
                "provider_task_id": task_id,
                "local_task_id": str(request.local_task_id) if request and request.local_task_id is not None else None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                # Keep the paid request's provider controls beside the remote
                # task. A later Celery retry can resume the accepted task
                # without silently falling back to the process defaults.
                "request_options": {
                    "provider": self.name.value,
                    "request_mode": request.request_mode if request else None,
                    "multi_shot": request.multi_shot if request else None,
                    "native_audio": request.generate_audio if request else None,
                    "draft": request.draft if request else None,
                    "draft_task_id": request.draft_task_id if request else None,
                    "model": request.model if request else None,
                    "resolution": request.resolution if request else None,
                    "output_format": request.output_format if request else None,
                    "return_last_frame": request.return_last_frame if request else None,
                    "camera_fixed": request.camera_fixed if request else None,
                    "watermark": request.watermark if request else None,
                    "duration_seconds": request.duration_seconds if request else None,
                    "local_task_id": str(request.local_task_id) if request and request.local_task_id is not None else None,
                } if request else {},
                **({
                    "request_fingerprint": _video_request_fingerprint(
                        request, provider_prefix=self.env_prefix,
                    )
                } if request else {}),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            early_callback = claim_early_callback(task_id)
            if isinstance(early_callback, dict):
                callback_path = self._provider_callback_path(output_path)
                callback_temporary = callback_path.with_name(f".{callback_path.name}.{uuid4().hex}.part")
                try:
                    callback_temporary.write_text(
                        json.dumps(early_callback, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                    callback_temporary.replace(callback_path)
                finally:
                    callback_temporary.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not persist pending provider task {}: {}", task_id, exc)
            try:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _clear_pending_task(self, output_path: str) -> None:
        try:
            self._pending_task_path(output_path).unlink(missing_ok=True)
            self._provider_callback_path(output_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not clear pending provider task sidecar: {}", exc)

    def _validate_provider_video(
        self,
        output_path: str,
        *,
        require_audio: bool = False,
        expected_duration: float | None = None,
        request: VideoGenerationRequest | None = None,
    ) -> None:
        """Reject malformed external-provider output before it enters the project."""
        api_format = (
            _seedance_api_format(self.endpoint)
            if self.name == GenerationProviderName.SEEDANCE_API
            else ""
        )
        native_ark_contract = api_format in {"ark", "ark_v3", "volcengine", "volcengine_v3"}
        validation_enabled = _provider_bool(f"{self.env_prefix}_VALIDATE_OUTPUT", True)
        if not validation_enabled:
            self.last_result_metadata["output_validation_status"] = "disabled_by_configuration"
            return
        if not shutil.which("ffprobe"):
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise GenerationProviderError(
                f"{self.name.value} output validation requires ffprobe; install ffprobe or explicitly disable "
                f"{self.env_prefix}_VALIDATE_OUTPUT for a non-production run"
            )
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries",
                    "stream=codec_type,codec_name,pix_fmt,width,height:format=duration",
                    "-of", "json", output_path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            raw_probe = str(result.stdout or "")
            try:
                probe = json.loads(raw_probe)
            except (TypeError, ValueError, json.JSONDecodeError):
                # Keep compatibility with older gateway test doubles and
                # unusual ffprobe wrappers that still emit key=value lines.
                values = raw_probe.splitlines()
                has_video = any(line.strip() == "codec_type=video" for line in values)
                has_audio = any(line.strip() == "codec_type=audio" for line in values)
                codec_values = [line.split("=", 1)[1] for line in values if line.startswith("codec_name=")]
                pixel_format_values = [line.split("=", 1)[1] for line in values if line.startswith("pix_fmt=")]
                width_values = [line.split("=", 1)[1] for line in values if line.startswith("width=")]
                height_values = [line.split("=", 1)[1] for line in values if line.startswith("height=")]
                duration_values = [line.split("=", 1)[1] for line in values if line.startswith("duration=")]
            else:
                streams = probe.get("streams") if isinstance(probe, dict) else []
                streams = streams if isinstance(streams, list) else []
                video_stream = next(
                    (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
                    {},
                )
                has_video = bool(video_stream)
                has_audio = any(
                    isinstance(stream, dict) and stream.get("codec_type") == "audio"
                    for stream in streams
                )
                codec_values = [str(video_stream.get("codec_name"))] if video_stream.get("codec_name") else []
                pixel_format_values = [str(video_stream.get("pix_fmt"))] if video_stream.get("pix_fmt") else []
                width_values = [str(video_stream.get("width"))] if video_stream.get("width") is not None else []
                height_values = [str(video_stream.get("height"))] if video_stream.get("height") is not None else []
                format_data = probe.get("format") if isinstance(probe, dict) else {}
                duration_values = [str(format_data.get("duration"))] if isinstance(format_data, dict) and format_data.get("duration") is not None else []
            if codec_values:
                self.last_result_metadata["video_codec"] = codec_values[0]
            if pixel_format_values:
                pixel_format = pixel_format_values[0]
                self.last_result_metadata["video_pixel_format"] = pixel_format
                self.last_result_metadata["video_high_bit_depth"] = any(
                    token in pixel_format.lower() for token in ("p10", "p12", "p14")
                )
            width = int(width_values[0]) if width_values else 0
            height = int(height_values[0]) if height_values else 0
            if width > 0 and height > 0:
                self.last_result_metadata["video_width"] = width
                self.last_result_metadata["video_height"] = height
                if self.name == GenerationProviderName.SEEDANCE_API:
                    self._validate_native_ark_geometry(width, height, request)
            requested_resolution = str(
                self.last_result_metadata.get("requested_resolution")
                or (request.resolution if request else "")
                or ""
            ).strip().lower()
            requested_model = _seedance_model(model=request.model) if request else ""
            if request is not None:
                high_bit_depth = self.last_result_metadata.get("video_high_bit_depth") is True
                codec = str(self.last_result_metadata.get("video_codec") or "").lower()
                requested_output_format = str(
                    request.output_format
                    or _provider_setting("SEEDANCE_OUTPUT_FORMAT", "mp4")
                ).strip().lower()
                pixel_format = str(
                    self.last_result_metadata.get("video_pixel_format") or ""
                ).lower()
                if native_ark_contract and (
                    _seedance_model_is_25(requested_model)
                    and requested_resolution == "1080p"
                    and requested_output_format == "mov"
                ):
                    # Ark's 2.5 MOV path is the color-fidelity path: H.264
                    # video with 4:4:4 chroma and PCM/AAC audio, rather than
                    # the MP4 path's 10-bit HEVC contract.
                    if codec not in {"h264", "avc1"} or "yuv444" not in pixel_format:
                        raise ValueError(
                            "Native Seedance 2.5 1080p MOV output must use H.264 4:4:4; "
                            f"received codec={codec or 'unknown'}, pixel_format={pixel_format or 'unknown'}"
                        )
                elif native_ark_contract and (
                    (
                        _seedance_model_is_25(requested_model)
                        and requested_resolution == "1080p"
                    )
                    or (
                        _seedance_model_is_20(requested_model)
                        and not _seedance_model_is_20_limited(requested_model)
                        and requested_resolution == "4k"
                    )
                ) and (not high_bit_depth or codec not in {"hevc", "h265"}):
                    raise ValueError(
                        "Native high-resolution Seedance output must be 10-bit HEVC; "
                        f"received codec={codec or 'unknown'}, "
                        f"pixel_format={pixel_format or 'unknown'}"
                    )
            duration = float(duration_values[0]) if duration_values else 0.0
            if not has_video or not math.isfinite(duration) or duration <= 0:
                raise ValueError("ffprobe found no video stream or a non-positive duration")
            if expected_duration is not None and float(expected_duration) > 0:
                if not math.isfinite(float(expected_duration)):
                    raise ValueError("expected video duration is not finite")
                tolerance = max(
                    settings.GENERATION_VIDEO_DURATION_SYNC_TOLERANCE_SECONDS,
                    float(expected_duration) * 0.08,
                )
                if abs(duration - float(expected_duration)) > tolerance:
                    raise ValueError(
                        f"duration drift: requested {float(expected_duration):.3f}s, got {duration:.3f}s"
                    )
            if require_audio and not has_audio:
                raise ValueError("audio was requested but ffprobe found no audio stream")
            if self.name == GenerationProviderName.SEEDANCE_API:
                self._validate_native_ark_temporal_quality(output_path, require_audio=require_audio)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise GenerationProviderError(
                f"{self.name.value} returned an invalid video artifact: {output_path} ({exc})"
            ) from exc

    def _validate_native_ark_geometry(
        self,
        width: int,
        height: int,
        request: VideoGenerationRequest | None,
    ) -> None:
        """Reject Ark output that would require destructive postprocess cropping."""
        if request is None:
            return
        mode = str(request.request_mode or _provider_setting("SEEDANCE_REQUEST_MODE", "reference")).strip().lower()
        first_last = bool(
            request.end_image
            and len(_unique_media_paths(request.reference_images or []) or ([request.reference_image] if request.reference_image else [])) == 1
            and not request.reference_videos
            and not request.reference_audios
            and not request.extend_video
        )
        # Ark locks geometry to the input for first/last-frame, edit and extend
        # tasks; a caller's mobile ratio must not be treated as an expectation.
        expected_ratio = str(request.aspect_ratio or "").strip().lower()
        if mode in {"edit", "extend"} or first_last or expected_ratio in {"", "adaptive"}:
            expected_ratio = ""
        ratio_map = {
            "16:9": 16 / 9,
            "4:3": 4 / 3,
            "1:1": 1.0,
            "3:4": 3 / 4,
            "9:16": 9 / 16,
            "21:9": 21 / 9,
        }
        target_ratio = ratio_map.get(expected_ratio)
        actual_ratio = width / height
        if target_ratio is not None and abs(actual_ratio - target_ratio) / target_ratio > 0.025:
            raise ValueError(
                f"geometry drift: requested ratio {expected_ratio}, got {width}x{height}"
            )
        resolution = str(
            self.last_result_metadata.get("requested_resolution")
            or request.resolution
            or _provider_setting("SEEDANCE_RESOLUTION", "720p")
        ).strip().lower()
        minimum_short_edge = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}.get(resolution)
        if minimum_short_edge and min(width, height) < minimum_short_edge * 0.9:
            raise ValueError(
                f"resolution drift: requested {resolution}, got {width}x{height}"
            )

    def _validate_native_ark_temporal_quality(
        self, output_path: str, *, require_audio: bool = False,
    ) -> None:
        """Reject technically playable Ark output with obvious temporal failures."""
        metrics = video_candidate_metrics(output_path)
        if metrics.get("status") != "available":
            self.last_result_metadata["temporal_quality_status"] = "unavailable"
            raise ValueError(
                "temporal quality evidence is unavailable: "
                f"{metrics.get('error') or 'video frames could not be sampled'}"
            )
        temporal_error = temporal_sample_evidence_error(metrics, context="native provider output")
        if temporal_error:
            self.last_result_metadata["temporal_quality_status"] = "insufficient"
            raise ValueError(temporal_error)
        self.last_result_metadata["temporal_quality"] = {
            key: metrics.get(key)
            for key in (
                "motion_energy", "max_static_run_seconds", "max_black_run_seconds",
                "brightness_step_p95", "motion_jitter_ratio", "temporal_jump_ratio",
                "temporal_jump_p95",
                "technical_score",
                "audio_video_start_delta_seconds",
            )
            if key in metrics
        }
        self.last_result_metadata["temporal_quality_status"] = "available"
        if require_audio or metrics.get("audio_present") is True:
            audio_signal_status = str(metrics.get("audio_signal_status") or "").strip().lower()
            if audio_signal_status != "usable":
                raise ValueError(
                    "audio signal is not usable: "
                    f"{metrics.get('audio_signal_status') or 'unavailable'}"
                )
            if str(metrics.get("audio_clipping_status") or "").strip().lower() == "clipped":
                raise ValueError("audio signal is clipped at digital full scale")
            audio_delta = metrics.get("audio_duration_delta_seconds")
            if audio_delta is not None and float(audio_delta) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS:
                raise ValueError(
                    "audio/video duration drift: "
                    f"{float(audio_delta):.3f}s exceeds {settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS:.3f}s"
                )
            start_delta = metrics.get("audio_video_start_delta_seconds")
            if start_delta is not None and abs(float(start_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS:
                raise ValueError(
                    "audio/video stream start offset: "
                    f"{abs(float(start_delta)):.3f}s exceeds {settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS:.3f}s"
                )
        static_seconds = float(metrics.get("max_static_run_seconds") or 0.0)
        motion_energy = float(metrics.get("motion_energy") or 0.0)
        if (
            static_seconds > float(settings.GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS)
            and motion_energy < 0.4
        ):
            raise ValueError(
                "temporal quality gate: frozen/static run "
                f"{static_seconds:.3f}s with motion_energy={motion_energy:.3f}"
            )
        black_seconds = float(metrics.get("max_black_run_seconds") or 0.0)
        if black_seconds > float(settings.GENERATION_VIDEO_MAX_BLACK_SECONDS):
            raise ValueError(
                "temporal quality gate: black-frame run "
                f"{black_seconds:.3f}s exceeds {settings.GENERATION_VIDEO_MAX_BLACK_SECONDS:.3f}s"
            )
        black_frame_ratio = float(metrics.get("black_frame_ratio") or 0.0)
        if black_frame_ratio > float(settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO):
            raise ValueError(
                "temporal quality gate: too many black frames "
                f"black_frame_ratio={black_frame_ratio:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO:.3f}"
            )
        brightness_step = float(metrics.get("brightness_step_p95") or 0.0)
        if brightness_step > float(settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95):
            raise ValueError(
                "temporal quality gate: exposure jumps "
                f"brightness_step_p95={brightness_step:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95:.3f}"
            )
        motion_jitter = float(metrics.get("motion_jitter_ratio") or 0.0)
        if motion_jitter > float(settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO):
            raise ValueError(
                "temporal quality gate: unstable motion cadence "
                f"motion_jitter_ratio={motion_jitter:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO:.3f}"
            )
        temporal_jump_ratio = float(metrics.get("temporal_jump_ratio") or 0.0)
        if temporal_jump_ratio > float(settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO):
            raise ValueError(
                "temporal quality gate: repeated temporal visual resets "
                f"temporal_jump_ratio={temporal_jump_ratio:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO:.3f}"
            )
        temporal_jump_p95 = float(metrics.get("temporal_jump_p95") or 0.0)
        if temporal_jump_p95 > float(settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95):
            raise ValueError(
                "temporal quality gate: extreme temporal visual reset "
                f"temporal_jump_p95={temporal_jump_p95:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95:.3f}"
            )

    def _headers(self) -> dict[str, str]:
        token = self.api_key if not self.auth_scheme else f"{self.auth_scheme} {self.api_key}"
        return {self.auth_header: token, "Accept": "application/json"}

    def _idempotency_key(self, request: VideoGenerationRequest) -> tuple[str, str] | None:
        """Return a stable create-request key when the gateway supports deduplication."""
        enabled = _provider_setting(f"{self.env_prefix}_IDEMPOTENCY_ENABLED", "true")
        if str(enabled).strip().lower() not in {"1", "true", "yes", "on"}:
            return None
        header = str(
            _provider_setting(f"{self.env_prefix}_IDEMPOTENCY_KEY_HEADER", "Idempotency-Key")
        ).strip()
        if not header:
            return None
        return header, _video_request_fingerprint(
            request, provider_prefix=self.env_prefix,
        )

    def _request_with_retry(
        self,
        client,
        method: str,
        url: str,
        *,
        retry_transport_errors: bool = True,
        retry_status_errors: bool = True,
        **kwargs,
    ):
        """Retry only transient transport/server failures with bounded backoff."""
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            retry_response = None
            try:
                response = getattr(client, method)(url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                retry_response = exc.response
                status = exc.response.status_code if exc.response is not None else 0
                retryable = status in {408, 409, 425, 429} or status >= 500
                if not retry_status_errors:
                    # A 429 is an explicit rejection and is safe to retry;
                    # other creation responses may be ambiguous after the
                    # provider accepted the task.
                    retryable = status == 429
                if not retryable or attempt >= attempts - 1:
                    if not retry_status_errors:
                        detail = ""
                        try:
                            body = exc.response.json() if exc.response is not None else None
                            detail = _format_provider_error(body) if body else ""
                        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                            detail = str(getattr(exc.response, "text", "") or "").strip()
                        retry_after = getattr(exc.response, "headers", {}).get("Retry-After") if exc.response is not None else None
                        suffix = f": {detail[:500]}" if detail else ""
                        if retry_after:
                            suffix += f" (Retry-After: {retry_after})"
                        raise GenerationProviderError(
                            f"{self.name.value} provider returned HTTP {status} for {method.upper()} {url}{suffix}"
                        ) from exc
                    raise
            except httpx.RequestError as exc:
                if not retry_transport_errors or attempt >= attempts - 1:
                    raise GenerationProviderError(
                        f"{self.name.value} transport failed while requesting {method.upper()} {url}"
                    ) from exc
            delay = self._retry_delay(retry_response, attempt)
            if delay:
                time.sleep(delay)
        raise GenerationProviderError(f"{self.name.value} request failed after retries")

    def _retry_delay(self, response, attempt: int) -> float:
        """Honor a gateway Retry-After hint before falling back to backoff."""
        retry_after = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
        if retry_after is not None:
            try:
                return max(0.0, min(600.0, float(str(retry_after).strip())))
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(str(retry_after))
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max(0.0, min(600.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
        return max(0.0, min(600.0, self.retry_backoff * (2 ** attempt)))

    def _cancel_remote_task_if_supported(self, client, headers: dict[str, str]) -> None:
        """Best-effort cancellation for queued native Ark tasks.

        Ark only cancels tasks while they are queued; DELETE on a running task
        is rejected. The local cancellation must therefore remain authoritative
        and this cleanup must never replace the original cancellation error.
        """
        if self.name != GenerationProviderName.SEEDANCE_API:
            return
        api_format = _seedance_api_format(self.endpoint)
        if api_format not in {"ark", "ark_v3", "volcengine", "volcengine_v3"}:
            return
        task_id = self.last_result_metadata.get("provider_task_id")
        if not task_id or not self.status_endpoint:
            return
        cancel_url = self.status_endpoint.replace("{job_id}", str(task_id)).replace("{request_id}", str(task_id))
        try:
            response = client.delete(cancel_url, headers=headers)
            response.raise_for_status()
            self.last_result_metadata["remote_cancel_requested"] = True
        except Exception as exc:
            self.last_result_metadata["remote_cancel_requested"] = False
            logger.info("Remote provider task could not be cancelled (it may already be running): {}", exc)

    def _video_payload(self, request: VideoGenerationRequest) -> dict:
        references = []
        for index, path in enumerate(request.reference_images or [], start=1):
            references.append({"id": f"Image{index}", "type": "image", "source": _file_data_url(path)})
        for index, path in enumerate(request.reference_videos or [], start=1):
            references.append({"id": f"Video{index}", "type": "video", "source": _file_data_url(path)})
        for index, path in enumerate(request.reference_audios or [], start=1):
            references.append({"id": f"Audio{index}", "type": "audio", "source": _file_data_url(path)})

        # Keep the legacy single-image field populated for gateways that have
        # not adopted the multimodal contract yet.
        primary_image = request.reference_image
        if primary_image is None and request.reference_images:
            primary_image = request.reference_images[0]

        payload = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or "",
            "reference_image": _file_data_url(primary_image),
            "end_image": _file_data_url(request.end_image),
            "references": references,
            "audio": _file_data_url(request.audio_path),
            "generate_audio": request.generate_audio,
            "return_last_frame": _provider_bool_value(request.return_last_frame, "SEEDANCE_RETURN_LAST_FRAME"),
            "camera_fixed": _provider_bool_value(request.camera_fixed, "SEEDANCE_CAMERA_FIXED"),
            "watermark": _provider_bool_value(request.watermark, "SEEDANCE_WATERMARK"),
            "output_format": request.output_format,
            "resolution": request.resolution,
            "request_mode": request.request_mode,
            "draft": _provider_bool_value(request.draft, "SEEDANCE_DRAFT"),
            "draft_task_id": request.draft_task_id,
            "multi_shot": request.multi_shot,
            "extend_video": _file_data_url(request.extend_video),
            "shot_plan": request.shot_plan or {},
            "duration_seconds": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "width": request.width,
            "height": request.height,
            "fps": request.fps,
            "seed": request.seed,
            "motion_bucket_id": request.motion_bucket_id,
            "noise_aug_strength": request.noise_aug_strength,
        }
        return payload

    def _resolve_video_result(
        self,
        client,
        data: dict,
        output_path: str,
        headers: dict[str, str],
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancellation_check: Optional[Callable[[], bool]] = None,
        status_endpoint: str | None = None,
    ) -> str:
        self._remember_result_metadata(data)
        direct = _extract_video_url(data)
        if direct:
            final_path = self._download_video_with_retry(client, str(direct), output_path, headers)
            self._report_progress(progress_callback, 100, "downloaded")
            return final_path
        encoded = _extract_first(data, ("video_base64", "base64", "output_base64"))
        if encoded:
            final_path = _write_base64_video(str(encoded), output_path)
            self._report_progress(progress_callback, 100, "downloaded")
            return final_path
        job_id = _extract_first(data, ("job_id", "task_id", "request_id", "id"))
        if not job_id:
            raise GenerationProviderError(
                f"{self.name.value} response has no video_url/video_base64/job_id/request_id"
            )
        effective_status_endpoint = str(status_endpoint or self.status_endpoint or "").strip()
        if not effective_status_endpoint:
            raise GenerationProviderError(f"{self.name.value} returned job_id but {self.env_prefix}_STATUS_ENDPOINT is not configured")
        status_url = effective_status_endpoint.replace("{job_id}", str(job_id)).replace("{request_id}", str(job_id))
        # Keep both guards: ``timeout`` is the wall-clock contract exposed to
        # operators, while ``max_polls`` protects against a bad interval or a
        # gateway that never advances its task state.  The old implementation
        # only enforced max_polls, so changing the configured timeout had no
        # effect on an in-flight async task.
        poll_deadline = time.monotonic() + max(0.001, float(self.timeout))
        for poll_index in range(self.max_polls):
            if time.monotonic() >= poll_deadline:
                break
            self._check_cancelled(cancellation_check)
            callback_status = self._load_provider_callback(output_path, str(job_id))
            if callback_status is not None:
                status = callback_status
                self.last_result_metadata["callback_received"] = True
            else:
                status_response = self._request_with_retry(client, "get", status_url, headers=headers)
                status = self._parse_json_response(status_response, "task status")
            self._remember_result_metadata(status)
            state = str(_extract_first(status, ("status", "state", "task_status")) or "").lower()
            terminal_state = state in {"completed", "complete", "succeeded", "success", "done"}
            self._report_progress(
                progress_callback,
                99 if terminal_state else min(
                    95, 10 + int(((poll_index + 1) / max(self.max_polls, 1)) * 85)
                ),
                state or "processing",
            )
            if state in {"failed", "error", "cancelled", "canceled", "expired"}:
                self._report_progress(progress_callback, 100, "failed")
                detail = _format_provider_error(status)
                raise GenerationProviderError(f"{self.name.value} job {state}: {detail}")
            direct = _extract_video_url(status)
            if direct:
                final_path = self._download_video_with_retry(client, str(direct), output_path, headers)
                self._report_progress(progress_callback, 100, "downloaded")
                return final_path
            encoded = _extract_first(status, ("video_base64", "base64", "output_base64"))
            if encoded:
                final_path = _write_base64_video(str(encoded), output_path)
                self._report_progress(progress_callback, 100, "downloaded")
                return final_path
            state = str(_extract_first(status, ("status", "state", "task_status")) or "").lower()
            if state in {"completed", "complete", "succeeded", "success", "done"} and self.result_endpoint:
                result_response = self._request_with_retry(
                    client,
                    "get",
                    self.result_endpoint.replace("{job_id}", str(job_id)).replace("{request_id}", str(job_id)),
                    headers=headers,
                )
                result = self._parse_json_response(result_response, "task result")
                self._remember_result_metadata(result)
                direct = _extract_video_url(result)
                if direct:
                    final_path = self._download_video_with_retry(client, str(direct), output_path, headers)
                    self._report_progress(progress_callback, 100, "downloaded")
                    return final_path
                encoded = _extract_first(result, ("video_base64", "base64", "output_base64"))
                if encoded:
                    final_path = _write_base64_video(str(encoded), output_path)
                    self._report_progress(progress_callback, 100, "downloaded")
                    return final_path
            if state in {"completed", "complete", "succeeded", "success", "done"} and callback_status is not None:
                # A webhook may only acknowledge completion. Fetch the
                # terminal artifact from the status resource before declaring
                # a successful remote task unusable.
                fallback_response = self._request_with_retry(
                    client,
                    "get",
                    status_url,
                    headers=headers,
                )
                fallback = self._parse_json_response(fallback_response, "completed task status")
                self._remember_result_metadata(fallback)
                fallback_state = str(
                    _extract_first(fallback, ("status", "state", "task_status")) or ""
                ).lower()
                if fallback_state in {"failed", "error", "cancelled", "canceled", "expired"}:
                    self._report_progress(progress_callback, 100, "failed")
                    detail = _format_provider_error(fallback)
                    raise GenerationProviderError(
                        f"{self.name.value} job {fallback_state}: {detail}"
                    )
                direct = _extract_video_url(fallback)
                if direct:
                    final_path = self._download_video_with_retry(client, str(direct), output_path, headers)
                    self._report_progress(progress_callback, 100, "downloaded")
                    return final_path
                encoded = _extract_first(fallback, ("video_base64", "base64", "output_base64"))
                if encoded:
                    final_path = _write_base64_video(str(encoded), output_path)
                    self._report_progress(progress_callback, 100, "downloaded")
                    return final_path
            if state in {"completed", "complete", "succeeded", "success", "done"}:
                raise GenerationProviderError(
                    f"{self.name.value} job completed without a video result"
                )
            self._check_cancelled(cancellation_check)
            remaining = poll_deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(max(0.0, self.poll_interval), remaining))
        self._report_progress(progress_callback, 100, "timeout")
        task_id = self.last_result_metadata.get("provider_task_id")
        task_suffix = f" (provider_task_id={task_id})" if task_id else ""
        raise GenerationProviderError(
            f"{self.name.value} job timed out after {self.timeout}s or {self.max_polls} polls"
            f"{task_suffix}"
        )

    @staticmethod
    def _report_progress(callback: Optional[Callable[[int, str], None]], progress: int, state: str) -> None:
        if not callable(callback):
            return
        try:
            callback(max(0, min(99, int(progress))), str(state or "processing"))
        except Exception:
            # Progress reporting must never turn a successful provider result
            # into a failed generation task.
            logger.debug("Video provider progress callback failed", exc_info=True)

    @staticmethod
    def _check_cancelled(cancellation_check: Optional[Callable[[], bool]]) -> None:
        if not callable(cancellation_check):
            return
        try:
            cancelled = bool(cancellation_check())
        except Exception as exc:
            # A status-store failure must not silently cancel a paid provider job.
            logger.warning("Could not check video generation cancellation state: {}", exc)
            return
        if cancelled:
            raise GenerationCancelledError("Video generation was cancelled by the user")

    def _remember_result_metadata(self, data) -> None:
        provider_model = _extract_first(data, ("model",))
        if provider_model:
            self.last_result_metadata["provider_model"] = str(provider_model)
        state = _extract_first(data, ("status", "state", "task_status"))
        if state:
            self.last_result_metadata["provider_task_status"] = str(state)
        last_frame = _extract_media_url(data, ("last_frame_url", "last_frame", "last_frame_uri"))
        if last_frame:
            self.last_result_metadata["last_frame_url"] = last_frame
        draft_task_id = _extract_first(data, ("draft_task_id", "draft_id"))
        if draft_task_id:
            self.last_result_metadata["provider_draft_task_id"] = str(draft_task_id)
        task_id = _extract_first(data, ("task_id", "job_id", "request_id", "id"))
        # Some gateways wrap a Draft in a request envelope and expose both
        # identifiers. Only the Draft ID can be promoted later, so it must be
        # the resumable/persisted task identity for an explicit Draft run.
        if self.last_result_metadata.get("requested_draft") and draft_task_id:
            task_id = draft_task_id
        if task_id:
            self.last_result_metadata["provider_task_id"] = str(task_id)
        created_at = _extract_first(data, ("created_at", "createdAt", "create_time"))
        if created_at is not None and not isinstance(created_at, (dict, list)):
            self.last_result_metadata["provider_created_at"] = str(created_at)
        expires_at = _extract_first(data, ("expires_at", "expiresAt", "expire_time", "expiration_time"))
        if expires_at is not None and not isinstance(expires_at, (dict, list)):
            self.last_result_metadata["provider_expires_at"] = str(expires_at)
        duration = _extract_first(data, ("duration", "duration_seconds", "video_duration"))
        try:
            if duration is not None:
                self.last_result_metadata["provider_duration_seconds"] = float(duration)
        except (TypeError, ValueError):
            pass
        for source_key, metadata_key in (
            ("resolution", "provider_resolution"),
            ("ratio", "provider_ratio"),
            ("output_format", "provider_output_format"),
            ("service_tier", "provider_service_tier"),
        ):
            value = _extract_first(data, (source_key,))
            if value is not None and not isinstance(value, (dict, list)):
                self.last_result_metadata[metadata_key] = str(value)
        fps = _extract_first(data, ("framespersecond", "fps", "frame_rate"))
        try:
            if fps is not None:
                self.last_result_metadata["provider_fps"] = float(fps)
        except (TypeError, ValueError):
            pass
        seed = _extract_first(data, ("seed",))
        if seed is not None and not isinstance(seed, (dict, list)):
            self.last_result_metadata["provider_seed"] = seed
        usage = _extract_first(data, ("usage",))
        if isinstance(usage, dict):
            for source_key, metadata_key in (
                ("completion_tokens", "provider_completion_tokens"),
                ("total_tokens", "provider_total_tokens"),
            ):
                value = usage.get(source_key)
                if value is not None:
                    try:
                        self.last_result_metadata[metadata_key] = int(value)
                    except (TypeError, ValueError):
                        pass
        error = _extract_first(data, ("error", "message", "detail"))
        if error:
            self.last_result_metadata["provider_error"] = _format_provider_error(data)
            if isinstance(error, dict):
                code = error.get("code") or error.get("type") or error.get("error_code")
                if code:
                    self.last_result_metadata["provider_error_code"] = str(code)
        status = _extract_first(data, ("status", "state", "task_status"))
        if status:
            self.last_result_metadata["provider_status"] = str(status)

    def _parse_json_response(self, response, context: str):
        """Convert provider JSON failures into actionable generation errors."""
        try:
            data = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            body = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
            if len(body) > 240:
                body = body[:240] + "…"
            detail = f": {body}" if body else ""
            raise GenerationProviderError(
                f"{self.name.value} returned invalid JSON for {context}{detail}"
            ) from exc
        if not isinstance(data, (dict, list)):
            raise GenerationProviderError(
                f"{self.name.value} returned an invalid JSON shape for {context}"
            )
        return data

    def _download_video_with_retry(self, client, url: str, output_path: str, headers: dict[str, str]) -> str:
        _validate_provider_download_url(url, self.name.value)
        response = self._request_with_retry(
            client, "get", url, headers=self._media_download_headers(url, headers),
        )
        content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
        if "json" in content_type or content_type.startswith("text/"):
            try:
                detail = response.json()
            except Exception:
                detail = response.content[:200]
            raise GenerationProviderError(f"{self.name.value} returned a non-video download response: {detail}")
        return _atomic_write_video(response.content, output_path)

    def _media_download_headers(self, url: str, headers: dict[str, str]) -> dict[str, str]:
        """Do not forward provider credentials to signed media/CDN URLs."""
        parsed_media = urlparse(str(url))
        parsed_endpoint = urlparse(str(self.endpoint or ""))
        media_host = (parsed_media.hostname or "").lower()
        endpoint_host = (parsed_endpoint.hostname or "").lower()
        if media_host and endpoint_host and media_host != endpoint_host:
            return {"Accept": "video/*, image/*, application/octet-stream"}
        return headers

    def _persist_last_frame(self, client, output_path: str, headers: dict[str, str]) -> str | None:
        """Download a provider continuity frame before its URL expires.

        The frame is an optimization for continuity, not the video result
        itself. A failure must therefore leave a successful generation intact;
        the task layer can still extract a local frame from the downloaded
        video as a fallback.
        """
        url = self.last_result_metadata.get("last_frame_url")
        if not isinstance(url, str) or not url.strip():
            return None
        target = Path(output_path).with_name(f"{Path(output_path).stem}.last_frame.png")
        temporary = target.with_name(f".{target.name}.part")
        try:
            response = self._request_with_retry(
                client, "get", url.strip(),
                headers=self._media_download_headers(url.strip(), headers),
            )
            content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
            if "json" in content_type or content_type.startswith("text/"):
                raise GenerationProviderError("last-frame endpoint returned a non-image response")
            if content_type and not content_type.startswith("image/") and content_type not in {
                "application/octet-stream",
                "binary/octet-stream",
            }:
                raise GenerationProviderError("last-frame endpoint returned a non-image response")
            if not response.content:
                raise GenerationProviderError("last-frame endpoint returned an empty response")
            try:
                from PIL import Image

                with Image.open(BytesIO(response.content)) as image:
                    image.verify()
            except Exception as exc:
                raise GenerationProviderError(
                    "last-frame endpoint returned invalid image bytes"
                ) from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(response.content)
            temporary.replace(target)
            self.last_result_metadata["last_frame_path"] = str(target)
            return str(target)
        except (GenerationProviderError, OSError, httpx.HTTPError) as exc:
            logger.warning("Could not persist provider last frame; using video extraction fallback: {}", exc)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return None


class JimengApiProvider(ApiVideoProvider):
    name = GenerationProviderName.JIMENG_API
    env_prefix = "JIMENG"


class KlingApiProvider(ApiVideoProvider):
    name = GenerationProviderName.KLING_API
    env_prefix = "KLING"


class HailuoApiProvider(ApiVideoProvider):
    name = GenerationProviderName.HAILUO_API
    env_prefix = "HAILUO"


class HttpVideoApiProvider(ApiVideoProvider):
    name = GenerationProviderName.HTTP_VIDEO_API
    env_prefix = "HTTP_VIDEO"


class SeedanceApiProvider(ApiVideoProvider):
    """Seedance reference-to-video adapter.

    The endpoint remains configurable because hosted gateways expose different
    queue/status URLs. The request shape follows the public reference API
    convention: separate image/video/audio URL arrays plus Seedance controls.
    """

    name = GenerationProviderName.SEEDANCE_API
    env_prefix = "SEEDANCE"

    def _video_payload(self, request: VideoGenerationRequest) -> dict:
        api_format = _seedance_api_format(self.endpoint)
        if api_format in {"ark", "ark_v3", "volcengine", "volcengine_v3"}:
            return self._ark_video_payload(request)
        if api_format not in {"legacy", "generic", "compatible"}:
            raise GenerationProviderError(
                f"Unsupported SEEDANCE_API_FORMAT: {api_format}; choose legacy or ark_v3"
            )
        self.last_result_metadata["requested_model"] = _seedance_model(model=request.model)
        self._validate_reference_limits(request)
        prompt = _seedance_prompt(request)
        image_paths = _unique_media_paths(request.reference_images or [])
        if not image_paths and request.reference_image:
            image_paths = [request.reference_image]
        request_mode = str(
            request.request_mode or _provider_setting("SEEDANCE_REQUEST_MODE", "reference")
        ).strip().lower()
        explicit_frame_mode = request_mode in {"first_frame", "first_last_frame"}
        if (
            request.continuity_reference_image
            and not explicit_frame_mode
            and request.continuity_reference_image not in image_paths
        ):
            image_paths.append(request.continuity_reference_image)
        video_paths = _unique_media_paths(request.reference_videos or [])
        audio_paths = _unique_media_paths(request.reference_audios or [])
        if not audio_paths and request.audio_path:
            audio_paths = [request.audio_path]
        payload = {
            "prompt": prompt,
            "image_urls": [
                _file_data_url(path) for path in image_paths if path
            ],
            "video_urls": [
                _file_data_url(path) for path in video_paths if path
            ],
            "audio_urls": [
                _file_data_url(path) for path in audio_paths if path
            ],
            "duration": _seedance_duration(request.duration_seconds),
            "resolution": request.resolution or _provider_setting("SEEDANCE_RESOLUTION", "720p"),
            "aspect_ratio": request.aspect_ratio,
            "generate_audio": request.generate_audio,
            "bitrate_mode": _provider_setting("SEEDANCE_BITRATE_MODE", "high"),
            "codec": _provider_setting("SEEDANCE_CODEC", "H264"),
            "return_last_frame": _provider_bool_value(request.return_last_frame, "SEEDANCE_RETURN_LAST_FRAME"),
            "camera_fixed": _provider_bool_value(request.camera_fixed, "SEEDANCE_CAMERA_FIXED"),
            "watermark": _provider_bool_value(request.watermark, "SEEDANCE_WATERMARK"),
            "draft": _provider_bool_value(request.draft, "SEEDANCE_DRAFT"),
            "output_format": (
                (request.output_format or _provider_setting("SEEDANCE_OUTPUT_FORMAT", "mp4")).strip().lower()
                or "mp4"
            ),
        }
        self.last_result_metadata["requested_resolution"] = str(payload["resolution"])
        self.last_result_metadata["requested_output_format"] = payload["output_format"]
        self.last_result_metadata["requested_watermark"] = payload["watermark"]
        self.last_result_metadata["requested_return_last_frame"] = payload["return_last_frame"]
        callback_url = _provider_setting("SEEDANCE_CALLBACK_URL", "").strip()
        if callback_url:
            payload["callback_url"] = callback_url
        request_mode = str(
            request.request_mode or _provider_setting("SEEDANCE_REQUEST_MODE", "reference_to_video")
        ).strip().lower()
        include_experimental = _provider_setting("SEEDANCE_INCLUDE_EXPERIMENTAL_FIELDS", "false").lower() in {"1", "true", "yes", "on"}
        # An explicit per-run model must always reach a compatible gateway;
        # otherwise the UI selection would only affect local metadata while
        # the provider silently uses its environment default.
        if request.model or include_experimental or request_mode in {"multi_shot", "seedance_2_5", "2.5"}:
            payload.update({
                "model": (request.model or _provider_setting("SEEDANCE_MODEL", "bytedance/seedance-2.0/reference-to-video")).strip()
                or "bytedance/seedance-2.0/reference-to-video",
                "negative_prompt": request.negative_prompt or "",
                "end_image_url": _file_data_url(request.end_image),
                "fps": request.fps,
                "seed": request.seed,
                "multi_shot": request.multi_shot,
                "shot_plan": request.shot_plan or {},
            })
        if request_mode in {"multi_shot", "seedance_2_5", "2.5"}:
            payload["multi_shot"] = True
        return payload

    def _ark_video_payload(self, request: VideoGenerationRequest) -> dict:
        """Build the native Volcano Ark ``content[]`` Seedance contract."""
        model = _seedance_model(model=request.model)
        # The Settings default predates the native Ark adapter. If the user
        # selected Ark but did not set a model, choose the current 2.5 model;
        # an explicit environment override still wins.
        if request.model is None and "SEEDANCE_MODEL" not in os.environ and model == "bytedance/seedance-2.0/reference-to-video":
            model = "doubao-seedance-2-5-260628"
        is_25 = _seedance_model_is_25(model)
        is_10 = _seedance_model_is_10(model)
        self.last_result_metadata["requested_model"] = model

        # Ark Draft promotion is a separate contract. The model reuses the
        # prompt, references, duration, ratio, seed, audio setting, and task
        # type from the Draft; resending them causes a validation error.
        if request.draft_task_id:
            if not is_25:
                raise GenerationProviderError(
                    f"Native Seedance model {model} does not support Draft promotion; use Seedance 2.5"
                )
            output_format = (
                (request.output_format or _provider_setting("SEEDANCE_OUTPUT_FORMAT", "mp4")).strip().lower()
                or "mp4"
            )
            if output_format not in {"mp4", "mov"}:
                raise GenerationProviderError("SEEDANCE_OUTPUT_FORMAT must be mp4 or mov")
            payload = {
                "model": model,
                "content": [{"type": "draft_task", "draft_task": {"id": request.draft_task_id}}],
                "resolution": "1080p",
                "output_format": output_format,
                "watermark": _provider_bool_value(request.watermark, "SEEDANCE_WATERMARK"),
            }
            self.last_result_metadata["requested_resolution"] = "1080p"
            self.last_result_metadata["requested_output_format"] = output_format
            self.last_result_metadata["requested_watermark"] = payload["watermark"]
            # Draft promotion reuses the task's generation inputs. Keep the
            # local request intent observable, but do not resend this field to
            # Ark where the promotion contract only accepts output controls.
            self.last_result_metadata["requested_return_last_frame"] = _provider_bool_value(
                request.return_last_frame, "SEEDANCE_RETURN_LAST_FRAME"
            )
            return payload

        self._validate_reference_limits(request, native_ark=True)
        prompt = _seedance_prompt(request, native_ark=True)
        request_mode = str(
            request.request_mode or _provider_setting("SEEDANCE_REQUEST_MODE", "reference")
        ).strip().lower()
        explicit_frame_mode = request_mode in {"first_frame", "first_last_frame"}
        user_prompt_lower = str(request.prompt or "").strip().lower()
        content: list[dict] = [{"type": "text", "text": prompt}]
        image_paths = _unique_media_paths(request.reference_images or [])
        if not image_paths and request.reference_image:
            image_paths = [request.reference_image]
        if (
            request.continuity_reference_image
            and not explicit_frame_mode
            and request.continuity_reference_image not in image_paths
        ):
            image_paths.append(request.continuity_reference_image)
        video_paths = _unique_media_paths(request.reference_videos or [])
        audio_paths = _unique_media_paths(request.reference_audios or [])
        if not audio_paths and request.audio_path:
            audio_paths = [request.audio_path]
        if request_mode in {"seedance_2_5", "2.5"}:
            request_mode = "multi_shot"
        if request_mode not in {
            "reference", "reference_to_video", "auto", "multi_shot",
            "first_frame", "first_last_frame", "edit", "extend",
        }:
            raise GenerationProviderError(
                f"Unsupported native Seedance request mode: {request_mode}; "
                "choose reference, reference_to_video, auto, multi_shot, first_frame, "
                "first_last_frame, edit, or extend"
            )
        if request_mode == "first_frame":
            if len(image_paths) != 1 or request.end_image or video_paths or audio_paths or request.extend_video:
                raise GenerationProviderError(
                    "Native Seedance first_frame mode requires exactly one first-frame image "
                    "and no end frame, reference video, or reference audio"
                )
        if request_mode == "first_last_frame":
            if len(image_paths) != 1 or not request.end_image or video_paths or audio_paths or request.extend_video:
                raise GenerationProviderError(
                    "Native Seedance first_last_frame mode requires exactly one first-frame image, "
                    "one end frame, and no reference video or reference audio"
                )
        if request_mode == "first_frame" and not (is_10 or is_25):
            raise GenerationProviderError(
                f"Native Seedance model {model} does not support explicit first_frame mode"
            )
        audio_public = _validate_native_ark_audio_references(
            audio_paths,
            maximum_duration=30.0 if is_25 else 15.0,
        )
        image_public = _validate_native_ark_image_references(
            image_paths + ([request.end_image] if request.end_image else []),
            model=model,
        )
        media_template = _provider_setting("SEEDANCE_MEDIA_URL_TEMPLATE", "").strip()
        inline_image_paths = [*image_paths]
        if request.end_image and request.end_image not in inline_image_paths:
            inline_image_paths.append(request.end_image)
        inline_media_bytes = sum(
            Path(path).stat().st_size
            for path in [*inline_image_paths, *audio_paths]
            if path and Path(path).is_file()
        )
        if inline_media_bytes > 45 * 1024 * 1024:
            if not media_template:
                raise GenerationProviderError(
                    "Native Ark local image/audio references exceed the safe Base64 request-body budget; "
                    "set SEEDANCE_MEDIA_URL_TEMPLATE"
                )
            # The 64MB limit applies to the complete JSON body, not each
            # media category independently. Keep all local image/audio items
            # out of Base64 once their aggregate raw size is risky.
            image_public = True
            audio_public = True

        # First/last-frame mode is mutually exclusive with omni reference
        # mode. Use it only for a true two-frame shot.
        first_last_frame = bool(
            (request.end_image or request_mode == "first_last_frame")
            and len(image_paths) == 1
            and not video_paths
            and not audio_paths
            and not request.extend_video
        )
        if request_mode == "first_last_frame" and not request.end_image:
            raise GenerationProviderError(
                "Native Seedance first_last_frame mode requires end_image"
            )
        if first_last_frame and not _seedance_model_supports_first_last_frame(model):
            raise GenerationProviderError(
                f"Native Seedance model {model} does not support first/last-frame generation"
            )
        single_first_frame = bool(
            (is_10 or (is_25 and request_mode == "first_frame"))
            and len(image_paths) == 1
            and not request.end_image
            and not video_paths
            and not audio_paths
            and not request.extend_video
        )
        if first_last_frame or single_first_frame:
            content.extend([
                {"type": "image_url", "role": "first_frame", "image_url": {"url": _ark_media_source(image_paths[0], "image", force_public=image_public)}},
            ] + ([
                {"type": "image_url", "role": "last_frame", "image_url": {"url": _ark_media_source(request.end_image, "image", force_public=image_public)}},
            ] if first_last_frame else []))
            ratio = "adaptive"
        else:
            # Ark forbids mixing first/last-frame roles with omni references.
            # Preserve an end-frame instruction as an explicit terminal
            # composition reference instead of silently dropping it.
            if request.end_image and request.end_image not in image_paths:
                image_paths.append(request.end_image)
            content.extend(
                {"type": "image_url", "role": "reference_image", "image_url": {"url": _ark_media_source(path, "image", force_public=image_public)}}
                for path in image_paths if path
            )
            content.extend(
                {"type": "video_url", "role": "reference_video", "video_url": {"url": _ark_media_source(path, "video")}}
                for path in video_paths if path
            )
            content.extend(
                {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": _ark_media_source(path, "audio", force_public=audio_public)}}
                for path in audio_paths if path
            )
            ratio = request.aspect_ratio

        if request_mode == "auto" and not is_25:
            raise GenerationProviderError(
                f"Native Seedance model {model} does not support omni_reference_task_type=auto; use Seedance 2.5"
            )
        if is_10 and request_mode in {"edit", "extend"}:
            raise GenerationProviderError(
                f"Native Seedance model {model} does not support {request_mode} tasks; use Seedance 2.0 or 2.5"
            )
        task_type = (
            "extend" if request.extend_video or request_mode == "extend"
            else "edit" if request_mode == "edit"
            else "auto" if request_mode == "auto"
            else "reference"
        )
        auto_video_task = task_type == "auto" and is_25 and bool(video_paths or request.extend_video)
        if auto_video_task:
            # Ark 2.5 may classify an auto task with a reference video as edit
            # or extend. Use the shared locked-input contract up front so the
            # task does not fail asynchronously after it has been accepted.
            ratio = "adaptive"
        if task_type in {"edit", "extend"} and not (video_paths or request.extend_video):
            raise GenerationProviderError(
                f"Seedance {task_type} mode requires at least one public reference video"
            )
        if task_type == "edit" and not any(
            token in user_prompt_lower for token in ("edit", "modify", "remove", "replace", "编辑", "修改", "删除", "替换")
        ):
            prompt = f"Edit the reference video according to this instruction: {prompt}"
        elif task_type == "extend" and not any(
            token in user_prompt_lower for token in ("extend", "continue", "续写", "延长", "延续", "续接", "向前", "向后")
        ):
            prompt = f"Extend the reference video according to this instruction: {prompt}"
        content[0]["text"] = prompt
        videos_to_validate = list(video_paths)
        if request.extend_video and request.extend_video not in videos_to_validate:
            videos_to_validate.append(request.extend_video)
        _validate_native_ark_video_references(
            videos_to_validate,
            is_25=is_25,
            edit_or_extend=task_type in {"edit", "extend"},
        )
        if request.extend_video and request.extend_video not in video_paths:
            content.append({
                "type": "video_url",
                "role": "reference_video",
                "video_url": {"url": _ark_media_source(request.extend_video, "video")},
            })
        minimum_duration, maximum_duration = _seedance_duration_bounds(model, request_mode)
        duration = _seedance_duration(
            request.duration_seconds,
            maximum=maximum_duration,
            minimum=minimum_duration,
        )
        if duration == "auto":
            # Native Ark uses -1 for model-selected duration on 2.x. Seedance
            # 1.0 only accepts an explicit 2-12 second duration, so use the
            # product's default 5-second clip when callers request auto.
            duration = -1 if not is_10 else 5
        if (task_type in {"edit", "extend"} and is_25) or auto_video_task:
            duration = -1
            ratio = "adaptive"
        output_format = ((request.output_format or _provider_setting("SEEDANCE_OUTPUT_FORMAT", "mp4")).strip().lower() or "mp4")
        if output_format not in {"mp4", "mov"}:
            raise GenerationProviderError("SEEDANCE_OUTPUT_FORMAT must be mp4 or mov")
        if output_format == "mov" and not is_25:
            raise GenerationProviderError(
                f"Native Seedance model {model} supports MP4 output only; MOV output requires Seedance 2.5"
            )
        draft_requested = _provider_bool_value(request.draft, "SEEDANCE_DRAFT")
        if draft_requested and not is_25:
            raise GenerationProviderError(
                f"Native Seedance model {model} does not support Draft generation; use Seedance 2.5"
            )
        # Seedance 2.5 first/last-frame generation is a two-phase workflow:
        # the first request must create a 480p Draft task, then the returned
        # draft_task_id is promoted to the final output.  Rejecting Draft here
        # would make the documented keyframe workflow impossible and would
        # leave callers with a task id that cannot be promoted reliably.
        if first_last_frame and is_25 and not draft_requested:
            raise GenerationProviderError(
                "Seedance 2.5 first/last-frame generation requires Draft=true; "
                "promote the returned draft task for the final video"
            )
        if request_mode == "first_frame" and is_25 and not draft_requested:
            raise GenerationProviderError(
                "Seedance 2.5 first-frame generation requires Draft=true; "
                "promote the returned draft task for the final video"
            )
        resolution = (
            "480p"
            if draft_requested
            else (request.resolution or _provider_setting("SEEDANCE_RESOLUTION", "720p"))
        ).strip().lower()
        supported_resolutions = _seedance_supported_resolutions(model)
        if resolution not in supported_resolutions:
            raise GenerationProviderError(
                f"Native Seedance model {model} does not support resolution {resolution}; "
                f"choose one of {', '.join(sorted(supported_resolutions))}"
            )
        content_bindings = []
        reference_indices = {"image_url": 0, "video_url": 0, "audio_url": 0}
        reference_tags = {"image_url": "image", "video_url": "video", "audio_url": "audio"}
        for content_index, item in enumerate(content):
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type not in reference_tags:
                continue
            reference_indices[item_type] += 1
            content_bindings.append({
                "content_index": content_index,
                "type": item_type,
                "role": item.get("role"),
                "provider_reference_tag": (
                    f"@{reference_tags[item_type]}{reference_indices[item_type]}"
                ),
            })
        payload = {
            "model": model,
            "content": content,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "generate_audio": request.generate_audio,
            "watermark": _provider_bool_value(request.watermark, "SEEDANCE_WATERMARK"),
            "output_format": output_format,
        }
        # Ark documents seed/camera_fixed for Seedance 1.0 Pro. Do not send
        # those strong-validated fields to 2.0/2.5, where they are not part of
        # the model contract and can cause a paid request to be rejected.
        supports_seed_camera = _seedance_model_supports_seed_camera(model)
        if supports_seed_camera:
            payload.update({
                "seed": request.seed,
                "camera_fixed": _provider_bool_value(request.camera_fixed, "SEEDANCE_CAMERA_FIXED"),
            })
        # First/last-frame generation is its own Ark task family. The
        # omni-reference discriminator is only meaningful for reference/edit/
        # extend inputs and can create a task-type mismatch when combined with
        # first_frame/last_frame roles.
        frame_mode = first_last_frame or single_first_frame
        if not frame_mode and is_25:
            payload["omni_reference_task_type"] = task_type
        payload["return_last_frame"] = _provider_bool_value(request.return_last_frame, "SEEDANCE_RETURN_LAST_FRAME")
        payload["draft"] = draft_requested
        callback_url = _provider_setting("SEEDANCE_CALLBACK_URL", "").strip()
        if callback_url:
            payload["callback_url"] = callback_url
        self.last_result_metadata["requested_resolution"] = str(payload["resolution"])
        self.last_result_metadata["requested_output_format"] = output_format
        self.last_result_metadata["requested_watermark"] = payload["watermark"]
        self.last_result_metadata["requested_return_last_frame"] = payload["return_last_frame"]
        self.last_result_metadata["ark_task_type"] = task_type
        self.last_result_metadata["ark_content_bindings"] = content_bindings
        return payload

    def _validate_reference_limits(self, request: VideoGenerationRequest, native_ark: bool = False) -> None:
        model = _seedance_model(model=request.model)
        if native_ark and (
            not model
            or (request.model is None and "SEEDANCE_MODEL" not in os.environ and model == "bytedance/seedance-2.0/reference-to-video")
        ):
            model = "doubao-seedance-2-5-260628"
        is_25 = native_ark and _seedance_model_is_25(model)
        legacy_limits = {"images": 9, "videos": 3, "audios": 3}
        native_limits = {"images": 30, "videos": 10, "audios": 10}
        limits = {}
        for kind in ("images", "videos", "audios"):
            setting_name = f"SEEDANCE_MAX_REFERENCE_{kind.upper()}"
            configured = _provider_setting(setting_name, str(legacy_limits[kind]))
            # Settings defaults represent 2.0. Automatically use 2.5's
            # larger limits only when the user has not explicitly overridden
            # the setting in the environment or Settings object.
            if is_25 and setting_name not in os.environ and getattr(settings, setting_name, None) == legacy_limits[kind]:
                configured = str(native_limits[kind])
            limits[kind] = int(configured)
        image_paths = _unique_media_paths(request.reference_images or [])
        if not image_paths and request.reference_image:
            image_paths = [request.reference_image]
        explicit_frame_mode = str(request.request_mode or _provider_setting(
            "SEEDANCE_REQUEST_MODE", "reference"
        )).strip().lower() in {"first_frame", "first_last_frame"}
        if (
            request.continuity_reference_image
            and not explicit_frame_mode
            and request.continuity_reference_image not in image_paths
        ):
            image_paths.append(request.continuity_reference_image)
        first_last_frame = bool(
            native_ark
            and request.end_image
            and len(image_paths) == 1
            and not request.reference_videos
            and not request.reference_audios
            and not request.extend_video
        )
        end_image_without_first_frame = bool(native_ark and request.end_image and not image_paths)
        if native_ark and request.end_image and not first_last_frame and request.end_image not in image_paths:
            image_paths.append(request.end_image)
        video_paths = _unique_media_paths(request.reference_videos or [])
        if native_ark and request.extend_video and request.extend_video not in video_paths:
            video_paths.append(request.extend_video)
        audio_paths = _unique_media_paths(request.reference_audios or [])
        if not audio_paths and request.audio_path:
            audio_paths = [request.audio_path]
        counts = {
            "images": len(image_paths),
            "videos": len(video_paths),
            "audios": len(audio_paths),
        }
        if first_last_frame:
            counts["images"] += 1
        for kind, count in counts.items():
            if count > max(0, limits[kind]):
                raise GenerationProviderError(
                    f"Seedance reference limit exceeded for {kind}: {count} > {limits[kind]}; "
                    f"reduce inputs or configure SEEDANCE_MAX_REFERENCE_{kind.upper()}"
                )
        if native_ark:
            if _seedance_model_is_10(model):
                if video_paths or audio_paths:
                    raise GenerationProviderError(
                        f"Native Seedance model {model} supports first/last-frame images only; "
                        "video and audio references require Seedance 2.0 or 2.5"
                    )
                if len(image_paths) > 1:
                    raise GenerationProviderError(
                        f"Native Seedance model {model} accepts one first-frame image, or one first image plus end_image"
                    )
                if end_image_without_first_frame:
                    raise GenerationProviderError(
                        f"Native Seedance model {model} requires a first-frame image when end_image is provided"
                    )
                if request.end_image and not _seedance_model_supports_first_last_frame(model):
                    raise GenerationProviderError(
                        f"Native Seedance model {model} does not support first/last-frame generation"
                    )
            total_limit = 50 if is_25 else 15
            if sum(counts.values()) > total_limit:
                raise GenerationProviderError(
                    f"Native Seedance reference limit exceeded: "
                    f"{sum(counts.values())} total references > {total_limit}"
                )
            if counts["audios"]:
                if not _seedance_model_supports_reference_audio(model):
                    raise GenerationProviderError(
                        f"Native Seedance model {model} does not support audio references"
                    )
                if not is_25 and not (counts["images"] or counts["videos"]):
                    raise GenerationProviderError(
                        "Native Seedance 2.0 audio references require at least one image or video reference"
                    )


def _request_requires_audio(request: VideoGenerationRequest) -> bool:
    """Treat generated and reference audio as required output contracts."""
    return bool(request.generate_audio or request.audio_path or request.reference_audios)


def _seedance_duration(value: float, maximum: int = 15, minimum: int = 2) -> int | str:
    """Map local fractional timing to a model-specific duration contract."""
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return "auto"
    if duration <= 0:
        return "auto"
    return max(minimum, min(maximum, int(round(duration))))


def _unique_media_paths(paths: list[str] | tuple[str, ...]) -> list[str]:
    """Preserve media order while removing duplicate references."""
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _video_request_fingerprint(
    request: VideoGenerationRequest,
    *,
    provider_prefix: str = "SEEDANCE",
) -> str:
    """Hash the request identity used to safely resume a remote task."""
    # Pending tasks must be tied to the controls that actually reached the
    # provider, not only to fields explicitly copied into the request object.
    # Otherwise changing .env between a transport failure and a retry could
    # attach an old paid task to a different model or output contract.
    prefix = str(provider_prefix or "SEEDANCE").strip().upper()
    seedance_defaults = prefix == "SEEDANCE"
    effective_model = (
        _seedance_model(model=request.model)
        if seedance_defaults
        else (request.model or "")
    )
    effective_request_mode = request.request_mode or (
        _provider_setting(f"{prefix}_REQUEST_MODE", "reference")
        if seedance_defaults else ""
    )
    effective_resolution = request.resolution or (
        _provider_setting(f"{prefix}_RESOLUTION", "720p")
        if seedance_defaults else ""
    )
    effective_output_format = request.output_format or (
        _provider_setting(f"{prefix}_OUTPUT_FORMAT", "mp4")
        if seedance_defaults else ""
    )

    def effective_bool(value: bool | None, suffix: str, default: bool = False) -> bool:
        if value is not None:
            return bool(value)
        if not seedance_defaults:
            return default
        return _provider_bool(f"{prefix}_{suffix}", default)

    effective_return_last_frame = effective_bool(request.return_last_frame, "RETURN_LAST_FRAME")
    effective_camera_fixed = effective_bool(request.camera_fixed, "CAMERA_FIXED")
    effective_watermark = effective_bool(request.watermark, "WATERMARK")
    effective_draft = effective_bool(request.draft, "DRAFT")
    effective_multi_shot = bool(request.multi_shot)
    if seedance_defaults and not request.multi_shot:
        effective_multi_shot = _provider_bool("SEEDANCE_MULTI_SHOT", False)
    def media_identity(value: str | None) -> dict[str, object] | str | None:
        if not value:
            return value
        path = Path(str(value))
        identity: dict[str, object] = {"path": str(value)}
        try:
            stat = path.stat()
            identity.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
            if stat.st_size <= 64 * 1024 * 1024 and path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                identity["sha256"] = digest.hexdigest()
        except OSError:
            pass
        return identity

    media_fields = (
        "reference_image", "end_image", "continuity_reference_image",
        "audio_path", "extend_video",
    )
    payload: dict[str, object] = {
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "reference_images": [media_identity(path) for path in request.reference_images or []],
        "reference_videos": [media_identity(path) for path in request.reference_videos or []],
        "reference_audios": [media_identity(path) for path in request.reference_audios or []],
        "generate_audio": request.generate_audio,
        "return_last_frame": effective_return_last_frame,
        "camera_fixed": effective_camera_fixed,
        "watermark": effective_watermark,
        "output_format": effective_output_format,
        "resolution": effective_resolution,
        "model": effective_model,
        "request_mode": effective_request_mode,
        "draft": effective_draft,
        "draft_task_id": request.draft_task_id,
        "multi_shot": effective_multi_shot,
        "shot_plan": request.shot_plan or {},
        "duration_seconds": request.duration_seconds,
        "aspect_ratio": request.aspect_ratio,
        "width": request.width,
        "height": request.height,
        "fps": request.fps,
        "seed": request.seed,
        "motion_bucket_id": request.motion_bucket_id,
        "noise_aug_strength": request.noise_aug_strength,
        "quality_mode": request.quality_mode,
        "repair_action": request.repair_action,
        "quality_pipeline": request.quality_pipeline or {},
    }
    for field in media_fields:
        value = getattr(request, field)
        if value:
            payload[field] = media_identity(value)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


DEFAULT_SEEDANCE_PRODUCTION_CONTRACT = (
    "premium mobile short-drama shot, one continuous readable action beat, natural facial performance and eye-line, "
    "preserve identity, wardrobe, background and prop continuity, stable cinematic camera, phone-readable composition, "
    "no jump cuts, no frozen still-image feeling, no extra people or invented props"
)


def _spatial_prompt_directive(shot_plan: dict | None) -> str:
    """Render spatial controls into a provider-neutral prompt fallback.

    Custom workflows can consume the JSON placeholders directly. Prompting is
    still useful for SVD and gateways that ignore structured metadata, so the
    approved camera/blocking contract is never silently dropped.
    """
    plan = shot_plan.get("spatial_plan") if isinstance(shot_plan, dict) else None
    if not isinstance(plan, dict):
        return ""
    fields = (
        ("shot scale", "shot_scale"),
        ("camera angle", "camera_angle"),
        ("camera axis", "camera_axis"),
        ("camera movement", "camera_movement"),
        ("character positions", "character_positions"),
        ("prop focus", "prop_focus"),
        ("continuity", "continuity_prompt"),
    )
    parts = []
    for label, key in fields:
        value = plan.get(key)
        if isinstance(value, dict):
            value = ", ".join(f"{name}: {detail}" for name, detail in value.items())
        value = str(value or "").strip()
        if value:
            parts.append(f"{label}={value}")
    controls = plan.get("control_references") if isinstance(plan.get("control_references"), dict) else {}
    control_parts = [
        str(value).strip()
        for key, value in controls.items()
        if key.endswith("_prompt") and str(value).strip()
    ]
    if control_parts:
        parts.append("control references=" + "; ".join(control_parts))
    return "Spatial blocking contract: " + "; ".join(parts) if parts else ""


def _seedance_prompt(request: VideoGenerationRequest, native_ark: bool | None = None) -> str:
    """Bind internal director metadata to the provider's documented prompt field."""
    prompt = str(request.prompt or "").strip()
    if native_ark is None:
        native_ark = _provider_setting("SEEDANCE_API_FORMAT", "legacy").strip().lower() in {
            "ark", "ark_v3", "volcengine", "volcengine_v3",
        }
    # Native Ark uses lowercase @image1/@video1/@audio1 bindings. Generic
    # gateways keep the historical capitalized labels for compatibility.
    image_tag = lambda index: f"@image{index}" if native_ark else f"@Image{index}"
    video_tag = lambda index: f"@video{index}" if native_ark else f"@Video{index}"
    audio_tag = lambda index: f"@audio{index}" if native_ark else f"@Audio{index}"
    if request.negative_prompt:
        prompt = f"{prompt}. Avoid: {request.negative_prompt.strip()}"
    plan = request.shot_plan if isinstance(request.shot_plan, dict) else {}
    director_prompt = str(plan.get("director_prompt") or "").strip()
    if director_prompt and director_prompt not in prompt:
        prompt = f"{prompt}. Director direction: {director_prompt}."
    structured_camera = []
    for key, label in (
        ("framing", "framing"),
        ("camera_movement", "camera movement"),
        ("performance_direction", "performance direction"),
        ("edit_intent", "editorial intent"),
    ):
        value = str(plan.get(key) or "").strip()
        if value:
            structured_camera.append(f"{label}={value}")
    if structured_camera:
        prompt = f"{prompt}. Structured shot language: {'; '.join(structured_camera)}."
    spatial_directive = _spatial_prompt_directive(plan)
    if spatial_directive:
        prompt = f"{prompt}. {spatial_directive}."
    if DEFAULT_SEEDANCE_PRODUCTION_CONTRACT not in prompt:
        prompt = f"{prompt}. Production motion contract: {DEFAULT_SEEDANCE_PRODUCTION_CONTRACT}."
    if str(request.aspect_ratio or "").strip() == "9:16":
        prompt = f"{prompt}. Compose for a vertical 9:16 mobile frame with clear face and action readability."
    context = plan.get("sequence_context") if isinstance(plan.get("sequence_context"), dict) else {}
    contract = context.get("continuity_contract") if isinstance(context.get("continuity_contract"), list) else []
    if contract:
        prompt = f"{prompt}. Continuity contract: {'; '.join(str(item) for item in contract[:5])}."
    sequence_parts = []
    for label, key in (("previous shot", "previous"), ("current shot", "current"), ("next shot", "next")):
        shot = context.get(key) if isinstance(context.get(key), dict) else None
        if not shot:
            continue
        summary = str(shot.get("visual_summary") or "").strip()[:180]
        character = str(shot.get("character_name") or "").strip()[:80]
        dialogue = str(shot.get("dialogue") or "").strip()[:100]
        details = [f"scene {shot.get('scene_number')}"]
        if character:
            details.append(f"character={character}")
        if summary:
            details.append(f"visual={summary}")
        if dialogue:
            details.append(f"dialogue={dialogue}")
        sequence_parts.append(f"{label}: {', '.join(details)}")
    if sequence_parts:
        prompt = f"{prompt}. Bounded sequence context: {'; '.join(sequence_parts)}."
    shots = plan.get("shots") if isinstance(plan.get("shots"), list) else []
    if request.multi_shot and shots:
        total_duration = max(1, int(round(float(request.duration_seconds or 0))))
        default_duration = max(1, total_duration // len(shots))
        raw_durations = []
        for shot in shots:
            try:
                raw_durations.append(max(1, float(shot.get("duration_seconds") or 0)) if isinstance(shot, dict) else 0)
            except (TypeError, ValueError):
                raw_durations.append(0)
        raw_total = sum(raw_durations)
        timeline = []
        provided_timeline = plan.get("sequence_timeline") if isinstance(plan.get("sequence_timeline"), list) else []
        if len(provided_timeline) >= len(shots):
            for index, shot in enumerate(shots, start=1):
                item = provided_timeline[index - 1]
                if not isinstance(item, dict):
                    continue
                try:
                    start = float(item.get("start_seconds"))
                    end = float(item.get("end_seconds"))
                except (TypeError, ValueError):
                    continue
                if end <= start:
                    continue
                visual = str(shot.get("visual") or shot.get("visual_summary") or "").strip()[:220]
                character = str(shot.get("character") or shot.get("character_name") or "").strip()[:80]
                dialogue = str(shot.get("dialogue") or "").strip()[:120]
                details = [f"visual={visual}" if visual else ""]
                if character:
                    details.append(f"character={character}")
                if dialogue:
                    details.append(f"dialogue={dialogue}")
                timeline.append(
                    f"Shot {index} [{start:.3f}s-{end:.3f}s]: {', '.join(item for item in details if item)}"
                )
        if not timeline:
            cursor = 0
            for index, shot in enumerate(shots, start=1):
                if not isinstance(shot, dict):
                    continue
                if raw_total:
                    shot_duration = max(1, int(round(raw_durations[index - 1] / raw_total * total_duration)))
                else:
                    shot_duration = default_duration
                start = cursor
                end = total_duration if index == len(shots) else min(total_duration, cursor + shot_duration)
                cursor = end
                visual = str(shot.get("visual") or shot.get("visual_summary") or "").strip()[:220]
                character = str(shot.get("character") or shot.get("character_name") or "").strip()[:80]
                dialogue = str(shot.get("dialogue") or "").strip()[:120]
                details = [f"visual={visual}" if visual else ""]
                if character:
                    details.append(f"character={character}")
                if dialogue:
                    details.append(f"dialogue={dialogue}")
                timeline.append(f"Shot {index} [{start}s-{end}s]: {', '.join(item for item in details if item)}")
        if timeline:
            prompt = (
                f"{prompt}. Multi-shot timeline (follow these integer-second ranges and cut only at the marked boundaries): "
                f"{' | '.join(timeline)}. Keep motion continuous across each cut."
            )
    bindings = []
    base_image_paths = _unique_media_paths(request.reference_images or [])
    if not base_image_paths and request.reference_image:
        base_image_paths = [request.reference_image]
    base_image_count = len(base_image_paths)
    sequence_level = bool(plan.get("sequence_level"))
    continuity_is_separate = bool(
        request.continuity_reference_image
        and request.continuity_reference_image not in base_image_paths
    )
    continuity_index = base_image_count + 1 if continuity_is_separate else None
    video_paths = _unique_media_paths(request.reference_videos or [])
    extend_video_index = None
    if request.extend_video:
        if request.extend_video in video_paths:
            extend_video_index = video_paths.index(request.extend_video) + 1
        else:
            extend_video_index = len(video_paths) + 1
    video_count = len(video_paths) + (
        1 if request.extend_video and request.extend_video not in video_paths else 0
    )
    audio_paths = _unique_media_paths(request.reference_audios or [])
    if not audio_paths and request.audio_path:
        audio_paths = [request.audio_path]
    audio_count = len(audio_paths)
    end_is_separate = bool(
        request.end_image
        and (
            request.end_image not in base_image_paths
            or (
                len(base_image_paths) == 1
                and not video_count
                and not audio_count
                and not continuity_is_separate
                and request.end_image == base_image_paths[0]
            )
        )
    )
    end_index = (continuity_index or base_image_count) + 1 if end_is_separate else None
    if base_image_count:
        if sequence_level and shots:
            explicit_bindings = plan.get("sequence_image_bindings")
            if isinstance(explicit_bindings, list) and explicit_bindings:
                for item in explicit_bindings:
                    if not isinstance(item, dict):
                        continue
                    try:
                        image_index = int(item.get("image_index"))
                    except (TypeError, ValueError):
                        continue
                    if image_index < 1 or image_index > base_image_count:
                        continue
                    role = str(item.get("role") or "reference").strip()
                    if role == "shot_keyframe":
                        bindings.append(f"{image_tag(image_index)} is the keyframe for scene {item.get('scene_number')}")
                    elif role == "character_identity":
                        names = ", ".join(str(name) for name in item.get("character_names") or ["character"])
                        bindings.append(f"{image_tag(image_index)} is a locked identity reference for {names}")
            else:
                shot_image_count = min(base_image_count, len(shots))
                bindings.append(
                    f"{image_tag(1)} through {image_tag(shot_image_count)} map in order to the shot keyframes in the timeline"
                )
                if base_image_count > shot_image_count:
                    bindings.append(
                        f"{image_tag(shot_image_count + 1)} onward are frozen character identity and wardrobe references"
                    )
        else:
            bindings.append(f"{image_tag(1)} is the current scene keyframe and establishes composition")
        if base_image_count > 1 and not sequence_level:
            bindings.append(f"{image_tag(2)} through {image_tag(base_image_count)} are frozen character identity and wardrobe references")
        if end_index and (
            base_image_count > 1
            or request.reference_videos
            or request.reference_audios
            or request.extend_video
            or continuity_index
        ):
            bindings.append(f"{image_tag(end_index)} is the desired ending composition reference")
    if continuity_index:
        bindings.append(f"{image_tag(continuity_index)} is the last frame of the previous shot; continue its pose, eyeline, and screen direction")
    if video_count:
        bindings.append(f"{video_tag(1)} onward are motion and pacing references; continue their action without copying unrelated subjects")
    if extend_video_index:
        bindings.append(
            f"{video_tag(extend_video_index)} is the source video to extend; continue from its final motion and composition"
        )
    if audio_count:
        explicit_audio_bindings = plan.get("sequence_audio_bindings")
        if isinstance(explicit_audio_bindings, list) and explicit_audio_bindings:
            for item in explicit_audio_bindings:
                if not isinstance(item, dict):
                    continue
                try:
                    audio_index = int(item.get("audio_index"))
                except (TypeError, ValueError):
                    continue
                if 1 <= audio_index <= audio_count:
                    bindings.append(
                        f"{audio_tag(audio_index)} is the dialogue or sound reference for scene {item.get('scene_number')}"
                    )
        else:
            bindings.append(f"{audio_tag(1)} onward are dialogue or sound references; keep visible mouth/action timing aligned")
    if bindings:
        prompt = f"{prompt}. Reference binding: {'; '.join(bindings)}."
    character_bindings = plan.get("character_reference_bindings")
    if isinstance(character_bindings, list):
        identity_bindings = []
        for item in character_bindings:
            if not isinstance(item, dict):
                continue
            try:
                image_index = int(item.get("image_index"))
            except (TypeError, ValueError):
                continue
            if image_index < 1:
                continue
            name = str(item.get("character_name") or "character").strip()[:80]
            view = str(item.get("view") or "front").strip()[:40]
            features = item.get("expected_features")
            feature_text = ""
            if isinstance(features, dict):
                feature_text = ", ".join(
                    f"{str(key)[:32]}={str(value)[:100]}"
                    for key, value in features.items()
                    if str(value or "").strip()
                )
            detail = f"{image_tag(image_index)} is {name}'s locked {view} character reference"
            if feature_text:
                detail += f" ({feature_text})"
            identity_bindings.append(detail)
        if identity_bindings:
            prompt = (
                f"{prompt}. Character identity binding: {'; '.join(identity_bindings)}. "
                "Never swap these references between named roles or merge their facial geometry."
            )
    return prompt


class HybridGenerationProvider:
    """Use API providers for production quality and local ComfyUI as fallback."""

    name = GenerationProviderName.HYBRID

    def __init__(self, primary: GenerationProvider, fallback: GenerationProvider):
        self.primary = primary
        self.fallback = fallback

    def _prefer_local(self, request) -> bool:
        """Route only explicitly low-value shot roles to the local engine."""
        configured = _provider_setting("GENERATION_HYBRID_LOCAL_SHOT_ROLES", "establishing")
        roles = {item.strip().lower() for item in configured.split(",") if item.strip()}
        if not roles:
            return False
        shot_plan = getattr(request, "shot_plan", None)
        role = shot_plan.get("shot_role") if isinstance(shot_plan, dict) else None
        role = role or getattr(request, "scene_type", None)
        return str(role or "").strip().lower() in roles

    @staticmethod
    def _annotate(result: GenerationResult, route: str) -> GenerationResult:
        metadata = dict(result.metadata) if isinstance(result.metadata, dict) else {}
        metadata["hybrid_route"] = route
        return GenerationResult(result.provider, result.output_path, result.asset_type, metadata)

    def generate_image(self, request: ImageGenerationRequest) -> GenerationResult:
        if self._prefer_local(request):
            try:
                return self._annotate(self.fallback.generate_image(request), "local_policy")
            except (GenerationProviderError, httpx.HTTPError, OSError, ValueError) as exc:
                logger.warning("Local hybrid image route failed; trying primary provider: {}", exc)
        try:
            return self._annotate(self.primary.generate_image(request), "primary_after_local_failure" if self._prefer_local(request) else "primary_default")
        except (GenerationProviderError, httpx.HTTPError, OSError, ValueError) as exc:
            if self._remote_task_was_accepted(request):
                raise
            logger.warning("Primary image provider failed; falling back to local provider: {}", exc)
            return self._annotate(self.fallback.generate_image(request), "local_fallback")

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        if self._prefer_local(request):
            try:
                return self._annotate(self.fallback.generate_video(request), "local_policy")
            except (GenerationProviderError, httpx.HTTPError, OSError, ValueError) as exc:
                logger.warning("Local hybrid video route failed; trying primary provider: {}", exc)
        try:
            return self._annotate(self.primary.generate_video(request), "primary_after_local_failure" if self._prefer_local(request) else "primary_default")
        except (GenerationProviderError, httpx.HTTPError, OSError, ValueError) as exc:
            if self._remote_task_was_accepted(request):
                raise
            logger.warning("Primary video provider failed; falling back to local provider: {}", exc)
            return self._annotate(self.fallback.generate_video(request), "local_fallback")

    def _remote_task_was_accepted(self, request) -> bool:
        """Never duplicate an already accepted paid remote generation."""
        metadata = getattr(self.primary, "last_result_metadata", None)
        if isinstance(metadata, dict) and (
            metadata.get("provider_task_id")
            or metadata.get("provider_request_submitted") is True
        ):
            return True
        output_path = getattr(request, "output_path", None)
        if not output_path:
            return False
        pending_path = Path(str(output_path)).with_suffix(".provider.pending.json")
        return pending_path.is_file()

    def release_generation_resources(self) -> None:
        # A failed API attempt can still leave a local fallback holding GPU
        # memory; release both sides when the task is complete.
        for provider in (self.primary, self.fallback):
            release = getattr(provider, "release_generation_resources", None)
            if callable(release):
                release()


def get_generation_provider(provider_name: Optional[str] = None) -> GenerationProvider:
    configured = provider_name or _provider_setting("GENERATION_PROVIDER", "local_comfyui")
    try:
        name = GenerationProviderName(configured)
    except ValueError as exc:
        raise GenerationProviderError(
            f"Unsupported generation provider: {configured}. "
            f"Choose one of: {', '.join(item.value for item in GenerationProviderName)}"
        ) from exc

    if name == GenerationProviderName.LOCAL_COMFYUI:
        return LocalComfyUIProvider()
    if name == GenerationProviderName.JIMENG_API:
        return JimengApiProvider()
    if name == GenerationProviderName.KLING_API:
        return KlingApiProvider()
    if name == GenerationProviderName.HAILUO_API:
        return HailuoApiProvider()
    if name == GenerationProviderName.HTTP_VIDEO_API:
        return HttpVideoApiProvider()
    if name == GenerationProviderName.SEEDANCE_API:
        return SeedanceApiProvider()
    if name == GenerationProviderName.HYBRID:
        primary_name = _provider_setting("GENERATION_PRIMARY_PROVIDER", GenerationProviderName.JIMENG_API.value)
        return HybridGenerationProvider(
            primary=get_generation_provider(primary_name),
            fallback=LocalComfyUIProvider(),
        )

    raise GenerationProviderError(f"Unsupported generation provider: {provider_name}")


def _extract_first(data: dict, keys: tuple[str, ...]):
    for key in keys:
        value = _deep_get(data, key)
        if value:
            return value
    return None


def _format_provider_error(data) -> str:
    """Keep provider error codes/messages actionable without leaking a full payload."""
    error = _extract_first(data, ("error", "message", "detail"))
    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        message = error.get("message") or error.get("detail") or error.get("msg")
        if code and message:
            return f"{code}: {message}"
        if message:
            return str(message)
        return json.dumps(error, ensure_ascii=False, sort_keys=True)
    if isinstance(error, list):
        return "; ".join(str(item) for item in error)
    return str(error if error is not None else data)


def _extract_video_url(data) -> str | None:
    """Extract string URLs from both flat and nested provider responses."""
    # Ark's JSON examples use ``content.video_url``. Some SDK response
    # models also expose the same artifact as ``content.file_url``; accept
    # both so a successful task is never discarded because of serialization
    # differences between the REST and SDK layers.
    return _extract_media_url(data, ("video_url", "file_url", "output_url", "download_url", "url"))


def _extract_media_url(data, keys: tuple[str, ...]) -> str | None:
    candidate = _extract_first(data, keys)
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if isinstance(candidate, dict):
        for key in ("url", "uri", "href", "download_url"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(candidate, list):
        for item in candidate:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                value = _extract_media_url(item, keys)
                if value:
                    return value
    return None


def _deep_get(value, key: str):
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            found = _deep_get(item, key)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _deep_get(item, key)
            if found:
                return found
    return None


def _file_data_url(path: str | None) -> str | None:
    if not path:
        return None

    file_path = Path(path)
    if not file_path.is_file():
        return path
    suffix = file_path.suffix.lower()
    mime_by_suffix = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
    }
    mime = mime_by_suffix.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _ark_media_source(path: str | None, media_kind: str, *, force_public: bool = False) -> str | None:
    """Return a media source accepted by the native Ark video API.

    Ark accepts local-image Base64 data URLs and small local audio references;
    video references must be reachable URLs or pre-ingested asset IDs. A URL
    template makes the local storage layout explicit without silently exposing
    arbitrary filesystem paths in a paid request.
    """
    if not path:
        return None
    value = str(path)
    if value.startswith(("https://", "http://")):
        _validate_public_media_url(value, media_kind)
        return value
    if value.startswith("asset://"):
        return value
    file_path = Path(value)
    if not file_path.is_file():
        raise GenerationProviderError(
            f"Native Ark {media_kind} reference does not exist or is not a public URL/asset id: {value}"
        )
    template = _provider_setting("SEEDANCE_MEDIA_URL_TEMPLATE", "").strip()
    if media_kind == "image" and not force_public:
        if file_path.stat().st_size <= 30 * 1024 * 1024:
            return _file_data_url(value)
        if not template:
            raise GenerationProviderError("Native Ark local image references must each be 30MB or smaller")
    if media_kind == "audio" and not force_public and file_path.stat().st_size <= 15 * 1024 * 1024:
        return _file_data_url(value)
    if template:
        template_fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
        if not template_fields.intersection({"filename", "path"}):
            raise GenerationProviderError(
                "SEEDANCE_MEDIA_URL_TEMPLATE must include {filename} or {path}"
            )
        try:
            public_url = template.format(
                filename=quote(file_path.name),
                path=quote(str(file_path).lstrip("/")),
            )
        except (KeyError, ValueError) as exc:
            raise GenerationProviderError(
                "SEEDANCE_MEDIA_URL_TEMPLATE must use {filename} or {path}"
            ) from exc
        _validate_public_media_url(public_url, media_kind)
        return public_url
    raise GenerationProviderError(
        f"Native Ark requires a public URL or asset:// id for local {media_kind} reference: {value}; "
        "set SEEDANCE_MEDIA_URL_TEMPLATE or pre-ingest the asset"
    )


def _validate_public_media_url(url: str, media_kind: str) -> None:
    """Reject local/private media URLs before an Ark request is submitted."""
    parsed = urlparse(str(url))
    hostname = (parsed.hostname or "").strip().lower()
    private_host = hostname in {"localhost", "localhost.localdomain"}
    try:
        address = ipaddress.ip_address(hostname)
        private_host = private_host or (
            address.is_private or address.is_loopback or address.is_link_local or address.is_reserved
        )
    except ValueError:
        pass
    if parsed.scheme != "https" or not parsed.netloc or private_host:
        raise GenerationProviderError(
            f"Native Ark local {media_kind} reference URL must be a public HTTPS URL; "
            f"got {url}"
        )


def _validate_provider_download_url(url: str, provider_name: str = "provider") -> None:
    """Reject malformed, credential-bearing, or private result URLs before downloading."""
    try:
        parsed = urlparse(str(url).strip())
        hostname = (parsed.hostname or "").strip().lower()
    except ValueError:
        parsed = None
        hostname = ""
    private_host = hostname in {
        "localhost", "localhost.localdomain", "metadata.google.internal",
    } or hostname.endswith((".localhost", ".local", ".internal"))
    if hostname:
        try:
            address = ipaddress.ip_address(hostname)
            private_host = private_host or (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            )
        except ValueError:
            pass
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username
        or parsed.password
        or private_host
    ):
        raise GenerationProviderError(
            f"{provider_name} returned an invalid video download URL"
        )
    if parsed.fragment:
        raise GenerationProviderError(
            f"{provider_name} returned a video URL with an unsupported fragment"
        )


def _validate_native_ark_image_references(
    image_paths: list[str],
    *,
    model: str | None = None,
) -> bool:
    """Validate image limits and indicate when images should use public URLs."""
    local_paths = [Path(path) for path in image_paths if path and Path(path).is_file()]
    if not local_paths:
        return False
    supported_formats = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
    if not _seedance_model_is_10(model):
        supported_formats.update({".heic", ".heif"})
    unsupported = [path for path in local_paths if path.suffix.lower() not in supported_formats]
    if unsupported:
        allowed = ", ".join(sorted(suffix.lstrip(".") for suffix in supported_formats))
        raise GenerationProviderError(
            f"Native Ark reference image format is unsupported for {model or 'the selected model'}: "
            f"{', '.join(str(path) for path in unsupported)}; allowed formats: {allowed}"
        )
    oversized = [path for path in local_paths if path.stat().st_size > 30 * 1024 * 1024]
    total_bytes = sum(path.stat().st_size for path in local_paths)
    # Base64 expands by roughly 4/3; keep a conservative raw budget for the
    # documented 64MB request-body cap after JSON and text prompt overhead.
    needs_public = total_bytes > 45 * 1024 * 1024
    template = _provider_setting("SEEDANCE_MEDIA_URL_TEMPLATE", "").strip()
    if (oversized or needs_public) and not template:
        if oversized:
            raise GenerationProviderError(
                "Native Ark local image references must each be 30MB or smaller; "
                "set SEEDANCE_MEDIA_URL_TEMPLATE for large images"
            )
        raise GenerationProviderError(
            "Native Ark local image references exceed the safe Base64 request-body budget; "
            "set SEEDANCE_MEDIA_URL_TEMPLATE"
        )
    if shutil.which("ffprobe"):
        for path in local_paths:
            try:
                result = subprocess.run(
                    [
                        "ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "csv=p=0:s=x", str(path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                dimensions = result.stdout.strip().split("x")
                if len(dimensions) != 2:
                    continue
                width, height = (int(value) for value in dimensions)
                if width <= 0 or height <= 0:
                    continue
                ratio = width / height if height else 0.0
                if width < 300 or height < 300 or width > 6000 or height > 6000:
                    raise GenerationProviderError(
                        f"Native Ark image dimensions must be 300-6000px: {path} is {width}x{height}"
                    )
                if ratio < 0.4 or ratio > 2.5:
                    raise GenerationProviderError(
                        f"Native Ark image aspect ratio must be 0.4-2.5: {path} is {ratio:.3f}"
                    )
            except GenerationProviderError:
                raise
            except (OSError, ValueError, subprocess.SubprocessError):
                # Placeholder fixtures and uncommon image codecs may not be
                # probeable here; the Ark request remains responsible for
                # validating those formats.
                continue
    return bool(template and (oversized or needs_public))


def _validate_native_ark_audio_references(
    audio_paths: list[str],
    *,
    maximum_duration: float = 30.0,
) -> bool:
    """Validate local audio against Ark's per-file and aggregate limits."""
    local_paths = [Path(path) for path in audio_paths if path and Path(path).is_file()]
    if not local_paths:
        return False
    unsupported = [path for path in local_paths if path.suffix.lower() not in {".wav", ".mp3"}]
    if unsupported:
        raise GenerationProviderError(
            "Native Ark reference audio must use WAV or MP3: "
            + ", ".join(str(path) for path in unsupported)
        )
    media_template = _provider_setting("SEEDANCE_MEDIA_URL_TEMPLATE", "").strip()
    total_bytes = sum(path.stat().st_size for path in local_paths)
    oversized = any(path.stat().st_size > 15 * 1024 * 1024 for path in local_paths)
    needs_public = oversized or total_bytes > 48 * 1024 * 1024
    if oversized and not media_template:
        raise GenerationProviderError("Native Ark local audio references must each be 15MB or smaller")
    # Base64 expansion plus prompt/image payload leaves a conservative 48MB
    # raw-audio budget under Ark's 64MB request-body limit.
    if total_bytes > 48 * 1024 * 1024 and not media_template:
        raise GenerationProviderError("Native Ark local audio references exceed the safe 48MB aggregate payload budget")
    if not shutil.which("ffprobe"):
        raise GenerationProviderError(
            "Native Ark local audio references require ffprobe for duration and signal validation"
        )
    durations: list[float] = []
    for path in local_paths:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            duration = float(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise GenerationProviderError(
                f"Could not measure Native Ark audio reference duration: {path}"
            ) from exc
        if duration < 2.0 or duration > maximum_duration:
            raise GenerationProviderError(
                f"Native Ark audio reference must be 2-{maximum_duration:g} seconds: "
                f"{path} is {duration:.3f}s"
            )
        durations.append(duration)
    if durations and sum(durations) > maximum_duration:
        raise GenerationProviderError(
            f"Native Ark audio references must total {maximum_duration:g} seconds or less"
        )
    return bool(media_template and needs_public)


def _validate_native_ark_video_references(
    video_paths: list[str],
    *,
    is_25: bool,
    edit_or_extend: bool,
) -> None:
    """Validate local reference videos before sending a paid Ark request.

    Public URLs and ``asset://`` IDs cannot be inspected safely from this
    process, so Ark remains the authority for those inputs. Local files are
    checked against the documented container, size, duration, frame-rate and
    aggregate-duration contract when ffprobe can read them.
    """
    local_paths = [Path(path) for path in video_paths if path and Path(path).is_file()]
    if not local_paths:
        return
    unsupported = [path for path in local_paths if path.suffix.lower() not in {".mp4", ".mov"}]
    if unsupported:
        raise GenerationProviderError(
            "Native Ark reference video must use MP4 or MOV: "
            + ", ".join(str(path) for path in unsupported)
        )
    media_template = _provider_setting("SEEDANCE_MEDIA_URL_TEMPLATE", "").strip()
    oversized = [path for path in local_paths if path.stat().st_size > 200 * 1024 * 1024]
    if oversized and not media_template:
        raise GenerationProviderError(
            "Native Ark local reference videos must each be 200MB or smaller; "
            "set SEEDANCE_MEDIA_URL_TEMPLATE for large videos"
        )
    if not shutil.which("ffprobe"):
        raise GenerationProviderError(
            "Native Ark local video references require ffprobe for geometry and duration validation"
        )

    durations: list[float] = []
    for path in local_paths:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries",
                    "stream=width,height,r_frame_rate:format=duration",
                    "-of", "json", str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            payload = json.loads(result.stdout)
            streams = payload.get("streams") or []
            stream = streams[0] if streams and isinstance(streams[0], dict) else {}
            format_data = payload.get("format") or {}
            duration = float(format_data.get("duration") or 0)
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            fps = _parse_provider_frame_rate(str(stream.get("r_frame_rate") or "0/1"))
        except (OSError, TypeError, ValueError, KeyError, IndexError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            raise GenerationProviderError(
                f"Could not inspect Native Ark video reference: {path}"
            ) from exc
        if duration <= 0:
            raise GenerationProviderError(
                f"Native Ark video reference has no measurable duration: {path}"
            )
        minimum_duration = 4.0 if is_25 and edit_or_extend else 2.0
        maximum_duration = 30.0 if is_25 else 15.0
        if duration < minimum_duration or duration > maximum_duration:
            raise GenerationProviderError(
                f"Native Ark reference video must be {minimum_duration:g}-{maximum_duration:g} seconds: "
                f"{path} is {duration:.3f}s"
            )
        if fps < 24.0 or fps > 60.0:
            raise GenerationProviderError(
                f"Native Ark reference video FPS must be 24-60: {path} is {fps:.3f}"
            )
        if width and height:
            ratio = width / height
            pixels = width * height
            if ratio < 0.4 or ratio > 2.5:
                raise GenerationProviderError(
                    f"Native Ark reference video aspect ratio must be 0.4-2.5: "
                    f"{path} is {ratio:.3f}"
                )
            if pixels < 407696 or pixels > 8295044:
                raise GenerationProviderError(
                    f"Native Ark reference video pixel count is outside 407696-8295044: "
                    f"{path} is {width}x{height}"
                )
        durations.append(duration)
    if durations:
        total_limit = 30.0 if is_25 else 15.0
        if sum(durations) > total_limit + 1e-3:
            raise GenerationProviderError(
                f"Native Ark reference videos must total {total_limit:g} seconds or less"
            )


def _parse_provider_frame_rate(value: str) -> float:
    try:
        if "/" not in value:
            return float(value or 0)
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator or 1)
        return float(numerator or 0) / denominator_value if denominator_value else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _download_video(client, url: str, output_path: str, headers: dict[str, str]) -> str:
    response = client.get(url, headers=headers)
    response.raise_for_status()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(response.content)
    if Path(output_path).stat().st_size <= 0:
        raise GenerationProviderError("Downloaded video is empty")
    return output_path


def _write_base64_video(encoded: str, output_path: str) -> str:
    if "," in encoded and encoded.strip().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise GenerationProviderError("Video base64 payload is invalid") from exc
    return _atomic_write_video(decoded, output_path)


def _atomic_write_video(content: bytes, output_path: str) -> str:
    """Commit a downloaded/decoded video only after the complete write succeeds."""
    if not content:
        raise GenerationProviderError("Video payload is empty")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    try:
        temporary.write_bytes(content)
        if temporary.stat().st_size <= 0:
            raise GenerationProviderError("Video payload is empty")
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(destination)
