"""Short-lived links to project-owned artifacts; no public storage directory."""
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.api.auth import create_access_token, decode_access_token
from src.api.dependencies import get_current_user
from src.database.models import Project
from src.database.session import get_db_session
from src.utils.storage import storage_manager

router = APIRouter(prefix="/api", tags=["媒体"])
ALLOWED = {".mp4", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".srt", ".ass", ".json", ".wav", ".mp3"}


def project_file(project_id: int, path: str) -> Path:
    root = storage_manager.get_project_path(project_id).resolve()
    reference_root = (storage_manager.base_path / "characters" / str(project_id)).resolve()
    candidate = Path(path).resolve()
    if not (candidate.is_relative_to(root) or candidate.is_relative_to(reference_root)) or candidate.suffix.lower() not in ALLOWED or not candidate.is_file():
        raise HTTPException(404, "文件不存在")
    return candidate


@router.get("/projects/{project_id}/media-url")
def media_url(project_id: int, path: str, user=Depends(get_current_user), db: Session = Depends(get_db_session)):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user.id).first()
    if project is None:
        raise HTTPException(404, "项目不存在")
    candidate = project_file(project_id, path)
    token = create_access_token({"kind": "media", "project_id": project_id, "path": str(candidate)}, timedelta(minutes=30))
    return {"url": f"/api/media?token={token}"}


@router.get("/media")
def read_media(token: str, download: bool = False):
    payload = decode_access_token(token)
    if not payload or payload.get("kind") != "media":
        raise HTTPException(401, "媒体链接无效或已过期")
    candidate = project_file(payload["project_id"], payload["path"])
    return FileResponse(candidate, filename=candidate.name if download else None, headers={"Cache-Control": "private, max-age=60"})
