"""
图像生成任务
使用 Celery 异步执行图像生成任务
"""

from typing import Optional
from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Scene
from src.services.comfyui_service import get_comfyui_service
from src.utils.storage import get_scene_image_path
from src.utils.logger import get_logger
import asyncio

logger = get_logger(__name__)


@celery_app.task(bind=True, name="generate_image")
def generate_image_task(
    self,
    scene_id: int,
    prompt: str,
    project_id: int,
    task_id: int,
    character_name: str = None,
    **kwargs
):
    """
    生成图像任务
    
    Args:
        self: 任务实例
        scene_id: 分镜ID
        prompt: 图像生成提示词
        project_id: 项目ID
        task_id: 任务ID
        character_name: 角色名称（用于面部一致性）
        **kwargs: 其他参数
    
    Returns:
        dict: 包含生成结果的字典
    """
    logger.info(f"开始生成图像: scene_id={scene_id}, character={character_name}")
    
    # 更新任务状态
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "图像生成"})
    
    try:
        # 获取数据库会话
        db = next(get_db())
        
        # 查询分镜
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        
        # 获取角色管理器
        from src.services.character_service import get_character_manager
        character_manager = get_character_manager()
        
        # 自动处理角色参考图像
        reference_image = None
        if scene.character_name:
            # 查找或创建角色记录
            from src.database.models import Character
            character = db.query(Character).filter(
                Character.project_id == project_id,
                Character.name == scene.character_name
            ).first()
            
            if not character:
                # 首次出现，创建新角色
                logger.info(f"检测到新角色 '{scene.character_name}'，创建角色记录")
                character = Character(
                    project_id=project_id,
                    name=scene.character_name,
                    description=f"从剧本中自动识别的角色",
                    personality=None,
                    appearance=None
                )
                db.add(character)
                db.commit()
                db.refresh(character)
                logger.info(f"角色 '{scene.character_name}' 创建成功，ID={character.id}")
            
            # 查找该角色的参考图像
            reference_images = character_manager.get_character_references(character.id, project_id)
            
            if reference_images:
                # 已有参考图像，使用第一张
                reference_image = reference_images[0]
                logger.info(f"角色 '{scene.character_name}' 已有 {len(reference_images)} 张参考图，使用: {reference_image}")
            else:
                logger.info(f"角色 '{scene.character_name}' 首次生成，将保存生成的图像作为参考")
        
        # 构建增强提示词（翻译为英文 + 加入角色描述）
        enhanced_prompt = prompt
        character_appearance = None
        
        if scene.character_name:
            # 查询角色外貌特征
            from src.database.models import Character
            character = db.query(Character).filter(
                Character.project_id == project_id,
                Character.name == scene.character_name
            ).first()
            
            if character and character.appearance:
                character_appearance = character.appearance
                logger.info(f"角色 '{scene.character_name}' 外貌特征: {character_appearance}")
            else:
                logger.warning(f"角色 '{scene.character_name}' 没有设置外貌特征，可能导致角色外观不一致")
            
            # 使用 Prompt Enhancer 将中文提示词翻译并增强为英文
            from src.services.prompt_enhancer import get_prompt_enhancer
            enhancer = get_prompt_enhancer()
            
            try:
                enhanced_prompt = enhancer.enhance_prompt(
                    visual_description=prompt,
                    character_name=scene.character_name,
                    character_appearance=character_appearance,
                    scene_context=None
                )
                logger.info(f"提示词已增强并翻译: {enhanced_prompt[:80]}...")
            except Exception as e:
                logger.warning(f"提示词增强失败，使用原始提示词: {e}")
                # 如果增强失败，至少要把角色外貌特征加入提示词
                if character_appearance:
                    enhanced_prompt = f"{scene.character_name} ({character_appearance}), {prompt}"
                else:
                    enhanced_prompt = f"{scene.character_name}, {prompt}"
        else:
            # 没有角色名，仍然需要翻译为英文
            from src.services.prompt_enhancer import get_prompt_enhancer
            enhancer = get_prompt_enhancer()
            
            try:
                enhanced_prompt = enhancer.enhance_prompt(
                    visual_description=prompt,
                    character_name=None,
                    character_appearance=None,
                    scene_context=None
                )
                logger.info(f"提示词已增强并翻译: {enhanced_prompt[:80]}...")
            except Exception as e:
                logger.warning(f"提示词增强失败，使用原始提示词: {e}")
        
        # 获取 ComfyUI 服务
        comfyui_service = get_comfyui_service()
        
        # 生成图像路径
        image_path = get_scene_image_path(project_id, scene_id)
        
        # 调用 ComfyUI 服务生成图像
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "调用 ComfyUI"})
        
        # 使用优化参数 (真实感 + RTX 3060 友好)
        result_path = comfyui_service.generate_image(
            prompt=enhanced_prompt,  # 使用增强提示词
            output_path=image_path,
            width=kwargs.get("width", 1024),  # RTX 3060 推荐宽度
            height=kwargs.get("height", 576),  # RTX 3060 推荐高度 (16:9)
            steps=kwargs.get("steps", 28),  # 优化步数 (平衡质量和速度)
            cfg_scale=kwargs.get("cfg_scale", 6.0),  # 降低 CFG 增强真实感
            reference_image=reference_image,  # 传递参考图像
            use_ipadapter=True if reference_image else False  # 有参考图像时启用 IP-Adapter
        )
        
        # 更新数据库 - 分镜图像路径
        scene.image_path = result_path
        
        # 初始化进度变量
        completed_images = 0
        total_scenes = 0
        progress_percentage = 0.0
        
        # 更新任务进度到数据库
        from src.database.models import Task as TaskModel
        task_model = db.query(TaskModel).filter(
            TaskModel.celery_task_id == str(task_id)
        ).first()
        
        if task_model:
            # 计算当前进度：已完成的图像数 / 总分镜数
            completed_images = db.query(Scene).filter(
                Scene.project_id == project_id,
                Scene.image_path.isnot(None)
            ).count()
            
            total_scenes = db.query(Scene).filter(
                Scene.project_id == project_id
            ).count()
            
            # 更新进度（假设图像生成占总进度的25%）
            progress_percentage = (completed_images / total_scenes) * 25.0 if total_scenes > 0 else 0
            task_model.progress = progress_percentage
            task_model.current_step = completed_images
            db.commit()
            logger.info(f"任务进度更新: {completed_images}/{total_scenes} 个图像已完成, 进度={progress_percentage:.1f}%")
        
        db.commit()
        
        logger.info(f"图像生成成功: scene_id={scene_id}, path={result_path}")
        
        # 如果是角色首次出现，将生成的图像保存为参考图
        if scene.character_name and not reference_image:
            from src.database.models import Character
            character = db.query(Character).filter(
                Character.project_id == project_id,
                Character.name == scene.character_name
            ).first()
            
            if character:
                try:
                    saved_ref_path = character_manager.save_character_reference(
                        character_id=character.id,
                        project_id=project_id,
                        image_path=result_path,
                        description=f"自动生成于分镜 {scene.scene_number}"
                    )
                    logger.info(f"已将生成的图像保存为角色 '{scene.character_name}' 的参考图: {saved_ref_path}")
                except Exception as e:
                    logger.warning(f"保存角色参考图失败: {e}")
        
        # 通过 WebSocket 推送进度更新
        try:
            from src.api.websocket import manager
            asyncio.run(manager.broadcast(project_id, {
                "type": "progress",
                "task_id": str(task_id),
                "project_id": project_id,
                "scene_id": scene_id,
                "task_type": "image",
                "status": "completed",
                "progress": progress_percentage / 100.0 if task_model else 0.0,  # 转换为0-1范围
                "current_step": f"分镜 {scene.scene_number} 图像生成完成 ({completed_images}/{total_scenes})",
                "message": f"图像生成成功 ({completed_images}/{total_scenes})"
            }))
        except Exception as e:
            logger.warning(f"WebSocket 推送失败: {e}")
        
        return {
            "scene_id": scene_id,
            "image_path": result_path,
            "status": "completed"
        }
    
    except Exception as e:
        logger.error(f"图像生成失败: scene_id={scene_id}, error={e}")
        raise


@celery_app.task(bind=True, name="batch_generate_images")
def batch_generate_images_task(self, scene_ids: list, **kwargs):
    """
    批量生成图像任务
    
    Args:
        self: 任务实例
        scene_ids: 分镜ID列表
        **kwargs: 其他参数
    
    Returns:
        dict: 包含批量生成结果的字典
    """
    results = []
    total = len(scene_ids)
    
    for i, scene_id in enumerate(scene_ids):
        # 更新进度
        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": total}
        )
        
        # TODO: 调用单个图像生成任务
        # result = generate_image_task.delay(scene_id)
        # results.append(result)
    
    return {
        "total": total,
        "completed": len(results),
        "results": results
    }
