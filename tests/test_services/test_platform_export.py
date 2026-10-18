import hashlib
import json
from pathlib import Path

import pytest

from src.services.platform_export import PlatformExportError, export_platform_video as _export_platform_video


def export_platform_video(source, project_root, preset, **kwargs):
    kwargs.setdefault("approval_report", _approved_report(Path(source)))
    return _export_platform_video(source, project_root, preset, **kwargs)


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
        "temporal_sample_evidence": "sufficient",
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


def test_platform_export_invalidates_cache_without_temporal_evidence(tmp_path, monkeypatch):
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
        "temporal_sample_evidence": "sufficient",
    })
    export_platform_video(source, tmp_path, "douyin")
    manifest = tmp_path / "exports" / "douyin.json"
    cached = json.loads(manifest.read_text())
    cached["technical_metrics"].pop("temporal_sample_evidence")
    manifest.write_text(json.dumps(cached), encoding="utf-8")

    export_platform_video(source, tmp_path, "douyin")

    assert len(calls) == 2


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
    approval = _approved_report(source)
    approval["video_signature"] = "stable-signature"
    export_platform_video(source, tmp_path, "douyin", approval_report=approval)
    (tmp_path / "exports" / "douyin.mp4").write_bytes(b"tampered")

    export_platform_video(source, tmp_path, "douyin", approval_report=approval)

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
        {
            "status": "available", "width": 1080, "height": 1920,
            "fps": 30.0, "duration_seconds": 2.0, "audio_present": True,
            "audio_signal_status": "usable", "audio_clipping_status": "ok",
        },
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
        ("temporal_jump_p95", 0.9, "extreme temporal visual reset"),
        ("black_frame_ratio", 0.2, "too many black frames"),
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


def test_platform_export_rejects_insufficient_temporal_evidence(tmp_path, monkeypatch):
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
        "sampled_frames": 3,
        "temporal_sample_evidence": "insufficient",
        "temporal_sample_minimum": 4,
    }
    monkeypatch.setattr(
        "src.services.platform_export.video_candidate_metrics",
        lambda *_args, **_kwargs: dict(metrics),
    )

    with pytest.raises(PlatformExportError, match="insufficient temporal evidence"):
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


def test_platform_export_rejects_unmeasurable_audio_signal(tmp_path, monkeypatch):
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
    })

    with pytest.raises(PlatformExportError, match="audio signal is not usable: unavailable"):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_audio_start_drift(tmp_path, monkeypatch):
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
        "audio_clipping_status": "ok",
        "audio_video_start_delta_seconds": 0.5,
    })

    with pytest.raises(PlatformExportError, match="start offset"):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_audio_level_drift(tmp_path, monkeypatch):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    metrics = iter([
        {
            "status": "available", "width": 1080, "height": 1920,
            "fps": 30.0, "duration_seconds": 2.0, "audio_present": True,
            "audio_signal_status": "usable", "audio_clipping_status": "ok",
            "audio_peak_db": -8.0,
        },
        {
            "status": "available", "width": 1080, "height": 1920,
            "fps": 30.0, "duration_seconds": 2.0, "audio_present": True,
            "audio_signal_status": "usable", "audio_clipping_status": "ok",
            "audio_peak_db": -30.0,
        },
    ])
    monkeypatch.setattr(
        "src.services.platform_export.video_candidate_metrics",
        lambda *_args, **_kwargs: next(metrics),
    )

    with pytest.raises(PlatformExportError, match="audio level drifted"):
        export_platform_video(source, tmp_path, "douyin")


@pytest.mark.parametrize(
    ("audio_rms_db", "expected"),
    [(-40.0, "too quiet"), (-6.0, "too loud")],
)
def test_platform_export_rejects_extreme_audio_mix_level(tmp_path, monkeypatch, audio_rms_db, expected):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")

    def fake_run(command, **_kwargs):
        output = tmp_path / "exports" / ".douyin.tmp.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exported")

    monkeypatch.setattr("src.services.platform_export.subprocess.run", fake_run)
    metrics = {
        "status": "available", "width": 1080, "height": 1920,
        "fps": 30.0, "duration_seconds": 2.0, "audio_present": True,
        "audio_signal_status": "usable", "audio_clipping_status": "ok",
        "audio_rms_db": audio_rms_db,
    }
    monkeypatch.setattr(
        "src.services.platform_export.video_candidate_metrics",
        lambda *_args, **_kwargs: metrics,
    )

    with pytest.raises(PlatformExportError, match=expected):
        export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_unknown_preset(tmp_path):
    source = tmp_path / "final.mp4"
    source.write_bytes(b"source")
    with pytest.raises(PlatformExportError, match="Unknown"):
        export_platform_video(source, tmp_path, "unknown")
def _approved_report(source, **updates):
    report = {
        "status": "passed",
        "video_path": str(source),
        "video_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "video_signature": f"{source.resolve()}:{source.stat().st_size}:{source.stat().st_mtime_ns}",
        "final_technical_metrics": {
            "status": "available",
            "temporal_sample_evidence": "sufficient",
        },
    }
    report.update(updates)
    return report


def test_platform_export_requires_final_composition_approval(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    with pytest.raises(PlatformExportError, match="approval evidence"):
        _export_platform_video(source, tmp_path, "douyin")


def test_platform_export_rejects_stale_final_composition_approval(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    report = _approved_report(source)
    source.write_bytes(b"changed")

    with pytest.raises(PlatformExportError, match="stale"):
        export_platform_video(source, tmp_path, "douyin", approval_report=report)


def test_platform_export_requires_native_audio_evidence(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    report = _approved_report(source, final_audio_expected=True)

    with pytest.raises(PlatformExportError, match="native-audio evidence"):
        export_platform_video(source, tmp_path, "douyin", approval_report=report)
