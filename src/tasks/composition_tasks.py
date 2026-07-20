"""
视频合成任务
使用 Celery 异步执行视频合成任务
"""

from typing import Optional
from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Project, ProjectStatus, Scene
from src.services.video_composer import get_video_composer
from src.services.subtitle_generator import get_subtitle_generator
from src.utils.storage import get_project_final_video_path
from src.utils.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="compose_final_video")
def compose_final_video_task(
    self,
    project_id: int,
    task_id: int,
    add_bgm: bool = False,
    bgm_path: Optional[str] = None,
    **kwargs
):
    """
    合成最终视频任务
    
    Args:
        self: 任务实例
        project_id: 项目ID
        task_id: 任务ID
        add_bgm: 是否添加背景音乐
        bgm_path: 背景音乐文件路径
        **kwargs: 其他参数
    
    Returns:
        dict: 包含合成结果的字典
    """
    logger.info(f"开始合成最终视频: project_id={project_id}")
    
    # 更新任务状态
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "视频合成"})
    
    try:
        # 获取数据库会话
        db = next(get_db())
        
        # 查询项目
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        # 查询所有分镜（按顺序）
        scenes = db.query(Scene).filter(
            Scene.project_id == project_id
        ).order_by(Scene.scene_number).all()
        
        if not scenes:
            raise ValueError(f"项目没有分镜: {project_id}")
        
        # 获取视频合成服务
        video_composer = get_video_composer()
        subtitle_generator = get_subtitle_generator()
        
        # 收集所有分镜的视频和音频路径
        video_paths = []
        audio_paths = []
        subtitle_paths = []
        
        for scene in scenes:
            if scene.video_path:
                video_paths.append(scene.video_path)
            if scene.audio_path:
                audio_paths.append(scene.audio_path)
            if scene.subtitle_path:
                subtitle_paths.append(scene.subtitle_path)
        
        if not video_paths:
            raise ValueError(f"项目没有生成的视频: {project_id}")
        
        logger.info(f"收集到 {len(video_paths)} 个视频片段")
        
        # 生成最终视频路径
        final_video_path = get_project_final_video_path(project_id)
        
        # 步骤 1: 拼接视频（20%）
        self.update_state(state="PROGRESS", meta={"current": 20, "total": 100, "step": "拼接视频"})
        
        temp_video_path = final_video_path.replace(".mp4", "_temp.mp4")
        video_composer.concat_videos(video_paths, temp_video_path)
        
        # 步骤 2: 同步音频（40%）
        self.update_state(state="PROGRESS", meta={"current": 40, "total": 100, "step": "同步音频"})
        
        if audio_paths:
            temp_video_with_audio = final_video_path.replace(".mp4", "_with_audio.mp4")
            audio_path = audio_paths[0]
            if len(audio_paths) > 1:
                merged_audio_path = final_video_path.replace(".mp4", "_merged_audio.mp3")
                audio_path = video_composer._concat_audio(audio_paths, merged_audio_path)
            video_composer.sync_audio_video(
                video_path=temp_video_path,
                audio_path=audio_path,
                output_path=temp_video_with_audio
            )
            temp_video_path = temp_video_with_audio
        
        # 步骤 3: 添加背景音乐（60%）
        self.update_state(state="PROGRESS", meta={"current": 60, "total": 100, "step": "添加背景音乐"})
        
        if add_bgm and bgm_path:
            temp_video_with_bgm = final_video_path.replace(".mp4", "_with_bgm.mp4")
            video_composer.add_bgm(
                video_path=temp_video_path,
                bgm_path=bgm_path,
                output_path=temp_video_with_bgm,
                bgm_volume=kwargs.get("bgm_volume", 0.3)
            )
            temp_video_path = temp_video_with_bgm
        
        # 步骤 4: 烧录字幕（80%）
        self.update_state(state="PROGRESS", meta={"current": 80, "total": 100, "step": "烧录字幕"})
        
        if subtitle_paths:
            # 合并所有字幕文件
            merged_subtitle_path = final_video_path.replace(".mp4", ".srt")
            _merge_subtitles(subtitle_paths, merged_subtitle_path, scenes)
            
            # 烧录字幕到视频
            subtitle_generator.burn_subtitle(
                video_path=temp_video_path,
                subtitle_path=merged_subtitle_path,
                output_path=final_video_path
            )
        else:
            # 如果没有字幕，直接重命名为最终视频
            import shutil
            shutil.move(temp_video_path, final_video_path)
        
        # 更新项目状态
        project.final_video_path = final_video_path
        project.status = ProjectStatus.COMPLETED
        db.commit()
        
        logger.info(f"视频合成成功: project_id={project_id}, path={final_video_path}")
        
        return {
            "project_id": project_id,
            "final_video_path": final_video_path,
            "status": "completed"
        }
    
    except Exception as e:
        logger.error(f"视频合成失败: project_id={project_id}, error={e}")
        
        # 更新项目状态为失败
        db = next(get_db())
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = ProjectStatus.FAILED
            db.commit()
        
        raise


def _merge_subtitles(subtitle_paths: list, output_path: str, scenes: list) -> None:
    """
    合并多个字幕文件
    
    Args:
        subtitle_paths: 字幕文件路径列表
        output_path: 输出路径
        scenes: 分镜列表
    """
    import re
    
    merged_subtitles = []
    current_time_offset = 0.0
    subtitle_index = 1
    
    for i, subtitle_path in enumerate(subtitle_paths):
        scene = scenes[i]
        
        # 读取字幕文件
        with open(subtitle_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 解析字幕条目
        entries = re.split(r"\n\n+", content.strip())
        
        for entry in entries:
            lines = entry.strip().split("\n")
            if len(lines) < 3:
                continue
            
            # 解析时间轴
            time_line = lines[1]
            match = re.match(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", time_line)
            if not match:
                continue
            
            start_time = _parse_srt_time(match.group(1))
            end_time = _parse_srt_time(match.group(2))
            
            # 调整时间偏移
            new_start_time = start_time + current_time_offset
            new_end_time = end_time + current_time_offset
            
            # 重新格式化
            new_entry = f"{subtitle_index}\n"
            new_entry += f"{_format_srt_time(new_start_time)} --> {_format_srt_time(new_end_time)}\n"
            new_entry += "\n".join(lines[2:])
            
            merged_subtitles.append(new_entry)
            subtitle_index += 1
        
        # 更新时间偏移（使用音频时长）
        if scene.audio_duration:
            current_time_offset += scene.audio_duration
    
    # 写入合并后的字幕文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(merged_subtitles))


def _parse_srt_time(time_str: str) -> float:
    """
    解析 SRT 时间格式为秒数
    
    Args:
        time_str: SRT 时间字符串（HH:MM:SS,mmm）
    
    Returns:
        float: 秒数
    """
    import re
    match = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", time_str)
    if not match:
        return 0.0
    
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    milliseconds = int(match.group(4))
    
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def _format_srt_time(seconds: float) -> str:
    """
    格式化秒数为 SRT 时间格式
    
    Args:
        seconds: 秒数
    
    Returns:
        str: SRT 时间字符串（HH:MM:SS,mmm）
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
