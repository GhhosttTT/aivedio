"""Celery tasks for source-video localization."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict

from src.database.database import get_db
from src.database.models import LocalizationJobStatus, LocalizationStage
from src.services.localization_pipeline import LocalizationPipeline
from src.services.occlusion_removal import OcclusionRemovalError
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _run_job_branch(job_id: int, branch: str, runner: Callable[[LocalizationPipeline, int], str]) -> str:
    """Run one localization preprocessing branch with an isolated DB session."""
    db = next(get_db())
    pipeline = LocalizationPipeline(db)
    try:
        logger.info("localization branch started: job_id={}, branch={}", job_id, branch)
        result = runner(pipeline, job_id)
        logger.info("localization branch completed: job_id={}, branch={}", job_id, branch)
        return result
    finally:
        db.close()


def _run_visual_branch(pipeline: LocalizationPipeline, job_id: int) -> str:
    job = pipeline.get_job(job_id)
    return pipeline.run_cleaning(job)


def _run_audio_branch(pipeline: LocalizationPipeline, job_id: int) -> str:
    job = pipeline.get_job(job_id)
    return pipeline.run_asr(job)


def run_parallel_preprocessing(job_id: int) -> Dict[str, str]:
    """Run visual cleanup and audio transcription at the same time.

    Visual branch:
        source video -> mask detection -> inpainting -> clean master video.
    Audio branch:
        source video audio -> ASR -> timed Chinese transcript/subtitles.
    """
    branches = {
        "visual_cleaning": _run_visual_branch,
        "audio_asr": _run_audio_branch,
    }
    results: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="localization-preprocess") as executor:
        future_to_branch = {
            executor.submit(_run_job_branch, job_id, branch, runner): branch
            for branch, runner in branches.items()
        }
        for future in as_completed(future_to_branch):
            branch = future_to_branch[future]
            results[branch] = future.result()

    return results


@celery_app.task(bind=True, name="run_localization_job")
def run_localization_job_task(self, job_id: int):
    """Run the source-video localization pipeline."""
    db = next(get_db())
    pipeline = LocalizationPipeline(db)

    try:
        job = pipeline.get_job(job_id)
        job.celery_task_id = self.request.id
        db.commit()

        self.update_state(state="PROGRESS", meta={"stage": "preprocessing", "progress": 10})
        pipeline.update_stage(job_id, LocalizationStage.PREPROCESSING, 10)
        preprocess_results = run_parallel_preprocessing(job_id)

        self.update_state(
            state="PROGRESS",
            meta={
                "stage": "translation",
                "progress": 55,
                "preprocessing": preprocess_results,
            },
        )
        pipeline.update_stage(job_id, LocalizationStage.TRANSLATION, 55)
        pipeline.run_translation(pipeline.get_job(job_id))

        self.update_state(state="PROGRESS", meta={"stage": "rendering", "progress": 80})
        pipeline.update_stage(job_id, LocalizationStage.RENDERING, 80)
        pipeline.run_rendering(pipeline.get_job(job_id))

        self.update_state(state="PROGRESS", meta={"stage": "moderation", "progress": 95})
        pipeline.update_stage(job_id, LocalizationStage.MODERATION, 95)
        pipeline.run_moderation(pipeline.get_job(job_id))

        pipeline.update_stage(
            job_id,
            LocalizationStage.COMPLETED,
            100,
            status=LocalizationJobStatus.COMPLETED,
        )
        return {
            "job_id": job_id,
            "status": "completed",
            "preprocessing": preprocess_results,
        }

    except OcclusionRemovalError as exc:
        logger.warning("localization visual cleanup needs review: job_id={}, error={}", job_id, exc)
        pipeline.mark_needs_review(job_id, str(exc))
        raise
    except Exception as exc:
        logger.error("localization job failed: job_id={}, error={}", job_id, exc)
        pipeline.mark_failed(job_id, str(exc))
        raise
    finally:
        db.close()
