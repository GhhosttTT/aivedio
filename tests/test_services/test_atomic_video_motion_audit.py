import json
from types import SimpleNamespace

from src.services.atomic_video_motion_audit import AtomicVideoMotionAuditService


def _scene(number, video_path):
    return SimpleNamespace(scene_number=number, video_path=str(video_path))


def _write_sidecar(video, **metrics):
    video.write_bytes(b"video")
    video.with_suffix(".quality.json").write_text(json.dumps({"metrics": metrics}), encoding="utf-8")


def test_atomic_video_motion_audit_accepts_stable_clips(tmp_path):
    first = tmp_path / "scene_1.mp4"
    second = tmp_path / "scene_2.mp4"
    _write_sidecar(first, technical_score=4.5, motion_energy=12, static_transition_ratio=0.2, max_black_run_seconds=0.0, motion_jitter_ratio=0.3)
    _write_sidecar(second, technical_score=4.4, motion_energy=11, static_transition_ratio=0.25, max_black_run_seconds=0.0, motion_jitter_ratio=0.4)

    report = AtomicVideoMotionAuditService().audit([_scene(1, first), _scene(2, second)])

    assert report.status == "passed"
    assert report.checked_scene_count == 2


def test_atomic_video_motion_audit_flags_freeze_and_jitter(tmp_path):
    video = tmp_path / "scene_1.mp4"
    _write_sidecar(video, technical_score=2.5, motion_energy=0.2, static_transition_ratio=0.9, max_black_run_seconds=0.0, motion_jitter_ratio=2.0)

    report = AtomicVideoMotionAuditService().audit([_scene(1, video)])

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} >= {
        "technical_score_low", "frozen_motion", "motion_cadence_unstable",
    }
    assert {item["action"] for item in report.to_dict()["repair_queue"]} >= {
        "increase_motion_and_regenerate_video", "lower_motion_and_regenerate_video",
    }


def test_atomic_video_motion_audit_flags_scattered_black_frames(tmp_path):
    video = tmp_path / "scene_1.mp4"
    _write_sidecar(
        video,
        technical_score=4.2,
        motion_energy=10,
        static_transition_ratio=0.1,
        max_black_run_seconds=0.0,
        black_frame_ratio=0.2,
        motion_jitter_ratio=0.2,
    )

    report = AtomicVideoMotionAuditService().audit([_scene(1, video)])

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "black_frame_ratio_high"


def test_atomic_video_motion_audit_flags_temporal_visual_resets(tmp_path):
    video = tmp_path / "scene_1.mp4"
    _write_sidecar(
        video,
        technical_score=4.2,
        motion_energy=10,
        static_transition_ratio=0.1,
        max_black_run_seconds=0.0,
        motion_jitter_ratio=0.2,
        temporal_jump_ratio=0.5,
        temporal_jump_p95=0.9,
    )

    report = AtomicVideoMotionAuditService().audit([_scene(1, video)])

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "temporal_visual_jump"


def test_atomic_video_motion_audit_flags_extreme_temporal_visual_reset(tmp_path):
    video = tmp_path / "scene_1.mp4"
    _write_sidecar(
        video,
        technical_score=4.2,
        motion_energy=10,
        static_transition_ratio=0.1,
        max_black_run_seconds=0.0,
        motion_jitter_ratio=0.2,
        temporal_jump_ratio=0.01,
        temporal_jump_p95=0.9,
    )

    report = AtomicVideoMotionAuditService().audit([_scene(1, video)])

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "extreme_temporal_visual_jump"
    assert report.issues[0]["action"] == "lower_motion_and_regenerate_video"


def test_atomic_video_motion_audit_is_not_applicable_without_quality_sidecar(tmp_path):
    video = tmp_path / "scene_1.mp4"
    video.write_bytes(b"video")

    report = AtomicVideoMotionAuditService().audit([_scene(1, video)])

    assert report.status == "not_applicable"
