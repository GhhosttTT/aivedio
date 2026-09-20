"""Audio generation Celery tasks."""

from src.database.database import get_db
from src.database.models import Scene
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.subtitle_generator import get_subtitle_generator
from src.services.tts_service import get_tts_service
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_audio_path

logger = get_logger(__name__)


def has_spoken_dialogue(text: str | None) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    return normalized not in {"无", "无对白", "none", "null", "n/a", "na", "-", "没有对白"}


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

        try:
            generated = get_tts_service().generate_speech(
                text=text,
                output_path=audio_path,
                speaker=speaker,
                emotion=kwargs.get("emotion", "neutral"),
                speed=kwargs.get("speed", 1.0),
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

        if not duration or duration <= 0:
            duration = get_draft_media_service().estimate_dialogue_duration(text)

        scene.audio_path = result_path
        scene.audio_duration = duration
        db.commit()

        logger.info("Audio generation completed: scene_id={}, path={}, duration={}", scene_id, result_path, duration)
        return {"scene_id": scene_id, "audio_path": result_path, "duration": duration, "status": "completed"}
    except Exception as exc:
        logger.error("Audio generation failed: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()
