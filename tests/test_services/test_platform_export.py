import json

import pytest

from src.services.platform_export import PlatformExportError, export_platform_video


def test_platform_export_is_cached_and_has_contract(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    monkeypatch.setattr("src.services.platform_export.video_candidate_metrics", lambda *_args, **_kwargs: {
        "status": "available",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "duration_seconds": 2.0,
    })
    first = export_platform_video(source, tmp_path, "douyin")
    second = export_platform_video(source, tmp_path, "douyin")

    assert first["width"] == 1080
    assert first["height"] == 1920
    assert second["output_path"] == first["output_path"]
    assert len(calls) == 1
    assert json.loads((tmp_path / "exports" / "douyin.json").read_text())["preset"] == "douyin"
    assert first["technical_metrics"]["status"] == "available"
    assert len(first["source_sha256"]) == 64
    assert len(first["output_sha256"]) == 64


def test_platform_export_rebuilds_when_content_changes_without_signature_change(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    monkeypatch.setattr("src.services.platform_export._signature", lambda _path: "stable-signature")
    monkeypatch.setattr("src.services.platform_export.video_candidate_metrics", lambda *_args, **_kwargs: {
        "status": "available", "width": 1080, "height": 1920, "fps": 30.0, "duration_seconds": 2.0,
    })
    export_platform_video(source, tmp_path, "douyin")
    (tmp_path / "exports" / "douyin.mp4").write_bytes(b"tampered")

    export_platform_video(source, tmp_path, "douyin")

    assert len(calls) == 2


def test_platform_export_rejects_decoded_geometry_drift(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    monkeypatch.setattr("src.services.platform_export.video_candidate_metrics", lambda *_args, **_kwargs: {
        "status": "available",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "duration_seconds": 2.0,
    })

    with pytest.raises(PlatformExportError, match="geometry drifted"):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_unreadable_output(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    monkeypatch.setattr("src.services.platform_export.video_candidate_metrics", lambda *_args, **_kwargs: {
        "status": "unavailable",
        "error": "ffprobe failed",
    })

    with pytest.raises(PlatformExportError, match="technical validation"):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_audio_loss_and_duration_drift(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    metrics = iter([
        {"status": "available", "width": 1080, "height": 1920, "fps": 30.0, "duration_seconds": 2.0, "audio_present": True},
        {"status": "available", "width": 1080, "height": 1920, "fps": 30.0, "duration_seconds": 3.0, "audio_present": False},
    ])
    monkeypatch.setattr(
        "src.services.platform_export.video_candidate_metrics",
        lambda *_args, **_kwargs: next(metrics),
    )

    with pytest.raises(PlatformExportError, match="duration drifted"):
        export_platform_video(source, tmp_path, "douyin")


@pytest.mark.parametrize(
    ("metric", "value", "message"),
    [
        ("temporal_jump_ratio", 0.8, "temporal visual resets"),
        ("motion_jitter_ratio", 2.0, "unstable motion cadence"),
        ("brightness_step_p95", 60.0, "temporal exposure jumps"),
    ],
)
def test_platform_export_rejects_temporal_quality_regression(tmp_path, monkeypatch, metric, value, message):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    metrics = {
        "status": "available",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "duration_seconds": 2.0,
        metric: value,
    }
    monkeypatch.setattr(
        "src.services.platform_export.video_candidate_metrics",
        lambda *_args, **_kwargs: dict(metrics),
    )

    with pytest.raises(PlatformExportError, match=message):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_clipped_audio(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    monkeypatch.setattr("src.services.platform_export.video_candidate_metrics", lambda *_args, **_kwargs: {
        "status": "available",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "duration_seconds": 2.0,
        "audio_present": True,
        "audio_signal_status": "usable",
        "audio_clipping_status": "clipped",
    })

    with pytest.raises(PlatformExportError, match="audio signal is clipped"):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_unknown_preset(tmp_path):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    with pytest.raises(PlatformExportError, match="Unknown"):
        export_platform_video(source, tmp_path, "unknown")
