"""
视频合成任务
使用 Celery 异步执行视频合成任务
"""

import json
import re
from pathlib import Path
from typing import Optional
from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Project, ProjectStatus, Scene, Task as TaskModel, TaskStatus
from src.config import settings
from src.services.generation_review import (
    FINAL_COMPOSITION_FINISHING_FEATURES,
    GenerationReviewService,
    VIDEO_AESTHETIC_FEATURES,
    write_report,
)
from src.services.repair_queue import attach_repair_queue
from src.services.video_composer import get_video_composer
from src.services.subtitle_generator import get_subtitle_generator
from src.tasks.audio_tasks import has_spoken_dialogue
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
        _require_passed_scene_audio(scenes)
        _require_scene_subtitles(scenes)
        _require_audio_video_duration_alignment(scenes, video_composer)

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


def _require_passed_scene_audio(scenes: list[Scene]) -> None:
    missing = []
    failed = []
    for scene in scenes:
        if not has_spoken_dialogue(scene.dialogue):
            continue
        if not scene.audio_path:
            missing.append(str(scene.scene_number))
            continue
        audio_path = Path(scene.audio_path)
        if not audio_path.is_file():
            missing.append(str(scene.scene_number))
            continue
        quality_path = audio_path.with_suffix(".quality.json")
        if not quality_path.is_file():
            failed.append(f"{scene.scene_number}: missing audio quality report")
            continue
        try:
            report = json.loads(quality_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failed.append(f"{scene.scene_number}: invalid audio quality report: {exc}")
            continue
        if report.get("status") != "passed":
            failed.append(f"{scene.scene_number}: audio quality status={report.get('status') or 'unknown'}")
            continue
        gate = report.get("dialogue_audio_quality_gate")
        if isinstance(gate, dict) and gate.get("status") != "passed":
            failed.append(f"{scene.scene_number}: dialogue audio quality gate failed")
    if missing:
        raise ValueError("Missing generated audio for spoken-dialogue scenes: " + ", ".join(missing))
    if failed:
        raise ValueError("Scene audio is not production-ready: " + "; ".join(failed))


def _require_scene_subtitles(scenes: list[Scene]) -> None:
    missing = []
    failed = []
    for scene in scenes:
        if not has_spoken_dialogue(scene.dialogue):
            continue
        if not scene.subtitle_path:
            missing.append(str(scene.scene_number))
            continue
        subtitle_path = Path(scene.subtitle_path)
        if not subtitle_path.is_file():
            missing.append(str(scene.scene_number))
            continue
        try:
            content = subtitle_path.read_text(encoding="utf-8")
        except OSError as exc:
            failed.append(f"{scene.scene_number}: cannot read subtitle: {exc}")
            continue
        if not _srt_has_timing(content):
            failed.append(f"{scene.scene_number}: subtitle has no valid SRT timing")
            continue
        if not _subtitle_matches_dialogue(content, scene.dialogue or ""):
            failed.append(f"{scene.scene_number}: subtitle text does not cover spoken dialogue")
    if missing:
        raise ValueError("Missing subtitle for spoken-dialogue scenes: " + ", ".join(missing))
    if failed:
        raise ValueError("Scene subtitles are not production-ready: " + "; ".join(failed))


def _require_audio_video_duration_alignment(
    scenes: list[Scene],
    video_composer,
    tolerance_seconds: float = 1.0,
    tolerance_ratio: float = 0.15,
) -> None:
    video_total = 0.0
    audio_total = 0.0
    video_count = 0
    audio_count = 0
    failed = []
    for scene in scenes:
        if scene.video_path:
            duration = video_composer._get_duration(scene.video_path)
            if duration <= 0:
                failed.append(f"{scene.scene_number}: video duration is unreadable")
            else:
                video_total += duration
                video_count += 1
        if has_spoken_dialogue(scene.dialogue):
            if scene.audio_path:
                duration = video_composer._get_duration(scene.audio_path)
                if duration <= 0 and scene.audio_duration:
                    duration = float(scene.audio_duration)
                if duration <= 0:
                    failed.append(f"{scene.scene_number}: audio duration is unreadable")
                else:
                    audio_total += duration
                    audio_count += 1
    if failed:
        raise ValueError("Scene media durations are not production-ready: " + "; ".join(failed))
    if not video_count or not audio_count:
        return
    allowed_delta = max(tolerance_seconds, video_total * tolerance_ratio)
    delta = abs(video_total - audio_total)
    if delta > allowed_delta:
        raise ValueError(
            "Scene audio/video duration mismatch before composition: "
            f"video_total={video_total:.2f}s, audio_total={audio_total:.2f}s, "
            f"delta={delta:.2f}s, allowed={allowed_delta:.2f}s"
        )


def _srt_has_timing(content: str) -> bool:
    return bool(re.search(r"\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}", content))


def _subtitle_matches_dialogue(content: str, dialogue: str) -> bool:
    dialogue_text = _normalize_subtitle_text(dialogue)
    subtitle_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or "-->" in stripped:
            continue
        subtitle_lines.append(stripped)
    subtitle_text = _normalize_subtitle_text("".join(subtitle_lines))
    if not dialogue_text:
        return True
    if not subtitle_text:
        return False
    return dialogue_text in subtitle_text or subtitle_text in dialogue_text


def _normalize_subtitle_text(text: str) -> str:
    return re.sub(r"[\s,，.。!！?？:：;；\"'“”‘’、…-]+", "", text or "").lower()


def _gate_status_passed(review: dict, key: str) -> bool:
    gate = review.get(key)
    if not isinstance(gate, dict) or gate.get("status") != "passed":
        return False
    if gate.get("missing") or gate.get("low"):
        return False
    min_score = gate.get("min_score")
    scores = gate.get("scores")
    if isinstance(min_score, (int, float)) and isinstance(scores, dict):
        for item in scores.values():
            if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
                if float(item["score"]) < float(min_score):
                    return False
    return True


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
    if not _gate_status_passed(review, "platform_reference_gate"):
        return "final normalized video platform reference gate failed"
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
                "exposure, skin tone, color grade, and sharpness feel unified after concat",
                "dialogue reaction beats are readable",
                "burned subtitles are readable and do not cover faces",
                "audio and lip/action timing feel aligned",
                "the full clip is publishable on a mobile short-drama feed",
            ],
            "finishing_features": list(FINAL_COMPOSITION_FINISHING_FEATURES),
        },
    }


