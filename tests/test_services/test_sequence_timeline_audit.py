from src.services.sequence_timeline_audit import SequenceTimelineAuditService


def _planned(scene_number, duration, start=0.0):
    return {
        "scene_number": scene_number,
        "start_seconds": start,
        "end_seconds": start + duration,
        "duration_seconds": duration,
    }


def test_sequence_timeline_audit_accepts_segment_durations_within_tolerance():
    report = SequenceTimelineAuditService().audit(
        [_planned(1, 2.0), _planned(2, 3.0, 2.0)],
        [{"scene_number": 1, "duration_seconds": 2.08}, {"scene_number": 2, "duration_seconds": 2.9}],
    )

    assert report.status == "passed"
    assert report.issues == []


def test_sequence_timeline_audit_flags_duration_drift_and_count_mismatch():
    report = SequenceTimelineAuditService().audit(
        [_planned(1, 2.0), _planned(2, 3.0, 2.0)],
        [{"scene_number": 1, "duration_seconds": 2.8}],
    )

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} >= {
        "segment_count_mismatch", "segment_duration_drift", "segment_duration_unavailable",
    }
    assert report.to_dict()["repair_queue"][0]["action"] == "fix_video_output_contract"


def test_sequence_timeline_audit_is_not_applicable_without_segments():
    report = SequenceTimelineAuditService().audit([], [])

    assert report.status == "not_applicable"
