import json
from pathlib import Path

from src.services.asr_service import ASRSegment
from src.services.localization_quality_service import LocalizationQualityService
from src.services.localization_review import LocalizationReviewStore


def test_localization_review_is_invalidated_when_report_changes(tmp_path):
    report_path = tmp_path / "moderation_report.json"
    report = {"status": "passed", "score": 0.91}
    store = LocalizationReviewStore(report_path)
    decision = store.record("approved", "人工复核通过", report, user_id=3)

    assert store.apply(report)["decision"] == "approved"
    assert store.apply({**report, "score": 0.72})["decision"] == "stale"
    assert decision["report_signature"] != store.report_signature({**report, "score": 0.72})


def test_localization_review_keeps_decision_history(tmp_path):
    store = LocalizationReviewStore(tmp_path / "moderation_report.json")
    report = {"status": "needs_review", "score": 0.61}
    store.record("rejected", "字幕过长", report, user_id=3)
    store.record("approved", "修复后复核通过", report, user_id=4)

    history = store.history()
    assert [item["decision"] for item in history] == ["rejected", "approved"]
    assert history[-1]["reviewed_by"] == 4


def test_quality_service_flags_timestamp_and_reading_speed_issues(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    translated_dir = tmp_path / "translations"
    translated_dir.mkdir()
    report = tmp_path / "moderation_report.json"

    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "\u4e0a\u754c\u6765\u4eba\u4e86",
                        "source": "ocr_asr_fused",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (translated_dir / "en.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 0.2,
                        "end": 1.0,
                        "text": "A messenger from the celestial upper realm has arrived immediately.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (translated_dir / "story_context.json").write_text(
        json.dumps({"story_summary": "fantasy conflict"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.services.localization_quality_service.settings.TRANSLATION_BACKEND", "command")

    result = LocalizationQualityService().assess(
        transcript_path=str(transcript),
        translated_subtitle_dir=str(translated_dir),
        target_languages=["en"],
        output_path=str(report),
    )

    assert result.status == "needs_review"
    assert report.exists()
    categories = {issue.category for issue in result.issues}
    assert "timestamp_mismatch" in categories
    assert "reading_speed" in categories


def test_quality_service_passes_clean_subtitles(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    translated_dir = tmp_path / "translations"
    translated_dir.mkdir()
    report = tmp_path / "moderation_report.json"
    rendered_dir = tmp_path / "rendered"
    rendered_dir.mkdir()
    (rendered_dir / "en.mp4").write_bytes(b"rendered")

    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 0.0, "end": 2.0, "text": "\u4f60\u597d", "source": "ocr", "confidence": 0.9},
                    {"start": 2.2, "end": 4.2, "text": "\u6211\u4e0d\u4f1a\u59a5\u534f", "source": "ocr", "confidence": 0.92},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (translated_dir / "en.json").write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 0.0, "end": 2.0, "text": "Hello."},
                    {"start": 2.2, "end": 4.2, "text": "I will not compromise."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.services.localization_quality_service.settings.TRANSLATION_BACKEND", "command")
    monkeypatch.setattr(
        LocalizationQualityService,
        "_inspect_rendered_subtitles",
        lambda self, path, segments: {
            "status": "available",
            "sampled_cues": len(segments),
            "visible_ratio": 1.0,
            "score": 0.95,
            "issues": [],
        },
    )

    result = LocalizationQualityService().assess(
        transcript_path=str(transcript),
        translated_subtitle_dir=str(translated_dir),
        target_languages=["en"],
        output_path=str(report),
        rendered_video_dir=str(rendered_dir),
    )

    assert result.status == "passed"
    assert result.score >= 0.78
    assert result.target_summary["en"]["rendered_visual"]["score"] == 0.95


def test_quality_service_flags_many_ocr_asr_disagreements(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    translated_dir = tmp_path / "translations"
    translated_dir.mkdir()
    report = tmp_path / "moderation_report.json"

    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "\u4f60\u597d", "source": "ocr_asr_fused"},
                    {"start": 1.2, "end": 2.2, "text": "\u6211\u6765\u4e86", "source": "ocr_asr_fused"},
                    {"start": 2.4, "end": 3.4, "text": "\u8d70\u5427", "source": "ocr"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (translated_dir / "en.json").write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "Hello."},
                    {"start": 1.2, "end": 2.2, "text": "I'm here."},
                    {"start": 2.4, "end": 3.4, "text": "Let's go."},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.services.localization_quality_service.settings.TRANSLATION_BACKEND", "command")

    result = LocalizationQualityService().assess(
        transcript_path=str(transcript),
        translated_subtitle_dir=str(translated_dir),
        target_languages=["en"],
        output_path=str(report),
    )

    assert result.status == "needs_review"
    assert any(issue.category == "visual_audio_alignment" for issue in result.issues)


def test_rendered_subtitle_visual_audit_fails_closed_for_unreadable_video(tmp_path):
    report = LocalizationQualityService()._inspect_rendered_subtitles(
        tmp_path / "missing.mp4",
        [ASRSegment(start=0.0, end=1.0, text="Hello", source="translation")],
    )

    assert report["status"] == "unavailable"
    assert report["issues"] == []
