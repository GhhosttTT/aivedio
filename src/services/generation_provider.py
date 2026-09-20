"""Generation provider abstraction.

The system can use local ComfyUI for low-cost drafts and API providers for
high-quality production shots. API providers are intentionally strict: without
real integration settings they fail clearly instead of returning fake assets.
"""

from __future__ import annotations

import os
import base64
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Protocol

import httpx

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GenerationProviderError(Exception):
    """Raised when a generation provider cannot fulfill a request."""


class GenerationProviderName(str, Enum):
    LOCAL_COMFYUI = "local_comfyui"
    JIMENG_API = "jimeng_api"
    KLING_API = "kling_api"
    HAILUO_API = "hailuo_api"
    HTTP_VIDEO_API = "http_video_api"
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


@dataclass
class VideoGenerationRequest:
    prompt: str
    output_path: str
    negative_prompt: Optional[str] = None
    reference_image: Optional[str] = None
    end_image: Optional[str] = None
    duration_seconds: float = 5.0
    aspect_ratio: str = "16:9"
    width: int = 1024
    height: int = 576
    fps: int = 8
    seed: int = -1
    motion_bucket_id: int = 127
    noise_aug_strength: float = 0.02


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
        high_quality_request = str(request.quality_mode or "").lower() in {"high_quality", "ultra"}
        enable_prompt_optimization = bool(
            settings.GENERATION_ENABLE_PROMPT_OPTIMIZATION
            and (high_quality_request or request.optimization_mode)
        )
        enable_parameter_optimization = bool(
            settings.GENERATION_ENABLE_PARAMETER_OPTIMIZATION
            and high_quality_request
        )
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
            quality_mode=request.quality_mode,
            optimization_mode=request.optimization_mode,
            enable_realism=False,
            enable_prompt_optimization=enable_prompt_optimization,
            enable_parameter_optimization=enable_parameter_optimization,
        )
        return GenerationResult(
            provider=self.name.value,
            output_path=output_path,
            asset_type="image",
            metadata={"width": request.width, "height": request.height},
        )

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        output_path = self.comfyui_service.generate_video(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt or "",
            reference_image=request.reference_image,
            end_image=request.end_image,
            output_path=request.output_path,
            width=request.width,
            height=request.height,
            duration_seconds=request.duration_seconds,
            fps=request.fps,
            seed=request.seed,
            motion_bucket_id=request.motion_bucket_id,
            noise_aug_strength=request.noise_aug_strength,
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
                "motion_bucket_id": request.motion_bucket_id,
                "noise_aug_strength": request.noise_aug_strength,
            },
        )


