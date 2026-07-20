"""Tests for generation provider abstraction."""

import pytest

from src.services.generation_provider import (
    GenerationProviderError,
    GenerationProviderName,
    GenerationResult,
    HailuoApiProvider,
    ImageGenerationRequest,
    JimengApiProvider,
    KlingApiProvider,
    LocalComfyUIProvider,
    get_generation_provider,
)


class FakeComfyUIService:
    def __init__(self):
        self.last_kwargs = None

    def generate_image(self, **kwargs):
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
    assert service.last_kwargs["enable_realism"] is True


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


def test_get_generation_provider_from_argument(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "jimeng_api")
    provider = get_generation_provider("local_comfyui")
    assert isinstance(provider, LocalComfyUIProvider)


def test_get_generation_provider_from_environment(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "kling_api")
    provider = get_generation_provider()
    assert isinstance(provider, KlingApiProvider)
