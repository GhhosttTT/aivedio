from unittest.mock import Mock

from src.tasks.audio_tasks import dialogue_audio_profile, dialogue_audio_quality_report


def test_dialogue_audio_profile_detects_short_drama_emotion_and_pacing():
    profile = dialogue_audio_profile("你为什么骗我？！", "refine_dialogue_audio_delivery")

    assert profile["emotion"] == "angry"
    assert profile["speed"] < 1.0
    assert profile["profile"] == "short_drama_repair"


def test_dialogue_audio_profile_forces_non_neutral_emotion_on_repair():
    profile = dialogue_audio_profile("到底发生了什么", "refine_dialogue_audio_delivery")

    assert profile["emotion"] != "neutral"
    assert profile["profile"] == "short_drama_repair"


def test_dialogue_audio_quality_report_creates_audio_repair_queue_for_bad_pacing():
    scene = Mock(scene_number=6)
    report = dialogue_audio_quality_report(
        scene,
        "这是一句非常长非常长非常长非常长非常长非常长的对白",
        duration=1.0,
        audio_path="scene_006.mp3",
        profile={"emotion": "neutral", "speed": 1.0},
    )

    assert report["status"] == "needs_review"
    assert report["dialogue_audio_quality_gate"]["low"]["speech_pacing"]["score"] == 2
    assert report["repair_queue"][0]["action"] == "refine_dialogue_audio_delivery"
    assert report["repair_queue"][0]["execution"] == "auto"
