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

logger = get_logger(__name__)


@celery_app.task(bind=True, name="generate_image")
def generate_image_task(
    self,
    scene_id: int,
    prompt: str,
    project_id: int,
    task_id: int,
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
        **kwargs: 其他参数
    
    Returns:
        dict: 包含生成结果的字典
    """
    logger.info(f"开始生成图像: scene_id={scene_id}, prompt={prompt[:50]}...")
    
    # 更新任务状态
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "图像生成"})
    
    try:
        # 获取数据库会话
        db = next(get_db())
        
        # 查询分镜
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        
        # 获取 ComfyUI 服务
        comfyui_service = get_comfyui_service()
        
        # 生成图像路径
        image_path = get_scene_image_path(project_id, scene_id)
        
        # 调用 ComfyUI 服务生成图像
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "调用 ComfyUI"})
        
        result_path = comfyui_service.generate_image(
            prompt=prompt,
            output_path=image_path,
            width=kwargs.get("width", 768),
            height=kwargs.get("height", 768),
            steps=kwargs.get("steps", 20),
            cfg_scale=kwargs.get("cfg_scale", 7.0)
        )
        
        # 更新数据库
        scene.image_path = result_path
        db.commit()
        
        logger.info(f"图像生成成功: scene_id={scene_id}, path={result_path}")
        
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
