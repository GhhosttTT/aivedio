from types import SimpleNamespace
import json
import hashlib

from src.services.dialogue_delivery_audit import DialogueDeliveryAuditService
from src.utils.media_quality_paths import audio_quality_report_path, subtitle_quality_report_path


def _scene(number, dialogue="你到底是谁？", audio_path=None, subtitle_path=None, duration=2.0):
    return SimpleNamespace(
        scene_number=number,
        dialogue=dialogue,
        audio_path=str(audio_path) if audio_path else None,
        subtitle_path=str(subtitle_path) if subtitle_path else None,
        audio_duration=duration,
    )


def test_dialogue_delivery_audit_accepts_complete_non_overlapping_assets(tmp_path):
    audio = tmp_path / "scene.wav"
    subtitle = tmp_path / "scene.srt"
    audio.write_bytes(b"audio")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n你到底是谁？\n", encoding="utf-8")
    audio_report = {
        "voice_identity": {"requested_speaker": "default", "voice_id": "voice-a"},
        "dialogue_audio_quality_gate": {"status": "passed", "low": {}, "missing": []},
        "dialogue_fingerprint": hashlib.sha256("你到底是谁？".encode("utf-8")).hexdigest(),
        "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "audio_signal": {"audio_signal_status": "usable"},
        "duration_measured": 2.0,
    }
    audio_quality_report_path(audio).write_text(json.dumps(audio_report), encoding="utf-8")
    subtitle_quality_report_path(subtitle).write_text(json.dumps({
        "status": "passed",
        "expected_text": "你到底是谁？",
        "subtitle_sha256": hashlib.sha256(subtitle.read_bytes()).hexdigest(),
    }), encoding="utf-8")

    report = DialogueDeliveryAuditService().audit([_scene(1, audio_path=audio, subtitle_path=subtitle)])

    assert report.status == "passed"
    assert report.cues_count == 1
    assert report.to_dict()["repair_queue"] == []


def test_dialogue_delivery_audit_rejects_stale_audio_and_subtitle_evidence(tmp_path):
    audio = tmp_path / "scene.wav"
    subtitle = tmp_path / "scene.srt"
    audio.write_bytes(b"new audio")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n你到底是谁？\n", encoding="utf-8")
    audio_quality_report_path(audio).write_text(json.dumps({
        "voice_identity": {"requested_speaker": "default", "voice_id": "voice-a"},
        "dialogue_audio_quality_gate": {"status": "passed"},
        "dialogue_fingerprint": "stale",
        "audio_sha256": "stale",
        "audio_signal": {"audio_signal_status": "near_silent"},
        "duration_measured": 2.0,
    }), encoding="utf-8")
    subtitle_quality_report_path(subtitle).write_text(json.dumps({
        "status": "passed",
        "expected_text": "旧对白",
        "subtitle_sha256": "stale",
    }), encoding="utf-8")

    report = DialogueDeliveryAuditService().audit([_scene(1, audio_path=audio, subtitle_path=subtitle)])

    codes = {issue["code"] for issue in report.issues}
    assert {"stale_dialogue_audio_evidence", "stale_dialogue_audio_file_evidence", "unusable_dialogue_audio_signal"} <= codes
    assert {"stale_subtitle_dialogue_evidence", "stale_subtitle_file_evidence"} <= codes


def test_dialogue_delivery_audit_flags_missing_audio_and_subtitle_overrun(tmp_path):
    subtitle = tmp_path / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:03,000\n超出音频\n", encoding="utf-8")

    report = DialogueDeliveryAuditService().audit([_scene(1, subtitle_path=subtitle, duration=2.0)])

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} >= {
        "missing_dialogue_audio",
        "subtitle_past_audio",
    }
    assert report.to_dict()["repair_queue"][0]["action"] == "refine_dialogue_audio_delivery"


def test_dialogue_delivery_audit_requires_voice_identity_evidence(tmp_path):
    audio = tmp_path / "scene.wav"
    subtitle = tmp_path / "scene.srt"
    audio.write_bytes(b"audio")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n台词\n", encoding="utf-8")

    report = DialogueDeliveryAuditService().audit([
        _scene(1, audio_path=audio, subtitle_path=subtitle),
    ])

    assert report.status == "needs_review"
    assert any(issue["code"] == "missing_voice_identity_evidence" for issue in report.issues)


def test_dialogue_delivery_audit_ignores_unrendered_dialogue_scenes(tmp_path):
    scenes = [_scene(1), _scene(2, dialogue="")]

    report = DialogueDeliveryAuditService().audit(scenes)

    assert report.status == "not_applicable"
    assert report.dialogue_scene_count == 1


def test_dialogue_delivery_audit_flags_inconsistent_voice_identity(tmp_path):
    subtitle_one = tmp_path / "scene_001.srt"
    subtitle_two = tmp_path / "scene_002.srt"
    audio_one = tmp_path / "scene_001.wav"
    audio_two = tmp_path / "scene_002.wav"
    for audio in (audio_one, audio_two):
        audio.write_bytes(b"audio")
    for subtitle in (subtitle_one, subtitle_two):
        subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n台词\n", encoding="utf-8")
    audio_one.with_suffix(".quality.json").write_text(json.dumps({
        "voice_identity": {
            "requested_speaker": "林安",
            "voice_id": "voice-a",
        },
    }), encoding="utf-8")
    audio_two.with_suffix(".quality.json").write_text(json.dumps({
        "voice_identity": {
            "requested_speaker": "林安",
            "voice_id": "voice-b",
        },
    }), encoding="utf-8")

    report = DialogueDeliveryAuditService().audit([
        _scene(1, audio_path=audio_one, subtitle_path=subtitle_one),
        _scene(2, audio_path=audio_two, subtitle_path=subtitle_two),
    ])

    assert report.status == "needs_review"
    assert any(issue["code"] == "inconsistent_voice_identity" for issue in report.issues)


def test_dialogue_delivery_audit_rejects_out_of_range_subtitle_timecodes(tmp_path):
    subtitle = tmp_path / "scene.srt"
    subtitle.write_text("1\n00:61:00,000 --> 00:61:01,000\n对白\n", encoding="utf-8")

    report = DialogueDeliveryAuditService().audit([
        _scene(1, audio_path=None, subtitle_path=subtitle),
    ])

    assert report.status == "needs_review"
    assert any(issue["code"] == "empty_subtitles" for issue in report.issues)
