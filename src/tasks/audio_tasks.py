"""Audio generation Celery tasks."""

import json
from pathlib import Path

from src.database.database import get_db
from src.database.models import Scene
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.repair_queue import attach_repair_queue
from src.services.subtitle_generator import get_subtitle_generator
from src.services.tts_service import get_tts_service
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_audio_path

logger = get_logger(__name__)


EMOTION_KEYWORDS = (
    ("angry", ("怒", "气", "恨", "滚", "骗", "背叛", "凭什么", "混蛋", "闭嘴")),
    ("sad", ("哭", "泪", "痛", "伤心", "失望", "离开", "不要走", "对不起")),
    ("fearful", ("怕", "别过来", "救命", "危险", "完了", "怎么办")),
    ("surprised", ("什么", "怎么会", "不可能", "竟然", "真的")),
    ("happy", ("开心", "太好了", "终于", "谢谢", "喜欢")),
)


def has_spoken_dialogue(text: str | None) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    return normalized not in {"无", "无对白", "none", "null", "n/a", "na", "-", "没有对白"}


def dialogue_audio_profile(text: str | None, repair_action: str | None = None) -> dict[str, object]:
    """Return TTS controls tuned for mobile short-drama dialogue delivery."""
    normalized = (text or "").strip()
    emotion = "neutral"
    reason = "default_dialogue"
    for candidate, keywords in EMOTION_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            emotion = candidate
            reason = f"keyword_{candidate}"
            break

    punctuation_count = sum(normalized.count(mark) for mark in "！？!?")
    short_line = 0 < len(normalized) <= 12
    long_line = len(normalized) >= 42
    speed = 1.0
    if punctuation_count >= 2 or short_line:
        speed = 0.92
    if long_line:
        speed = 1.08

    if repair_action == "refine_dialogue_audio_delivery":
        if emotion == "neutral":
            emotion = "angry" if any(term in normalized for term in ("为什么", "到底", "骗", "不许")) else "surprised"
            reason = "repair_forced_emotion"
        speed = min(1.12, max(0.88, speed))
        return {
            "emotion": emotion,
            "speed": speed,
            "profile": "short_drama_repair",
            "source": "tts",
            "reason": reason,
        }

    return {
        "emotion": emotion,
        "speed": speed,
        "profile": "short_drama_default",
        "source": "tts",
        "reason": reason,
    }


def dialogue_audio_quality_report(
    scene: Scene,
    text: str | None,
    duration: float | None,
    audio_path: str | None,
    profile: dict[str, object],
) -> dict[str, object]:
    low: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    if has_spoken_dialogue(text):
        if not audio_path:
            missing.append("dialogue_audio_present")
        elif not Path(str(audio_path)).is_file():
            missing.append("dialogue_audio_file")
        if not duration or duration <= 0:
            missing.append("audio_duration")
        else:
            char_count = max(1, len("".join((text or "").split())))
            chars_per_second = char_count / duration
            if chars_per_second < 1.2 or chars_per_second > 8.5:
                low["speech_pacing"] = {
                    "score": 2,
                    "evidence": f"dialogue audio speech_pacing out of range: {chars_per_second:.2f} chars/sec",
                    "scene_number": scene.scene_number,
                }
        if profile.get("emotion") == "neutral" and any(mark in (text or "") for mark in "！？!?"):
            low["tts_emotion_match"] = {
                "score": 2,
                "evidence": "dialogue audio tts_emotion_match is neutral on an emotional short-drama line",
                "scene_number": scene.scene_number,
            }
        if profile.get("source") == "draft_silent_fallback" or profile.get("is_draft") is True:
            low["voice_delivery"] = {
                "score": 0,
                "evidence": "dialogue audio is a silent draft fallback and cannot satisfy production voice delivery",
                "scene_number": scene.scene_number,
            }
    gate = {
        "status": "needs_review" if low or missing else "passed",
        "low": low,
        "missing": missing,
    }
    report = {
        "status": gate["status"],
        "stage": "audio",
        "scene": {"scene_number": scene.scene_number},
        "audio_path": audio_path,
        "duration": duration or 0.0,
        "audio_profile": profile,
        "dialogue_audio_quality_gate": gate,
    }
    return attach_repair_queue(report, "audio")


@celery_app.task(bind=True, name="generate_audio")
def generate_audio_task(
    self,
    scene_id: int,
    text: str,
    speaker: str,
    project_id: int,
    task_id: int,
    **kwargs,
):
    """Generate narration/dialogue audio for one scene."""
    logger.info("Start audio generation: scene_id={}, text_len={}", scene_id, len(text or ""))
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "audio_generation"})

    db = next(get_db())
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"Scene not found: {scene_id}")

        if not has_spoken_dialogue(text):
            scene.audio_path = None
            scene.audio_duration = 0.0
            db.commit()
            return {"scene_id": scene_id, "audio_path": None, "duration": 0.0, "status": "skipped"}

        audio_path = get_scene_audio_path(project_id, scene_id)
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "tts_generation"})
        profile = dialogue_audio_profile(text, kwargs.get("repair_action"))

        try:
            generated = get_tts_service().generate_speech(
                text=text,
                output_path=audio_path,
                speaker=speaker,
                emotion=kwargs.get("emotion", profile["emotion"]),
                speed=kwargs.get("speed", profile["speed"]),
            )
            if isinstance(generated, tuple):
                result_path, duration = generated
            else:
                result_path = generated
                duration = get_subtitle_generator()._get_audio_duration(result_path)
        except Exception as exc:
            if not draft_fallback_enabled():
                raise
            logger.warning("Real TTS failed; using draft silent audio: scene_id={}, error={}", scene_id, exc)
            result_path, duration = get_draft_media_service().generate_silent_audio(
                text=text,
                output_path=audio_path,
            )
            profile = {
                **profile,
                "source": "draft_silent_fallback",
                "is_draft": True,
                "fallback_error": str(exc),
            }

        if not duration or duration <= 0:
            duration = get_draft_media_service().estimate_dialogue_duration(text)

        scene.audio_path = result_path
        scene.audio_duration = duration
        scene.subtitle_path = None
        report = dialogue_audio_quality_report(scene, text, duration, result_path, profile)
        Path(result_path).with_suffix(".quality.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        db.commit()

        logger.info("Audio generation completed: scene_id={}, path={}, duration={}", scene_id, result_path, duration)
        return {
            "scene_id": scene_id,
            "audio_path": result_path,
            "duration": duration,
            "status": "completed",
            "audio_profile": profile,
            "quality_status": report["status"],
        }
    except Exception as exc:
        logger.error("Audio generation failed: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()
