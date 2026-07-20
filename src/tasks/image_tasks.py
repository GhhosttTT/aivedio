"""Image generation Celery tasks."""

import asyncio
from typing import Optional

from src.database.database import get_db
from src.database.models import Character, Scene, Task as TaskModel
from src.services.generation_provider import ImageGenerationRequest, get_generation_provider
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_image_path

logger = get_logger(__name__)


def _enhance_prompt(scene: Scene, project_id: int, prompt: str, db) -> str:
    character_appearance: Optional[str] = None

    if scene.character_name:
        character = (
            db.query(Character)
            .filter(Character.project_id == project_id, Character.name == scene.character_name)
            .first()
        )
        if character and character.appearance:
            character_appearance = character.appearance
        else:
            logger.warning("角色 {} 未配置外貌特征，可能影响一致性", scene.character_name)

    try:
        from src.services.prompt_enhancer import get_prompt_enhancer

        enhancer = get_prompt_enhancer()
        return enhancer.enhance_prompt(
            visual_description=prompt,
            character_name=scene.character_name,
            character_appearance=character_appearance,
            scene_context=None,
        )
    except Exception as exc:
        logger.warning("提示词增强失败，使用原始提示词: {}", exc)
        if scene.character_name and character_appearance:
            return f"{scene.character_name} ({character_appearance}), {prompt}"
        if scene.character_name:
            return f"{scene.character_name}, {prompt}"
        return prompt


def _get_or_create_character(scene: Scene, project_id: int, db) -> Optional[Character]:
    if not scene.character_name:
        return None

    character = (
        db.query(Character)
        .filter(Character.project_id == project_id, Character.name == scene.character_name)
        .first()
    )
    if character:
        return character

    character = Character(
        project_id=project_id,
        name=scene.character_name,
        description="Automatically detected from script",
        personality=None,
        appearance=None,
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


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
    task_model = db.query(TaskModel).filter(TaskModel.celery_task_id == str(task_id)).first()
    completed_images = db.query(Scene).filter(
        Scene.project_id == project_id,
        Scene.image_path.isnot(None),
    ).count()
    total_scenes = db.query(Scene).filter(Scene.project_id == project_id).count()
    progress_percentage = (completed_images / total_scenes) * 25.0 if total_scenes else 0.0

    if task_model:
        task_model.progress = progress_percentage
        task_model.current_step = completed_images
        db.commit()

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
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")

        character = _get_or_create_character(scene, project_id, db)
        reference_image = _get_reference_image(character, project_id)
        enhanced_prompt = _enhance_prompt(scene, project_id, prompt, db)

        image_path = get_scene_image_path(project_id, scene_id)
        provider = get_generation_provider(kwargs.get("provider"))

        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "generation_provider"})
        result = provider.generate_image(
            ImageGenerationRequest(
                prompt=enhanced_prompt,
                output_path=image_path,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 576),
                steps=kwargs.get("steps", 28),
                cfg_scale=kwargs.get("cfg_scale", 6.0),
                reference_image=reference_image,
                use_ipadapter=reference_image is not None,
                quality_mode=kwargs.get("quality_mode"),
                optimization_mode=kwargs.get("optimization_mode"),
            )
        )

        scene.image_path = result.output_path
        db.commit()

        if character and not reference_image:
            _save_first_reference(character, project_id, scene, result.output_path)

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
