"""
音频生成任务
使用 Celery 异步执行音频生成任务
"""

from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Scene
from src.services.tts_service import get_tts_service
from src.utils.storage import get_scene_audio_path
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="generate_audio")
def generate_audio_task(
    self,
    scene_id: int,
    text: str,
    speaker: str,
    project_id: int,
    task_id: int,
    **kwargs
):
    """
    生成音频任务（TTS）
    
    Args:
        self: 任务实例
        scene_id: 分镜ID
        text: 对话文本
        speaker: 说话人
        project_id: 项目ID
        task_id: 任务ID
        **kwargs: 其他参数
    
    Returns:
        dict: 包含生成结果的字典
    """
    logger.info(f"开始生成音频: scene_id={scene_id}, text={text[:50] if text else ''}...")
    
    # 更新任务状态
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "音频生成"})
    
    try:
        # 获取数据库会话
        db = next(get_db())
        
        # 查询分镜
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"分镜不存在: {scene_id}")
        
        # 如果没有对话文本，跳过
        if not text or text.strip() == "":
            logger.info(f"分镜没有对话，跳过音频生成: scene_id={scene_id}")
            return {
                "scene_id": scene_id,
                "audio_path": None,
                "duration": 0.0,
                "status": "skipped"
            }
        
        # 获取 TTS 服务
        tts_service = get_tts_service()
        
        # 生成音频路径
        audio_path = get_scene_audio_path(project_id, scene_id)
        
        # 调用 TTS 服务生成音频
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "调用 TTS API"})
        
        result_path, duration = tts_service.generate_speech(
            text=text,
            output_path=audio_path,
            speaker=speaker,
            emotion=kwargs.get("emotion", "neutral"),
            speed=kwargs.get("speed", 1.0)
        )
        
        # 更新数据库
        scene.audio_path = result_path
        scene.audio_duration = duration
        db.commit()
        
        logger.info(f"音频生成成功: scene_id={scene_id}, path={result_path}, duration={duration}")
        
        return {
            "scene_id": scene_id,
            "audio_path": result_path,
            "duration": duration,
            "status": "completed"
        }
    
    except Exception as e:
        logger.error(f"音频生成失败: scene_id={scene_id}, error={e}")
        raise
