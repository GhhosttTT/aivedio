"""Tests for generation provider abstraction."""

import json
import os
import subprocess
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import src.services.generation_provider as generation_provider
from PIL import Image

from src.services.generation_provider import (
    GenerationCancelledError,
    GenerationProviderError,
    GenerationProviderName,
    GenerationResult,
    HailuoApiProvider,
    HttpVideoApiProvider,
    ImageGenerationRequest,
    JimengApiProvider,
    KlingApiProvider,
    LocalComfyUIProvider,
    HybridGenerationProvider,
    SeedanceApiProvider,
    VideoGenerationRequest,
    _seedance_prompt,
    _seedance_duration_bounds,
    _extract_video_url,
    _extract_media_url,
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


@pytest.fixture(autouse=True)
def disable_generic_output_validation_for_legacy_doubles(monkeypatch):
    """Legacy gateway doubles return bytes, not actual playable videos."""
    for prefix in ("JIMENG", "KLING", "HAILUO", "HTTP_VIDEO"):
        monkeypatch.setenv(f"{prefix}_VALIDATE_OUTPUT", "false")


@pytest.fixture(autouse=True)
def probe_placeholder_media_as_valid_test_inputs(monkeypatch):
    """Make tiny test doubles behave like measured media until a test overrides ffprobe."""
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")

    def fake_run(command, **_kwargs):
        command_text = " ".join(str(item) for item in command)
        if "codec_type" in command_text:
            return SimpleNamespace(stdout=json.dumps({
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1080, "height": 1920},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
                "format": {"duration": "5.0"},
            }))
        if "stream=width,height,r_frame_rate:format=duration" in command_text:
            return SimpleNamespace(stdout=json.dumps({
                "streams": [{"width": 1080, "height": 1920, "r_frame_rate": "24/1"}],
                "format": {"duration": "5.0"},
            }))
        if "stream=width,height" in command_text:
            return SimpleNamespace(stdout="1080x1920\n")
        return SimpleNamespace(stdout="5.0\n")

    monkeypatch.setattr(generation_provider.subprocess, "run", fake_run)


@pytest.mark.parametrize(
    ("suffix", "mime"),
    [(".bmp", "image/bmp"), (".gif", "image/gif"), (".tiff", "image/tiff"), (".heic", "image/heic"), (".flac", "audio/flac")],
)
def test_local_media_data_url_uses_supported_mime_type(tmp_path, suffix, mime):
    path = tmp_path / f"asset{suffix}"
    path.write_bytes(b"media")

    assert generation_provider._file_data_url(str(path)).startswith(f"data:{mime};base64,")


def test_native_ark_video_reference_validation_rejects_invalid_fps(tmp_path, monkeypatch):
    path = tmp_path / "reference.mp4"
    path.write_bytes(b"video")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def fake_run(_command, **_kwargs):
        return SimpleNamespace(
            stdout=json.dumps({
                "streams": [{
                    "width": 1080,
                    "height": 1920,
                    "r_frame_rate": "15/1",
                }],
                "format": {"duration": "5"},
            })
        )

    monkeypatch.setattr(generation_provider.subprocess, "run", fake_run)
    with pytest.raises(GenerationProviderError, match="FPS must be 24-60"):
        generation_provider._validate_native_ark_video_references(
            [str(path)], is_25=True, edit_or_extend=False,
        )


def test_native_ark_video_reference_validation_enforces_aggregate_duration(tmp_path, monkeypatch):
    paths = [tmp_path / "one.mp4", tmp_path / "two.mp4"]
    for path in paths:
        path.write_bytes(b"video")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def fake_run(_command, **_kwargs):
        return SimpleNamespace(
            stdout=json.dumps({
                "streams": [{
                    "width": 1080,
                    "height": 1920,
                    "r_frame_rate": "24/1",
                }],
                "format": {"duration": "16"},
            })
        )

    monkeypatch.setattr(generation_provider.subprocess, "run", fake_run)
    with pytest.raises(GenerationProviderError, match="total 30 seconds or less"):
        generation_provider._validate_native_ark_video_references(
            [str(path) for path in paths], is_25=True, edit_or_extend=False,
        )


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

    assert result.provider == GenerationProviderName.LOCAL_COMFYUI.value
    assert result.output_path == "storage/project_1/images/scene_1.png"
    assert result.asset_type == "image"
    assert result.metadata["width"] == 1024
    assert result.metadata["height"] == 576
    assert result.metadata["prompt_optimization"] is False
    assert result.metadata["parameter_optimization"] is False
    assert service.last_kwargs["prompt"] == "raw photo, short drama shot"
    assert service.last_kwargs["enable_realism"] is False
    assert service.last_kwargs["enable_prompt_optimization"] is False
    assert service.last_kwargs["enable_parameter_optimization"] is False


def test_local_comfyui_provider_forwards_spatial_control_contract():
    service = FakeComfyUIService()
    provider = LocalComfyUIProvider(comfyui_service=service)

    provider.generate_image(ImageGenerationRequest(
        prompt="locked shot",
        output_path="storage/project_1/images/scene_1.png",
        spatial_plan={"camera_angle": "eye level"},
        spatial_control_references={"pose_reference_prompt": "hands visible"},
        spatial_asset_pack={"scene_contract_hash": "scene-hash"},
    ))

    assert service.last_kwargs["spatial_plan"] == {"camera_angle": "eye level"}
    assert service.last_kwargs["spatial_control_references"] == {"pose_reference_prompt": "hands visible"}
    assert service.last_kwargs["spatial_asset_pack"]["scene_contract_hash"] == "scene-hash"


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


def test_local_comfyui_provider_maps_reference_profiles_to_supported_quality_modes(monkeypatch):
    service = FakeComfyUIService()
    provider = LocalComfyUIProvider(comfyui_service=service)
    monkeypatch.setattr("src.services.generation_provider.settings.GENERATION_ENABLE_PROMPT_OPTIMIZATION", True)
    monkeypatch.setattr("src.services.generation_provider.settings.GENERATION_ENABLE_PARAMETER_OPTIMIZATION", True)

    result = provider.generate_image(
        ImageGenerationRequest(
            prompt="raw photo, premium vertical short drama shot",
            output_path="storage/project_1/images/scene_1.png",
            quality_mode="seed_dance_reference",
            optimization_mode="quality",
        )
    )

    assert service.last_kwargs["quality_mode"] == "ultra"
    assert service.last_kwargs["enable_prompt_optimization"] is True
    assert service.last_kwargs["enable_parameter_optimization"] is True
    assert result.metadata["quality_mode"] == "seed_dance_reference"
    assert result.metadata["effective_quality_mode"] == "ultra"


def test_local_comfyui_provider_reports_actual_workflow_parameters(tmp_path):
    class WorkflowWritingComfyUIService(FakeComfyUIService):
        def generate_image(self, **kwargs):
            self.last_kwargs = kwargs
            workflow = {
                "8": {
                    "class_type": "KSampler",
                    "inputs": {
                        "steps": 45,
                        "cfg": 7.0,
                        "seed": 123,
                        "sampler_name": "dpmpp_2m",
                        "scheduler": "karras",
                    },
                },
                "7": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": 1344, "height": 768, "batch_size": 1},
                },
            }
            workflow_path = tmp_path / "scene.workflow.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            return str(tmp_path / "scene.png")

    provider = LocalComfyUIProvider(comfyui_service=WorkflowWritingComfyUIService())

    result = provider.generate_image(
        ImageGenerationRequest(
            prompt="raw photo, short drama shot",
            output_path=str(tmp_path / "scene.png"),
            quality_mode="ultra",
            optimization_mode="quality",
        )
    )

    assert result.metadata["workflow"]["steps"] == 45
    assert result.metadata["workflow"]["cfg"] == 7.0
    assert result.metadata["workflow"]["sampler_name"] == "dpmpp_2m"
    assert result.metadata["workflow"]["latent_width"] == 1344
    assert result.metadata["workflow"]["latent_height"] == 768


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


def test_api_provider_reads_loaded_settings_when_environment_is_empty(monkeypatch):
    for name in (
        "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_STATUS_ENDPOINT",
        "SEEDANCE_RESULT_ENDPOINT", "SEEDANCE_TIMEOUT_SECONDS",
        "SEEDANCE_POLL_INTERVAL_SECONDS", "SEEDANCE_MAX_POLLS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = __import__("src.services.generation_provider", fromlist=["settings"]).settings
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://example.test/generate")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "settings-token")
    monkeypatch.setattr(settings, "SEEDANCE_STATUS_ENDPOINT", "https://example.test/status/{job_id}")
    monkeypatch.setattr(settings, "SEEDANCE_RESULT_ENDPOINT", "https://example.test/result/{request_id}")

    provider = SeedanceApiProvider()

    assert provider.endpoint == "https://example.test/generate"
    assert provider.api_key == "settings-token"
    assert provider.status_endpoint.endswith("{job_id}")
    assert provider.result_endpoint.endswith("{request_id}")


def test_seedance_ark_provider_derives_task_status_endpoint(monkeypatch):
    for name in ("SEEDANCE_STATUS_ENDPOINT", "SEEDANCE_RESULT_ENDPOINT", "SEEDANCE_API_FORMAT"):
        monkeypatch.delenv(name, raising=False)
    settings = __import__("src.services.generation_provider", fromlist=["settings"]).settings
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(
        endpoint="https://ark.example/api/v3/contents/generations/tasks",
        api_key="secret",
    )

    assert provider.status_endpoint.endswith("tasks/{job_id}")
    assert provider.result_endpoint == ""


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
            quality_mode="seed_dance_reference",
            repair_action="refine_video_commercial_aesthetic",
            quality_pipeline={"stages": ["platform_reference_gap_repair"]},
            shot_plan={
                "spatial_asset_pack": {
                    "scene_contract_hash": "scene-hash",
                    "project_signature": "project-hash",
                },
            },
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
    assert service.last_kwargs["quality_mode"] == "seed_dance_reference"
    assert service.last_kwargs["repair_action"] == "refine_video_commercial_aesthetic"
    assert service.last_kwargs["quality_pipeline"] == {"stages": ["platform_reference_gap_repair"]}
    assert result.metadata["motion_bucket_id"] == 96
    assert result.metadata["noise_aug_strength"] == 0.012
    assert result.metadata["quality_mode"] == "seed_dance_reference"
    assert result.metadata["repair_action"] == "refine_video_commercial_aesthetic"
    assert result.metadata["quality_pipeline"] == {"stages": ["platform_reference_gap_repair"]}
    assert result.metadata["spatial_asset_pack"]["scene_contract_hash"] == "scene-hash"
    assert service.last_kwargs["shot_plan"]["spatial_asset_pack"]["project_signature"] == "project-hash"


def test_video_generation_request_defaults_to_mobile_short_drama_canvas():
    request = VideoGenerationRequest(prompt="vertical reaction shot", output_path="scene.mp4")

    assert request.aspect_ratio == "9:16"
    assert request.width == 768
    assert request.height == 1344


def test_get_generation_provider_from_argument(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "jimeng_api")
    provider = get_generation_provider("local_comfyui")
    assert isinstance(provider, LocalComfyUIProvider)


def test_get_generation_provider_from_environment(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "kling_api")
    provider = get_generation_provider()
    assert isinstance(provider, KlingApiProvider)


def test_get_generation_provider_reads_settings_when_environment_is_empty(monkeypatch):
    monkeypatch.delenv("GENERATION_PROVIDER", raising=False)
    settings = __import__("src.services.generation_provider", fromlist=["settings"]).settings
    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")

    provider = get_generation_provider()

    assert isinstance(provider, SeedanceApiProvider)


def test_get_generation_provider_reports_invalid_provider(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "does_not_exist")

    with pytest.raises(GenerationProviderError, match="Unsupported generation provider"):
        get_generation_provider()


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


def test_native_ark_output_validation_rejects_non_video_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "invalid.mp4"
    output.write_bytes(b"not a video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=audio\nduration=4.0\n"),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="invalid video artifact"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_generic_provider_output_validation_rejects_non_video_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_VIDEO_VALIDATE_OUTPUT", "true")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "generic-invalid.mp4"
    output.write_bytes(b"not a video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=audio\nduration=4.0\n"),
    )
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")

    with pytest.raises(GenerationProviderError, match="invalid video artifact"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_fails_closed_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "true")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: None)
    output = tmp_path / "unverified.mp4"
    output.write_bytes(b"unverified-video")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="requires ffprobe"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_legacy_seedance_output_validation_does_not_skip_media_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "legacy")
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "true")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "legacy-invalid.mp4"
    output.write_bytes(b"not a video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=audio\nduration=4.0\n"),
    )
    provider = SeedanceApiProvider(endpoint="https://gateway.example/video", api_key="secret")

    with pytest.raises(GenerationProviderError, match="invalid video artifact"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_accepts_video_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "valid.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_name=hevc\npix_fmt=yuv420p10le\nduration=4.0\n"
        ),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {"status": "available", "motion_energy": 8.0},
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    provider._validate_provider_video(str(output))
    assert output.exists()
    assert provider.last_result_metadata["video_codec"] == "hevc"
    assert provider.last_result_metadata["video_pixel_format"] == "yuv420p10le"
    assert provider.last_result_metadata["video_high_bit_depth"] is True


