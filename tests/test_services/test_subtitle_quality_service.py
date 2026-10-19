from src.services.subtitle_quality_service import assess_subtitle_timeline


def test_assess_subtitle_timeline_passes_matching_non_overlapping_dialogue():
    report = assess_subtitle_timeline(
        "1\n00:00:00,000 --> 00:00:02,000\n你为什么骗我？\n",
        "你为什么骗我？",
    )

    assert report["status"] == "passed"
    assert report["entry_count"] == 1
    assert report["entries"][0]["reading_speed"]["kind"] == "cjk"


def test_assess_subtitle_timeline_flags_overlap_and_text_coverage():
    report = assess_subtitle_timeline(
        "1\n00:00:00,000 --> 00:00:02,000\n你来了\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n别走\n",
        "你为什么骗我",
    )

    assert report["status"] == "needs_review"
    assert {issue["code"] for issue in report["issues"]} >= {"overlap", "text_coverage"}


def test_assess_subtitle_timeline_flags_fast_reading_speed():
    report = assess_subtitle_timeline(
        "1\n00:00:00,000 --> 00:00:00,500\n这是一个很长很长很长很长很长的对白\n"
    )

    assert report["status"] == "needs_review"
    assert any(issue["code"] == "reading_speed" for issue in report["issues"])


def test_assess_subtitle_timeline_rejects_out_of_range_timecode_fields():
    report = assess_subtitle_timeline(
        "1\n00:61:00,000 --> 00:61:02,000\n对白\n"
    )

    assert report["status"] == "needs_review"
    assert any(issue["code"] == "invalid_timing" for issue in report["issues"])
