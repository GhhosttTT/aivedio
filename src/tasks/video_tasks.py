"""
视频生成任务
使用 Celery 异步执行视频生成任务
"""

from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Scene
from src.services.svd_service import get_svd_service
from src.utils.storage import get_scene_video_path
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="generate_video")
def generate_video_task(
    self,
    previous_result,
    scene_id: int,
    project_id: int,
    task_id: int,
    **kwargs
):
    """
    生成视频任务（图生视频）
    
    Args:
        self: 任务实例
        previous_result: 前一个任务的返回值（在任务链中自动传递，可忽略）
        scene_id: 分镜ID
        project_id: 项目ID
        task_id: 任务ID
        **kwargs: 其他参数
    
    Returns:
        dict: 包含生成结果的字典
    """
    logger.info(f"开始生成视频: scene_id={scene_id}")
    
    # 更新任务状态
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "视频生成"})
    
    try:
        # 获取数据库会话
        db = next(get_db())
        
        # 查询分镜
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        
        # 检查图像是否存在
        if not scene.image_path:
            raise ValueError(f"分镜图像不存在: {scene_id}")
        
        # 获取 SVD 服务
        svd_service = get_svd_service()
        
        # 生成视频路径
        video_path = get_scene_video_path(project_id, scene_id)
        
        # 调用 SVD 服务生成视频
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "调用 SVD"})
        
        result_path = svd_service.generate_video(
            image_path=scene.image_path,
            output_path=video_path,
            num_frames=kwargs.get("num_frames", 16),
            fps=kwargs.get("fps", 8),
            motion_bucket_id=kwargs.get("motion_bucket_id", 127),
            noise_aug_strength=kwargs.get("noise_aug_strength", 0.02)
        )
        
        # 更新数据库
        scene.video_path = result_path
        db.commit()
        
        logger.info(f"视频生成成功: scene_id={scene_id}, path={result_path}")
        
        return {
            "scene_id": scene_id,
            "video_path": result_path,
            "status": "completed"
        }
    
    except Exception as e:
        logger.error(f"视频生成失败: scene_id={scene_id}, error={e}")
        raise
