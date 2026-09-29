"""
视频合成任务
使用 Celery 异步执行视频合成任务
"""

import json
from pathlib import Path
from typing import Optional
from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Project, ProjectStatus, Scene, Task as TaskModel, TaskStatus
from src.config import settings
from src.services.generation_review import GenerationReviewService, VIDEO_AESTHETIC_FEATURES, write_report
from src.services.repair_queue import attach_repair_queue
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
        from src.tasks.review_tasks import require_generation_review
        require_generation_review(project, scenes)
        
        # 获取视频合成服务
        video_composer = get_video_composer()
        subtitle_generator = get_subtitle_generator()
        
        _require_passed_scene_videos(scenes)

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
        temp_video_path = video_composer.concat_videos(video_paths, temp_video_path)
        
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
            import os

            # concat_videos returns the source path directly when there is only one scene.
            # Keep scene assets intact; only move files that are composition temp outputs.
            if os.path.abspath(temp_video_path) != os.path.abspath(final_video_path):
                if temp_video_path in video_paths:
                    shutil.copy2(temp_video_path, final_video_path)
                else:
                    shutil.move(temp_video_path, final_video_path)

        composition_review = _review_final_composed_video(project, scenes, final_video_path)
        
        # 更新项目状态
        project.final_video_path = final_video_path
        project.status = ProjectStatus.COMPLETED
        task_model = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if task_model is None:
            task_model = (
                db.query(TaskModel)
                .filter(TaskModel.project_id == project_id)
                .order_by(TaskModel.created_at.desc())
                .first()
            )
        if task_model:
            task_model.status = TaskStatus.COMPLETED
            task_model.progress = 100.0
            task_model.result_path = final_video_path
        db.commit()
        
        logger.info(f"视频合成成功: project_id={project_id}, path={final_video_path}")
        
        result = {
            "project_id": project_id,
            "final_video_path": final_video_path,
            "status": "completed"
        }
        if composition_review:
            result["composition_review_path"] = composition_review.get("path")
        return result
    
    except Exception as e:
        logger.error(f"视频合成失败: project_id={project_id}, error={e}")
        
        # 更新项目状态为失败
        db = next(get_db())
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.status = ProjectStatus.FAILED
        task_model = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if task_model:
            task_model.status = TaskStatus.FAILED
            task_model.error_message = str(e)
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


