import json
from unittest.mock import Mock

from src.tasks import audio_tasks
from src.tasks.audio_tasks import dialogue_audio_profile, dialogue_audio_quality_report
from src.utils.media_quality_paths import audio_quality_report_path


def test_dialogue_audio_profile_detects_short_drama_emotion_and_pacing():
    profile = dialogue_audio_profile("你为什么骗我？！", "refine_dialogue_audio_delivery")

    assert profile["emotion"] == "angry"
    assert profile["speed"] < 1.0
    assert profile["profile"] == "short_drama_repair"
    assert profile["source"] == "tts"


def test_dialogue_audio_profile_forces_non_neutral_emotion_on_repair():
    profile = dialogue_audio_profile("到底发生了什么", "refine_dialogue_audio_delivery")

    assert profile["emotion"] != "neutral"
    assert profile["profile"] == "short_drama_repair"


def test_dialogue_audio_profile_uses_character_personality_when_line_is_neutral():
    profile = dialogue_audio_profile("好的，我知道了。", personality="外冷内热、克制、沉稳")

    assert profile["emotion"] == "neutral"
    assert profile["personality_influence"] == "restrained_pacing"
    assert profile["speed"] == 0.92  # short lines keep the existing mobile pacing guard


def test_dialogue_audio_profile_lets_line_emotion_override_personality():
    profile = dialogue_audio_profile("你竟然骗我！", personality="温柔、乐观")

    assert profile["emotion"] == "angry"
    assert profile["reason"] == "keyword_angry"


def test_dialogue_audio_quality_report_creates_audio_repair_queue_for_bad_pacing(tmp_path):
    audio = tmp_path / "scene_006.mp3"
    audio.write_bytes(b"fake audio")
    scene = Mock(scene_number=6)
    report = dialogue_audio_quality_report(
        scene,
        "这是一句非常长非常长非常长非常长非常长非常长的对白",
        duration=1.0,
        audio_path=str(audio),
        profile={"emotion": "neutral", "speed": 1.0, "source": "tts"},
        speaker="hero",
    )

    assert report["status"] == "needs_review"
    assert report["dialogue_audio_quality_gate"]["low"]["speech_pacing"]["score"] == 2
    assert report["repair_queue"][0]["action"] == "refine_dialogue_audio_delivery"
    assert report["repair_queue"][0]["execution"] == "auto"
    assert report["speaker"] == "hero"
    assert report["voice_identity"]["binding"] == "scene_character_name"


def test_dialogue_audio_quality_report_requires_existing_audio_file():
    scene = Mock(scene_number=7)
    report = dialogue_audio_quality_report(
        scene,
        "你到底瞒了我多久",
        duration=3.0,
        audio_path="missing_scene_007.mp3",
        profile={"emotion": "angry", "speed": 1.0, "source": "tts"},
    )

    assert report["status"] == "needs_review"
    assert "dialogue_audio_file" in report["dialogue_audio_quality_gate"]["missing"]
    assert report["repair_queue"][0]["action"] == "refine_dialogue_audio_delivery"


def test_dialogue_audio_quality_report_blocks_draft_silent_fallback(tmp_path):
    audio = tmp_path / "scene_008.mp3"
    audio.write_bytes(b"silent draft audio")
    scene = Mock(scene_number=8)
    report = dialogue_audio_quality_report(
        scene,
        "你为什么骗我",
        duration=3.0,
        audio_path=str(audio),
        profile={"emotion": "angry", "speed": 1.0, "source": "draft_silent_fallback", "is_draft": True},
    )

    gate = report["dialogue_audio_quality_gate"]
    assert report["status"] == "needs_review"
    assert gate["low"]["voice_delivery"]["score"] == 0
    assert report["repair_queue"][0]["action"] == "refine_dialogue_audio_delivery"