def test_native_ark_output_validation_uses_video_stream_when_audio_is_first(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "audio-first.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps({
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le", "width": 1920, "height": 1080},
            ],
            "format": {"duration": "4.0"},
        })),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {"status": "available", "motion_energy": 8.0},
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    provider._validate_provider_video(str(output))
    assert provider.last_result_metadata["video_codec"] == "hevc"
    assert provider.last_result_metadata["video_high_bit_depth"] is True


def test_provider_reads_terminal_seedance_callback(tmp_path):
    output = tmp_path / "scene.mp4"
    callback = output.with_suffix(".provider.callback.json")
    callback.write_text(json.dumps({
        "id": "cgt-123",
        "status": "succeeded",
        "content": {"video_url": "https://media.example/video.mp4"},
    }), encoding="utf-8")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    result = provider._load_provider_callback(str(output), "cgt-123")

    assert result["status"] == "succeeded"
    assert provider._load_provider_callback(str(output), "other-task") is None


def test_async_provider_fetches_artifact_after_callback_only_completion(tmp_path, monkeypatch):
    output = tmp_path / "scene.mp4"
    output.with_suffix(".provider.callback.json").write_text(json.dumps({
        "id": "callback-task",
        "status": "completed",
    }), encoding="utf-8")
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.result_endpoint = ""
    provider.max_polls = 1
    provider.poll_interval = 0
    calls = []

    class FakeResponse:
        def json(self):
            return {"status": "completed", "video_url": "https://media.example/scene.mp4"}

    def fake_request(_client, method, url, **_kwargs):
        calls.append((method, url))
        return FakeResponse()

    def fake_download(_client, _url, path, _headers):
        Path(path).write_bytes(b"video")
        return str(path)

    monkeypatch.setattr(provider, "_request_with_retry", fake_request)
    monkeypatch.setattr(provider, "_download_video_with_retry", fake_download)

    result = provider._resolve_video_result(
        object(),
        {"job_id": "callback-task"},
        str(output),
        {},
    )

    assert result == str(output)
    assert calls == [("get", "https://gateway.example/status/callback-task")]
    assert output.read_bytes() == b"video"


def test_async_provider_preserves_failure_from_callback_artifact_lookup(tmp_path, monkeypatch):
    output = tmp_path / "scene.mp4"
    output.with_suffix(".provider.callback.json").write_text(json.dumps({
        "id": "callback-task",
        "status": "completed",
    }), encoding="utf-8")
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.result_endpoint = ""
    provider.max_polls = 1
    provider.poll_interval = 0

    class FakeResponse:
        def json(self):
            return {"status": "failed", "error": {"message": "render worker crashed"}}

    monkeypatch.setattr(provider, "_request_with_retry", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(GenerationProviderError, match="render worker crashed"):
        provider._resolve_video_result(
            object(),
            {"job_id": "callback-task"},
            str(output),
            {},
        )


def test_provider_remembers_draft_creation_time():
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    provider._remember_result_metadata({
        "id": "draft-1",
        "created_at": "2026-10-10T12:00:00Z",
        "status": "succeeded",
    })

    assert provider.last_result_metadata["provider_created_at"] == "2026-10-10T12:00:00Z"


def test_provider_remembers_draft_expiry_time():
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    provider._remember_result_metadata({
        "id": "draft-1",
        "expires_at": "2026-10-17T12:00:00Z",
    })

    assert provider.last_result_metadata["provider_expires_at"] == "2026-10-17T12:00:00Z"


def test_video_request_fingerprint_resolves_environment_defaults(monkeypatch):
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "reference")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "4k")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mp4")
    request = VideoGenerationRequest(prompt="a shot", output_path="scene.mp4")

    first = generation_provider._video_request_fingerprint(request)
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    second = generation_provider._video_request_fingerprint(request)

    assert first != second


def test_video_request_fingerprint_changes_with_motion_and_repair_controls():
    base = VideoGenerationRequest(
        prompt="a shot",
        output_path="scene.mp4",
        width=768,
        height=1344,
        motion_bucket_id=92,
        noise_aug_strength=0.012,
        repair_action="increase_motion_and_regenerate_video",
        quality_pipeline={"stages": ["motion_control"]},
    )
    changed = VideoGenerationRequest(
        prompt="a shot",
        output_path="scene.mp4",
        width=768,
        height=1344,
        motion_bucket_id=118,
        noise_aug_strength=0.012,
        repair_action="increase_motion_and_regenerate_video",
        quality_pipeline={"stages": ["motion_control"]},
    )

    assert generation_provider._video_request_fingerprint(base) != generation_provider._video_request_fingerprint(changed)


def test_video_request_fingerprint_binds_multimodal_reference_file_state(tmp_path):
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference-v1")
    request = VideoGenerationRequest(
        prompt="a shot",
        output_path="scene.mp4",
        reference_images=[str(reference)],
    )
    first = generation_provider._video_request_fingerprint(request)
    reference.write_bytes(b"reference-v2")
    second = generation_provider._video_request_fingerprint(request)

    assert first != second


def test_video_request_fingerprint_detects_content_change_with_preserved_mtime(tmp_path):
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference-v1")
    original_stat = reference.stat()
    request = VideoGenerationRequest(
        prompt="a shot",
        output_path="scene.mp4",
        reference_images=[str(reference)],
    )
    first = generation_provider._video_request_fingerprint(request)
    reference.write_bytes(b"reference-v2")
    os.utime(reference, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = generation_provider._video_request_fingerprint(request)

    assert first != second


def test_native_ark_25_1080p_rejects_8_bit_h264_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "low-fidelity.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_name=h264\npix_fmt=yuv420p\n"
            "width=1920\nheight=1080\nduration=5.0\n"
        ),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="10-bit HEVC"):
        provider._validate_provider_video(
            str(output),
            request=VideoGenerationRequest(
                prompt="vertical shot",
                output_path=str(output),
                model="doubao-seedance-2-5-260628",
                resolution="1080p",
                aspect_ratio="16:9",
            ),
        )
    assert not output.exists()


def test_native_ark_25_1080p_mov_accepts_h264_444_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "native.mov"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_name=h264\npix_fmt=yuv444p\n"
            "width=1920\nheight=1080\nduration=5.0\n"
        ),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {"status": "available", "motion_energy": 8.0},
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    provider._validate_provider_video(
        str(output),
        request=VideoGenerationRequest(
            prompt="vertical shot",
            output_path=str(output),
            model="doubao-seedance-2-5-260628",
            resolution="1080p",
            output_format="mov",
            aspect_ratio="16:9",
        ),
    )
    assert output.exists()


def test_native_ark_20_4k_rejects_8_bit_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "low-fidelity-4k.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_name=h264\npix_fmt=yuv420p\n"
            "width=3840\nheight=2160\nduration=5.0\n"
        ),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="10-bit HEVC"):
        provider._validate_provider_video(
            str(output),
            request=VideoGenerationRequest(
                prompt="wide cinematic shot",
                output_path=str(output),
                model="doubao-seedance-2-0-260128",
                resolution="4k",
                aspect_ratio="16:9",
            ),
        )
    assert not output.exists()


def test_native_ark_output_validation_rejects_geometry_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "1080p")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "wrong-ratio.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=(
                "codec_type=video\ncodec_name=hevc\npix_fmt=yuv420p10le\n"
                "width=1920\nheight=1080\nduration=5.0\n"
            )
        ),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="geometry drift"):
        provider._validate_provider_video(
            str(output),
            request=VideoGenerationRequest(
                prompt="vertical shot",
                output_path=str(output),
                aspect_ratio="9:16",
                resolution="1080p",
            ),
        )
    assert not output.exists()


def test_native_ark_output_validation_rejects_resolution_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "low-resolution.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_name=h264\npix_fmt=yuv420p\nwidth=480\nheight=854\nduration=5.0\n"
        ),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="resolution drift"):
        provider._validate_provider_video(
            str(output),
            request=VideoGenerationRequest(
                prompt="vertical shot",
                output_path=str(output),
                aspect_ratio="9:16",
                resolution="1080p",
            ),
        )
    assert not output.exists()


def test_native_ark_output_validation_requires_audio_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "silent.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=4.0\n"),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="no audio stream"):
        provider._validate_provider_video(str(output), require_audio=True)
    assert not output.exists()


@pytest.mark.parametrize(
    ("metrics", "message"),
    [
        ({"audio_signal_status": "near_silent", "audio_duration_delta_seconds": 0.0}, "audio signal is not usable"),
        ({"audio_signal_status": "usable", "audio_duration_delta_seconds": 0.36}, "audio/video duration drift"),
        ("audio_start_offset", "audio/video stream start offset"),
    ],
)
def test_native_ark_output_validation_rejects_invalid_requested_audio(
    tmp_path, monkeypatch, metrics, message,
):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "invalid-audio.mp4"
    output.write_bytes(b"video")
    if metrics == "audio_start_offset":
        metrics = {
            "audio_signal_status": "usable",
            "audio_duration_delta_seconds": 0.0,
            "audio_video_start_delta_seconds": -0.6,
        }
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_type=audio\nduration=4.0\n"
        ),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "motion_energy": 4.0,
            "max_static_run_seconds": 0.0,
            "max_black_run_seconds": 0.0,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
            **metrics,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match=message):
        provider._validate_provider_video(str(output), require_audio=True)
    assert not output.exists()


def test_native_ark_output_validation_rejects_unusable_returned_audio_without_request(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "returned-silent-audio.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_type=audio\nduration=4.0\n"
        ),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "audio_present": True,
            "audio_signal_status": "near_silent",
            "audio_duration_delta_seconds": 0.0,
            "audio_video_start_delta_seconds": 0.0,
            "motion_energy": 8.0,
            "max_static_run_seconds": 0.0,
            "max_black_run_seconds": 0.0,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="audio signal is not usable"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_rejects_clipped_returned_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "clipped-audio.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="codec_type=video\ncodec_type=audio\nduration=4.0\n"
        ),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "audio_present": True,
            "audio_signal_status": "usable",
            "audio_clipping_status": "clipped",
            "audio_duration_delta_seconds": 0.0,
            "audio_video_start_delta_seconds": 0.0,
            "motion_energy": 8.0,
            "max_static_run_seconds": 0.0,
            "max_black_run_seconds": 0.0,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="audio signal is clipped"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_rejects_duration_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "drifted.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=2.0\n"),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="duration drift"):
        provider._validate_provider_video(str(output), expected_duration=5.0)
    assert not output.exists()


