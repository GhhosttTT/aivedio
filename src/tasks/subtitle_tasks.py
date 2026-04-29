"""
字幕生成任务
使用 Celery 异步执行字幕生成任务
"""

from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Scene
from src.services.subtitle_generator import get_subtitle_generator
from src.utils.storage import get_scene_subtitle_path
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="generate_subtitle")
def generate_subtitle_task(
    self,
    scene_id: int,
    project_id: int,
    task_id: int,
    **kwargs
):
    """
    生成字幕任务
    
    Args:
        self: 任务实例
        scene_id: 分镜ID
        project_id: 项目ID
        task_id: 任务ID
        **kwargs: 其他参数
    
    Returns:
        dict: 包含生成结果的字典
    """
    logger.info(f"开始生成字幕: scene_id={scene_id}")
    
    # 更新任务状态
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "字幕生成"})
    
    try:
        # 获取数据库会话
        db = next(get_db())
        
        # 查询分镜
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        
        # 如果没有对话或音频，跳过
        if not scene.dialogue or not scene.audio_path:
            logger.info(f"分镜没有对话或音频，跳过字幕生成: scene_id={scene_id}")
            return {
                "scene_id": scene_id,
                "subtitle_path": None,
                "status": "skipped"
            }
        
        # 获取字幕生成服务
        subtitle_generator = get_subtitle_generator()
        
        # 生成字幕路径
        subtitle_path = get_scene_subtitle_path(project_id, scene_id)
        
        # 生成字幕文件
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "生成 SRT"})
        
        result_path = subtitle_generator.generate_srt(
            text=scene.dialogue,
            audio_path=scene.audio_path,
            output_path=subtitle_path
        )
        
        # 更新数据库
        scene.subtitle_path = result_path
        db.commit()
        
        logger.info(f"字幕生成成功: scene_id={scene_id}, path={result_path}")
        
        return {
            "scene_id": scene_id,
            "subtitle_path": result_path,
            "status": "completed"
        }
    
    except Exception as e:
        logger.error(f"字幕生成失败: scene_id={scene_id}, error={e}")
        raise