def test_dialogue_audio_quality_report_blocks_near_silent_signal(tmp_path, monkeypatch):
    audio = tmp_path / "scene_009.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(audio_tasks, "_audio_signal_metrics", lambda *_args: {
        "audio_signal_status": "near_silent",
        "audio_silence_ratio": 1.0,
    })
    report = dialogue_audio_quality_report(
        Mock(scene_number=9),
        "你为什么骗我",
        duration=1.0,
        audio_path=str(audio),
        profile={"emotion": "angry", "speed": 1.0, "source": "tts"},
    )

    assert report["status"] == "needs_review"
    assert report["dialogue_audio_quality_gate"]["low"]["audio_signal"]["score"] == 0


def test_dialogue_audio_quality_report_accepts_measurable_signal(tmp_path, monkeypatch):
    audio = tmp_path / "scene_010.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(audio_tasks, "_audio_signal_metrics", lambda *_args: {
        "audio_signal_status": "usable",
        "audio_silence_ratio": 0.1,
    })
    report = dialogue_audio_quality_report(
        Mock(scene_number=10),
        "你好",
        duration=1.0,
        audio_path=str(audio),
        profile={"emotion": "neutral", "speed": 1.0, "source": "tts"},
    )

    assert report["status"] == "passed"
    assert report["audio_signal"]["audio_signal_status"] == "usable"


def test_dialogue_audio_quality_report_rejects_clipped_signal(tmp_path, monkeypatch):
    audio = tmp_path / "scene_010_clip.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(audio_tasks, "_audio_signal_metrics", lambda *_args: {
        "audio_signal_status": "usable",
        "audio_peak_db": 0.0,
        "audio_clipping_status": "clipped",
    })
    report = dialogue_audio_quality_report(
        Mock(scene_number=10),
        "你好",
        duration=1.0,
        audio_path=str(audio),
        profile={"emotion": "neutral", "speed": 1.0, "source": "tts"},
    )

    assert report["status"] == "needs_review"
    assert report["dialogue_audio_quality_gate"]["low"]["audio_clipping"]["score"] == 0


def test_dialogue_audio_quality_report_keeps_reported_and_measured_duration(tmp_path, monkeypatch):
    audio = tmp_path / "scene_011.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(audio_tasks, "_audio_signal_metrics", lambda *_args: {
        "audio_signal_status": "usable",
    })
    report = dialogue_audio_quality_report(
        Mock(scene_number=11),
        "你好啊",
        duration=1.0,
        audio_path=str(audio),
        profile={"emotion": "neutral", "speed": 1.0, "source": "tts"},
        measured_duration=1.5,
        reported_duration=1.0,
    )

    assert report["status"] == "passed"
    assert report["duration"] == 1.5
    assert report["duration_reported"] == 1.0
    assert report["duration_measured"] == 1.5


def test_generate_audio_task_marks_draft_fallback_audio_for_repair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_DRAFT_MEDIA_FALLBACK", "true")
    monkeypatch.setattr(audio_tasks, "get_tts_service", lambda: (_ for _ in ()).throw(RuntimeError("tts unavailable")))

    class FakeDraftMediaService:
        def generate_silent_audio(self, text: str, output_path: str):
            path = tmp_path / output_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"silent draft audio")
            return str(path), 3.0

        def estimate_dialogue_duration(self, text: str) -> float:
            return 3.0

    monkeypatch.setattr(audio_tasks, "get_draft_media_service", lambda: FakeDraftMediaService())

    scene = Mock(id=8, project_id=3, scene_number=8, audio_path=None, audio_duration=None, subtitle_path="old.srt")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = scene

    def fake_get_db():
        yield db

    monkeypatch.setattr(audio_tasks, "get_db", fake_get_db)
    monkeypatch.setattr(audio_tasks.generate_audio_task, "update_state", Mock())

    result = audio_tasks.generate_audio_task.run(8, "你为什么骗我", "hero", 3, 4)
    report = audio_quality_report_path(tmp_path / result["audio_path"])
    quality = json.loads(report.read_text(encoding="utf-8"))

    assert result["quality_status"] == "needs_review"
    assert result["audio_profile"]["source"] == "draft_silent_fallback"
    assert quality["dialogue_audio_quality_gate"]["low"]["voice_delivery"]["score"] == 0
    db.commit.assert_called_once()
