"""Video generation Celery tasks."""

from src.database.database import get_db
from src.database.models import Scene
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.svd_service import get_svd_service
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_video_path

logger = get_logger(__name__)


@celery_app.task(bind=True, name="generate_video")
def generate_video_task(
    self,
    scene_id: int,
    project_id: int,
    task_id: int,
    **kwargs,
):
    """Generate a video clip for one scene."""
    logger.info("Start video generation: scene_id={}", scene_id)
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "video_generation"})

    db = next(get_db())
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"Scene not found: {scene_id}")
        if not scene.image_path:
            raise ValueError(f"Scene image is missing: {scene_id}")

        video_path = get_scene_video_path(project_id, scene_id)
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "svd_generation"})

        try:
            from src.services.comfyui_service import get_comfyui_service
            get_comfyui_service().free_memory()
            svd_service = get_svd_service()
            result_path = svd_service.generate_video(
                image_path=scene.image_path,
                output_path=video_path,
                num_frames=kwargs.get("num_frames", 16),
                fps=kwargs.get("fps", 8),
                motion_bucket_id=kwargs.get("motion_bucket_id", 127),
                noise_aug_strength=kwargs.get("noise_aug_strength", 0.02),
            )
        except Exception as exc:
            if not draft_fallback_enabled():
                raise
            duration = get_draft_media_service().estimate_dialogue_duration(scene.dialogue or "")
            logger.warning(
                "Real video generation failed; using draft still-video fallback: scene_id={}, duration={}, error={}",
                scene_id,
                duration,
                exc,
            )
            result_path = get_draft_media_service().generate_video_from_image(
                image_path=scene.image_path,
                output_path=video_path,
                duration=duration,
                fps=kwargs.get("fps", 24),
            )

        scene.video_path = result_path
        db.commit()

        logger.info("Video generation completed: scene_id={}, path={}", scene_id, result_path)
        return {"scene_id": scene_id, "video_path": result_path, "status": "completed"}
    except Exception as exc:
        logger.error("Video generation failed: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()