class ApiVideoProvider:
    """Base class for external image/video generation providers."""

    name: GenerationProviderName
    env_prefix: str

    def __init__(self, endpoint: Optional[str] = None, api_key: Optional[str] = None):
        self.endpoint = endpoint or os.getenv(f"{self.env_prefix}_ENDPOINT", "")
        self.api_key = api_key or os.getenv(f"{self.env_prefix}_API_KEY", "")
        self.status_endpoint = os.getenv(f"{self.env_prefix}_STATUS_ENDPOINT", "")
        self.timeout = int(os.getenv(f"{self.env_prefix}_TIMEOUT_SECONDS", "1800"))
        self.poll_interval = float(os.getenv(f"{self.env_prefix}_POLL_INTERVAL_SECONDS", "5"))
        self.max_polls = int(os.getenv(f"{self.env_prefix}_MAX_POLLS", "240"))
        self.auth_header = os.getenv(f"{self.env_prefix}_AUTH_HEADER", "Authorization")
        self.auth_scheme = os.getenv(f"{self.env_prefix}_AUTH_SCHEME", "Bearer")

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
        payload = self._video_payload(request)
        headers = self._headers()
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            final_path = self._resolve_video_result(client, data, request.output_path, headers)
        return GenerationResult(
            provider=self.name.value,
            output_path=final_path,
            asset_type="video",
            metadata={"endpoint": self.endpoint, "status_endpoint": self.status_endpoint or None},
        )

    def _headers(self) -> dict[str, str]:
        token = self.api_key if not self.auth_scheme else f"{self.auth_scheme} {self.api_key}"
        return {self.auth_header: token, "Accept": "application/json"}

    def _video_payload(self, request: VideoGenerationRequest) -> dict:
        return {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or "",
            "reference_image": _file_data_url(request.reference_image),
            "end_image": _file_data_url(request.end_image),
            "duration_seconds": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "width": request.width,
            "height": request.height,
            "fps": request.fps,
            "seed": request.seed,
            "motion_bucket_id": request.motion_bucket_id,
            "noise_aug_strength": request.noise_aug_strength,
        }

    def _resolve_video_result(self, client, data: dict, output_path: str, headers: dict[str, str]) -> str:
        direct = _extract_first(data, ("video_url", "url", "output_url", "download_url"))
        if direct:
            return _download_video(client, str(direct), output_path, headers)
        encoded = _extract_first(data, ("video_base64", "base64", "output_base64"))
        if encoded:
            return _write_base64_video(str(encoded), output_path)
        job_id = _extract_first(data, ("job_id", "task_id", "id"))
        if not job_id:
            raise GenerationProviderError(f"{self.name.value} response has no video_url/video_base64/job_id")
        if not self.status_endpoint:
            raise GenerationProviderError(f"{self.name.value} returned job_id but {self.env_prefix}_STATUS_ENDPOINT is not configured")
        status_url = self.status_endpoint.replace("{job_id}", str(job_id))
        for _ in range(self.max_polls):
            status_response = client.get(status_url, headers=headers)
            status_response.raise_for_status()
            status = status_response.json()
            state = str(_extract_first(status, ("status", "state", "task_status")) or "").lower()
            if state in {"failed", "error", "cancelled", "canceled"}:
                raise GenerationProviderError(f"{self.name.value} job failed: {status}")
            direct = _extract_first(status, ("video_url", "url", "output_url", "download_url"))
            if direct:
                return _download_video(client, str(direct), output_path, headers)
            encoded = _extract_first(status, ("video_base64", "base64", "output_base64"))
            if encoded:
                return _write_base64_video(str(encoded), output_path)
            time.sleep(self.poll_interval)
        raise GenerationProviderError(f"{self.name.value} job timed out")


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


class HybridGenerationProvider:
    """Use API providers for production quality and local ComfyUI as fallback."""

    name = GenerationProviderName.HYBRID

    def __init__(self, primary: GenerationProvider, fallback: GenerationProvider):
        self.primary = primary
        self.fallback = fallback

    def generate_image(self, request: ImageGenerationRequest) -> GenerationResult:
        try:
            return self.primary.generate_image(request)
        except GenerationProviderError as exc:
            logger.warning("Primary image provider failed; falling back to local provider: {}", exc)
            return self.fallback.generate_image(request)

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        try:
            return self.primary.generate_video(request)
        except GenerationProviderError as exc:
            logger.warning("Primary video provider failed; falling back to local provider: {}", exc)
            return self.fallback.generate_video(request)


def get_generation_provider(provider_name: Optional[str] = None) -> GenerationProvider:
    configured = provider_name or os.getenv("GENERATION_PROVIDER", "local_comfyui")
    name = GenerationProviderName(configured)

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
    if name == GenerationProviderName.HYBRID:
        primary_name = os.getenv("GENERATION_PRIMARY_PROVIDER", GenerationProviderName.JIMENG_API.value)
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
    mime = "image/png" if suffix == ".png" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else "application/octet-stream"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(base64.b64decode(encoded))
    if Path(output_path).stat().st_size <= 0:
        raise GenerationProviderError("Decoded video is empty")
    return output_path
