import json
from types import SimpleNamespace

from src.services.first_frame_consistency_audit import FirstFrameConsistencyAuditService


def _scene(number, video_path):
    return SimpleNamespace(scene_number=number, video_path=str(video_path), image_path=f"keyframe-{number}.png")


def _write_sidecar(video, reference):
    video.write_bytes(b"video")
    video.with_suffix(".quality.json").write_text(json.dumps({"metrics": {"start_frame_reference": reference}}), encoding="utf-8")


def test_first_frame_audit_accepts_reference_backed_clips(tmp_path):
    video = tmp_path / "scene_1.mp4"
    _write_sidecar(video, {"status": "available", "score": 4.1, "brightness_delta": 0.02})

    report = FirstFrameConsistencyAuditService().audit([_scene(1, video)])

    assert report.status == "passed"
    assert report.checked_scene_count == 1
    assert report.issues == []


def test_first_frame_audit_flags_drift_and_missing_evidence(tmp_path):
    drift = tmp_path / "scene_1.mp4"
    missing = tmp_path / "scene_2.mp4"
    _write_sidecar(drift, {"status": "available", "score": 1.9})
    _write_sidecar(missing, {"status": "unavailable", "error": "unreadable"})

    report = FirstFrameConsistencyAuditService().audit([_scene(1, drift), _scene(2, missing)])

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} == {"opening_frame_drift", "reference_evidence_unavailable"}


def test_first_frame_audit_ignores_clips_without_quality_evidence(tmp_path):
    video = tmp_path / "scene_1.mp4"
    video.write_bytes(b"video")

    report = FirstFrameConsistencyAuditService().audit([_scene(1, video)])

    assert report.status == "not_applicable"


def test_first_frame_audit_reads_final_review_technical_evidence(tmp_path):
    video = tmp_path / "scene_1.mp4"
    video.write_bytes(b"video")
    video.with_suffix(".quality.json").write_text(
        json.dumps({
            "final_video_review": {
                "path": str(video),
                "technical_metrics": {
                    "start_frame_reference": {"status": "available", "score": 1.8},
                },
            },
        }),
        encoding="utf-8",
    )

    report = FirstFrameConsistencyAuditService().audit([_scene(1, video)])

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "opening_frame_drift"


def test_first_frame_audit_reads_matching_candidate_technical_evidence(tmp_path):
    video = tmp_path / "scene_1.mp4"
    video.write_bytes(b"video")
    video.with_suffix(".quality.json").write_text(
        json.dumps({
            "candidates": [
                {
                    "path": str(tmp_path / "other.mp4"),
                    "technical_metrics": {
                        "start_frame_reference": {"status": "available", "score": 1.5},
                    },
                },
                {
                    "path": str(video),
                    "technical_metrics": {
                        "start_frame_reference": {"status": "available", "score": 4.0},
                    },
                },
            ],
        }),
        encoding="utf-8",
    )

    report = FirstFrameConsistencyAuditService().audit([_scene(1, video)])

    assert report.status == "passed"
    assert report.scenes[0]["score"] == 4.0


def test_first_frame_audit_blocks_partial_reference_evidence(tmp_path):
    valid = tmp_path / "scene_1.mp4"
    missing = tmp_path / "scene_2.mp4"
    _write_sidecar(valid, {"status": "available", "score": 4.0})
    missing.write_bytes(b"video")

    report = FirstFrameConsistencyAuditService().audit([
        _scene(1, valid),
        _scene(2, missing),
    ])

    assert report.status == "needs_review"
    assert report.checked_scene_count == 2
    assert report.issues[0]["code"] == "missing_reference_evidence"


def test_boundary_audit_reports_end_frame_and_cross_shot_continuity_drift(tmp_path):
    video = tmp_path / "scene_1.mp4"
    video.write_bytes(b"video")
    video.with_suffix(".quality.json").write_text(
        json.dumps({
            "metrics": {
                "start_frame_reference": {"status": "available", "score": 4.0},
                "end_frame_reference": {"status": "available", "score": 1.8},
                "continuity_reference": {"status": "available", "score": 1.2},
            },
        }),
        encoding="utf-8",
    )

    report = FirstFrameConsistencyAuditService().audit([_scene(1, video)])

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} == {
        "ending_frame_drift",
        "continuity_reference_drift",
    }
    assert report.scenes[0]["end_frame_reference"]["score"] == 1.8
    assert report.scenes[0]["continuity_reference"]["score"] == 1.2
