"""Tests for generation provider abstraction."""

import pytest

from src.services.generation_provider import (
    GenerationProviderError,
    GenerationProviderName,
    GenerationResult,
    HailuoApiProvider,
    HttpVideoApiProvider,
    ImageGenerationRequest,
    JimengApiProvider,
    KlingApiProvider,
    LocalComfyUIProvider,
    VideoGenerationRequest,
    get_generation_provider,
)


class FakeComfyUIService:
    def __init__(self):
        self.last_kwargs = None

    def generate_image(self, **kwargs):
        self.last_kwargs = kwargs
        return kwargs["output_path"]

    def generate_video(self, **kwargs):
        self.last_kwargs = kwargs
        return kwargs["output_path"]


def test_local_comfyui_provider_delegates_image_generation():
    service = FakeComfyUIService()
    provider = LocalComfyUIProvider(comfyui_service=service)

    result = provider.generate_image(
        ImageGenerationRequest(
            prompt="raw photo, short drama shot",
            output_path="storage/project_1/images/scene_1.png",
            width=1024,
            height=576,
        )
    )

    assert result == GenerationResult(
        provider=GenerationProviderName.LOCAL_COMFYUI.value,
        output_path="storage/project_1/images/scene_1.png",
        asset_type="image",
        metadata={"width": 1024, "height": 576},
    )
    assert service.last_kwargs["prompt"] == "raw photo, short drama shot"
    assert service.last_kwargs["enable_realism"] is False
    assert service.last_kwargs["enable_prompt_optimization"] is False
    assert service.last_kwargs["enable_parameter_optimization"] is False


def test_local_comfyui_provider_enables_optimizers_for_ultra_quality(monkeypatch):
    service = FakeComfyUIService()
    provider = LocalComfyUIProvider(comfyui_service=service)
    monkeypatch.setattr("src.services.generation_provider.settings.GENERATION_ENABLE_PROMPT_OPTIMIZATION", True)
    monkeypatch.setattr("src.services.generation_provider.settings.GENERATION_ENABLE_PARAMETER_OPTIMIZATION", True)

    provider.generate_image(
        ImageGenerationRequest(
            prompt="raw photo, short drama shot",
            output_path="storage/project_1/images/scene_1.png",
            quality_mode="ultra",
            optimization_mode="quality",
        )
    )

    assert service.last_kwargs["quality_mode"] == "ultra"
    assert service.last_kwargs["optimization_mode"] == "quality"
    assert service.last_kwargs["enable_prompt_optimization"] is True
    assert service.last_kwargs["enable_parameter_optimization"] is True


@pytest.mark.parametrize(
    "provider_cls,prefix",
    [
        (JimengApiProvider, "JIMENG"),
        (KlingApiProvider, "KLING"),
        (HailuoApiProvider, "HAILUO"),
    ],
)
def test_api_provider_requires_configuration(provider_cls, prefix, monkeypatch):
    monkeypatch.delenv(f"{prefix}_ENDPOINT", raising=False)
    monkeypatch.delenv(f"{prefix}_API_KEY", raising=False)

    provider = provider_cls()
    with pytest.raises(GenerationProviderError, match=f"{prefix}_ENDPOINT"):
        provider.generate_image(
            ImageGenerationRequest(prompt="test", output_path="out.png")
        )


def test_local_comfyui_provider_delegates_video_generation():
    service = FakeComfyUIService()
    provider = LocalComfyUIProvider(comfyui_service=service)

    result = provider.generate_video(
        VideoGenerationRequest(
            prompt="woman turns toward camera",
            negative_prompt="flicker",
            reference_image="scene.png",
            output_path="storage/project_1/videos/scene_1.mp4",
            duration_seconds=2.0,
            width=1344,
            height=768,
            fps=8,
            seed=42,
            motion_bucket_id=96,
            noise_aug_strength=0.012,
        )
    )

    assert result.provider == GenerationProviderName.LOCAL_COMFYUI.value
    assert result.asset_type == "video"
    assert result.output_path == "storage/project_1/videos/scene_1.mp4"
    assert service.last_kwargs["prompt"] == "woman turns toward camera"
    assert service.last_kwargs["reference_image"] == "scene.png"
    assert service.last_kwargs["negative_prompt"] == "flicker"
    assert service.last_kwargs["fps"] == 8
    assert service.last_kwargs["motion_bucket_id"] == 96
    assert service.last_kwargs["noise_aug_strength"] == 0.012
    assert result.metadata["motion_bucket_id"] == 96
    assert result.metadata["noise_aug_strength"] == 0.012


def test_get_generation_provider_from_argument(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "jimeng_api")
    provider = get_generation_provider("local_comfyui")
    assert isinstance(provider, LocalComfyUIProvider)


def test_get_generation_provider_from_environment(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "kling_api")
    provider = get_generation_provider()
    assert isinstance(provider, KlingApiProvider)


def test_http_video_provider_downloads_synchronous_video(tmp_path, monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload=None, content=b"video"):
            self.payload = payload or {}
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, json, headers):
            calls.append(("post", url, json, headers))
            return FakeResponse({"video_url": "https://media.example/out.mp4"})

        def get(self, url, headers):
            calls.append(("get", url, headers))
            return FakeResponse(content=b"mp4-bytes")

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    output = tmp_path / "scene.mp4"

    result = provider.generate_video(VideoGenerationRequest(prompt="hero turns", output_path=str(output)))

    assert result.output_path == str(output)
    assert output.read_bytes() == b"mp4-bytes"
    assert calls[1][2]["prompt"] == "hero turns"
    assert calls[1][3]["Authorization"] == "Bearer secret"


def test_http_video_provider_polls_async_job(tmp_path, monkeypatch):
    class FakeResponse:
        def __init__(self, payload=None, content=b"video"):
            self.payload = payload or {}
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        polls = 0

        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse({"job_id": "abc"})

        def get(self, url, **_kwargs):
            if "status" in url:
                FakeClient.polls += 1
                if FakeClient.polls == 1:
                    return FakeResponse({"status": "running"})
                return FakeResponse({"status": "completed", "video_url": "https://media.example/out.mp4"})
            return FakeResponse(content=b"done")

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    monkeypatch.setattr("src.services.generation_provider.time.sleep", lambda *_args: None)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.poll_interval = 0
    output = tmp_path / "scene.mp4"

    result = provider.generate_video(VideoGenerationRequest(prompt="hero turns", output_path=str(output)))

    assert result.output_path == str(output)
    assert output.read_bytes() == b"done"
    assert FakeClient.polls == 2


def test_get_generation_provider_supports_http_video(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "http_video_api")
    provider = get_generation_provider()
    assert isinstance(provider, HttpVideoApiProvider)