def test_native_ark_output_validation_rejects_non_finite_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "non-finite.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=nan\n"),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="non-positive duration"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_rejects_temporal_freeze(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "frozen.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=4.0\n"),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "motion_energy": 0.1,
            "max_static_run_seconds": 2.0,
            "max_black_run_seconds": 0.0,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="frozen/static"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_rejects_scattered_black_frames(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "black-frames.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=4.0\n"),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "motion_energy": 8.0,
            "max_static_run_seconds": 0.0,
            "max_black_run_seconds": 0.0,
            "black_frame_ratio": 0.2,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="too many black frames"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_rejects_temporal_visual_resets(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "reset-heavy.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=4.0\n"),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "motion_energy": 8.0,
            "max_static_run_seconds": 0.0,
            "max_black_run_seconds": 0.0,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
            "temporal_jump_ratio": 0.5,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="temporal visual resets"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_rejects_extreme_temporal_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "extreme-reset.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=4.0\n"),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "motion_energy": 8.0,
            "max_static_run_seconds": 0.0,
            "max_black_run_seconds": 0.0,
            "brightness_step_p95": 0.0,
            "motion_jitter_ratio": 0.0,
            "temporal_jump_ratio": 0.01,
            "temporal_jump_p95": 0.9,
        },
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="extreme temporal visual reset"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_native_ark_output_validation_fails_closed_without_temporal_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    output = tmp_path / "uninspectable.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="codec_type=video\nduration=4.0\n"),
    )
    monkeypatch.setattr(
        generation_provider,
        "video_candidate_metrics",
        lambda _path: {"status": "unavailable", "error": "unsupported codec"},
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="temporal quality evidence is unavailable"):
        provider._validate_provider_video(str(output))
    assert not output.exists()


def test_seedance_auto_duration_modes_skip_fixed_duration_gate(monkeypatch):
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    assert provider._expected_provider_duration(
        VideoGenerationRequest(
            prompt="extend the shot",
            output_path="scene.mp4",
            request_mode="extend",
            duration_seconds=5.0,
        )
    ) is None
    assert provider._expected_provider_duration(
        VideoGenerationRequest(
            prompt="reference shot",
            output_path="scene.mp4",
            request_mode="reference",
            duration_seconds=5.0,
        )
    ) == 5.0


def test_reference_audio_is_an_output_contract_for_provider_validation(tmp_path):
    request = VideoGenerationRequest(
        prompt="use the supplied dialogue",
        output_path=str(tmp_path / "scene.mp4"),
        reference_audios=[str(tmp_path / "dialogue.wav")],
        generate_audio=False,
    )

    assert generation_provider._request_requires_audio(request) is True


def test_api_provider_preserves_last_frame_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "false")
    class FakeResponse:
        headers = {"content-type": "application/json"}
        content = b"mp4-bytes"

        def __init__(self, payload=None):
            self.payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse({
                "video_url": "https://media.example/out.mp4",
                "last_frame_url": {"url": "https://media.example/last.png"},
            })

        def get(self, *_args, **_kwargs):
            response = FakeResponse()
            response.headers = {"content-type": "video/mp4"}
            return response

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    provider = SeedanceApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    result = provider.generate_video(VideoGenerationRequest(
        prompt="hero turns",
        output_path=str(tmp_path / "scene.mp4"),
        return_last_frame=True,
    ))

    assert result.metadata["last_frame_url"] == "https://media.example/last.png"
    assert result.metadata["requested_draft"] is False


def test_api_provider_does_not_forward_bearer_to_external_signed_media():
    provider = SeedanceApiProvider(endpoint="https://ark.cn-beijing.volcengine.com/api/v3/contents/generations/tasks", api_key="secret")
    headers = {"Authorization": "Bearer secret", "Accept": "application/json"}

    assert provider._media_download_headers(
        "https://tos.example/video.mp4", headers,
    ) == {"Accept": "video/*, image/*, application/octet-stream"}
    assert provider._media_download_headers(
        "https://ark.cn-beijing.volcengine.com/media/video.mp4", headers,
    ) == headers


def test_seedance_legacy_persists_requested_output_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "legacy")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/video", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a premium short-drama shot",
        output_path=str(tmp_path / "out.mp4"),
        output_format="mov",
        resolution="1080p",
        watermark=False,
        return_last_frame=True,
    ))

    assert payload["output_format"] == "mov"
    assert provider.last_result_metadata["requested_resolution"] == "1080p"
    assert provider.last_result_metadata["requested_output_format"] == "mov"
    assert provider.last_result_metadata["requested_watermark"] is False
    assert provider.last_result_metadata["requested_return_last_frame"] is True


def test_api_provider_persists_last_frame_for_cross_shot_continuity(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "false")
    image_buffer = BytesIO()
    Image.new("RGB", (2, 2), (32, 64, 96)).save(image_buffer, format="PNG")
    valid_png = image_buffer.getvalue()

    class FakeResponse:
        def __init__(self, payload=None, *, content=b"", content_type="application/json"):
            self.payload = payload or {}
            self.content = content
            self.headers = {"content-type": content_type}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse({
                "video_url": "https://media.example/out.mp4",
                "last_frame_url": "https://media.example/last.png",
            })

        def get(self, url, **_kwargs):
            if url.endswith("last.png"):
                return FakeResponse(content=valid_png, content_type="image/png")
            return FakeResponse(content=b"mp4-bytes", content_type="video/mp4")

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    output = tmp_path / "scene.mp4"
    provider = SeedanceApiProvider(endpoint="https://gateway.example/video", api_key="secret")

    result = provider.generate_video(VideoGenerationRequest(
        prompt="hero turns",
        output_path=str(output),
        return_last_frame=True,
    ))

    persisted = tmp_path / "scene.last_frame.png"
    assert persisted.read_bytes() == valid_png
    assert result.metadata["last_frame_path"] == str(persisted)


def test_api_provider_rejects_invalid_last_frame_bytes(tmp_path):
    class FakeResponse:
        headers = {"content-type": "image/png"}
        content = b"not-an-image"

        def raise_for_status(self):
            return None

    class FakeClient:
        def get(self, *_args, **_kwargs):
            return FakeResponse()

    provider = SeedanceApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.last_result_metadata["last_frame_url"] = "https://media.example/last.png"

    result = provider._persist_last_frame(
        FakeClient(),
        str(tmp_path / "scene.mp4"),
        {"Authorization": "Bearer secret"},
    )

    assert result is None
    assert "last_frame_path" not in provider.last_result_metadata
    assert not (tmp_path / "scene.last_frame.png").exists()


def test_native_ark_nested_content_response_urls_are_extracted():
    response = {
        "id": "task-123",
        "status": "succeeded",
        "content": {
            "video_url": "https://tos.example/video.mp4",
            "last_frame_url": "https://tos.example/last.png",
        },
    }

    assert _extract_video_url(response) == "https://tos.example/video.mp4"
    assert _extract_media_url(response, ("last_frame_url",)) == "https://tos.example/last.png"


def test_native_ark_sdk_file_url_is_accepted_as_video_result():
    assert _extract_video_url({
        "status": "succeeded",
        "content": {"file_url": "https://tos.example/sdk-file.mp4"},
    }) == "https://tos.example/sdk-file.mp4"


def test_native_ark_result_metadata_preserves_quality_provenance():
    provider = SeedanceApiProvider(
        endpoint="https://ark.cn-beijing.volcengine.com/api/v3/contents/generations/tasks",
        api_key="secret",
    )
    provider._remember_result_metadata({
        "id": "cgt-123",
        "model": "doubao-seedance-2-5-260628",
        "status": "succeeded",
        "content": {
            "video_url": "https://tos.example/video.mp4",
            "last_frame_url": "https://tos.example/last.png",
        },
        "usage": {"completion_tokens": 246840, "total_tokens": 246840},
        "resolution": "1080p",
        "ratio": "9:16",
        "duration": 5,
        "framespersecond": 24,
        "output_format": "mp4",
        "seed": 58944,
        "service_tier": "default",
    })

    assert provider.last_result_metadata["provider_model"] == "doubao-seedance-2-5-260628"
    assert provider.last_result_metadata["provider_resolution"] == "1080p"
    assert provider.last_result_metadata["provider_ratio"] == "9:16"
    assert provider.last_result_metadata["provider_fps"] == 24.0
    assert provider.last_result_metadata["provider_seed"] == 58944
    assert provider.last_result_metadata["provider_completion_tokens"] == 246840


def test_api_provider_retries_transient_gateway_failure(monkeypatch):
    class RetryResponse:
        status_code = 503
        request = httpx.Request("POST", "https://gateway.example/video")

        def raise_for_status(self):
            raise httpx.HTTPStatusError("temporary gateway failure", request=self.request, response=self)

    class SuccessResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        calls = 0

        def post(self, _url, **_kwargs):
            self.calls += 1
            return RetryResponse() if self.calls == 1 else SuccessResponse()

    monkeypatch.setenv("HTTP_VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("HTTP_VIDEO_RETRY_BACKOFF_SECONDS", "0")
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    client = FakeClient()

    response = provider._request_with_retry(client, "post", provider.endpoint, json={}, headers={})

    assert isinstance(response, SuccessResponse)
    assert client.calls == 2


def test_api_provider_honors_retry_after_header(monkeypatch):
    class RetryResponse:
        status_code = 429
        headers = {"Retry-After": "7"}
        request = httpx.Request("POST", "https://gateway.example/video")

        def raise_for_status(self):
            raise httpx.HTTPStatusError("rate limited", request=self.request, response=self)

    class SuccessResponse:
        headers = {}

        def raise_for_status(self):
            return None

    class FakeClient:
        calls = 0

        def post(self, _url, **_kwargs):
            self.calls += 1
            return RetryResponse() if self.calls == 1 else SuccessResponse()

    sleeps = []
    monkeypatch.setenv("HTTP_VIDEO_MAX_RETRIES", "1")
    monkeypatch.setenv("HTTP_VIDEO_RETRY_BACKOFF_SECONDS", "1")
    monkeypatch.setattr("src.services.generation_provider.time.sleep", sleeps.append)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")

    response = provider._request_with_retry(FakeClient(), "post", provider.endpoint, json={}, headers={})

    assert isinstance(response, SuccessResponse)
    assert sleeps == [7.0]


def test_api_provider_does_not_resubmit_ambiguous_generation_post(monkeypatch):
    class FakeClient:
        calls = 0

        def post(self, _url, **_kwargs):
            self.calls += 1
            raise httpx.ConnectError("connection lost after acceptance")

    monkeypatch.setenv("HTTP_VIDEO_MAX_RETRIES", "3")
    monkeypatch.setenv("HTTP_VIDEO_RETRY_BACKOFF_SECONDS", "0")
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    client = FakeClient()

    with pytest.raises(GenerationProviderError, match="transport failed"):
        provider._request_with_retry(
            client,
            "post",
            provider.endpoint,
            json={},
            headers={},
            retry_transport_errors=False,
        )

    assert client.calls == 1


def test_api_provider_adds_stable_idempotency_key_to_new_generation_request(tmp_path, monkeypatch):
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    request = VideoGenerationRequest(prompt="same request", output_path=str(tmp_path / "clip.mp4"))

    headers = provider._headers()
    header_name, key = provider._idempotency_key(request)
    headers[header_name] = key

    assert header_name == "Idempotency-Key"
    assert len(headers[header_name]) == 64
    assert provider._idempotency_key(request)[1] == key


def test_api_provider_can_disable_idempotency_key(monkeypatch, tmp_path):
    monkeypatch.setenv("HTTP_VIDEO_IDEMPOTENCY_ENABLED", "false")
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    request = VideoGenerationRequest(prompt="no key", output_path=str(tmp_path / "clip.mp4"))

    assert provider._idempotency_key(request) is None


def test_api_provider_does_not_retry_ambiguous_generation_5xx(monkeypatch):
    class RetryResponse:
        status_code = 503
        headers = {}
        request = httpx.Request("POST", "https://gateway.example/video")

        def raise_for_status(self):
            raise httpx.HTTPStatusError("gateway unavailable", request=self.request, response=self)

    class FakeClient:
        calls = 0

        def post(self, _url, **_kwargs):
            self.calls += 1
            return RetryResponse()

    monkeypatch.setenv("HTTP_VIDEO_MAX_RETRIES", "3")
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    client = FakeClient()

    with pytest.raises(GenerationProviderError, match="HTTP 503"):
        provider._request_with_retry(
            client,
            "post",
            provider.endpoint,
            json={},
            headers={},
            retry_status_errors=False,
        )

    assert client.calls == 1


def test_api_provider_surfaces_rate_limit_detail_when_creation_is_rejected(monkeypatch):
    class RateLimitResponse:
        status_code = 429
        headers = {"Retry-After": "12"}
        request = httpx.Request("POST", "https://ark.example/tasks")

        def raise_for_status(self):
            raise httpx.HTTPStatusError("rate limited", request=self.request, response=self)

        def json(self):
            return {"error": {"code": "QuotaExceeded", "message": "concurrency limit reached"}}

    class FakeClient:
        def post(self, _url, **_kwargs):
            return RateLimitResponse()

    monkeypatch.setenv("SEEDANCE_MAX_RETRIES", "0")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="QuotaExceeded: concurrency limit reached.*Retry-After: 12"):
        provider._request_with_retry(
            FakeClient(),
            "post",
            provider.endpoint,
            json={},
            headers={},
            retry_status_errors=False,
        )


