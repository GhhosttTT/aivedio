import json
import numpy as np
import pytest

from src.services.video_quality_metrics import (
    _probe,
    _sample_frames,
    temporal_sample_evidence_error,
    video_boundary_continuity,
    video_start_frame_reference_metrics,
    video_technical_score,
)


def test_adaptive_sampling_scales_with_duration_and_stays_bounded(monkeypatch, tmp_path):
    class FakeCapture:
        def __init__(self):
            self.positions = []

        def isOpened(self):
            return True

        def get(self, property_id):
            return 2400

        def set(self, property_id, value):
            self.positions.append(value)

        def read(self):
            return True, object()

        def release(self):
            pass

    capture = FakeCapture()
    class FakeCV2:
        CAP_PROP_FRAME_COUNT = 7
        CAP_PROP_POS_FRAMES = 1
        INTER_AREA = 3

        @staticmethod
        def VideoCapture(_path):
            return capture

        @staticmethod
        def resize(frame, _size, interpolation=None):
            return frame

    frames = _sample_frames(
        tmp_path / "long.mp4", None, FakeCV2, np, duration_seconds=30.0,
    )

    assert len(frames) == 96
    assert len(capture.positions) == 96


def test_explicit_sampling_budget_is_preserved(monkeypatch, tmp_path):
    class FakeCapture:
        def isOpened(self):
            return True

        def get(self, _property_id):
            return 2400

        def set(self, _property_id, _value):
            pass

        def read(self):
            return True, object()

        def release(self):
            pass

    class FakeCV2:
        CAP_PROP_FRAME_COUNT = 7
        CAP_PROP_POS_FRAMES = 1
        INTER_AREA = 3

        @staticmethod
        def VideoCapture(_path):
            return FakeCapture()

        @staticmethod
        def resize(frame, _size, interpolation=None):
            return frame

    frames = _sample_frames(
        tmp_path / "comparison.mp4", 6, FakeCV2, np, duration_seconds=30.0,
    )

    assert len(frames) == 6


def test_video_boundary_continuity_is_not_applicable_for_one_clip(tmp_path):
    report = video_boundary_continuity([tmp_path / "only.mp4"])
    assert report == {"status": "not_applicable", "boundary_count": 0, "boundaries": []}


def test_video_start_frame_reference_is_not_applicable_without_reference(tmp_path):
    assert video_start_frame_reference_metrics(tmp_path / "clip.mp4", None) == {
        "status": "not_applicable"
    }


def test_video_technical_score_prefers_readable_motion_and_sharpness():
    weak = video_technical_score({
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 0.2,
        "sharpness": 2.0,
        "brightness": 40.0,
        "brightness_variance": 900.0,
    })
    strong = video_technical_score({
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 10.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
    })

    assert strong > weak
    assert strong >= 4.0
    assert weak < 3.0


def test_video_technical_score_does_not_penalize_valid_long_form_duration():
    metrics = {
        "duration_seconds": 30.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 10.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
    }

    score = video_technical_score(
        metrics,
        duration_low=4.0,
        duration_high=30.0,
        duration_soft_low=2.0,
        duration_soft_high=32.0,
    )

    assert score >= 4.0


def test_video_technical_score_penalizes_frozen_transitions():
    shared = {
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 8.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
    }
    dynamic = video_technical_score({**shared, "static_transition_ratio": 0.0})
    frozen = video_technical_score({**shared, "static_transition_ratio": 1.0})
    assert dynamic - frozen >= 0.5


def test_video_technical_score_penalizes_black_frame_runs():
    shared = {
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 8.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
        "static_transition_ratio": 0.0,
    }
    clean = video_technical_score({**shared, "max_black_run_seconds": 0.0})
    black = video_technical_score({**shared, "max_black_run_seconds": 0.6})
    assert clean - black >= 0.2


def test_video_technical_score_penalizes_temporal_instability():
    shared = {
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 8.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
        "static_transition_ratio": 0.0,
        "max_black_run_seconds": 0.0,
    }
    stable = video_technical_score({
        **shared, "brightness_step_p95": 4.0, "motion_jitter_ratio": 0.1,
    })
    unstable = video_technical_score({
        **shared, "brightness_step_p95": 60.0, "motion_jitter_ratio": 2.0,
    })
    assert stable - unstable >= 0.2


def test_video_technical_score_penalizes_repeated_temporal_visual_jumps():
    shared = {
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 8.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
        "static_transition_ratio": 0.0,
        "max_black_run_seconds": 0.0,
    }
    stable = video_technical_score({**shared, "temporal_jump_ratio": 0.0})
    reset_heavy = video_technical_score({**shared, "temporal_jump_ratio": 0.6})
    assert stable - reset_heavy >= 0.15


def test_temporal_sample_evidence_error_rejects_insufficient_samples():
    error = temporal_sample_evidence_error({
        "status": "available",
        "sampled_frames": 3,
        "temporal_sample_evidence": "insufficient",
        "temporal_sample_minimum": 4,
    }, context="final composed video")

    assert error == "final composed video has insufficient temporal evidence: sampled_frames=3, minimum=4"


def test_temporal_sample_evidence_error_allows_sufficient_samples():
    assert temporal_sample_evidence_error({
        "status": "available",
        "sampled_frames": 4,
        "temporal_sample_evidence": "sufficient",
        "temporal_sample_minimum": 4,
    }) is None


def test_probe_reports_audio_stream_and_duration(monkeypatch, tmp_path):
    class Result:
        stdout = json.dumps({
            "streams": [
                {
                    "codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le",
                    "width": 1920, "height": 1080, "r_frame_rate": "24/1",
                    "start_time": "0.000",
                },
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "duration": "5.02", "start_time": "0.420"},
            ],
            "format": {"duration": "5.00"},
        })

    monkeypatch.setattr("src.services.video_quality_metrics.subprocess.run", lambda *args, **kwargs: Result())

    metrics = _probe(tmp_path / "scene.mp4")

    assert metrics["audio_present"] is True
    assert metrics["audio_duration_seconds"] == 5.02
    assert metrics["audio_codec"] == "aac"
    assert metrics["audio_channels"] == 2
    assert metrics["video_codec"] == "hevc"
    assert metrics["pixel_format"] == "yuv420p10le"
    assert metrics["high_bit_depth"] is True
    assert metrics["audio_video_start_delta_seconds"] == 0.42


@pytest.mark.parametrize(
    ("format_data", "stream", "message"),
    [
        ({"duration": "0"}, {"codec_type": "video", "width": 1920, "height": 1080, "r_frame_rate": "24/1"}, "duration"),
        ({"duration": "5"}, {"codec_type": "video", "width": 0, "height": 1080, "r_frame_rate": "24/1"}, "geometry"),
        ({"duration": "5"}, {"codec_type": "video", "width": 1920, "height": 1080, "r_frame_rate": "0/1"}, "frame rate"),
    ],
)
def test_probe_rejects_unverifiable_video_metadata(
    monkeypatch, tmp_path, format_data, stream, message,
):
    class Result:
        stdout = json.dumps({"streams": [stream], "format": format_data})

    monkeypatch.setattr("src.services.video_quality_metrics.subprocess.run", lambda *args, **kwargs: Result())

    with pytest.raises(ValueError, match=message):
        _probe(tmp_path / "invalid.mp4")
