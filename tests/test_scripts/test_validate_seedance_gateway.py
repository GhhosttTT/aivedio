import json
from types import SimpleNamespace

from scripts.validate_seedance_gateway import _validate_live_output, _validate_temporal_quality, main
from src.services.generation_provider import GenerationProviderError, VideoGenerationRequest


def test_seedance_gateway_dry_run_is_side_effect_free(capsys, monkeypatch):
    monkeypatch.delenv("SEEDANCE_ENDPOINT", raising=False)
    monkeypatch.delenv("SEEDANCE_API_KEY", raising=False)

    assert main(["--mode", "multi_shot"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["configured"] is False
    assert output["live"] is False
    assert output["payload"]["aspect_ratio"] == "9:16"
    assert output["payload"]["multi_shot"] is True
    assert output["payload"]["image_urls"] == []


def test_seedance_gateway_accepts_explicit_dry_run(capsys, monkeypatch):
    monkeypatch.delenv("SEEDANCE_ENDPOINT", raising=False)
    monkeypatch.delenv("SEEDANCE_API_KEY", raising=False)

    assert main(["--dry-run", "--mode", "reference"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["live"] is False


def test_seedance_gateway_dry_run_supports_native_auto_mode(capsys, monkeypatch):
    monkeypatch.delenv("SEEDANCE_ENDPOINT", raising=False)
    monkeypatch.delenv("SEEDANCE_API_KEY", raising=False)
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")

    assert main(["--dry-run", "--api-format", "ark_v3", "--mode", "auto"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["payload"]["omni_reference_task_type"] == "auto"
    assert output["payload"]["duration"] == 5


def test_seedance_gateway_rejects_missing_reference_file(capsys, tmp_path):
    assert main(["--reference-image", str(tmp_path / "missing.png")]) == 2
    assert "do not exist" in capsys.readouterr().err


def test_seedance_gateway_live_mode_requires_configuration(capsys, monkeypatch):
    monkeypatch.delenv("SEEDANCE_ENDPOINT", raising=False)
    monkeypatch.delenv("SEEDANCE_API_KEY", raising=False)

    assert main(["--live"]) == 2
    assert "refusing live request" in capsys.readouterr().err


def test_seedance_gateway_dry_run_supports_edit_controls(capsys, tmp_path, monkeypatch):
    video = tmp_path / "reference.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", "https://cdn.example/{filename}")

    assert main([
        "--api-format", "ark_v3",
        "--mode", "edit",
        "--reference-video", str(video),
        "--resolution", "1080p",
        "--output-format", "mov",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["payload"]["omni_reference_task_type"] == "edit"
    assert output["payload"]["ratio"] == "adaptive"
    assert output["payload"]["duration"] == -1


def test_seedance_gateway_live_validates_downloaded_artifact(capsys, tmp_path, monkeypatch):
    output_path = tmp_path / "seedance.mp4"

    class FakeProvider:
        endpoint = "https://ark.example/tasks"
        api_key = "secret"

        def _video_payload(self, _request):
            return {"prompt": "test"}

        def generate_video(self, request):
            output_path.write_bytes(b"video")
            return SimpleNamespace(output_path=str(output_path))

    monkeypatch.setattr("scripts.validate_seedance_gateway.SeedanceApiProvider", FakeProvider)
    monkeypatch.setattr(
        "scripts.validate_seedance_gateway.video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "duration_seconds": 5.0,
            "width": 1080,
            "height": 1920,
            "audio_present": False,
        },
    )

    assert main(["--live", "--output", str(output_path)]) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["artifact_validation"]["width"] == 1080
    evidence_path = output_path.with_suffix(".generation.json")
    assert report["evidence_path"] == str(evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["kind"] == "seedance_live_validation"
    assert evidence["artifact_validation"]["width"] == 1080


def test_seedance_gateway_live_rejects_unreadable_download(capsys, monkeypatch):
    class FakeProvider:
        endpoint = "https://ark.example/tasks"
        api_key = "secret"

        def _video_payload(self, _request):
            return {"prompt": "test"}

        def generate_video(self, request):
            return SimpleNamespace(output_path=request.output_path)

    monkeypatch.setattr("scripts.validate_seedance_gateway.SeedanceApiProvider", FakeProvider)
    monkeypatch.setattr(
        "scripts.validate_seedance_gateway.video_candidate_metrics",
        lambda _path: {"status": "unavailable", "error": "invalid mp4"},
    )

    assert main(["--live"]) == 2
    assert "unreadable video artifact" in capsys.readouterr().err


def test_seedance_gateway_live_rejects_duration_drift(capsys, monkeypatch):
    class FakeProvider:
        endpoint = "https://ark.example/tasks"
        api_key = "secret"

        def _video_payload(self, _request):
            return {"prompt": "test"}

        def generate_video(self, request):
            return SimpleNamespace(output_path=request.output_path)

    monkeypatch.setattr("scripts.validate_seedance_gateway.SeedanceApiProvider", FakeProvider)
    monkeypatch.setattr(
        "scripts.validate_seedance_gateway.video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "duration_seconds": 2.0,
            "width": 1080,
            "height": 1920,
            "audio_present": False,
        },
    )

    assert main(["--live", "--duration", "5"]) == 2
    assert "duration is out of sync" in capsys.readouterr().err


def test_seedance_gateway_live_allows_model_selected_duration_for_ark_extend(
    tmp_path, monkeypatch,
):
    output_path = tmp_path / "extended.mp4"
    output_path.write_bytes(b"video")
    request = VideoGenerationRequest(
        prompt="continue the shot",
        output_path=str(output_path),
        request_mode="extend",
        duration_seconds=5.0,
    )
    monkeypatch.setattr(
        "scripts.validate_seedance_gateway.video_candidate_metrics",
        lambda _path: {
            "status": "available",
            "duration_seconds": 11.0,
            "width": 1080,
            "height": 1920,
            "audio_present": False,
        },
    )

    metrics = _validate_live_output(
        str(output_path),
        request,
        expected_duration=0.0,
    )

    assert metrics["duration_seconds"] == 11.0


def test_seedance_gateway_rejects_frozen_temporal_output():
    try:
        _validate_temporal_quality({
            "max_static_run_seconds": 2.0,
            "motion_energy": 0.1,
        })
    except GenerationProviderError as exc:
        assert "frozen/static" in str(exc)
    else:
        raise AssertionError("frozen output should be rejected")


def test_seedance_gateway_rejects_temporal_exposure_jump():
    try:
        _validate_temporal_quality({"brightness_step_p95": 100.0})
    except GenerationProviderError as exc:
        assert "exposure jumps" in str(exc)
    else:
        raise AssertionError("exposure jump should be rejected")


def test_seedance_gateway_rejects_black_frame_run():
    try:
        _validate_temporal_quality({"max_black_run_seconds": 1.0})
    except GenerationProviderError as exc:
        assert "black-frame" in str(exc)
    else:
        raise AssertionError("black-frame run should be rejected")