def test_api_provider_rejects_json_download_response(tmp_path):
    class JsonResponse:
        headers = {"content-type": "application/json"}
        content = b'{"error":"not ready"}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"error": "not ready"}

    class Client:
        def get(self, _url, **_kwargs):
            return JsonResponse()

    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.max_retries = 0

    with pytest.raises(GenerationProviderError, match="non-video download response"):
        provider._download_video_with_retry(Client(), "https://gateway.example/out", str(tmp_path / "out.mp4"), {})


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/out.mp4",
        "data:video/mp4;base64,AAAA",
        "https://user:secret@media.example/out.mp4",
        "https://media.example/out.mp4#download",
    ],
)
def test_api_provider_rejects_unsafe_video_download_urls(tmp_path, url):
    class Client:
        def get(self, *_args, **_kwargs):
            raise AssertionError("unsafe URL must be rejected before the client request")

    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.max_retries = 0

    with pytest.raises(GenerationProviderError, match="invalid video download URL|unsupported fragment"):
        provider._download_video_with_retry(Client(), url, str(tmp_path / "out.mp4"), {})


def test_http_video_provider_builds_multimodal_reference_contract(tmp_path):
    image = tmp_path / "actor.png"
    video = tmp_path / "motion.mp4"
    audio = tmp_path / "voice.wav"
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")
    audio.write_bytes(b"wav")

    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    payload = provider._video_payload(
        VideoGenerationRequest(
            prompt="@Image1 performs the motion from @Video1 to the beat of @Audio1",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(image)],
            reference_videos=[str(video)],
            reference_audios=[str(audio)],
            generate_audio=True,
            multi_shot=True,
            shot_plan={"shots": [{"id": 1, "role": "close_up"}]},
        )
    )

    assert [item["id"] for item in payload["references"]] == ["Image1", "Video1", "Audio1"]
    assert payload["references"][0]["source"].startswith("data:image/png;base64,")
    assert payload["references"][1]["source"].startswith("data:video/mp4;base64,")
    assert payload["references"][2]["source"].startswith("data:audio/wav;base64,")
    assert payload["generate_audio"] is True
    assert payload["multi_shot"] is True
    assert payload["shot_plan"]["shots"][0]["role"] == "close_up"


def test_seedance_provider_emits_reference_to_video_schema(tmp_path, monkeypatch):
    image = tmp_path / "actor.png"
    video = tmp_path / "motion.mp4"
    audio = tmp_path / "beat.wav"
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")
    audio.write_bytes(b"wav")
    monkeypatch.setenv("SEEDANCE_MODEL", "bytedance/seedance-2.0/reference-to-video")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "1080p")

    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")
    payload = provider._video_payload(
        VideoGenerationRequest(
            prompt="A cinematic reaction shot",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(image)],
            reference_videos=[str(video)],
            reference_audios=[str(audio)],
            generate_audio=True,
            multi_shot=True,
            aspect_ratio="9:16",
            shot_plan={
                "sequence_context": {
                    "continuity_contract": ["match identity"],
                    "previous": {
                        "scene_number": 4,
                        "character_name": "Alice",
                        "visual_summary": "Alice reaches for the locked door",
                        "dialogue": "Wait.",
                    },
                    "current": {
                        "scene_number": 5,
                        "character_name": "Alice",
                        "visual_summary": "Alice turns toward the hallway",
                    },
                }
            },
        )
    )

    assert payload["resolution"] == "1080p"
    assert payload["image_urls"][0].startswith("data:image/png;base64,")
    assert payload["video_urls"][0].startswith("data:video/mp4;base64,")
    assert payload["audio_urls"][0].startswith("data:audio/wav;base64,")
    assert payload["generate_audio"] is True
    assert payload["duration"] == 5
    assert payload["bitrate_mode"] == "high"
    assert payload["codec"] == "H264"
    assert "model" not in payload
    assert "multi_shot" not in payload
    assert "@Image1 is the current scene keyframe" in payload["prompt"]
    assert "@Video1 onward are motion and pacing references" in payload["prompt"]
    assert "@Audio1 onward are dialogue or sound references" in payload["prompt"]
    assert "match identity" in payload["prompt"]
    assert "previous shot: scene 4" in payload["prompt"]
    assert "Alice reaches for the locked door" in payload["prompt"]
    assert "current shot: scene 5" in payload["prompt"]


def test_seedance_provider_adds_production_contract_for_direct_requests(tmp_path):
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")
    payload = provider._video_payload(
        VideoGenerationRequest(
            prompt="A woman looks up from a contract",
            output_path=str(tmp_path / "out.mp4"),
        )
    )

    assert "Production motion contract" in payload["prompt"]
    assert "vertical 9:16 mobile frame" in payload["prompt"]
    assert "no frozen still-image feeling" in payload["prompt"]


def test_seedance_provider_keeps_production_contract_with_shot_plan():
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")
    payload = provider._video_payload(VideoGenerationRequest(
        prompt="the lead turns toward the door",
        output_path="scene.mp4",
        shot_plan={"director_prompt": "medium close-up, slow push-in", "shots": [{"visual": "door"}]},
    ))

    assert "Production motion contract" in payload["prompt"]
    assert "preserve identity" in payload["prompt"]
    assert "medium close-up, slow push-in" in payload["prompt"]


def test_seedance_provider_rejects_reference_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_MAX_REFERENCE_IMAGES", "1")
    image_a = tmp_path / "actor_a.png"
    image_b = tmp_path / "actor_b.png"
    image_a.write_bytes(b"a")
    image_b.write_bytes(b"b")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")

    with pytest.raises(GenerationProviderError, match="images: 2 > 1"):
        provider._video_payload(
            VideoGenerationRequest(
                prompt="two characters",
                output_path=str(tmp_path / "out.mp4"),
                reference_images=[str(image_a), str(image_b)],
            )
        )


def test_seedance_25_rejects_total_reference_limit(monkeypatch):
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_MAX_REFERENCE_AUDIOS", "11")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")
    request = VideoGenerationRequest(
        prompt="many references",
        output_path="out.mp4",
        reference_images=[f"image-{index}.png" for index in range(30)],
        reference_videos=[f"video-{index}.mp4" for index in range(10)],
        reference_audios=[f"audio-{index}.wav" for index in range(11)],
    )

    with pytest.raises(GenerationProviderError, match="total references > 50"):
        provider._validate_reference_limits(request, native_ark=True)


def test_seedance_20_accepts_audio_reference_and_enforces_total_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MAX_REFERENCE_VIDEOS", "10")
    provider = SeedanceApiProvider(
        endpoint="https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        api_key="secret",
    )
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"RIFF" + b"audio")
    audio_request = VideoGenerationRequest(
        prompt="use the reference voice",
        output_path="out.mp4",
        reference_images=[f"https://cdn.example/image-{index}.png" for index in range(9)],
        reference_audios=[str(audio_path)],
    )

    provider._validate_reference_limits(audio_request, native_ark=True)
    payload = provider._video_payload(audio_request)
    assert payload["content"][-1]["type"] == "audio_url"
    assert payload["content"][-1]["role"] == "reference_audio"

    over_limit_request = VideoGenerationRequest(
        prompt="many references",
        output_path="out.mp4",
        reference_images=[f"image-{index}.png" for index in range(9)],
        reference_videos=[f"video-{index}.mp4" for index in range(7)],
    )
    with pytest.raises(GenerationProviderError, match="total references > 15"):
        provider._validate_reference_limits(over_limit_request, native_ark=True)


def test_seedance_20_rejects_audio_only_reference_request(monkeypatch, tmp_path):
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"RIFF" + b"audio")
    provider = SeedanceApiProvider(
        endpoint="https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        api_key="secret",
    )

    with pytest.raises(GenerationProviderError, match="require at least one image or video"):
        provider._video_payload(VideoGenerationRequest(
            prompt="use this voice",
            output_path="out.mp4",
            reference_audios=[str(audio_path)],
        ))

def test_seedance_reference_count_matches_deduplicated_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_MAX_REFERENCE_IMAGES", "1")
    image = str(tmp_path / "same.png")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")

    provider._validate_reference_limits(
        VideoGenerationRequest(
            prompt="reuse one identity anchor",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[image, image],
            continuity_reference_image=image,
        ),
        native_ark=True,
    )


def test_seedance_prompt_bindings_match_deduplicated_reference_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "legacy")
    image = tmp_path / "same.png"
    image.write_bytes(b"png")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="keep the identity stable",
        output_path=str(tmp_path / "out.mp4"),
        reference_images=[str(image), str(image)],
    ))

    assert len(payload["image_urls"]) == 1
    assert "@Image1 is the current scene keyframe" in payload["prompt"]
    assert "@Image2" not in payload["prompt"]


def test_seedance_provider_can_emit_multi_shot_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "multi_shot")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")

    payload = provider._video_payload(
        VideoGenerationRequest(
            prompt="one continuous dramatic sequence",
            output_path=str(tmp_path / "out.mp4"),
            multi_shot=True,
            shot_plan={"shots": [{"scene_number": 1}, {"scene_number": 2}]},
        )
    )

    assert payload["multi_shot"] is True
    assert payload["shot_plan"]["shots"] == [{"scene_number": 1}, {"scene_number": 2}]


def test_seedance_provider_emits_native_ark_v3_content_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    image = tmp_path / "actor.png"
    video = tmp_path / "motion.mp4"
    audio = tmp_path / "voice.wav"
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")
    audio.write_bytes(b"wav")

    provider = SeedanceApiProvider(endpoint="https://ark.example/api/v3/contents/generations/tasks", api_key="secret")
    payload = provider._video_payload(
        VideoGenerationRequest(
            prompt="The character follows the reference motion",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(image)],
            reference_videos=[str(video)],
            reference_audios=[str(audio)],
            duration_seconds=30,
            aspect_ratio="9:16",
            generate_audio=True,
        )
    )

    assert payload["model"] == "doubao-seedance-2-5-260628"
    assert payload["omni_reference_task_type"] == "reference"
    assert payload["duration"] == 30
    assert payload["ratio"] == "9:16"
    assert [item["type"] for item in payload["content"]] == ["text", "image_url", "video_url", "audio_url"]
    assert [item["role"] for item in payload["content"][1:]] == [
        "reference_image", "reference_video", "reference_audio"
    ]
    assert payload["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert payload["content"][2]["video_url"]["url"] == "https://cdn.example/motion.mp4"
    assert "@image1 is the current scene keyframe" in payload["content"][0]["text"]
    assert "@video1 onward are motion and pacing references" in payload["content"][0]["text"]
    assert "@audio1 onward are dialogue or sound references" in payload["content"][0]["text"]


def test_seedance_provider_auto_detects_official_ark_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("SEEDANCE_API_FORMAT", raising=False)
    monkeypatch.delenv("SEEDANCE_MODEL", raising=False)
    provider = SeedanceApiProvider(
        endpoint="https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        api_key="secret",
    )

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A cinematic reaction",
        output_path=str(tmp_path / "out.mp4"),
        duration_seconds=5,
    ))

    assert payload["model"] == "doubao-seedance-2-5-260628"
    assert [item["type"] for item in payload["content"]] == ["text"]
    assert provider.status_endpoint.endswith("/{job_id}")


def test_seedance_provider_auto_detects_volcengine_ark_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("SEEDANCE_API_FORMAT", raising=False)
    provider = SeedanceApiProvider(
        endpoint="https://ark.cn-beijing.volcengine.com/api/v3/contents/generations/tasks",
        api_key="secret",
    )

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A cinematic reaction",
        output_path=str(tmp_path / "out.mp4"),
        duration_seconds=5,
    ))

    assert payload["content"][0]["type"] == "text"
    assert payload["model"] == "doubao-seedance-2-5-260628"


