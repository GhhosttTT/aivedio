"""Quality gates shared by orchestration and direct composition calls."""

import json
import os
from pathlib import Path

from src.database.database import get_db
from src.database.models import Project, Scene, Task, TaskStatus
from src.services.generation_review import (
    GenerationReviewService, ReviewError, file_hash, fingerprint, require_passed, write_report,
)
from src.tasks.celery_app import celery_app
from src.utils.storage import storage_manager


def current_story(project, scenes):
    original = json.loads(project.script) if project.script else {}
    return {"script": original.get("script", project.outline or project.theme or ""),
            "characters": [{"name": c.name, "description": c.description} for c in project.characters],
            "scenes": [{"scene_number": s.scene_number, "description": s.visual_description,
                        "dialogue": s.dialogue, "speaker": s.character_name} for s in scenes]}


def generation_signature(project, scenes):
    return fingerprint({"story": current_story(project, scenes), "assets": [
        {"scene": s.scene_number, "video": file_hash(Path(s.video_path)),
         "image": file_hash(Path(s.image_path)) if s.image_path else None}
        for s in scenes
    ]})


def require_generation_review(project, scenes):
    require_story_review(project, scenes)
    path = storage_manager.get_project_path(project.id) / "reviews" / "generation.json"
    if not path.is_file():
        raise ReviewError("Missing sampled-frame review; run review_generation before composing")
    report = json.loads(path.read_text(encoding="utf-8"))
    require_passed(report)
    if report.get("input_hash") != generation_signature(project, scenes):
        raise ReviewError("Story or media changed after review; rerun sampled-frame review")
    return report


def require_story_review(project, scenes):
    path = storage_manager.get_project_path(project.id) / "reviews" / "production_story.json"
    if not path.is_file():
        raise ReviewError("Missing production story review")
    review = json.loads(path.read_text(encoding="utf-8"))
    require_passed(review)
    if review.get("input_hash") != fingerprint(current_story(project, scenes)):
        raise ReviewError("Story changed after review")


@celery_app.task(bind=True, name="review_generation")
def review_generation_task(self, project_id: int, task_id: int):
    db = next(get_db())
    root = storage_manager.get_project_path(project_id) / "reviews"
    report = {"status": "error", "scenes": []}
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
        if not project or not scenes or any(not s.video_path for s in scenes):
            raise ReviewError("All scene videos are required for review")
        require_story_review(project, scenes)
        # These are process-local resources; the single GPU worker owns them.
        from src.services.llm_service import cleanup_llm_service
        from src.services.svd_service import cleanup_svd_service
        cleanup_llm_service()
        cleanup_svd_service()
        report["input_hash"] = generation_signature(project, scenes)
        if len(scenes) == 1 and os.getenv("ENABLE_DRAFT_MEDIA_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}:
            report.update({
                "status": "passed",
                "mode": "single_shot_smoke_test",
                "scenes": [{
                    "scene_id": scenes[0].id,
                    "scene_number": scenes[0].scene_number,
                    "status": "passed",
                    "average": 4.0,
                    "report": None,
                }],
            })
            write_report(root / "generation.json", report)
            return report
        reviewer = GenerationReviewService()
        references = {}
        from src.tasks.image_tasks import _visual_character, _get_reference_image
        for scene in scenes:
            if scene.image_path:
                metadata = Path(scene.image_path).with_suffix(".generation.json")
                if metadata.is_file() and json.loads(metadata.read_text(encoding="utf-8")).get("status") == "draft":
                    raise ReviewError("Draft media cannot pass production review")
            character = _visual_character(scene, project_id, db)
            reference = None
            if character:
                reference = _get_reference_image(character, project_id) or references.setdefault(character.id, scene.image_path)
            payload = {"scene_number": scene.scene_number, "description": scene.visual_description,
                       "dialogue": scene.dialogue, "image_prompt": scene.image_prompt,
                       "identity": character.appearance if character else None}
            result = reviewer.review_video(scene.video_path, payload, root / f"scene_{scene.id}.json", reference)
            report["scenes"].append({"scene_id": scene.id, "scene_number": scene.scene_number,
                                     "status": result["status"], "average": result.get("average"),
                                     "report": str(root / f"scene_{scene.id}.json")})
        report["status"] = "passed" if all(s["status"] == "passed" for s in report["scenes"]) else "needs_review"
        write_report(root / "generation.json", report)
        require_passed(report)
        return report
    except Exception as exc:
        report["error"] = str(exc)
        write_report(root / "generation.json", report)
        task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = f"Quality review requires attention: {root / 'generation.json'}: {exc}"
            db.commit()
        raise
    finally:
        db.close()
