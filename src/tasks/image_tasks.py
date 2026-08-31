"""Image generation Celery tasks."""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from src.database.database import get_db
from src.database.models import Character, Project, Scene, Task as TaskModel
from src.config import settings
from src.services.shot_prompt_service import ShotPromptService, CompiledShot
from src.services.generation_review import write_report
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.generation_provider import ImageGenerationRequest, get_generation_provider
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_image_path

logger = get_logger(__name__)


def _visual_character(scene: Scene, project_id: int, db) -> Optional[Character]:
    # Speaker and visible actor may differ, especially in narration and reaction shots.
    project = db.query(Project).filter(Project.id == project_id).first()
    plan = json.loads(project.script) if project and project.script else {}
    item = next((s for s in plan.get("scenes", []) if s.get("scene_number") == scene.scene_number), {})
    visible = item.get("characters")
    if visible is None:
        visible = [scene.character_name] if scene.character_name and scene.character_name in scene.visual_description else []
    if len(visible) != 1:
        return None
    return db.query(Character).filter(Character.project_id == project_id, Character.name == visible[0]).first()


def _prepare_prompt(scene: Scene, project_id: int, prompt: str, db, compiler=None):
    compiler = compiler or ShotPromptService()
    character = _visual_character(scene, project_id, db)
    appearance = character.appearance if character else None
    if appearance and (re.search(r"[\u3400-\u9fff]", appearance) or len(appearance.split()) > 25):
        from src.services.script_generator import ScriptGenerator
        if compiler.llm_service is None:
            from src.services.llm_service import get_llm_service
            compiler.llm_service = get_llm_service()
        appearance = ScriptGenerator(db, compiler.llm_service)._generate_character_appearance(character.name, appearance)
        character.appearance = appearance
        db.commit()
    artifact = Path(get_scene_image_path(project_id, scene.id)).with_suffix(".prompt.json")
    source_hash = compiler.source_hash(prompt, appearance)
    if artifact.is_file():
        cached = json.loads(artifact.read_text(encoding="utf-8"))
        if cached.get("source_hash") == source_hash and cached.get("version") == 1:
            compiler.validate_prompt(cached["prompt"])
            return CompiledShot(**cached), character
    compiled = compiler.compile(prompt, appearance)
    write_report(artifact, compiled.to_dict())
    return compiled, character


@celery_app.task(bind=True, name="prepare_generation")
def prepare_generation_task(self, project_id: int, task_id: int, compile_images: bool = True):
    db = next(get_db())
    try:
        scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
        if not scenes:
            raise ValueError("Project has no scenes")
        compiler = ShotPromptService()
        from src.services.generation_review import GenerationReviewService, TextReviewer, fingerprint, require_passed
        from src.tasks.review_tasks import current_story
        from src.utils.storage import storage_manager
        project = db.query(Project).filter(Project.id == project_id).first()
        story = current_story(project, scenes)
        review_path = storage_manager.get_project_path(project_id) / "reviews" / "production_story.json"
        reviewed = json.loads(review_path.read_text(encoding="utf-8")) if review_path.is_file() else {}
        if reviewed.get("input_hash") != fingerprint(story) or reviewed.get("status") != "passed":
            from src.services.llm_service import get_llm_service
            compiler.llm_service = get_llm_service()
            reviewed = GenerationReviewService(TextReviewer(compiler.llm_service)).review_story(story, review_path)
        require_passed(reviewed)
        if compile_images:
            for scene in scenes:
                _prepare_prompt(scene, project_id, scene.image_prompt or scene.visual_description, db, compiler)
        return {"prepared": len(scenes)}
    finally:
        from src.services.llm_service import cleanup_llm_service
        cleanup_llm_service()
        db.close()


def _get_reference_image(character: Optional[Character], project_id: int) -> Optional[str]:
    if not character:
        return None
    try:
        from src.services.character_service import get_character_manager

        references = get_character_manager().get_character_references(character.id, project_id)
        return references[0] if references else None
    except Exception as exc:
        logger.warning("读取角色参考图失败: {}", exc)
        return None


def _save_first_reference(character: Optional[Character], project_id: int, scene: Scene, image_path: str) -> None:
    if not character:
        return
    try:
        from src.services.character_service import get_character_manager

        get_character_manager().save_character_reference(
            character_id=character.id,
            project_id=project_id,
            image_path=image_path,
            description=f"Generated from scene {scene.scene_number}",
        )
    except Exception as exc:
        logger.warning("保存角色参考图失败: {}", exc)