def test_seedance_provider_treats_empty_api_format_as_auto(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "")
    monkeypatch.delenv("SEEDANCE_MODEL", raising=False)
    provider = SeedanceApiProvider(
        endpoint="https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        api_key="secret",
    )

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A cinematic reaction",
        output_path=str(tmp_path / "out.mp4"),
        duration_seconds=5,
    ))

    assert payload["content"][0]["type"] == "text"
    assert provider.status_endpoint.endswith("/{job_id}")


def test_seedance_provider_includes_optional_callback_url(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_CALLBACK_URL", "https://app.example/hooks/seedance")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A continuous cinematic shot",
        output_path=str(tmp_path / "out.mp4"),
        duration_seconds=5,
    ))

    assert payload["callback_url"] == "https://app.example/hooks/seedance"


def test_seedance_legacy_request_controls_override_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "legacy")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "720p")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mov")
    monkeypatch.setenv("SEEDANCE_RETURN_LAST_FRAME", "true")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a compatible gateway shot",
        output_path=str(tmp_path / "out.mp4"),
        resolution="1080p",
        output_format="mp4",
        return_last_frame=False,
    ))

    assert payload["resolution"] == "1080p"
    assert payload["output_format"] == "mp4"
    assert payload["return_last_frame"] is False


def test_seedance_provider_native_ark_uses_first_last_frame_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    continuity = tmp_path / "previous.last_frame.png"
    first.write_bytes(b"first")
    last.write_bytes(b"last")
    continuity.write_bytes(b"previous")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A person turns toward camera",
        output_path=str(tmp_path / "out.mp4"),
        reference_image=str(first),
        end_image=str(last),
        continuity_reference_image=str(continuity),
        request_mode="first_last_frame",
        duration_seconds=6,
        draft=True,
    ))

    assert payload["ratio"] == "adaptive"
    assert payload["resolution"] == "480p"
    assert payload["draft"] is True
    assert "omni_reference_task_type" not in payload
    assert [item["role"] for item in payload["content"][1:]] == ["first_frame", "last_frame"]


def test_seedance_native_ark_25_requires_draft_for_first_last_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"first")
    last.write_bytes(b"last")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="requires Draft=true"):
        provider._video_payload(VideoGenerationRequest(
            prompt="A person turns toward camera",
            output_path=str(tmp_path / "out.mp4"),
            reference_image=str(first),
            end_image=str(last),
            duration_seconds=6,
        ))


def test_seedance_native_ark_25_explicit_first_frame_uses_draft_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    first = tmp_path / "first.png"
    first.write_bytes(b"first")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A person turns toward camera",
        output_path=str(tmp_path / "out.mp4"),
        reference_image=str(first),
        request_mode="first_frame",
        duration_seconds=6,
        draft=True,
    ))

    assert payload["resolution"] == "480p"
    assert payload["draft"] is True
    assert "omni_reference_task_type" not in payload
    assert [item["role"] for item in payload["content"][1:]] == ["first_frame"]


def test_seedance_native_ark_20_rejects_explicit_first_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    first = tmp_path / "first.png"
    first.write_bytes(b"first")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not support explicit first_frame"):
        provider._video_payload(VideoGenerationRequest(
            prompt="A person turns toward camera",
            output_path=str(tmp_path / "out.mp4"),
            reference_image=str(first),
            request_mode="first_frame",
            duration_seconds=6,
        ))


def test_seedance_native_ark_rejects_extra_references_in_explicit_first_frame_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    first = tmp_path / "first.png"
    extra = tmp_path / "extra.png"
    first.write_bytes(b"first")
    extra.write_bytes(b"extra")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="exactly one first-frame image"):
        provider._video_payload(VideoGenerationRequest(
            prompt="A person turns toward camera",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(first), str(extra)],
            request_mode="first_frame",
            duration_seconds=6,
            draft=True,
        ))


def test_seedance_native_ark_rejects_mixed_media_in_explicit_first_last_frame_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"first")
    last.write_bytes(b"last")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="no reference video"):
        provider._video_payload(VideoGenerationRequest(
            prompt="A person turns toward camera",
            output_path=str(tmp_path / "out.mp4"),
            reference_image=str(first),
            end_image=str(last),
            reference_videos=["https://cdn.example/source.mp4"],
            request_mode="first_last_frame",
            duration_seconds=6,
            draft=True,
        ))


@pytest.mark.parametrize(
    "template",
    ["http://cdn.example/{filename}", "https://localhost/{filename}", "https://10.0.0.8/{filename}"],
)
def test_seedance_native_ark_rejects_non_public_media_template(tmp_path, monkeypatch, template):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", template)
    video = tmp_path / "reference.mp4"
    video.write_bytes(b"video")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="public HTTPS URL"):
        provider._video_payload(VideoGenerationRequest(
            prompt="edit the reference video",
            output_path=str(tmp_path / "out.mp4"),
            reference_videos=[str(video)],
            request_mode="edit",
        ))


@pytest.mark.parametrize(
    "reference_url",
    ["http://cdn.example/reference.mp4", "https://localhost/reference.mp4", "https://192.168.1.5/reference.mp4"],
)
def test_seedance_native_ark_rejects_non_public_direct_media_url(reference_url, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="public HTTPS URL"):
        provider._video_payload(VideoGenerationRequest(
            prompt="edit the reference video",
            output_path="out.mp4",
            reference_videos=[reference_url],
            request_mode="edit",
        ))


def test_seedance_native_ark_first_last_honors_explicit_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"first")
    last.write_bytes(b"last")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="A person turns toward camera",
        output_path=str(tmp_path / "out.mp4"),
        reference_image=str(first),
        end_image=str(last),
        resolution="720p",
        duration_seconds=6,
    ))

    assert payload["ratio"] == "adaptive"
    assert payload["resolution"] == "720p"


def test_seedance_native_ark_requests_last_frame(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_RETURN_LAST_FRAME", "true")
    monkeypatch.setenv("SEEDANCE_INCLUDE_EXPERIMENTAL_FIELDS", "true")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")
    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a clean turn",
        output_path="out.mp4",
    ))

    assert payload["return_last_frame"] is True


def test_seedance_native_ark_request_output_format_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mp4")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a premium short-drama shot",
        output_path=str(tmp_path / "out.mov"),
        output_format="mov",
    ))

    assert payload["output_format"] == "mov"


def test_seedance_native_ark_request_model_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a premium short-drama shot",
        output_path=str(tmp_path / "out.mp4"),
        model="doubao-seedance-2-5-260628",
        resolution="1080p",
    ))

    assert payload["model"] == "doubao-seedance-2-5-260628"
    assert payload["duration"] == 5
    assert provider.last_result_metadata["requested_model"] == "doubao-seedance-2-5-260628"


def test_seedance_native_ark_persists_requested_output_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a premium short-drama shot",
        output_path=str(tmp_path / "out.mp4"),
        model="doubao-seedance-2-5-260628",
        output_format="mov",
        watermark=False,
        return_last_frame=True,
        draft=True,
    ))

    assert payload["output_format"] == "mov"
    assert payload["watermark"] is False
    assert payload["return_last_frame"] is True
    assert provider.last_result_metadata["requested_output_format"] == "mov"
    assert provider.last_result_metadata["requested_watermark"] is False
    assert provider.last_result_metadata["requested_return_last_frame"] is True


def test_seedance_native_ark_explicit_false_controls_override_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_RETURN_LAST_FRAME", "true")
    monkeypatch.setenv("SEEDANCE_CAMERA_FIXED", "true")
    monkeypatch.setenv("SEEDANCE_WATERMARK", "true")
    monkeypatch.setenv("SEEDANCE_DRAFT", "true")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a premium short-drama shot",
        output_path=str(tmp_path / "out.mp4"),
        return_last_frame=False,
        camera_fixed=False,
        watermark=False,
        draft=False,
    ))

    assert payload["return_last_frame"] is False
    assert "camera_fixed" not in payload
    assert payload["watermark"] is False
    assert payload["draft"] is False


def test_seedance_native_ark_draft_mode_uses_480p_and_draft_task(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    draft = provider._video_payload(VideoGenerationRequest(
        prompt="preview the action",
        output_path=str(tmp_path / "draft.mp4"),
        draft=True,
        duration_seconds=8,
    ))
    final = provider._video_payload(VideoGenerationRequest(
        prompt="ignored when promoting draft",
        output_path=str(tmp_path / "final.mp4"),
        draft_task_id="draft-123",
    ))

    assert draft["draft"] is True
    assert draft["resolution"] == "480p"
    assert final["content"] == [{"type": "draft_task", "draft_task": {"id": "draft-123"}}]
    assert final["resolution"] == "1080p"
    assert "draft" not in final


def test_seedance_native_ark_draft_promotion_only_sends_reusable_output_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "720p")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="must be reused from draft",
        output_path=str(tmp_path / "final.mp4"),
        draft_task_id="draft-456",
        duration_seconds=30,
        aspect_ratio="9:16",
        generate_audio=True,
        seed=7,
    ))

    assert payload["resolution"] == "1080p"
    assert set(payload) == {
        "model", "content", "resolution", "output_format", "watermark",
    }


def test_seedance_native_ark_draft_promotion_output_format_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mp4")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="reused draft",
        output_path=str(tmp_path / "final.mov"),
        draft_task_id="draft-999",
        output_format="mov",
    ))

    assert payload["output_format"] == "mov"


@pytest.mark.parametrize("request_kwargs", [
    {"draft": True},
    {"draft_task_id": "draft-789"},
])
def test_seedance_native_ark_rejects_draft_for_non_25_model(tmp_path, monkeypatch, request_kwargs):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not support Draft"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a cinematic shot",
            output_path=str(tmp_path / "out.mp4"),
            **request_kwargs,
        ))


def test_seedance_legacy_request_model_and_explicit_false_controls_override_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "legacy")
    monkeypatch.setenv("SEEDANCE_MODEL", "bytedance/seedance-2.0/reference-to-video")
    monkeypatch.setenv("SEEDANCE_CAMERA_FIXED", "true")
    monkeypatch.setenv("SEEDANCE_WATERMARK", "true")
    monkeypatch.setenv("SEEDANCE_DRAFT", "true")
    provider = SeedanceApiProvider(endpoint="https://gateway.example/seedance", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a close-up reaction",
        output_path=str(tmp_path / "out.mp4"),
        model="doubao-seedance-2-5-260628",
        camera_fixed=False,
        watermark=False,
        draft=False,
    ))

    assert payload["model"] == "doubao-seedance-2-5-260628"
    assert payload["camera_fixed"] is False
    assert payload["watermark"] is False
    assert payload["draft"] is False


def test_seedance_native_ark_25_rejects_4k_before_submission(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not support resolution 4k"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a cinematic shot",
            output_path=str(tmp_path / "out.mp4"),
            resolution="4k",
        ))


def test_seedance_native_ark_binds_previous_last_frame_as_continuity_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    previous_last = tmp_path / "previous-last.png"
    current = tmp_path / "current.png"
    previous_last.write_bytes(b"last")
    current.write_bytes(b"current")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="continue the movement",
        output_path=str(tmp_path / "out.mp4"),
        reference_images=[str(current)],
        continuity_reference_image=str(previous_last),
    ))

    assert [item["role"] for item in payload["content"][1:]] == ["reference_image", "reference_image"]
    assert "last frame of the previous shot" in payload["content"][0]["text"]


def test_seedance_provider_native_ark_preserves_end_composition_with_identity_refs(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    current = tmp_path / "current.png"
    character = tmp_path / "character.png"
    end = tmp_path / "end.png"
    current.write_bytes(b"current")
    character.write_bytes(b"character")
    end.write_bytes(b"end")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="the character reaches the doorway",
        output_path=str(tmp_path / "out.mp4"),
        reference_images=[str(current), str(character)],
        end_image=str(end),
    ))

    assert [item["role"] for item in payload["content"][1:]] == [
        "reference_image", "reference_image", "reference_image",
    ]
    assert "@image3 is the desired ending composition reference" in payload["content"][0]["text"]


