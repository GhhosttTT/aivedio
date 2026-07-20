"""Generation provider abstraction.

The system can use local ComfyUI for low-cost drafts and API providers for
high-quality production shots. API providers are intentionally strict: without
real integration settings they fail clearly instead of returning fake assets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Protocol

from src.utils.logger import get_logger

logger = get_logger(__name__)


class GenerationProviderError(Exception):
    """Raised when a generation provider cannot fulfill a request."""


class GenerationProviderName(str, Enum):
    LOCAL_COMFYUI = "local_comfyui"
    JIMENG_API = "jimeng_api"
    KLING_API = "kling_api"
    HAILUO_API = "hailuo_api"
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
    reference_image: Optional[str] = None
    duration_seconds: float = 5.0
    aspect_ratio: str = "16:9"
    seed: int = -1


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
            enable_realism=True,
        )
        return GenerationResult(
            provider=self.name.value,
            output_path=output_path,
            asset_type="image",
            metadata={"width": request.width, "height": request.height},
        )

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        raise GenerationProviderError("本地 ComfyUI provider 暂未实现视频生成，请继续使用现有 SVD 任务")


class ApiVideoProvider:
    """Base class for external image/video generation providers."""

    name: GenerationProviderName
    env_prefix: str

    def __init__(self, endpoint: Optional[str] = None, api_key: Optional[str] = None):
        self.endpoint = endpoint or os.getenv(f"{self.env_prefix}_ENDPOINT", "")
        self.api_key = api_key or os.getenv(f"{self.env_prefix}_API_KEY", "")

    def _ensure_configured(self) -> None:
        if not self.endpoint or not self.api_key:
            raise GenerationProviderError(
                f"{self.name.value} 未配置。请设置 {self.env_prefix}_ENDPOINT 和 {self.env_prefix}_API_KEY"
            )

    def generate_image(self, request: ImageGenerationRequest) -> GenerationResult:
        self._ensure_configured()
        raise GenerationProviderError(f"{self.name.value} 图片生成 API 尚未接入具体协议")

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        self._ensure_configured()
        raise GenerationProviderError(f"{self.name.value} 视频生成 API 尚未接入具体协议")


class JimengApiProvider(ApiVideoProvider):
    name = GenerationProviderName.JIMENG_API
    env_prefix = "JIMENG"


class KlingApiProvider(ApiVideoProvider):
    name = GenerationProviderName.KLING_API
    env_prefix = "KLING"


class HailuoApiProvider(ApiVideoProvider):
    name = GenerationProviderName.HAILUO_API
    env_prefix = "HAILUO"


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
            logger.warning("主生成 provider 失败，回退到本地 provider: {}", exc)
            return self.fallback.generate_image(request)

    def generate_video(self, request: VideoGenerationRequest) -> GenerationResult:
        try:
            return self.primary.generate_video(request)
        except GenerationProviderError as exc:
            logger.warning("主视频 provider 失败，回退到本地 provider: {}", exc)
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
    if name == GenerationProviderName.HYBRID:
        primary_name = os.getenv("GENERATION_PRIMARY_PROVIDER", GenerationProviderName.JIMENG_API.value)
        return HybridGenerationProvider(
            primary=get_generation_provider(primary_name),
            fallback=LocalComfyUIProvider(),
        )

    raise GenerationProviderError(f"不支持的生成 provider: {provider_name}")
