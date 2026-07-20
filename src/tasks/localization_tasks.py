"""Celery tasks for source-video localization."""

from src.database.database import get_db
from src.database.models import LocalizationJobStatus, LocalizationStage
from src.services.localization_pipeline import LocalizationPipeline
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="run_localization_job")
def run_localization_job_task(self, job_id: int):
    """Run the source-video localization pipeline.

    The task currently exposes the stage skeleton and fails clearly until model
    backends are configured and implemented.
    """
    db = next(get_db())
    pipeline = LocalizationPipeline(db)

    try:
        job = pipeline.get_job(job_id)
        job.celery_task_id = self.request.id
        db.commit()

        self.update_state(state="PROGRESS", meta={"stage": "cleaning", "progress": 10})
        pipeline.update_stage(job_id, LocalizationStage.CLEANING, 10)
        pipeline.run_cleaning(job)

        self.update_state(state="PROGRESS", meta={"stage": "asr", "progress": 30})
        pipeline.update_stage(job_id, LocalizationStage.ASR, 30)
        pipeline.run_asr(job)

        self.update_state(state="PROGRESS", meta={"stage": "translation", "progress": 55})
        pipeline.update_stage(job_id, LocalizationStage.TRANSLATION, 55)
        pipeline.run_translation(job)

        self.update_state(state="PROGRESS", meta={"stage": "rendering", "progress": 80})
        pipeline.update_stage(job_id, LocalizationStage.RENDERING, 80)
        pipeline.run_rendering(job)

        self.update_state(state="PROGRESS", meta={"stage": "moderation", "progress": 95})
        pipeline.update_stage(job_id, LocalizationStage.MODERATION, 95)
        pipeline.run_moderation(job)

        pipeline.update_stage(
            job_id,
            LocalizationStage.COMPLETED,
            100,
            status=LocalizationJobStatus.COMPLETED,
        )
        return {"job_id": job_id, "status": "completed"}

    except Exception as exc:
        logger.error("出海译制任务失败: job_id={}, error={}", job_id, exc)
        pipeline.mark_failed(job_id, str(exc))
        raise