def test_seedance_provider_native_ark_rejects_local_video_without_public_source(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    video = tmp_path / "motion.mp4"
    video.write_bytes(b"mp4")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="SEEDANCE_MEDIA_URL_TEMPLATE"):
        provider._video_payload(VideoGenerationRequest(
            prompt="continue the motion",
            output_path=str(tmp_path / "out.mp4"),
            reference_videos=[str(video)],
        ))


def test_seedance_native_ark_rejects_static_media_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/fixed.mp4")
    video = tmp_path / "motion.mp4"
    video.write_bytes(b"mp4")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match=r"must include \{filename\} or \{path\}"):
        provider._video_payload(VideoGenerationRequest(
            prompt="continue the motion",
            output_path=str(tmp_path / "out.mp4"),
            reference_videos=[str(video)],
        ))


def test_seedance_native_ark_rejects_unsupported_local_video_format(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    video = tmp_path / "motion.webm"
    video.write_bytes(b"video")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="MP4 or MOV"):
        provider._video_payload(VideoGenerationRequest(
            prompt="continue the motion",
            output_path=str(tmp_path / "out.mp4"),
            reference_videos=[str(video)],
        ))


def test_seedance_provider_native_ark_rejects_missing_local_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not exist"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a cinematic shot",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(tmp_path / "missing.png")],
        ))


def test_seedance_native_ark_routes_oversized_images_to_public_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    image = tmp_path / "large.png"
    image.write_bytes(b"0")
    with image.open("ab") as handle:
        handle.truncate(31 * 1024 * 1024)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="large reference",
        output_path=str(tmp_path / "out.mp4"),
        reference_images=[str(image)],
    ))

    assert payload["content"][1]["image_url"]["url"] == "https://cdn.example/large.png"


def test_seedance_native_ark_rejects_oversized_image_without_public_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.delenv("SEEDANCE_MEDIA_URL_TEMPLATE", raising=False)
    image = tmp_path / "large.png"
    image.write_bytes(b"0")
    with image.open("ab") as handle:
        handle.truncate(31 * 1024 * 1024)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="30MB"):
        provider._video_payload(VideoGenerationRequest(
            prompt="large reference",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(image)],
        ))


def test_seedance_native_ark_rejects_invalid_image_dimensions(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    image = tmp_path / "wide.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="7000x200\n"),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="dimensions"):
        provider._video_payload(VideoGenerationRequest(
            prompt="invalid image",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(image)],
        ))


def test_seedance_10_native_ark_rejects_heic_reference_image(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    image = tmp_path / "portrait.heic"
    image.write_bytes(b"heic")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="reference image format is unsupported"):
        provider._video_payload(VideoGenerationRequest(
            prompt="use the portrait",
            output_path=str(tmp_path / "out.mp4"),
            reference_image=str(image),
        ))


def test_seedance_25_native_ark_accepts_heic_reference_image_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    image = tmp_path / "portrait.heic"
    image.write_bytes(b"heic")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="use the portrait",
        output_path=str(tmp_path / "out.mp4"),
        reference_image=str(image),
    ))

    assert payload["content"][1]["image_url"]["url"].startswith("data:image/heic;base64,")


def test_seedance_provider_native_ark_embeds_small_local_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"RIFF" + b"audio")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a character speaks the supplied dialogue",
        output_path=str(tmp_path / "out.mp4"),
        reference_audios=[str(audio)],
    ))

    assert payload["content"][1]["role"] == "reference_audio"
    assert payload["content"][1]["audio_url"]["url"].startswith("data:audio/wav;base64,")


def test_seedance_native_ark_rejects_unsupported_local_audio_format(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    audio = tmp_path / "dialogue.m4a"
    audio.write_bytes(b"audio")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="WAV or MP3"):
        provider._video_payload(VideoGenerationRequest(
            prompt="use the supplied dialogue",
            output_path=str(tmp_path / "out.mp4"),
            reference_audios=[str(audio)],
        ))


def test_seedance_provider_native_ark_rejects_oversized_local_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    audio = tmp_path / "oversized.wav"
    audio.write_bytes(b"0" * (15 * 1024 * 1024 + 1))
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="15MB"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a character speaks",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=["https://cdn.example/character.png"],
            reference_audios=[str(audio)],
        ))


def test_seedance_native_ark_routes_oversized_audio_to_public_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    audio = tmp_path / "large-dialogue.wav"
    audio.write_bytes(b"0" * (15 * 1024 * 1024 + 1))
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="use the supplied voice",
        output_path=str(tmp_path / "out.mp4"),
        reference_audios=[str(audio)],
    ))

    assert payload["content"][1]["audio_url"]["url"] == "https://cdn.example/large-dialogue.wav"


def test_seedance_native_ark_enforces_combined_image_audio_body_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    audio = tmp_path / "voice.wav"
    for path, size in ((image_a, 20), (image_b, 20), (audio, 6)):
        path.write_bytes(b"0")
        with path.open("ab") as handle:
            handle.truncate(size * 1024 * 1024)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="image/audio references exceed"):
        provider._video_payload(VideoGenerationRequest(
            prompt="combine the supplied references",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=[str(image_a), str(image_b)],
            reference_audios=[str(audio)],
        ))


def test_seedance_native_ark_routes_combined_image_audio_budget_to_public_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.png"
    audio = tmp_path / "voice.wav"
    for path, size in ((image_a, 20), (image_b, 20), (audio, 6)):
        path.write_bytes(b"0")
        with path.open("ab") as handle:
            handle.truncate(size * 1024 * 1024)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="combine the supplied references",
        output_path=str(tmp_path / "out.mp4"),
        reference_images=[str(image_a), str(image_b)],
        reference_audios=[str(audio)],
    ))

    media_items = [item for item in payload["content"] if item["type"] != "text"]
    assert [item["image_url"]["url"] for item in media_items[:2]] == [
        "https://cdn.example/a.png", "https://cdn.example/b.png",
    ]
    assert media_items[2]["audio_url"]["url"] == "https://cdn.example/voice.wav"


def test_seedance_provider_native_ark_routes_oversized_audio_through_public_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    audio = tmp_path / "oversized.wav"
    audio.write_bytes(b"0" * (15 * 1024 * 1024 + 1))
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a character speaks",
        output_path=str(tmp_path / "out.mp4"),
        reference_audios=[str(audio)],
    ))

    assert payload["content"][1]["audio_url"]["url"] == "https://cdn.example/oversized.wav"


def test_seedance_provider_native_ark_rejects_audio_over_30_seconds(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def fake_run(command, **_kwargs):
        duration = "18.0" if str(first) in command else "14.0"
        return SimpleNamespace(stdout=duration)

    monkeypatch.setattr(generation_provider.subprocess, "run", fake_run)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="total 30 seconds"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a character speaks",
            output_path=str(tmp_path / "out.mp4"),
            reference_audios=[str(first), str(second)],
        ))


def test_seedance_native_ark_rejects_local_audio_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"RIFF" + b"audio")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: None)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="require ffprobe"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a character speaks",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=["https://cdn.example/character.png"],
            reference_audios=[str(audio)],
        ))


def test_seedance_native_ark_rejects_unmeasurable_local_video(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    video = tmp_path / "source.mp4"
    video.write_bytes(b"not a video")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.SubprocessError("invalid media")),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="Could not inspect Native Ark video reference"):
        provider._video_payload(VideoGenerationRequest(
            prompt="continue the motion",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=["https://cdn.example/character.png"],
            reference_videos=[str(video)],
        ))


def test_seedance_20_native_ark_rejects_audio_over_15_seconds(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"RIFF" + b"audio")
    monkeypatch.setattr("src.services.generation_provider.shutil.which", lambda name: "/usr/bin/ffprobe")

    def fake_run(command, **_kwargs):
        return SimpleNamespace(stdout="16.0")

    monkeypatch.setattr("src.services.generation_provider.subprocess.run", fake_run)
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="2-15 seconds"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a character speaks",
            output_path=str(tmp_path / "out.mp4"),
            reference_images=["https://cdn.example/character.png"],
            reference_audios=[str(audio)],
        ))


def test_seedance_provider_native_ark_uses_minus_one_for_auto_duration(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="let the model choose a natural duration",
        output_path="scene.mp4",
        duration_seconds=0,
    ))

    assert payload["duration"] == -1


def test_seedance_native_ark_empty_model_env_uses_production_default(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a clean vertical reaction shot",
        output_path="scene.mp4",
    ))

    assert payload["model"] == "doubao-seedance-2-5-260628"
    assert payload["resolution"] == "1080p"


def test_seedance_native_ark_exposes_production_controls(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    monkeypatch.setenv("SEEDANCE_CAMERA_FIXED", "true")
    monkeypatch.setenv("SEEDANCE_WATERMARK", "false")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mp4")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a locked-off product shot",
        output_path="scene.mp4",
        seed=42,
    ))

    assert payload["seed"] == 42
    assert payload["camera_fixed"] is True
    assert payload["watermark"] is False
    assert payload["output_format"] == "mp4"


def test_seedance_10_native_ark_maps_single_image_to_first_frame(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a woman turns toward the camera",
        output_path="scene.mp4",
        reference_image="https://cdn.example/first.png",
    ))

    assert [item["role"] for item in payload["content"] if item["type"] == "image_url"] == ["first_frame"]
    assert payload["ratio"] == "adaptive"
    assert "omni_reference_task_type" not in payload


def test_seedance_10_native_ark_rejects_video_reference(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="video and audio references require"):
        provider._video_payload(VideoGenerationRequest(
            prompt="use the source motion",
            output_path="scene.mp4",
            reference_videos=["https://cdn.example/source.mp4"],
        ))


def test_seedance_10_fast_native_ark_rejects_first_last_frame(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-fast-251015")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not support first/last-frame"):
        provider._video_payload(VideoGenerationRequest(
            prompt="start and end on the supplied frames",
            output_path="scene.mp4",
            reference_image="https://cdn.example/start.png",
            end_image="https://cdn.example/end.png",
        ))


def test_seedance_10_native_ark_rejects_end_frame_without_first_frame(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="requires a first-frame image"):
        provider._video_payload(VideoGenerationRequest(
            prompt="end on this frame",
            output_path="scene.mp4",
            end_image="https://cdn.example/end.png",
        ))


def test_seedance_native_ark_2x_omits_1x_only_controls(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_CAMERA_FIXED", "true")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="a vertical reaction shot",
        output_path="scene.mp4",
        seed=42,
        camera_fixed=True,
    ))

    assert "seed" not in payload
    assert "camera_fixed" not in payload


def test_seedance_native_ark_rejects_mov_for_non_25_model(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mov")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="supports MP4 output only"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a scene",
            output_path="scene.mov",
        ))


def test_seedance_20_native_ark_omits_25_only_task_type_field(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "reference")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="use the supplied reference image to create a cinematic shot",
        output_path="scene.mp4",
        reference_images=["https://cdn.example/character.png"],
    ))

    assert "omni_reference_task_type" not in payload


def test_seedance_20_fast_native_ark_rejects_1080p(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-fast-260128")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not support resolution 1080p"):
        provider._video_payload(VideoGenerationRequest(
            prompt="a cinematic close-up",
            output_path="scene.mp4",
            resolution="1080p",
        ))


def test_seedance_10_native_ark_uses_two_to_twelve_second_duration(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    long_payload = provider._video_payload(VideoGenerationRequest(
        prompt="a product reveal",
        output_path="long.mp4",
        duration_seconds=20,
    ))
    auto_payload = provider._video_payload(VideoGenerationRequest(
        prompt="a product reveal",
        output_path="auto.mp4",
        duration_seconds=0,
    ))

    assert long_payload["duration"] == 12
    assert auto_payload["duration"] == 5


def test_seedance_native_ark_rejects_edit_without_video(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "edit")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="edit mode requires"):
        provider._video_payload(VideoGenerationRequest(
            prompt="edit the background",
            output_path="scene.mp4",
        ))


def test_seedance_native_ark_rejects_unknown_request_mode(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="Unsupported native Seedance request mode"):
        provider._video_payload(VideoGenerationRequest(
            prompt="generate a shot",
            output_path="scene.mp4",
            request_mode="unknown_mode",
        ))


