"""API routes for source-video export localization."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.models import LocalizationJob, SourceVideo
from src.database.session import get_db_session
from src.services.localization_pipeline import LocalizationPipeline
from src.tasks.localization_tasks import run_localization_job_task
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/localization", tags=["源片出海译制"])


class SourceVideoResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    project_id: int
    original_filename: str
    file_path: str
    clean_video_path: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: datetime


class CreateLocalizationJobRequest(BaseModel):
    source_video_id: int = Field(..., ge=1)
    target_languages: Optional[List[str]] = None
    auto_start: bool = True


class LocalizationJobResponse(BaseModel):
    id: int
    source_video_id: int
    celery_task_id: Optional[str] = None
    target_languages: List[str]
    status: str
    current_stage: str
    progress: float
    transcript_path: Optional[str] = None
    translated_subtitle_dir: Optional[str] = None
    rendered_video_dir: Optional[str] = None
    moderation_report_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


def _job_response(job: LocalizationJob) -> LocalizationJobResponse:
    try:
        languages = json.loads(job.target_languages)
    except Exception:
        languages = []
    return LocalizationJobResponse(
        id=job.id,
        source_video_id=job.source_video_id,
        celery_task_id=job.celery_task_id,
        target_languages=languages,
        status=job.status.value,
        current_stage=job.current_stage.value,
        progress=job.progress,
        transcript_path=job.transcript_path,
        translated_subtitle_dir=job.translated_subtitle_dir,
        rendered_video_dir=job.rendered_video_dir,
        moderation_report_path=job.moderation_report_path,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post(
    "/projects/{project_id}/source-videos",
    response_model=SourceVideoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source_video(
    project_id: int,
    file: UploadFile = File(...),
    db_session: Session = Depends(get_db_session),
):
    try:
        pipeline = LocalizationPipeline(db_session)
        source_video = pipeline.save_source_video(project_id, file)
        return source_video
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("上传源片失败: {}", exc)
        raise HTTPException(status_code=500, detail="上传源片失败") from exc


@router.post("/jobs", response_model=LocalizationJobResponse, status_code=status.HTTP_201_CREATED)
async def create_localization_job(
    request: CreateLocalizationJobRequest,
    db_session: Session = Depends(get_db_session),
):
    try:
        pipeline = LocalizationPipeline(db_session)
        job = pipeline.create_job(request.source_video_id, request.target_languages)
        if request.auto_start:
            async_result = run_localization_job_task.delay(job.id)
            job.celery_task_id = async_result.id
            db_session.commit()
            db_session.refresh(job)
        return _job_response(job)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("创建出海译制任务失败: {}", exc)
        raise HTTPException(status_code=500, detail="创建出海译制任务失败") from exc


@router.get("/jobs/{job_id}", response_model=LocalizationJobResponse)
async def get_localization_job(job_id: int, db_session: Session = Depends(get_db_session)):
    job = db_session.query(LocalizationJob).filter(LocalizationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="译制任务不存在")
    return _job_response(job)


@router.get("/projects/{project_id}/source-videos", response_model=List[SourceVideoResponse])
async def list_source_videos(project_id: int, db_session: Session = Depends(get_db_session)):
    return (
        db_session.query(SourceVideo)
        .filter(SourceVideo.project_id == project_id)
        .order_by(SourceVideo.created_at.desc())
        .all()
    )