def _update_progress(db, project_id: int, task_id: int) -> tuple[float, int, int]:
    task_model = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if task_model is None:
        task_model = (
            db.query(TaskModel)
            .filter(TaskModel.project_id == project_id)
            .order_by(TaskModel.created_at.desc())
            .first()
        )
    completed_images = db.query(Scene).filter(
        Scene.project_id == project_id,
        Scene.image_path.isnot(None),
    ).count()
    total_scenes = db.query(Scene).filter(Scene.project_id == project_id).count()
    progress_percentage = (completed_images / total_scenes) * 25.0 if total_scenes else 0.0

    if task_model:
        progress_percentage = task_model.progress

    return progress_percentage, completed_images, total_scenes


def _broadcast_progress(project_id: int, task_id: int, scene: Scene, progress: float, completed: int, total: int) -> None:
    try:
        from src.api.websocket import manager

        asyncio.run(
            manager.broadcast(
                project_id,
                {
                    "type": "progress",
                    "task_id": str(task_id),
                    "project_id": project_id,
                    "scene_id": scene.id,
                    "task_type": "image",
                    "status": "completed",
                    "progress": progress / 100.0,
                    "current_step": f"Scene {scene.scene_number} image completed ({completed}/{total})",
                    "message": f"Image generated ({completed}/{total})",
                },
            )
        )
    except Exception as exc:
        logger.warning("WebSocket 推送失败: {}", exc)


@celery_app.task(bind=True, name="generate_image")
def generate_image_task(
    self,
    scene_id: int,
    prompt: str,
    project_id: int,
    task_id: int,
    character_name: str = None,
    **kwargs,
):
    """Generate an image for one scene."""
    logger.info("开始生成图像: scene_id={}, character={}", scene_id, character_name)
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "image_generation"})

    db = next(get_db())
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene or scene.project_id != project_id:
            raise ValueError(f"分镜不存在: {scene_id}")

        try:
            compiled, character = _prepare_prompt(scene, project_id, prompt, db)
        finally:
            from src.services.llm_service import cleanup_llm_service
            cleanup_llm_service()
        reference_image = _get_reference_image(character, project_id)
        enhanced_prompt = compiled.prompt

        image_path = get_scene_image_path(project_id, scene_id)
        provider = get_generation_provider(kwargs.get("provider"))
        seed = kwargs.get("seed", int(hashlib.sha256(f"{project_id}:{scene_id}".encode()).hexdigest()[:8], 16))
        request = ImageGenerationRequest(
            prompt=enhanced_prompt, negative_prompt=compiled.negative_prompt,
            output_path=image_path, seed=seed,
            width=kwargs.get("width", settings.GENERATION_WIDTH),
            height=kwargs.get("height", settings.GENERATION_HEIGHT),
            steps=kwargs.get("steps", settings.GENERATION_STEPS),
            cfg_scale=kwargs.get("cfg_scale", settings.GENERATION_CFG),
            reference_image=reference_image, use_ipadapter=reference_image is not None,
        )

        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "generation_provider"})
        try:
            result = provider.generate_image(request)
        except Exception as exc:
            if not draft_fallback_enabled():
                raise
            logger.warning("真实图片生成失败，使用草稿兜底图: scene_id={}, error={}", scene_id, exc)
            draft_path = get_draft_media_service().generate_image(
                prompt=enhanced_prompt,
                output_path=image_path,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 576),
                scene_number=scene.scene_number,
            )
            result = type(
                "DraftImageResult",
                (),
                {"output_path": draft_path, "provider": "draft_fallback"},
            )()

        from dataclasses import asdict
        write_report(Path(image_path).with_suffix(".generation.json"), {
            "provider": result.provider, "request": asdict(request),
            "status": "draft" if result.provider == "draft_fallback" else "generated",
        })
        scene.image_path = result.output_path
        db.commit()

        # Generated frames become references only after explicit human selection.

        progress, completed, total = _update_progress(db, project_id, task_id)
        _broadcast_progress(project_id, task_id, scene, progress, completed, total)

        logger.info("图像生成成功: scene_id={}, path={}", scene_id, result.output_path)
        return {
            "scene_id": scene_id,
            "image_path": result.output_path,
            "provider": result.provider,
            "status": "completed",
        }
    except Exception as exc:
        logger.error("图像生成失败: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="batch_generate_images")
def batch_generate_images_task(self, scene_ids: list, **kwargs):
    """Placeholder for future batch image generation."""
    total = len(scene_ids)
    for i, _scene_id in enumerate(scene_ids):
        self.update_state(state="PROGRESS", meta={"current": i + 1, "total": total})
    return {"total": total, "completed": 0, "results": []}