def test_seedance_25_native_ark_supports_auto_task_type(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="根据参考视频意图自动判断是参考、编辑还是延长",
        output_path="scene.mp4",
        request_mode="auto",
        reference_videos=["https://cdn.example/source.mp4"],
    ))

    assert payload["omni_reference_task_type"] == "auto"
    assert payload["ratio"] == "adaptive"
    assert payload["duration"] == -1


def test_seedance_20_native_ark_rejects_auto_task_type(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="does not support omni_reference_task_type=auto"):
        provider._video_payload(VideoGenerationRequest(
            prompt="自动判断任务类型",
            output_path="scene.mp4",
            request_mode="auto",
            reference_images=["https://cdn.example/source.png"],
        ))


def test_seedance_native_ark_extend_mode_uses_extend_task_type(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "extend")
    video = tmp_path / "previous.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="continue the shot",
        output_path="scene.mp4",
        extend_video=str(video),
    ))

    assert payload["omni_reference_task_type"] == "extend"
    assert payload["ratio"] == "adaptive"
    assert [item["role"] for item in payload["content"][1:]] == ["reference_video"]


def test_seedance_native_ark_binds_extend_video_after_other_references(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "extend")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    reference = tmp_path / "reference.mp4"
    source = tmp_path / "source.mp4"
    reference.write_bytes(b"reference")
    source.write_bytes(b"source")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="continue the final movement",
        output_path="scene.mp4",
        reference_videos=[str(reference)],
        extend_video=str(source),
    ))

    assert [item["role"] for item in payload["content"][1:]] == ["reference_video", "reference_video"]
    assert "@video2 is the source video to extend" in payload["content"][0]["text"]
    assert [item["provider_reference_tag"] for item in provider.last_result_metadata["ark_content_bindings"]] == [
        "@video1", "@video2",
    ]
    assert provider.last_result_metadata["ark_task_type"] == "extend"


def test_seedance_native_ark_extend_with_end_image_keeps_video_reference(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "extend")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="continue into the final composition",
        output_path="scene.mp4",
        reference_images=["https://cdn.example/start.png"],
        end_image="https://cdn.example/end.png",
        extend_video="https://cdn.example/source.mp4",
    ))

    assert payload["omni_reference_task_type"] == "extend"
    assert payload["ratio"] == "adaptive"
    assert [item.get("role") for item in payload["content"][1:]] == [
        "reference_image", "reference_image", "reference_video",
    ]
    assert "@image2 is the desired ending composition reference" in payload["content"][0]["text"]


def test_seedance_native_ark_validates_standalone_extend_video(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    monkeypatch.setattr(generation_provider.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    video = tmp_path / "extend.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        generation_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps({
            "streams": [{
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "10/1",
            }],
            "format": {"duration": "5.0"},
        })),
    )
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    with pytest.raises(GenerationProviderError, match="FPS must be 24-60"):
        provider._video_payload(VideoGenerationRequest(
            prompt="continue the shot",
            output_path=str(tmp_path / "out.mp4"),
            request_mode="extend",
            extend_video=str(video),
        ))


def test_seedance_native_ark_request_mode_override_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "reference")
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="replace the background while preserving the actor",
        output_path="scene.mp4",
        reference_videos=[str(video)],
        request_mode="edit",
    ))

    assert payload["omni_reference_task_type"] == "edit"
    assert payload["ratio"] == "adaptive"


def test_seedance_25_duration_bounds_distinguish_normal_and_edit_tasks():
    model = "doubao-seedance-2-5-260628"

    assert _seedance_duration_bounds(model, "reference") == (2, 30)
    assert _seedance_duration_bounds(model, "multi_shot") == (2, 30)
    assert _seedance_duration_bounds(model, "edit") == (4, 30)
    assert _seedance_duration_bounds(model, "extend") == (4, 30)


def test_seedance_20_duration_bounds_match_generation_contract():
    assert _seedance_duration_bounds("doubao-seedance-2-0-260128", "reference") == (4, 15)


@pytest.mark.parametrize("alias", ["seedance_2_5", "2.5"])
def test_seedance_native_ark_normalizes_legacy_25_mode_aliases(monkeypatch, alias):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="generate a multi-shot sequence",
        output_path="scene.mp4",
        request_mode=alias,
    ))

    assert payload["omni_reference_task_type"] == "reference"


def test_seedance_multi_shot_prompt_contains_integer_timeline():
    request = VideoGenerationRequest(
        prompt="a continuous short drama beat",
        output_path="scene.mp4",
        multi_shot=True,
        duration_seconds=30,
        shot_plan={"shots": [
            {"scene_number": 1, "visual": "door opens", "duration_seconds": 10},
            {"scene_number": 2, "visual": "Alice looks up", "duration_seconds": 10},
            {"scene_number": 3, "visual": "Alice steps back", "duration_seconds": 10},
        ]},
    )

    prompt = _seedance_prompt(request)

    assert "Shot 1 [0s-10s]" in prompt
    assert "Shot 2 [10s-20s]" in prompt
    assert "Shot 3 [20s-30s]" in prompt


def test_seedance_sequence_prompt_binds_shot_keyframes_before_identity_refs():
    prompt = _seedance_prompt(VideoGenerationRequest(
        prompt="continuous short drama sequence",
        output_path="sequence.mp4",
        multi_shot=True,
        duration_seconds=30,
        reference_images=["scene1.png", "scene2.png", "identity.png"],
        shot_plan={
            "sequence_level": True,
            "shots": [
                {"scene_number": 1, "visual": "door opens", "duration_seconds": 15},
                {"scene_number": 2, "visual": "Alice looks up", "duration_seconds": 15},
            ],
        },
    ))

    assert "@Image1 through @Image2 map in order to the shot keyframes" in prompt
    assert "@Image3 onward are frozen character identity" in prompt


def test_seedance_sequence_prompt_uses_explicit_sampled_reference_bindings():
    prompt = _seedance_prompt(VideoGenerationRequest(
        prompt="sampled multi-shot sequence",
        output_path="sequence.mp4",
        multi_shot=True,
        duration_seconds=30,
        reference_images=["scene1.png", "scene7.png", "scene12.png", "identity.png"],
        shot_plan={
            "sequence_level": True,
            "shots": [{"scene_number": number, "visual": "beat", "duration_seconds": 7.5} for number in range(1, 5)],
            "sequence_image_bindings": [
                {"image_index": 1, "role": "shot_keyframe", "scene_number": 1},
                {"image_index": 2, "role": "shot_keyframe", "scene_number": 7},
                {"image_index": 3, "role": "shot_keyframe", "scene_number": 12},
                {"image_index": 4, "role": "character_identity", "character_names": ["Alice"]},
            ],
        },
    ))

    assert "@Image1 is the keyframe for scene 1" in prompt
    assert "@Image2 is the keyframe for scene 7" in prompt
    assert "@Image3 is the keyframe for scene 12" in prompt
    assert "@Image4 is a locked identity reference for Alice" in prompt


def test_seedance_sequence_prompt_binds_sampled_audio_to_scenes():
    prompt = _seedance_prompt(VideoGenerationRequest(
        prompt="sampled dialogue sequence",
        output_path="sequence.mp4",
        multi_shot=True,
        duration_seconds=30,
        reference_audios=["scene1.wav", "scene12.wav"],
        shot_plan={
            "sequence_level": True,
            "shots": [{"scene_number": 1}, {"scene_number": 12}],
            "sequence_audio_bindings": [
                {"audio_index": 1, "scene_number": 1},
                {"audio_index": 2, "scene_number": 12},
            ],
        },
    ))

    assert "@Audio1 is the dialogue or sound reference for scene 1" in prompt
    assert "@Audio2 is the dialogue or sound reference for scene 12" in prompt


def test_seedance_sequence_prompt_prefers_explicit_timestamp_timeline():
    prompt = _seedance_prompt(VideoGenerationRequest(
        prompt="continuous short drama sequence",
        output_path="sequence.mp4",
        multi_shot=True,
        duration_seconds=12,
        shot_plan={
            "shots": [
                {"scene_number": 1, "visual": "door opens", "duration_seconds": 4},
                {"scene_number": 2, "visual": "Alice looks up", "duration_seconds": 4},
                {"scene_number": 3, "visual": "Alice steps back", "duration_seconds": 4},
            ],
            "sequence_timeline": [
                {"scene_number": 1, "start_seconds": 0, "end_seconds": 4.25},
                {"scene_number": 2, "start_seconds": 4.25, "end_seconds": 8.5},
                {"scene_number": 3, "start_seconds": 8.5, "end_seconds": 12},
            ],
        },
    ))

    assert "Shot 2 [4.250s-8.500s]" in prompt
    assert "Shot 2 [4s-8s]" not in prompt


def test_seedance_prompt_binds_named_character_references_to_image_indexes():
    prompt = _seedance_prompt(VideoGenerationRequest(
        prompt="two actors confront each other in a cafe",
        output_path="scene.mp4",
        reference_images=["keyframe.png", "alice.png", "bob.png"],
        shot_plan={
            "character_reference_bindings": [
                {
                    "image_index": 2,
                    "character_name": "Alice",
                    "view": "front",
                    "expected_features": {"hair": "long dark hair", "distinctive_mark": "mole under left eye"},
                },
                {
                    "image_index": 3,
                    "character_name": "Bob",
                    "view": "three-quarter",
                },
            ],
        },
    ))

    assert "@Image2 is Alice's locked front character reference" in prompt
    assert "hair=long dark hair" in prompt
    assert "@Image3 is Bob's locked three-quarter character reference" in prompt
    assert "Never swap these references" in prompt


def test_seedance_prompt_includes_frozen_spatial_blocking_contract():
    prompt = _seedance_prompt(VideoGenerationRequest(
        prompt="Alice hands over a letter",
        output_path="scene.mp4",
        shot_plan={
            "spatial_plan": {
                "shot_scale": "medium two-shot",
                "camera_angle": "over shoulder",
                "camera_axis": "screen left to right",
                "character_positions": {"Alice": "frame left", "Bob": "frame right"},
                "control_references": {
                    "pose_reference_prompt": "hands remain visible",
                    "depth_reference_prompt": "keep the table in the foreground",
                },
            },
        },
    ))

    assert "Spatial blocking contract" in prompt
    assert "camera angle=over shoulder" in prompt
    assert "Alice: frame left" in prompt
    assert "hands remain visible" in prompt


def test_seedance_native_ark_makes_edit_intent_explicit(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="change the background to a rainy street",
        output_path="out.mp4",
        reference_videos=["https://cdn.example/source.mp4"],
        request_mode="edit",
    ))

    assert payload["omni_reference_task_type"] == "edit"
    assert payload["ratio"] == "adaptive"
    assert payload["duration"] == -1
    assert payload["content"][0]["text"].startswith("Edit the reference video")


def test_seedance_native_ark_makes_extend_intent_explicit(monkeypatch):
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    provider = SeedanceApiProvider(endpoint="https://ark.example/tasks", api_key="secret")

    payload = provider._video_payload(VideoGenerationRequest(
        prompt="the woman enters from the left",
        output_path="out.mp4",
        extend_video="https://cdn.example/source.mp4",
        request_mode="extend",
    ))

    assert payload["omni_reference_task_type"] == "extend"
    assert payload["ratio"] == "adaptive"
    assert payload["duration"] == -1
    assert payload["content"][0]["text"].startswith("Extend the reference video")


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
    progress = []

    result = provider.generate_video(VideoGenerationRequest(
        prompt="hero turns",
        output_path=str(output),
        progress_callback=lambda percent, state: progress.append((percent, state)),
    ))

    assert result.output_path == str(output)
    assert output.read_bytes() == b"done"
    assert FakeClient.polls == 2
    assert result.metadata["provider_task_id"] == "abc"
    assert "queued" in [state for _, state in progress]
    assert "running" in [state for _, state in progress]
    assert "completed" in [state for _, state in progress]
    assert progress[-1][1] == "downloaded"
    assert progress[-1][0] > progress[0][0]


