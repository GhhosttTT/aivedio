"""Source-video localization pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from src.config import settings
from src.database.models import (
    LocalizationJob,
    LocalizationJobStatus,
    LocalizationStage,
    Project,
    SourceVideo,
)
from src.services.occlusion_removal import OcclusionRemovalService
from src.utils.logger import get_logger

logger = get_logger(__name__)


class LocalizationPipelineError(Exception):
    """Raised when source-video localization cannot proceed."""


class LocalizationPipeline:
    """Coordinates source-video localization jobs."""

    def __init__(self, db: Session):
        self.db = db
        self.storage_root = Path(settings.STORAGE_PATH)

    def save_source_video(self, project_id: int, upload: UploadFile) -> SourceVideo:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"project does not exist: {project_id}")

        filename = Path(upload.filename or "source.mp4").name
        if not filename.lower().endswith((".mp4", ".mov", ".mkv", ".avi")):
            raise ValueError("only .mp4, .mov, .mkv, and .avi video files are supported")

        video_dir = self.storage_root / f"project_{project_id}" / "source_videos"
        video_dir.mkdir(parents=True, exist_ok=True)

        output_path = video_dir / filename
        with output_path.open("wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)

        source_video = SourceVideo(
            project_id=project_id,
            original_filename=filename,
            file_path=str(output_path),
        )
        self.db.add(source_video)
        self.db.commit()
        self.db.refresh(source_video)

        logger.info("source video saved: project_id={}, source_video_id={}", project_id, source_video.id)
        return source_video

    def create_job(
        self,
        source_video_id: int,
        target_languages: Optional[Iterable[str]] = None,
    ) -> LocalizationJob:
        source_video = self.db.query(SourceVideo).filter(SourceVideo.id == source_video_id).first()
        if not source_video:
            raise ValueError(f"source video does not exist: {source_video_id}")

        languages = self.normalize_languages(target_languages)
        job = LocalizationJob(
            source_video_id=source_video_id,
            target_languages=json.dumps(languages, ensure_ascii=False),
            status=LocalizationJobStatus.QUEUED,
            current_stage=LocalizationStage.UPLOADED,
            progress=0.0,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        logger.info("localization job created: job_id={}, languages={}", job.id, languages)
        return job

    def normalize_languages(self, target_languages: Optional[Iterable[str]]) -> List[str]:
        configured = settings.LOCALIZATION_TARGET_LANGUAGES.split(",")
        languages = list(target_languages or configured)
        cleaned = []
        for language in languages:
            code = language.strip().lower()
            if code and code not in cleaned:
                cleaned.append(code)
        if not cleaned:
            raise ValueError("target languages cannot be empty")
        return cleaned

    def update_stage(
        self,
        job_id: int,
        stage: LocalizationStage,
        progress: float,
        status: LocalizationJobStatus = LocalizationJobStatus.RUNNING,
    ) -> LocalizationJob:
        job = self.get_job(job_id)
        job.current_stage = stage
        job.progress = max(0.0, min(progress, 100.0))
        job.status = status
        self.db.commit()
        self.db.refresh(job)
        return job

    def mark_failed(self, job_id: int, error_message: str) -> None:
        job = self.get_job(job_id)
        job.status = LocalizationJobStatus.FAILED
        job.error_message = error_message
        self.db.commit()

    def mark_needs_review(self, job_id: int, error_message: str) -> None:
        job = self.get_job(job_id)
        job.status = LocalizationJobStatus.NEEDS_REVIEW
        job.error_message = error_message
        self.db.commit()

    def get_job(self, job_id: int) -> LocalizationJob:
        job = self.db.query(LocalizationJob).filter(LocalizationJob.id == job_id).first()
        if not job:
            raise ValueError(f"localization job does not exist: {job_id}")
        return job

    def run_cleaning(self, job: LocalizationJob) -> str:
        source_video = job.source_video
        if not source_video:
            raise LocalizationPipelineError(f"source video missing for job: {job.id}")

        output_dir = (
            self.storage_root
            / f"project_{source_video.project_id}"
            / "localization"
            / f"job_{job.id}"
            / "cleaning"
        )
        cleaner = OcclusionRemovalService()
        result = cleaner.run(source_video.file_path, str(output_dir))

        source_video.clean_video_path = result.clean_video_path
        self.db.commit()
        return result.clean_video_path

    def run_asr(self, job: LocalizationJob) -> str:
        raise NotImplementedError(f"ASR backend is not implemented: {settings.ASR_BACKEND}")

    def run_translation(self, job: LocalizationJob) -> str:
        raise NotImplementedError(f"translation backend is not implemented: {settings.TRANSLATION_BACKEND}")

    def run_rendering(self, job: LocalizationJob) -> str:
        raise NotImplementedError("multilingual subtitle rendering is not implemented")

    def run_moderation(self, job: LocalizationJob) -> str:
        raise NotImplementedError(f"moderation backend is not implemented: {settings.MODERATION_BACKEND}")
