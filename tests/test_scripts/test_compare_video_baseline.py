import shutil
from types import SimpleNamespace
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.compare_video_baseline import VideoStats, _audio_signal_stats, _parse_fps, _probe, compare


requires_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")


def _write_test_video(path: Path, *, frames: int = 12, moving: bool = True, size: tuple[int, int] = (160, 90)) -> None:
    width, height = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 8, size)
    assert writer.isOpened()
    for index in range(frames):
        frame = np.full((height, width, 3), 40, dtype=np.uint8)
        offset = min(index * 5 if moving else 0, max(width - 50, 0))
        top = max(4, height // 3)
        bottom = min(height - 4, top + max(16, height // 3))
        cv2.rectangle(frame, (10 + offset, top), (min(width - 8, 45 + offset), bottom), (220, 220, 220), -1)
        writer.write(frame)
    writer.release()


def test_parse_fps_fraction():
    assert _parse_fps("30000/1001") == pytest.approx(29.970, rel=0.001)


def test_audio_signal_stats_reads_ffmpeg_peak_level(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return type("Result", (), {
            "returncode": 0,
            "stdout": "",
            "stderr": "[Parsed_volumedetect_0 @ 0x0] max_volume: -12.3 dB",
        })()

    monkeypatch.setattr("scripts.compare_video_baseline.subprocess.run", fake_run)

    result = _audio_signal_stats(tmp_path / "dialogue.mp4")

    assert result["audio_signal_status"] == "usable"
    assert result["audio_clipping_status"] == "ok"
    assert result["audio_peak_db"] == pytest.approx(-12.3)
    assert captured["command"][2] == "info"


def test_probe_reads_video_and_audio_streams(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(
            stdout=(
                '{"streams":['
                '{"codec_type":"video","width":1920,"height":1080,'
                '"r_frame_rate":"24/1","duration":"5.0","codec_name":"h264",'
                '"pix_fmt":"yuv420p10le"},'
                '{"codec_type":"audio","duration":"4.9","codec_name":"aac"}'
                '],"format":{"duration":"5.0"}}'
            )
        )

    monkeypatch.setattr("scripts.compare_video_baseline.subprocess.run", fake_run)

    result = _probe(tmp_path / "candidate.mp4")

    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["audio_present"] is True
    assert result["audio_duration_seconds"] == pytest.approx(4.9)
    assert result["audio_codec"] == "aac"
    assert result["pixel_format"] == "yuv420p10le"
    assert "-select_streams" not in captured["command"]


@requires_ffprobe
def test_compare_video_baseline_reports_measurable_gates(tmp_path):
    baseline = tmp_path / "seed_dance.mp4"
    candidate = tmp_path / "candidate.mp4"
    _write_test_video(baseline)
    _write_test_video(candidate)

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["kind"] == "seed_dance_baseline_comparison"
    assert report["status"] == "passed"
    assert report["score"] >= report["min_score"]
    assert report["candidate"]["sampled_frames"] >= 4
    assert report["gates"]["duration_close"] is True
    assert report["gates"]["motion_not_static"] is True
    assert Path(report["contact_sheet_path"]).is_file()
    assert Path(report["contact_sheet_path"]).name == "seed_dance_contact_sheet.png"


@requires_ffprobe
def test_compare_video_baseline_blocks_static_candidate(tmp_path):
    baseline = tmp_path / "seed_dance.mp4"
    candidate = tmp_path / "candidate_static.mp4"
    _write_test_video(baseline, moving=True)
    _write_test_video(candidate, moving=False)

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["status"] == "needs_review"
    assert report["score"] < report["min_score"]
    assert report["gates"]["motion_not_static"] is False


@requires_ffprobe
def test_compare_video_baseline_blocks_aspect_ratio_mismatch(tmp_path):
    baseline = tmp_path / "seed_dance_vertical.mp4"
    candidate = tmp_path / "candidate_horizontal.mp4"
    _write_test_video(baseline, size=(90, 160))
    _write_test_video(candidate, size=(160, 90))

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["status"] == "needs_review"
    assert report["gates"]["resolution_not_lower"] is True
    assert report["gates"]["aspect_ratio_close"] is False
    assert abs(report["differences"]["aspect_ratio_delta"]) > 1


def test_compare_video_baseline_rejects_aspect_ratio_mismatch_without_video_probe(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        if "baseline" in path.name:
            return VideoStats(
                path=str(path),
                duration_seconds=2.0,
                width=90,
                height=160,
                fps=24,
                sampled_frames=6,
                motion_energy=8,
                sharpness=30,
                brightness=90,
                brightness_variance=40,
            )
        return VideoStats(
            path=str(path),
            duration_seconds=2.0,
            width=160,
            height=90,
            fps=24,
            sampled_frames=6,
            motion_energy=8,
            sharpness=30,
            brightness=90,
            brightness_variance=40,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["resolution_not_lower"] is True
    assert report["gates"]["aspect_ratio_close"] is False


def test_compare_video_baseline_rejects_large_exposure_shift_without_video_probe(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        brightness = 95 if "baseline" in path.name else 30
        return VideoStats(
            path=str(path),
            duration_seconds=2.0,
            width=90,
            height=160,
            fps=24,
            sampled_frames=6,
            motion_energy=8,
            sharpness=30,
            brightness=brightness,
            brightness_variance=40,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["aspect_ratio_close"] is True
    assert report["gates"]["exposure_close"] is False
    assert report["differences"]["brightness_delta"] == -65


def test_compare_video_baseline_blocks_missing_candidate_audio(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40, audio_present="baseline" in path.name,
            audio_duration_seconds=2.0 if "baseline" in path.name else None,
            audio_codec="aac" if "baseline" in path.name else None,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["audio_presence_matches"] is False
    assert report["gates"]["audio_duration_close"] is False


def test_compare_video_baseline_blocks_unusable_candidate_audio(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40, audio_present=True, audio_duration_seconds=2.0,
            audio_signal_status="near_silent" if "candidate" in path.name else "usable",
            audio_clipping_status="ok", audio_peak_db=-60.0 if "candidate" in path.name else -12.0,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["audio_signal_usable"] is False


def test_compare_video_baseline_blocks_audio_start_drift(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40, audio_present=True, audio_duration_seconds=2.0,
            audio_signal_status="usable", audio_clipping_status="ok",
            audio_video_start_delta_seconds=0.5 if "candidate" in path.name else 0.02,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["audio_start_aligned"] is False


def test_compare_video_baseline_blocks_large_audio_level_drift(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40, audio_present=True, audio_duration_seconds=2.0,
            audio_signal_status="usable", audio_clipping_status="ok",
            audio_peak_db=-30.0 if "candidate" in path.name else -8.0,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["audio_level_close"] is False
    assert report["differences"]["audio_peak_delta_db"] == -22.0


def test_compare_video_baseline_blocks_prolonged_static_run(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=4.0, width=160, height=90, fps=24,
            sampled_frames=8, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40, max_static_run_seconds=2.1 if "candidate" in path.name else 0.2,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=8)

    assert report["status"] == "needs_review"
    assert report["gates"]["motion_not_static"] is True
    assert report["gates"]["no_prolonged_static_run"] is False
    assert report["differences"]["max_static_run_delta_seconds"] == 1.9


def test_compare_video_baseline_blocks_scattered_black_frames(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40,
            black_frame_ratio=0.2 if "candidate" in path.name else 0.0,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["black_frame_ratio_acceptable"] is False


def test_compare_video_baseline_blocks_temporal_visual_resets(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40,
            temporal_jump_ratio=0.8 if "candidate" in path.name else 0.1,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["no_temporal_visual_resets"] is False
    assert report["differences"]["temporal_jump_ratio_delta"] == 0.7


def test_compare_video_baseline_blocks_extreme_temporal_visual_reset(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40,
            temporal_jump_ratio=0.01,
            temporal_jump_p95=0.9 if "candidate" in path.name else 0.2,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["no_temporal_visual_resets"] is True
    assert report["gates"]["no_extreme_temporal_visual_reset"] is False
    assert report["differences"]["temporal_jump_p95_delta"] == 0.7


def test_compare_video_baseline_blocks_large_fps_mismatch(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90,
            fps=12 if "candidate" in path.name else 24,
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["fps_close"] is False
    assert report["differences"]["fps_delta"] == -12


def test_compare_video_baseline_blocks_lower_pixel_format_fidelity(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        return VideoStats(
            path=str(path), duration_seconds=2.0, width=160, height=90, fps=24,
            pixel_format="yuv420p" if "candidate" in path.name else "yuv420p10le",
            sampled_frames=6, motion_energy=8, sharpness=30, brightness=90,
            brightness_variance=40,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["pixel_format_not_lower"] is False
    assert report["differences"]["pixel_format_match"] is False