def test_async_provider_resumes_pending_task_without_resubmitting(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, payload=None, content=b"", content_type="application/json"):
            self.payload = payload or {}
            self.content = content
            self.headers = {"content-type": content_type}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        phase = "first"
        urls = []

        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            if FakeClient.phase != "first":
                raise AssertionError("resuming a pending task must not submit a second POST")
            return FakeResponse({"job_id": "resume-task"})

        def get(self, url, **_kwargs):
            FakeClient.urls.append(url)
            if "status" in url:
                if FakeClient.phase == "first":
                    return FakeResponse({"status": "running"})
                return FakeResponse({"status": "succeeded", "video_url": "https://media.example/resumed.mp4"})
            return FakeResponse(content=b"resumed-video", content_type="video/mp4")

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    monkeypatch.setattr("src.services.generation_provider.time.sleep", lambda *_args: None)
    output = tmp_path / "scene.mp4"
    first = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    first.status_endpoint = "https://gateway.example/v1/status/{job_id}"
    first.max_polls = 1
    first.poll_interval = 0

    with pytest.raises(GenerationProviderError, match="timed out"):
        first.generate_video(VideoGenerationRequest(prompt="resume me", output_path=str(output)))
    pending = output.with_suffix(".provider.pending.json")
    assert pending.is_file()

    FakeClient.phase = "resumed"
    second = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    second.status_endpoint = "https://gateway.example/v2/status/{job_id}"
    second.poll_interval = 0
    result = second.generate_video(VideoGenerationRequest(prompt="resume me", output_path=str(output)))

    assert result.output_path == str(output)
    assert output.read_bytes() == b"resumed-video"
    assert result.metadata["resumed_pending_task"] is True
    assert not pending.exists()
    assert FakeClient.urls == [
        "https://gateway.example/v1/status/resume-task",
        "https://gateway.example/v1/status/resume-task",
        "https://media.example/resumed.mp4",
    ]


def test_pending_task_404_clears_sidecar_and_returns_actionable_error(tmp_path, monkeypatch):
    output = tmp_path / "scene.mp4"
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider._write_pending_task(str(output), "expired-task")

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            request = httpx.Request("GET", "https://gateway.example/status/expired-task")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)

    with pytest.raises(GenerationProviderError, match="HTTP 404"):
        provider.generate_video(VideoGenerationRequest(prompt="resume", output_path=str(output)))
    assert not output.with_suffix(".provider.pending.json").exists()


def test_pending_task_rejects_a_different_request_identity(tmp_path):
    output = tmp_path / "scene.mp4"
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    original = VideoGenerationRequest(prompt="original shot", output_path=str(output))
    provider._write_pending_task(str(output), "remote-task", original)

    with pytest.raises(GenerationProviderError, match="different video request"):
        provider.generate_video(VideoGenerationRequest(prompt="different shot", output_path=str(output)))


def test_pending_task_rejects_a_different_model_identity(tmp_path):
    output = tmp_path / "scene.mp4"
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    original = VideoGenerationRequest(
        prompt="same prompt",
        output_path=str(output),
        model="doubao-seedance-2-0-260128",
    )
    changed_model = VideoGenerationRequest(
        prompt="same prompt",
        output_path=str(output),
        model="doubao-seedance-2-5-260628",
    )
    provider._write_pending_task(str(output), "remote-task", original)

    pending = json.loads(output.with_suffix(".provider.pending.json").read_text())
    assert pending["request_options"]["model"] == "doubao-seedance-2-0-260128"

    with pytest.raises(GenerationProviderError, match="different video request"):
        provider.generate_video(changed_model)


def test_http_video_provider_stops_polling_when_cancelled(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload
            self.content = b""

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
            return FakeResponse({"job_id": "cancel-me"})

        def get(self, *_args, **_kwargs):
            FakeClient.polls += 1
            mark_cancelled()
            return FakeResponse({"status": "running"})

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    monkeypatch.setattr("src.services.generation_provider.time.sleep", lambda *_args: None)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.poll_interval = 0
    cancelled = False

    def cancellation_check():
        return cancelled

    def mark_cancelled():
        nonlocal cancelled
        cancelled = True

    with pytest.raises(GenerationCancelledError):
        provider.generate_video(VideoGenerationRequest(
            prompt="hero turns",
            output_path=str(tmp_path / "scene.mp4"),
            progress_callback=lambda *_args: None,
            cancellation_check=cancellation_check,
        ))

    assert FakeClient.polls == 1


def test_http_video_provider_treats_expired_as_terminal_failure(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload
            self.content = b""

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse({"job_id": "expired-task"})

        def get(self, *_args, **_kwargs):
            return FakeResponse({"status": "expired", "message": "task exceeded retention window"})

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.poll_interval = 0
    progress = []

    with pytest.raises(GenerationProviderError, match="expired"):
        provider.generate_video(VideoGenerationRequest(
            prompt="hero turns",
            output_path=str(tmp_path / "scene.mp4"),
            progress_callback=lambda percent, state: progress.append((percent, state)),
        ))

    assert provider.last_result_metadata["provider_task_status"] == "expired"
    assert provider.last_result_metadata["provider_error"] == "task exceeded retention window"
    assert progress[-1] == (99, "failed")


def test_async_provider_formats_structured_provider_error(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "failed", "error": {"code": "quota_exceeded", "message": "daily limit reached"}}

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            response = FakeResponse()
            response.json = lambda: {"job_id": "failed-task"}
            return response

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.poll_interval = 0

    with pytest.raises(GenerationProviderError, match="quota_exceeded: daily limit reached"):
        provider.generate_video(VideoGenerationRequest(
            prompt="failed shot",
            output_path=str(tmp_path / "scene.mp4"),
        ))

    assert provider.last_result_metadata["provider_error_code"] == "quota_exceeded"
    assert provider.last_result_metadata["provider_error"] == "quota_exceeded: daily limit reached"


def test_async_provider_enforces_wall_clock_timeout(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload
            self.content = b""

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
            return FakeResponse({"job_id": "slow-task"})

        def get(self, *_args, **_kwargs):
            FakeClient.polls += 1
            return FakeResponse({"status": "running"})

    clock = iter((10.0, 10.0, 10.0, 10.2, 10.2, 10.2))
    monkeypatch.setattr("src.services.generation_provider.time.monotonic", lambda: next(clock, 10.2))
    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    monkeypatch.setattr("src.services.generation_provider.time.sleep", lambda *_args: None)
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{job_id}"
    provider.timeout = 0.1
    provider.poll_interval = 30

    with pytest.raises(GenerationProviderError, match="timed out"):
        provider.generate_video(VideoGenerationRequest(
            prompt="slow shot",
            output_path=str(tmp_path / "scene.mp4"),
        ))

    assert FakeClient.polls == 1


def test_seedance_native_cancellation_attempts_remote_queued_cancel(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload
            self.content = b""

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        deleted = []

        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse({"id": "ark-task-1", "status": "queued"})

        def get(self, *_args, **_kwargs):
            mark_cancelled()
            return FakeResponse({"id": "ark-task-1", "status": "queued"})

        def delete(self, url, **_kwargs):
            FakeClient.deleted.append(url)
            return FakeResponse({})

    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    monkeypatch.setattr("src.services.generation_provider.time.sleep", lambda *_args: None)
    provider = SeedanceApiProvider(endpoint="https://ark.example/api/v3/contents/generations/tasks", api_key="secret")
    provider.status_endpoint = "https://ark.example/api/v3/contents/generations/tasks/{job_id}"
    provider.poll_interval = 0
    cancelled = False

    def cancellation_check():
        return cancelled

    def mark_cancelled():
        nonlocal cancelled
        cancelled = True

    with pytest.raises(GenerationCancelledError):
        provider.generate_video(VideoGenerationRequest(
            prompt="continue the shot",
            output_path=str(tmp_path / "scene.mp4"),
            cancellation_check=cancellation_check,
        ))

    assert FakeClient.deleted == ["https://ark.example/api/v3/contents/generations/tasks/ark-task-1"]
    assert provider.last_result_metadata["remote_cancel_requested"] is True


def test_seedance_provider_resolves_request_id_result_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "false")
    class FakeResponse:
        def __init__(self, payload=None, content=b"video"):
            self.payload = payload or {}
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse({"request_id": "req-123"})

        def get(self, url, **_kwargs):
            if "status" in url:
                return FakeResponse({"status": "COMPLETED"})
            if "result" in url:
                return FakeResponse({"video_url": {"url": "https://media.example/seedance.mp4"}})
            return FakeResponse(content=b"seedance-bytes")

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    monkeypatch.setattr("src.services.generation_provider.time.sleep", lambda *_args: None)
    provider = SeedanceApiProvider(endpoint="https://gateway.example/submit", api_key="secret")
    provider.status_endpoint = "https://gateway.example/status/{request_id}"
    provider.result_endpoint = "https://gateway.example/result/{request_id}"
    provider.poll_interval = 0
    output = tmp_path / "scene.mp4"

    result = provider.generate_video(VideoGenerationRequest(prompt="hero turns", output_path=str(output)))

    assert result.output_path == str(output)
    assert output.read_bytes() == b"seedance-bytes"
    assert len(result.metadata["video_sha256"]) == 64


def test_get_generation_provider_supports_http_video(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "http_video_api")
    provider = get_generation_provider()
    assert isinstance(provider, HttpVideoApiProvider)


def test_get_generation_provider_supports_seedance(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "seedance_api")
    provider = get_generation_provider()
    assert isinstance(provider, SeedanceApiProvider)


def test_api_provider_accepts_synchronous_binary_video_response(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "video/mp4"}
        content = b"direct-video"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("src.services.generation_provider.httpx.Client", FakeClient)
    output = tmp_path / "direct.mp4"
    provider = HttpVideoApiProvider(endpoint="https://gateway.example/video", api_key="secret")

    result = provider.generate_video(VideoGenerationRequest(prompt="hero turns", output_path=str(output)))

    assert result.metadata["response_mode"] == "binary"
    assert output.read_bytes() == b"direct-video"


def test_hybrid_provider_falls_back_on_transport_error():
    class Primary:
        def generate_video(self, _request):
            raise httpx.ConnectError("gateway unavailable")

    class Fallback:
        def generate_video(self, _request):
            return GenerationResult("local_comfyui", "fallback.mp4", "video", {})

    result = HybridGenerationProvider(Primary(), Fallback()).generate_video(
        VideoGenerationRequest(prompt="hero turns", output_path="scene.mp4")
    )

    assert result.output_path == "fallback.mp4"


def test_hybrid_provider_does_not_duplicate_accepted_remote_video_task():
    class Primary:
        last_result_metadata = {"provider_task_id": "task-accepted"}

        def generate_video(self, _request):
            raise GenerationProviderError("remote polling failed")

    class Fallback:
        def generate_video(self, _request):
            raise AssertionError("accepted remote task must not fall back locally")

    with pytest.raises(GenerationProviderError, match="remote polling failed"):
        HybridGenerationProvider(Primary(), Fallback()).generate_video(
            VideoGenerationRequest(prompt="hero turns", output_path="scene.mp4")
        )


def test_hybrid_provider_does_not_duplicate_pending_remote_video_task(tmp_path):
    output = tmp_path / "scene.mp4"
    output.with_suffix(".provider.pending.json").write_text(
        json.dumps({"provider_task_id": "task-pending"}),
        encoding="utf-8",
    )

    class Primary:
        def generate_video(self, _request):
            raise GenerationProviderError("provider timeout")

    class Fallback:
        def generate_video(self, _request):
            raise AssertionError("pending remote task must not fall back locally")

    with pytest.raises(GenerationProviderError, match="provider timeout"):
        HybridGenerationProvider(Primary(), Fallback()).generate_video(
            VideoGenerationRequest(prompt="hero turns", output_path=str(output))
        )


def test_hybrid_provider_does_not_fallback_after_remote_output_validation_failure():
    class Primary:
        last_result_metadata = {"provider_request_submitted": True}

        def generate_video(self, _request):
            raise GenerationProviderError("downloaded video failed validation")

    class Fallback:
        def generate_video(self, _request):
            raise AssertionError("remote output validation failure must not duplicate generation")

    with pytest.raises(GenerationProviderError, match="failed validation"):
        HybridGenerationProvider(Primary(), Fallback()).generate_video(
            VideoGenerationRequest(prompt="hero turns", output_path="scene.mp4")
        )