def _composition_review_error(report: dict) -> str | None:
    if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return None
    episode_style_gate = report.get("episode_style_consistency_gate")
    if isinstance(episode_style_gate, dict) and episode_style_gate.get("status") != "passed":
        return "final composed episode style consistency gate failed"
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
        if not _gate_status_passed(batch, "platform_reference_gate"):
            return f"composition review batch {index} platform reference gate failed"
        if not _optional_gate_status_passed(batch, "character_distinctiveness_gate"):
            return f"composition review batch {index} character distinctiveness gate failed"
        if not _gate_status_passed(batch, "video_performance_gate"):
            return f"composition review batch {index} performance gate failed"
        if not _gate_status_passed(batch, "episode_continuity_gate"):
            return f"composition review batch {index} episode continuity gate failed"
        if not _gate_status_passed(batch, "final_composition_finishing_gate"):
            return f"composition review batch {index} final composition finishing gate failed"
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
    style_gate = _episode_style_consistency_gate(scenes)
    if style_gate:
        report["episode_style_consistency_gate"] = style_gate
    error = _composition_review_error(report)
    if error:
        report["error"] = error
        attach_repair_queue(report, "video")
        write_report(report_path, report)
        raise ValueError("Final composed video is not production-ready: " + error)
    write_report(report_path, report)
    return report


def _episode_style_consistency_gate(scenes: list[Scene]) -> dict | None:
    """Aggregate keyframe style evidence across the composed episode."""
    scene_scores = []
    missing_reports = []
    min_score = settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE
    style_features = ("style_consistency", "color_grade", "lighting_quality", "production_polish")

    for scene in scenes:
        report = _read_scene_image_quality_report(scene)
        if not report:
            if _scene_image_path(scene) is not None:
                missing_reports.append(getattr(scene, "scene_number", None))
            continue
        candidate = _selected_image_candidate(report)
        gate = candidate.get("platform_aesthetic_gate") if isinstance(candidate.get("platform_aesthetic_gate"), dict) else {}
        scores = gate.get("scores") if isinstance(gate.get("scores"), dict) else {}
        feature_scores = {}
        for feature in style_features:
            item = scores.get(feature)
            if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
                feature_scores[feature] = {
                    "score": float(item["score"]),
                    "evidence": str(item.get("evidence") or "feature reviewed"),
                }
        if feature_scores:
            scene_scores.append({
                "scene_number": getattr(scene, "scene_number", None),
                "features": feature_scores,
                "average": round(sum(item["score"] for item in feature_scores.values()) / len(feature_scores), 2),
            })

    if not scene_scores and not missing_reports:
        return None

    low = {}
    for item in scene_scores:
        scene_number = item.get("scene_number")
        for feature, payload in item["features"].items():
            if payload["score"] < min_score:
                low[f"scene_{scene_number}_{feature}"] = {
                    "score": payload["score"],
                    "evidence": (
                        f"style drift scene {scene_number}: {feature} score {payload['score']}; "
                        f"{payload['evidence']}"
                    ),
                    "scene_number": scene_number,
                    "dimension": feature,
                }
    for scene_number in missing_reports:
        low[f"scene_{scene_number}_missing_style_report"] = {
            "score": 0.0,
            "evidence": f"style drift cannot be ruled out because scene {scene_number} has no image quality report",
            "scene_number": scene_number,
            "dimension": "style_consistency",
        }

    average = 0.0
    if scene_scores:
        average = round(sum(item["average"] for item in scene_scores) / len(scene_scores), 2)
    return {
        "status": "passed" if not low else "needs_review",
        "min_score": min_score,
        "average": average,
        "scenes_reviewed": len(scene_scores),
        "missing_reports": [item for item in missing_reports if item is not None],
        "scores": scene_scores,
        "low": low,
        "missing": [],
    }


def _read_scene_image_quality_report(scene: Scene) -> dict | None:
    image_path = _scene_image_path(scene)
    if image_path is None:
        return None
    path = Path(image_path).with_suffix(".quality.json")
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _scene_image_path(scene: Scene) -> str | Path | None:
    image_path = getattr(scene, "image_path", None)
    return image_path if isinstance(image_path, (str, Path)) else None


def _selected_image_candidate(report: dict) -> dict:
    postprocess = report.get("postprocess_review")
    if isinstance(postprocess, dict):
        return postprocess
    best = report.get("best_candidate")
    if isinstance(best, dict):
        return best
    candidates = report.get("candidates") if isinstance(report.get("candidates"), list) else []
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("status") == "passed":
            return candidate
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


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