def _require_passed_scene_videos(scenes: list[Scene]) -> None:
    missing = []
    failed = []
    for scene in scenes:
        if not scene.video_path:
            missing.append(str(scene.scene_number))
            continue
        video_path = Path(scene.video_path)
        if not video_path.is_file():
            missing.append(str(scene.scene_number))
            continue
        quality_path = video_path.with_suffix(".quality.json")
        if not quality_path.is_file():
            failed.append(f"{scene.scene_number}: missing video quality report")
            continue
        try:
            report = json.loads(quality_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failed.append(f"{scene.scene_number}: invalid video quality report: {exc}")
            continue
        if report.get("status") != "passed":
            failed.append(f"{scene.scene_number}: video quality status={report.get('status') or 'unknown'}")
            continue
        final_review_error = _final_video_review_error(report)
        if final_review_error:
            failed.append(f"{scene.scene_number}: {final_review_error}")
    if missing:
        raise ValueError("Missing generated video for scenes: " + ", ".join(missing))
    if failed:
        raise ValueError("Scene videos are not production-ready: " + "; ".join(failed))


def _gate_status_passed(review: dict, key: str) -> bool:
    gate = review.get(key)
    return isinstance(gate, dict) and gate.get("status") == "passed"


def _optional_gate_status_passed(review: dict, key: str) -> bool:
    gate = review.get(key)
    return not isinstance(gate, dict) or gate.get("status") == "passed"


def _final_video_review_error(report: dict) -> str | None:
    if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return None
    review = report.get("final_video_review")
    if not isinstance(review, dict):
        return "missing final normalized video review"
    if review.get("status") != "passed":
        return f"final normalized video review status={review.get('status') or 'unknown'}"
    if float(review.get("average") or 0) < settings.GENERATION_VIDEO_MIN_SCORE:
        return f"final normalized video average={review.get('average') or 0} below {settings.GENERATION_VIDEO_MIN_SCORE}"
    gate_scores = review.get("gate_scores") if isinstance(review.get("gate_scores"), dict) else {}
    if gate_scores:
        if float(gate_scores.get("facial_identity") or 0) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
            return "final normalized video facial identity gate failed"
        if float(gate_scores.get("identity_consistency") or 0) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
            return "final normalized video identity consistency gate failed"
        if float(gate_scores.get("temporal_consistency") or 0) < settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE:
            return "final normalized video temporal gate failed"
    platform_score = review.get("platform_score")
    if isinstance(platform_score, (int, float)) and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
        return f"final normalized video platform score={platform_score} below {settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE}"
    if not _gate_status_passed(review, "video_aesthetic_gate"):
        return "final normalized video aesthetic gate failed"
    if not _optional_gate_status_passed(review, "character_distinctiveness_gate"):
        return "final normalized video character distinctiveness gate failed"
    if not _gate_status_passed(review, "video_performance_gate"):
        return "final normalized video performance gate failed"
    return None


def _project_final_review_payload(project: Project, scenes: list[Scene]) -> dict:
    visible_characters = []
    seen = set()
    scene_summaries = []
    dialogue_lines = []
    for scene in scenes:
        if scene.character_name and scene.character_name not in seen:
            visible_characters.append({
                "name": scene.character_name,
                "appearance": scene.visual_description or scene.image_prompt or "",
            })
            seen.add(scene.character_name)
        scene_summaries.append({
            "scene_number": scene.scene_number,
            "visual_description": scene.visual_description,
            "dialogue": scene.dialogue,
            "has_audio": bool(scene.audio_path),
            "has_subtitle": bool(scene.subtitle_path),
        })
        if scene.dialogue:
            dialogue_lines.append(str(scene.dialogue))
    return {
        "scene_number": "final_composition",
        "project_id": project.id,
        "project_name": project.name,
        "visual_description": "Full composed mobile short-drama episode assembled from reviewed scene clips.",
        "dialogue": "\n".join(dialogue_lines),
        "scenes": scene_summaries,
        "visible_characters": visible_characters,
        "shot_plan": {
            "shot_role": "final_composed_short_drama",
            "review_scope": "full_episode_after_concat_audio_subtitles",
        },
        "platform_aesthetic_contract": {
            "video_features": list(VIDEO_AESTHETIC_FEATURES),
            "review_instruction": (
                "Judge the composed full episode for premium mobile short-drama polish, "
                "coherent transitions, readable subtitles when present, audio-video timing, "
                "consistent character identity across scene boundaries, and commercial finish."
            ),
        },
        "composition_contract": {
            "must_check": [
                "scene order is coherent",
                "cuts do not create jarring identity or position jumps",
                "dialogue reaction beats are readable",
                "burned subtitles are readable and do not cover faces",
                "audio and lip/action timing feel aligned",
                "the full clip is publishable on a mobile short-drama feed",
            ],
        },
    }


def _composition_review_error(report: dict) -> str | None:
    if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return None
    if report.get("status") != "passed":
        return f"composition review status={report.get('status') or 'unknown'}"
    if float(report.get("average") or 0) < settings.GENERATION_VIDEO_MIN_SCORE:
        return f"composition review average={report.get('average') or 0} below {settings.GENERATION_VIDEO_MIN_SCORE}"
    batches = report.get("batches") if isinstance(report.get("batches"), list) else []
    if not batches:
        return "composition review has no sampled-frame batches"
    for index, batch in enumerate(batches, start=1):
        if batch.get("status") != "passed":
            return f"composition review batch {index} status={batch.get('status') or 'unknown'}"
        review = batch.get("review") if isinstance(batch.get("review"), dict) else {}
        for key in ("facial_identity", "identity_consistency"):
            value = review.get(key)
            if isinstance(value, dict) and float(value.get("score") or 0) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
                return f"composition review batch {index} {key} gate failed"
        value = review.get("temporal_consistency")
        if isinstance(value, dict) and float(value.get("score") or 0) < settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE:
            return f"composition review batch {index} temporal gate failed"
        platform_score = batch.get("platform_score")
        if isinstance(platform_score, (int, float)) and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
            return f"composition review batch {index} platform score={platform_score} below {settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE}"
        if not _gate_status_passed(batch, "video_aesthetic_gate"):
            return f"composition review batch {index} aesthetic gate failed"
        if not _optional_gate_status_passed(batch, "character_distinctiveness_gate"):
            return f"composition review batch {index} character distinctiveness gate failed"
        if not _gate_status_passed(batch, "video_performance_gate"):
            return f"composition review batch {index} performance gate failed"
    return None


def _review_final_composed_video(project: Project, scenes: list[Scene], final_video_path: str) -> dict | None:
    if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return None
    report_path = Path(final_video_path).with_suffix(".composition_review.json")
    report = GenerationReviewService().review_video(
        final_video_path,
        _project_final_review_payload(project, scenes),
        report_path,
    )
    report["path"] = str(report_path)
    report["stage"] = "final_composition"
    error = _composition_review_error(report)
    if error:
        report["error"] = error
        attach_repair_queue(report, "video")
        write_report(report_path, report)
        raise ValueError("Final composed video is not production-ready: " + error)
    write_report(report_path, report)
    return report


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
