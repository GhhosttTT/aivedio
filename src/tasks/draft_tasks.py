"""Tasks that finish an explicit provider Draft run without publishing it."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.database.database import get_db
from src.database.models import Project, ProjectStatus, Scene, Task
from src.services.generation_review import file_hash, write_report
from src.tasks.celery_app import celery_app, _claim_task_completion
from src.utils.storage import storage_manager


@celery_app.task(bind=True, name="finalize_draft_generation")
def finalize_draft_generation_task(self, project_id: int, task_id: int):
    """Close a Draft-only run while keeping the project unpublished."""
    db = next(get_db())
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
        task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
        if not project or not task or not scenes:
            raise ValueError("Draft finalization requires an existing project, task, and scenes")

        report = {
            "status": "draft_ready",
            "mode": "provider_draft_only",
            "project_id": project_id,
            "task_id": task_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "publishable": False,
            "promotion_endpoint": f"/api/projects/{project_id}/promote-drafts",
            "scenes": [],
        }
        for scene in scenes:
            video_path = Path(scene.video_path) if scene.video_path else None
            current_video_hash = (
                file_hash(video_path)
                if video_path and video_path.is_file()
                else None
            )
            provider_metadata = Path(scene.video_path).with_suffix(".provider.json") if scene.video_path else None
            metadata = {}
            if provider_metadata and provider_metadata.is_file():
                try:
                    loaded = json.loads(provider_metadata.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        metadata = loaded
                except (OSError, TypeError, ValueError):
                    metadata = {}
            report["scenes"].append({
                "scene_id": scene.id,
                "scene_number": scene.scene_number,
                "video_path": scene.video_path,
                "provider_task_id": metadata.get("provider_task_id"),
                "provider_name": metadata.get("provider_name"),
                "requested_draft": bool(metadata.get("requested_draft")),
                "video_sha256": current_video_hash,
                "evidence_current": bool(
                    current_video_hash
                    and metadata.get("video_sha256") == current_video_hash
                ),
            })

        report_path = storage_manager.get_project_path(project_id) / "reviews" / "draft_generation.json"
        task = _claim_task_completion(db, project_id, task_id)
        write_report(report_path, report)
        project.final_video_path = None
        project.status = ProjectStatus.SCRIPT_GENERATED
        task.progress = 100.0
        task.current_step = task.total_steps
        task.result_path = str(report_path)
        task.error_message = None
        db.commit()
        return {"project_id": project_id, "task_id": task_id, "status": "draft_ready", "report_path": str(report_path)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
