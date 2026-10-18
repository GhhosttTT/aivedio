from types import SimpleNamespace

from src.services.dialogue_delivery_audit import DialogueDeliveryAuditService


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

    report = DialogueDeliveryAuditService().audit([_scene(1, audio_path=audio, subtitle_path=subtitle)])

    assert report.status == "passed"
    assert report.cues_count == 1
    assert report.to_dict()["repair_queue"] == []


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


def test_dialogue_delivery_audit_ignores_unrendered_dialogue_scenes(tmp_path):
    scenes = [_scene(1), _scene(2, dialogue="")]

    report = DialogueDeliveryAuditService().audit(scenes)

    assert report.status == "not_applicable"
    assert report.dialogue_scene_count == 1
