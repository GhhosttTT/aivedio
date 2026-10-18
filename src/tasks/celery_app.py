"""Celery application configuration."""

import os
import inspect
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv
from kombu import Exchange, Queue
from sqlalchemy import case
from src.services.comfyui_service import ComfyUIWaitTimeout
from src.services.generation_review import ReviewError
from src.services.image_postprocess import ImagePostprocessError
from src.services.generation_provider import GenerationCancelledError, GenerationProviderError

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"Celery loaded env file: {env_path}")
else:
    print(f"Celery env file not found: {env_path}")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "short_drama_production",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "src.tasks.image_tasks",
        "src.tasks.video_tasks",
        "src.tasks.audio_tasks",
        "src.tasks.subtitle_tasks",
        "src.tasks.composition_tasks",
        "src.tasks.localization_tasks",
        "src.tasks.review_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    result_expires=3600,
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_default_retry_delay=60,
    task_max_retries=3,
    task_soft_time_limit=3600,
    task_time_limit=3900,
    worker_prefetch_multiplier=1,
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "1")),
    worker_max_tasks_per_child=100,
    worker_disable_rate_limits=False,
    task_routes={
        "prepare_generation": {"queue": "image"},
        "generate_image": {"queue": "image"},
        # Keep video/API generation isolated from the image queue so worker
        # concurrency and provider rate limits can be tuned independently.
        "generate_video": {"queue": "video"},
        "review_generation": {"queue": "image"},
        "src.tasks.image_tasks.*": {"queue": "image"},
        "src.tasks.video_tasks.*": {"queue": "video"},
        "src.tasks.audio_tasks.*": {"queue": "audio"},
        "src.tasks.subtitle_tasks.*": {"queue": "default"},
        "src.tasks.composition_tasks.*": {"queue": "default"},
        "src.tasks.localization_tasks.*": {"queue": "localization"},
    },
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("image", Exchange("image"), routing_key="image"),
        Queue("video", Exchange("video"), routing_key="video"),
        Queue("audio", Exchange("audio"), routing_key="audio"),
        Queue("localization", Exchange("localization"), routing_key="localization"),
    ),
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    task_queue_max_priority=10,
    task_default_priority=5,
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
)


class BaseTask(celery_app.Task):
    """Common Celery task behavior."""

    autoretry_for = (Exception,)
    dont_autoretry_for = (
        ComfyUIWaitTimeout,
        ReviewError,
        ImagePostprocessError,
        GenerationProviderError,
        GenerationCancelledError,
        ValueError,
        TypeError,
        AttributeError,
    )
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    def _production_record(self, args, kwargs, db):
        if self.name not in {"prepare_generation", "generate_image", "generate_video", "generate_audio", "generate_subtitle", "review_generation", "compose_final_video", "finalize_draft_generation"}:
            return None
        from src.database.models import Task as TaskModel
        values = inspect.signature(self.run).bind(*args, **kwargs).arguments
        record_id = values.get("task_id")
        return db.query(TaskModel).filter(TaskModel.id == record_id).first() if record_id else None

    def before_start(self, task_id, args, kwargs):
        from celery.exceptions import Ignore
        from src.database.session import get_db_session
        from src.database.models import TaskStatus, ProjectStatus
        db = next(get_db_session())
        try:
            record = self._production_record(args, kwargs, db)
            if record and record.status == TaskStatus.PENDING:
                record.status = TaskStatus.RUNNING
                db.commit()
            if record and record.status == TaskStatus.RUNNING:
                from src.services.generation_review import write_report
                from src.utils.storage import storage_manager
                values = inspect.signature(self.run).bind(*args, **kwargs).arguments
                write_report(storage_manager.get_project_path(record.project_id) / "production_progress.json", {
                    "celery_task_id": record.celery_task_id, "stage": self.name,
                    "scene_id": values.get("scene_id"), "state": "running",
                })
            if record and record.status in {TaskStatus.CANCELLED, TaskStatus.FAILED}:
                if record.project.status == ProjectStatus.IN_PRODUCTION:
                    record.project.status = (
                        ProjectStatus.SCRIPT_GENERATED
                        if record.status == TaskStatus.CANCELLED
                        else ProjectStatus.FAILED
                    )
                    db.commit()
                raise Ignore()
        finally:
            db.close()

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        from src.database.session import get_db_session
        from src.database.models import TaskStatus, ProjectStatus
        db = next(get_db_session())
        try:
            record = self._production_record(args, kwargs, db)
            if record and record.status != TaskStatus.CANCELLED:
                record.status = TaskStatus.FAILED
                record.error_message = f"{self.name}: {exc}"
                record.project.status = ProjectStatus.FAILED
                db.commit()
        finally:
            db.close()
        print(f"Task failed: {task_id}")
        print(f"Exception: {exc}")
        print(f"Details: {einfo}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        print(f"Task retry: {task_id}")
        print(f"Exception: {exc}")
        print(f"Retries: {self.request.retries}")

    def on_success(self, retval, task_id, args, kwargs):
        from src.database.session import get_db_session
        from src.database.models import TaskStatus, ProjectStatus
        db = next(get_db_session())
        try:
            record = self._production_record(args, kwargs, db)
            if record and record.status == TaskStatus.CANCELLED:
                record.project.status = ProjectStatus.SCRIPT_GENERATED
                db.commit()
            elif record and record.status == TaskStatus.RUNNING:
                # Audio/subtitle groups finish concurrently; increment in the database.
                from src.database.models import Task as TaskModel
                next_step = case(
                    (TaskModel.current_step < TaskModel.total_steps, TaskModel.current_step + 1),
                    else_=TaskModel.total_steps,
                )
                task_query = db.query(TaskModel).filter(
                    TaskModel.id == record.id, TaskModel.status == TaskStatus.RUNNING,
                )
                task_query.update({
                    TaskModel.current_step: next_step,
                    TaskModel.progress: case(
                        (TaskModel.total_steps > 0, 100.0 * next_step / TaskModel.total_steps),
                        else_=100.0,
                    ),
                    TaskModel.status: case(
                        (next_step >= TaskModel.total_steps, TaskStatus.COMPLETED.name),
                        else_=TaskStatus.RUNNING.name,
                    ),
                }, synchronize_session=False)
                db.refresh(record)
                if record.status == TaskStatus.COMPLETED and record.project.status == ProjectStatus.IN_PRODUCTION and not record.project.final_video_path:
                    record.project.status = ProjectStatus.SCRIPT_GENERATED
                db.commit()
        finally:
            db.close()
        print(f"Task succeeded: {task_id}")


celery_app.Task = BaseTask

__all__ = ["celery_app"]
