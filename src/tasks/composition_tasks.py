"""
视频合成任务
使用 Celery 异步执行视频合成任务
"""

import json
import hashlib
import math
import re
from pathlib import Path
from typing import Optional
from uuid import uuid4
from src.tasks.celery_app import celery_app
from src.database.database import get_db
from src.database.models import Project, ProjectStatus, Scene, Task as TaskModel, TaskStatus
from src.config import settings
from src.services.generation_review import (
    FINAL_COMPOSITION_FINISHING_FEATURES,
    GenerationReviewService,
    VIDEO_AESTHETIC_FEATURES,
    file_hash,
    write_report,
)
from src.services.repair_queue import attach_repair_queue
from src.services.rhythm_audit import RhythmAuditService
from src.services.asr_service import ASRSegment
from src.services.localization_quality_service import LocalizationQualityService
from src.services.video_composer import get_video_composer
from src.services.video_quality_metrics import temporal_sample_evidence_error, video_boundary_continuity, video_candidate_metrics
from src.services.sequence_plan import build_sequence_context
from src.services.subtitle_generator import get_subtitle_generator
from src.services.subtitle_quality_service import assess_subtitle_timeline
from src.tasks.audio_tasks import has_spoken_dialogue
from src.tasks.video_tasks import _apply_audio_quality_contract
from src.utils.storage import get_project_final_video_path
from src.utils.storage import storage_manager
from src.utils.media_quality_paths import (
    existing_audio_quality_report_path,
    existing_subtitle_quality_report_path,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


SUPPORTED_AUDIO_EDITING_STRATEGIES = {
    "start_at_zero",
    "hold_room_tone_then_dialogue",
    "action_cut_with_short_crossfade",
    "cut_on_action",
    "dialogue_pre_lap",
    "room_tone_bridge",
    "short_crossfade",
}


def _video_version_signature(path: str | Path) -> str | None:
    """Return a cheap version marker for invalidating media-based reviews."""
    try:
        media_path = Path(path)
        stat = media_path.stat()
    except (OSError, TypeError, ValueError):
        return None
    return f"{media_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def composition_input_signature(
    project: Project,
    scenes: list[Scene],
    *,
    add_bgm: bool = False,
    bgm_path: str | Path | None = None,
    bgm_volume: float = 0.3,
) -> str:
    """Fingerprint every source asset and story field used by final composition."""
    from src.tasks.review_tasks import (
        _character_asset_evidence,
        _image_generation_contract_evidence,
        _production_control_asset_evidence,
    )

    payload = {
        "project_id": getattr(project, "id", None),
        "script": getattr(project, "script", None),
        "outline": getattr(project, "outline", None),
        "audio_mix": {
            "add_bgm": bool(add_bgm),
            "bgm_path": _video_version_signature(bgm_path) if bgm_path else None,
            "bgm_volume": round(float(bgm_volume), 4),
        },
        # Final composition review depends on the identity assets that shaped
        # the scene media. A changed character pack must invalidate an old
        # approval even when the existing video bytes are unchanged.
        "character_assets": _character_asset_evidence(project),
        "image_generation_contracts": _image_generation_contract_evidence(scenes),
        "production_controls": _production_control_asset_evidence(project),
        "scenes": [
            {
                "scene_number": getattr(scene, "scene_number", None),
                "dialogue": getattr(scene, "dialogue", None),
                "image": _video_version_signature(getattr(scene, "image_path", "")) if isinstance(getattr(scene, "image_path", None), (str, Path)) else None,
                "video": _video_version_signature(getattr(scene, "video_path", "")) if isinstance(getattr(scene, "video_path", None), (str, Path)) else None,
                "audio": _video_version_signature(getattr(scene, "audio_path", "")) if isinstance(getattr(scene, "audio_path", None), (str, Path)) else None,
                "subtitle": _video_version_signature(getattr(scene, "subtitle_path", "")) if isinstance(getattr(scene, "subtitle_path", None), (str, Path)) else None,
            }
            for scene in sorted(scenes, key=lambda item: int(getattr(item, "scene_number", 0) or 0))
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _native_audio_is_ready_for_video_paths(video_paths: list[str], video_composer) -> bool:
    """Honor per-run native-audio intent without enabling it for old assets."""
    if not video_paths:
        return False
    for video_path in video_paths:
        metadata_path = Path(video_path).with_suffix(".provider.json")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if (
            not isinstance(metadata, dict)
            or metadata.get("native_audio_requested") is not True
            or not isinstance(metadata.get("video_sha256"), str)
            or metadata.get("video_sha256") != file_hash(Path(video_path))
        ):
            return False
        if not video_composer.has_audio_stream(video_path):
            return False
        metrics = video_candidate_metrics(video_path)
        audio_delta = metrics.get("audio_duration_delta_seconds")
        audio_start_delta = metrics.get("audio_video_start_delta_seconds")
        if (
            metrics.get("status") != "available"
            or not metrics.get("audio_present")
            or not isinstance(audio_delta, (int, float))
            or abs(float(audio_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
            or (
                not isinstance(audio_start_delta, (int, float))
                or abs(float(audio_start_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
            )
            or metrics.get("audio_signal_status") != "usable"
            or metrics.get("audio_clipping_status") == "clipped"
        ):
            return False
    return True


def _scene_audio_expected(scene: Scene) -> bool:
    """Return whether a scene is expected to carry any audio into the edit."""
    if bool(getattr(scene, "audio_path", None)):
        return True
    video_path = getattr(scene, "video_path", None)
    if not isinstance(video_path, (str, Path)) or not str(video_path).strip():
        return False
    metadata_path = Path(video_path).with_suffix(".provider.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(metadata, dict)
        and metadata.get("native_audio_requested") is True
        and isinstance(metadata.get("video_sha256"), str)
        and metadata.get("video_sha256") == file_hash(Path(video_path))
    )


def _dialogue_fingerprint(text: str | None) -> str:
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8")).hexdigest()


def _publish_composition_candidate(
    candidate_path: str | Path,
    final_path: str | Path,
    review: dict | None = None,
) -> dict | None:
    """Publish a reviewed composition and its report as one filesystem transaction."""
    candidate = Path(candidate_path)
    final = Path(final_path)
    published_review = dict(review) if isinstance(review, dict) else None
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise ValueError(f"Composition candidate is missing or empty: {candidate}")
    if isinstance(published_review, dict):
        reviewed_hash = published_review.get("video_sha256")
        if isinstance(reviewed_hash, str) and reviewed_hash.strip():
            current_hash = file_hash(candidate)
            if reviewed_hash.strip().lower() != current_hash:
                raise ValueError("Composition review is stale for the current candidate video")

    pairs: list[tuple[Path, Path]] = [(candidate, final)]
    if published_review is not None:
        source_report = candidate.with_suffix(".composition_review.json")
        destination_report = final.with_suffix(".composition_review.json")
        if source_report.is_file():
            report_payload = json.loads(source_report.read_text(encoding="utf-8"))
            if isinstance(report_payload, dict):
                report_payload["path"] = str(destination_report)
                report_payload["video_path"] = str(final)
                write_report(source_report, report_payload)
            pairs.append((source_report, destination_report))
            published_review["path"] = str(destination_report)
            published_review["video_path"] = str(final)

    backups: list[tuple[Path, Path]] = []
    promoted: list[Path] = []
    try:
        for source, destination in pairs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = destination.with_name(f".{destination.name}.{uuid4().hex}.bak")
                destination.replace(backup)
                backups.append((backup, destination))
            source.replace(destination)
            promoted.append(destination)
    except Exception as exc:
        for destination in reversed(promoted):
            destination.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            if backup.exists():
                backup.replace(destination)
        raise RuntimeError(f"Could not publish the composed video: {exc}") from exc
    finally:
        for backup, destination in backups:
            if backup.exists() and destination.exists():
                backup.unlink(missing_ok=True)
    if published_review is not None:
        final_signature = _video_version_signature(final)
        final_hash = file_hash(final)
        published_review["video_signature"] = final_signature
        published_review["video_sha256"] = final_hash
        destination_report = final.with_suffix(".composition_review.json")
        if destination_report.is_file():
            report_payload = json.loads(destination_report.read_text(encoding="utf-8"))
            if isinstance(report_payload, dict):
                report_payload["video_signature"] = final_signature
                report_payload["video_sha256"] = final_hash
                write_report(destination_report, report_payload)
    return published_review


def _persist_failed_composition_review(project_id: int, report: dict) -> Path:
    """Keep a failed composition review after its temporary candidate is cleaned up."""
    destination = storage_manager.get_project_path(project_id) / "reviews" / "final_composition.json"
    payload = dict(report)
    payload["kind"] = "final_composition"
    payload["status"] = payload.get("status") or "needs_review"
    payload["path"] = str(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_report(destination, payload)
    return destination


@celery_app.task(bind=True, name="compose_final_video")
def compose_final_video_task(
    self,
    project_id: int,
    task_id: int,
    add_bgm: bool = False,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.3,
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
    db = None
    composition_candidate_path: Path | None = None
    composition_scratch: list[Path] = []
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
        scene_video_candidates = [scene.video_path for scene in scenes if scene.video_path]
        preserve_native_audio = bool(settings.GENERATION_PREFER_NATIVE_VIDEO_AUDIO) or _native_audio_is_ready_for_video_paths(
            scene_video_candidates, video_composer,
        )
        if preserve_native_audio:
            _require_native_scene_audio(scenes, video_composer)
        else:
            _require_passed_scene_audio(scenes)
        _require_scene_subtitles(scenes, video_composer)
        editing_plan = _require_editing_plan(project, scenes)
        audio_segments = None if preserve_native_audio else _require_audio_video_duration_alignment(scenes, video_composer)

        # 收集所有分镜的视频和音频路径
        video_paths = []
        subtitle_paths = []
        
        for scene in scenes:
            if scene.video_path:
                video_paths.append(scene.video_path)
            if scene.subtitle_path:
                subtitle_paths.append(scene.subtitle_path)
        
        if not video_paths:
            raise ValueError(f"项目没有生成的视频: {project_id}")
        
        logger.info(f"收集到 {len(video_paths)} 个视频片段")
        preserve_provider_quality = any(
            video_composer.has_provider_chroma_fidelity(path) for path in video_paths
        )
        
        # 生成最终视频路径
        final_video_path = get_project_final_video_path(project_id)
        composition_candidate_path = Path(final_video_path).with_name(
            f".{Path(final_video_path).stem}.candidate-{task_id}.mp4"
        )
        
        # 步骤 1: 拼接视频（20%）
        self.update_state(state="PROGRESS", meta={"current": 20, "total": 100, "step": "拼接视频"})
        
        temp_video_path = final_video_path.replace(".mp4", "_temp.mp4")
        temp_video_path = video_composer.concat_videos(
            video_paths,
            temp_video_path,
            preserve_audio=preserve_native_audio,
            preserve_provider_quality=preserve_provider_quality,
            editing_plan=editing_plan,
        )
        if Path(temp_video_path).resolve() not in {
            Path(path).resolve() for path in video_paths
        }:
            composition_scratch.append(
                Path(final_video_path.replace(".mp4", "_temp.mp4"))
            )
        
        # 步骤 2: 同步音频（40%）
        self.update_state(state="PROGRESS", meta={"current": 40, "total": 100, "step": "同步音频"})
        
        if not preserve_native_audio:
            temp_video_with_audio = final_video_path.replace(".mp4", "_with_audio.mp4")
            merged_audio_path = final_video_path.replace(".mp4", "_merged_audio.wav")
            composition_scratch.extend([
                Path(temp_video_with_audio),
                Path(merged_audio_path),
            ])
            audio_path = video_composer.compose_scene_audio(
                audio_segments,
                merged_audio_path,
                editing_plan=editing_plan,
            )
            video_composer.sync_audio_video(
                video_path=temp_video_path,
                audio_path=audio_path,
                output_path=temp_video_with_audio,
            )
            temp_video_path = temp_video_with_audio
        
        # 步骤 3: 添加背景音乐（60%）
        self.update_state(state="PROGRESS", meta={"current": 60, "total": 100, "step": "添加背景音乐"})
        
        if add_bgm and bgm_path:
            temp_video_with_bgm = final_video_path.replace(".mp4", "_with_bgm.mp4")
            composition_scratch.append(Path(temp_video_with_bgm))
            video_composer.add_bgm(
                video_path=temp_video_path,
                bgm_path=bgm_path,
                output_path=temp_video_with_bgm,
                bgm_volume=bgm_volume
            )
            temp_video_path = temp_video_with_bgm
        
        # 步骤 4: 烧录字幕（80%）
        self.update_state(state="PROGRESS", meta={"current": 80, "total": 100, "step": "烧录字幕"})
        
        if subtitle_paths:
            # 合并所有字幕文件
            merged_subtitle_path = final_video_path.replace(".mp4", ".srt")
            composition_scratch.append(Path(merged_subtitle_path))
            _merge_subtitles(
                subtitle_paths,
                merged_subtitle_path,
                scenes,
                video_composer,
                editing_plan=editing_plan,
            )
            
            # 烧录字幕到视频
            subtitle_generator.burn_subtitle(
                video_path=temp_video_path,
                subtitle_path=merged_subtitle_path,
                output_path=str(composition_candidate_path),
                preserve_provider_quality=preserve_provider_quality,
            )
        else:
            # 如果没有字幕，直接重命名为最终视频
            import shutil
            import os

            # concat_videos returns the source path directly when there is only one scene.
            # Keep scene assets intact; only move files that are composition temp outputs.
            if os.path.abspath(temp_video_path) != os.path.abspath(final_video_path):
                if temp_video_path in video_paths:
                    shutil.copy2(temp_video_path, composition_candidate_path)
                else:
                    shutil.move(temp_video_path, composition_candidate_path)
            elif os.path.abspath(temp_video_path) != os.path.abspath(composition_candidate_path):
                shutil.copy2(temp_video_path, composition_candidate_path)

        composition_review = _review_final_composed_video(
            project,
            scenes,
            str(composition_candidate_path),
            add_bgm=add_bgm,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            native_audio_expected=preserve_native_audio,
        )
        composition_review = _publish_composition_candidate(
            composition_candidate_path,
            final_video_path,
            composition_review,
        )
        
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
            task_model.current_step = task_model.total_steps
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
        if db is not None:
            db.rollback()
            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = ProjectStatus.FAILED
                project.final_video_path = None
            task_model = db.query(TaskModel).filter(TaskModel.id == task_id).first()
            if task_model and task_model.project_id == project_id:
                task_model.status = TaskStatus.FAILED
                task_model.error_message = str(e)
            db.commit()
        
        raise
    finally:
        _cleanup_composition_scratch(composition_scratch)
        if composition_candidate_path is not None:
            for candidate_artifact in composition_candidate_path.parent.glob(
                f"{composition_candidate_path.stem}*"
            ):
                if candidate_artifact.is_file():
                    candidate_artifact.unlink(missing_ok=True)
        if db is not None:
            db.close()


def _merge_subtitles(
    subtitle_paths: list,
    output_path: str,
    scenes: list,
    video_composer=None,
    editing_plan: list[dict] | None = None,
) -> None:
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
    
    fallback_subtitle_paths = iter(subtitle_paths or [])
    use_scene_subtitle_paths = any(_scene_subtitle_path(scene) for scene in scenes)

    for scene_index, scene in enumerate(scenes):
        subtitle_path = _scene_subtitle_path(scene)
        if not subtitle_path and not use_scene_subtitle_paths:
            subtitle_path = next(fallback_subtitle_paths, None)

        if subtitle_path:
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

        current_time_offset += _scene_composition_duration(scene, video_composer)
        # The compositor overlaps the next scene by the transition duration.
        # Keep subtitle cues on the rendered timeline instead of accumulating
        # the pre-transition source durations and drifting after every cut.
        next_plan = (editing_plan or [])[scene_index + 1] if scene_index + 1 < len(editing_plan or []) else None
        transition = next_plan.get("transition", {}) if isinstance(next_plan, dict) else {}
        transition_mode = transition.get("video")
        if transition_mode == "crossfade":
            try:
                overlap = float(transition.get("duration_seconds", 0.0) or 0.0)
            except (TypeError, ValueError):
                overlap = 0.0
            if math.isfinite(overlap) and overlap > 0:
                current_time_offset = max(0.0, round(current_time_offset - overlap, 3))
        elif transition_mode in {"hard_cut", "none"}:
            # The FFmpeg transition graph uses a 1ms xfade even for hard cuts
            # so mixed transition plans share one stable filter graph.
            current_time_offset = max(0.0, round(current_time_offset - 0.001, 3))
    
    # Publish the merged timeline atomically so a failed composition never
    # exposes a truncated or partially shifted subtitle file.
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    try:
        temporary.write_text("\n\n".join(merged_subtitles), encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _scene_subtitle_path(scene) -> str | Path | None:
    subtitle_path = getattr(scene, "subtitle_path", None)
    return subtitle_path if isinstance(subtitle_path, (str, Path)) and subtitle_path else None


def _cleanup_composition_scratch(paths: list[str | Path]) -> None:
    """Remove only intermediates created by one composition attempt."""
    sidecar_suffixes = (
        ".quality.json",
        ".provider.json",
        ".continuity.json",
        ".final_review.json",
        ".last_frame.png",
    )
    for raw_path in paths:
        artifact = Path(raw_path)
        for candidate in (
            artifact,
            *(artifact.with_suffix(suffix) for suffix in sidecar_suffixes),
        ):
            candidate.unlink(missing_ok=True)


def _scene_composition_duration(scene, video_composer=None) -> float:
    """Return the time this scene occupies in the final concat timeline."""

    if video_composer and getattr(scene, "video_path", None):
        try:
            duration = float(video_composer._get_duration(scene.video_path))
            if duration > 0:
                return duration
        except Exception as exc:
            logger.warning(
                "Cannot probe scene video duration for subtitle merge: scene={}, error={}",
                getattr(scene, "scene_number", None),
                exc,
            )
    audio_duration = getattr(scene, "audio_duration", None)
    if isinstance(audio_duration, (int, float)) and audio_duration > 0:
        return float(audio_duration)
    if video_composer and getattr(scene, "audio_path", None):
        try:
            duration = float(video_composer._get_duration(scene.audio_path))
            if duration > 0:
                return duration
        except Exception as exc:
            logger.warning(
                "Cannot probe scene audio duration for subtitle merge: scene={}, error={}",
                getattr(scene, "scene_number", None),
                exc,
            )
    return 0.0


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
        provider_metadata_path = video_path.with_suffix(".provider.json")
        if provider_metadata_path.is_file():
            try:
                provider_metadata = json.loads(provider_metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                provider_metadata = {}
            provider_metadata_is_current = (
                isinstance(provider_metadata, dict)
                and isinstance(provider_metadata.get("video_sha256"), str)
                and provider_metadata.get("video_sha256") == file_hash(video_path)
            )
            if provider_metadata_is_current and provider_metadata.get("requested_draft") is True:
                failed.append(f"{scene.scene_number}: provider Draft video must be promoted before composition")
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
            continue
        reported_hash = report.get("video_sha256")
        if not isinstance(reported_hash, str) or not reported_hash.strip():
            failed.append(f"{scene.scene_number}: video quality report is missing video hash evidence")
            continue
        try:
            current_hash = file_hash(video_path)
        except (OSError, ValueError) as exc:
            failed.append(f"{scene.scene_number}: cannot hash current video: {exc}")
            continue
        if reported_hash.strip().lower() != current_hash:
            failed.append(f"{scene.scene_number}: video quality report is stale for current file")
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
        quality_path = existing_audio_quality_report_path(audio_path)
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
        if report.get("audio_path") and Path(str(report["audio_path"])).resolve() != audio_path.resolve():
            failed.append(f"{scene.scene_number}: audio quality report points to a different file")
            continue
        if report.get("dialogue_fingerprint") != _dialogue_fingerprint(scene.dialogue):
            failed.append(f"{scene.scene_number}: audio quality report is stale for current dialogue")
            continue
        reported_speaker = report.get("speaker")
        expected_speaker = getattr(scene, "character_name", None)
        expected_speaker = (
            str(expected_speaker).strip()
            if isinstance(expected_speaker, str) and expected_speaker.strip()
            else "default"
        )
        if reported_speaker is not None and str(reported_speaker).strip() != expected_speaker:
            failed.append(
                f"{scene.scene_number}: audio voice binding is {reported_speaker!r}, expected {expected_speaker!r}"
            )
            continue
        reported_hash = report.get("audio_sha256")
        current_hash = file_hash(audio_path)
        if not isinstance(reported_hash, str) or reported_hash.strip().lower() != current_hash:
            failed.append(f"{scene.scene_number}: audio quality report is stale for current file")
            continue
        gate = report.get("dialogue_audio_quality_gate")
        if not isinstance(gate, dict):
            failed.append(f"{scene.scene_number}: missing dialogue audio quality gate")
            continue
        if gate.get("status") != "passed":
            failed.append(f"{scene.scene_number}: dialogue audio quality gate failed")
    if missing:
        raise ValueError("Missing generated audio for spoken-dialogue scenes: " + ", ".join(missing))
    if failed:
        raise ValueError("Scene audio is not production-ready: " + "; ".join(failed))


def _require_native_scene_audio(scenes: list[Scene], video_composer) -> None:
    missing = [
        str(scene.scene_number)
        for scene in scenes
        if not scene.video_path or not video_composer.has_audio_stream(scene.video_path)
    ]
    if missing:
        raise ValueError(
            "Native audio composition is enabled but these scene videos have no audio stream: "
            + ", ".join(missing)
        )


def _require_scene_subtitles(scenes: list[Scene], video_composer=None) -> None:
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
        subtitle_issue = _subtitle_readability_issue(content)
        if subtitle_issue:
            failed.append(f"{scene.scene_number}: {subtitle_issue}")
            continue
        if not _subtitle_matches_dialogue(content, scene.dialogue or ""):
            failed.append(f"{scene.scene_number}: subtitle text does not cover spoken dialogue")
            continue
        quality_path = existing_subtitle_quality_report_path(subtitle_path)
        if not quality_path.is_file():
            failed.append(f"{scene.scene_number}: missing subtitle quality report")
            continue
        try:
            quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failed.append(f"{scene.scene_number}: invalid subtitle quality report: {exc}")
            continue
        if quality_report.get("status") != "passed":
            failed.append(
                f"{scene.scene_number}: subtitle quality report status="
                f"{quality_report.get('status') or 'unknown'}"
            )
            continue
        expected_text = quality_report.get("expected_text")
        if not isinstance(expected_text, str) or not expected_text.strip() or not _subtitle_matches_dialogue(content, expected_text):
            failed.append(f"{scene.scene_number}: subtitle quality report is stale for current dialogue")
            continue
        reported_hash = quality_report.get("subtitle_sha256")
        current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not isinstance(reported_hash, str) or reported_hash.strip().lower() != current_hash:
            failed.append(f"{scene.scene_number}: subtitle quality report is stale for current file")
            continue
        subtitle_duration = quality_report.get("total_duration_seconds")
        if (
            video_composer is not None
            and scene.video_path
            and isinstance(subtitle_duration, (int, float))
        ):
            try:
                video_duration = float(video_composer._get_duration(scene.video_path))
            except (OSError, TypeError, ValueError):
                video_duration = 0.0
            if video_duration > 0 and float(subtitle_duration) > video_duration + (1.0 / max(int(settings.GENERATION_VIDEO_OUTPUT_FPS), 1)):
                failed.append(
                    f"{scene.scene_number}: subtitle timeline exceeds video duration "
                    f"subtitle={float(subtitle_duration):.3f}s, video={video_duration:.3f}s"
                )
    if missing:
        raise ValueError("Missing subtitle for spoken-dialogue scenes: " + ", ".join(missing))
    if failed:
        raise ValueError("Scene subtitles are not production-ready: " + "; ".join(failed))


def _require_audio_video_duration_alignment(
    scenes: list[Scene],
    video_composer,
    tolerance_seconds: float = 1.0,
    tolerance_ratio: float = 0.15,
) -> list[tuple[str | None, float]]:
    segments = []
    failed = []
    frame_tolerance = 1.0 / max(int(settings.GENERATION_VIDEO_OUTPUT_FPS), 1)
    for scene in scenes:
        video_duration = video_composer._get_duration(scene.video_path) if scene.video_path else 0.0
        if not math.isfinite(video_duration) or video_duration <= 0:
            failed.append(f"{scene.scene_number}: video duration is unreadable")
            continue
        audio_path = None
        if has_spoken_dialogue(scene.dialogue):
            if scene.audio_path:
                audio_path = scene.audio_path
                audio_duration = video_composer._get_duration(audio_path)
                if not math.isfinite(audio_duration) or audio_duration <= 0:
                    failed.append(f"{scene.scene_number}: audio duration is unreadable")
                    continue
                allowed_pause = max(tolerance_seconds, video_duration * tolerance_ratio)
                if audio_duration > video_duration + frame_tolerance or video_duration - audio_duration > allowed_pause:
                    failed.append(
                        f"{scene.scene_number}: audio/video duration mismatch "
                        f"video={video_duration:.2f}s, audio={audio_duration:.2f}s; "
                        "regenerate or split this scene"
                    )
            else:
                failed.append(f"{scene.scene_number}: spoken dialogue audio is missing")
        segments.append((audio_path, video_duration))
    if failed:
        raise ValueError("Scene media durations are not production-ready: " + "; ".join(failed))
    return segments


def _srt_has_timing(content: str) -> bool:
    return bool(re.search(r"\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}", content))


def _subtitle_readability_issue(content: str) -> str | None:
    """Reject overlapping or too-fast subtitle cues before final composition."""
    cues = []
    timing_pattern = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
    )
    for block in re.split(r"\n\s*\n", content.strip()):
        match = timing_pattern.search(block)
        if not match:
            continue
        start = _srt_timestamp_seconds(match.group("start"))
        end = _srt_timestamp_seconds(match.group("end"))
        text = " ".join(
            line.strip() for line in block[match.end():].splitlines() if line.strip()
        )
        if end <= start:
            return "subtitle cue has non-positive duration"
        units = sum(1.0 if "\u3400" <= char <= "\u9fff" else 0.5 for char in text if not char.isspace())
        if units / (end - start) > float(settings.SUBTITLE_MAX_READING_UNITS_PER_SECOND):
            return "subtitle reading speed is too fast"
        cues.append((start, end))
    for previous, current in zip(cues, cues[1:]):
        if current[0] < previous[1] - 1e-3:
            return "subtitle cues overlap"
    return None


def _srt_timestamp_seconds(value: str) -> float:
    hours, minutes, remainder = value.split(":", 2)
    seconds, milliseconds = remainder.split(",", 1)
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


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
    return dialogue_text == subtitle_text


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
    sequence_contexts = []
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
            "has_audio": _scene_audio_expected(scene),
            "has_subtitle": bool(scene.subtitle_path),
        })
        sequence_contexts.append(
            build_sequence_context(
                scenes,
                scene.scene_number,
                sequence_id=f"project-{project.id}",
            ).as_dict()
        )
        if scene.dialogue:
            dialogue_lines.append(str(scene.dialogue))
    rhythm_audit = RhythmAuditService().audit(project, scenes).to_dict()
    return {
        "scene_number": "final_composition",
        "project_id": project.id,
        "project_name": project.name,
        "visual_description": "Full composed mobile short-drama episode assembled from reviewed scene clips.",
        "dialogue": "\n".join(dialogue_lines),
        "scenes": scene_summaries,
        "sequence_contexts": sequence_contexts,
        "rhythm_audit": rhythm_audit,
        "editing_plan": rhythm_audit.get("editing_plan", []),
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
                "cuts follow the provided editorial intent and audio strategy",
            ],
            "finishing_features": list(FINAL_COMPOSITION_FINISHING_FEATURES),
            "editing_plan_contract": {
                "required": True,
                "rule": (
                    "Apply the per-boundary transition contract from rhythm_audit; "
                    "dialogue and action cuts must remain hard cuts, and any visual "
                    "crossfade must stay within its declared duration."
                ),
                "protected_audio_strategies": [
                    "start_at_zero",
                    "hold_room_tone_then_dialogue",
                    "cut_on_action",
                    "dialogue_pre_lap",
                ],
            },
        },
    }


def _require_editing_plan(project: Project, scenes: list[Scene]) -> list[dict]:
    """Validate the editorial contract before any final media is rendered.

    Rhythm reports are evidence for the reviewer, but they also define the
    boundary policy the compositor is expected to honor. Reject malformed or
    unsafe plans here so a stale/missing report cannot silently produce a
    different edit than the one that was reviewed.
    """
    report = RhythmAuditService().audit(project, scenes).to_dict()
    plan = report.get("editing_plan")
    ordered = sorted(list(scenes or []), key=lambda scene: scene.scene_number)
    if not isinstance(plan, list) or len(plan) != len(ordered):
        raise ValueError("Editing plan must cover every scene before final composition")
    allowed_video = {"none", "hard_cut", "crossfade"}
    for scene, item in zip(ordered, plan):
        if not isinstance(item, dict) or item.get("scene_number") != scene.scene_number:
            raise ValueError(f"Editing plan scene order is stale at scene {scene.scene_number}")
        transition = item.get("transition")
        if not isinstance(transition, dict):
            raise ValueError(f"Editing plan transition is missing at scene {scene.scene_number}")
        video_transition = transition.get("video")
        if video_transition not in allowed_video:
            raise ValueError(f"Unsupported editing transition at scene {scene.scene_number}")
        try:
            duration = float(transition.get("duration_seconds"))
        except (TypeError, ValueError):
            raise ValueError(f"Editing transition duration is invalid at scene {scene.scene_number}")
        if not math.isfinite(duration) or duration < 0 or duration > 0.12:
            raise ValueError(f"Editing transition duration exceeds safe limit at scene {scene.scene_number}")
        if transition.get("dialogue_protected") is not True:
            raise ValueError(f"Editing transition does not protect dialogue at scene {scene.scene_number}")
        audio_strategy = item.get("audio_strategy")
        if audio_strategy not in SUPPORTED_AUDIO_EDITING_STRATEGIES:
            raise ValueError(f"Unsupported audio editing strategy at scene {scene.scene_number}")
        if scene == ordered[0] and audio_strategy != "start_at_zero":
            raise ValueError("Opening scene audio strategy must start_at_zero")
        if scene != ordered[0] and audio_strategy == "start_at_zero":
            raise ValueError(f"Non-opening scene audio cannot use start_at_zero at scene {scene.scene_number}")
        if audio_strategy == "dialogue_pre_lap" and video_transition != "hard_cut":
            raise ValueError(f"Dialogue pre-lap requires a hard-cut video transition at scene {scene.scene_number}")
    return plan


def _composition_review_error(report: dict) -> str | None:
    if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return None
    subtitle_visual = report.get("rendered_subtitle_visual")
    if isinstance(subtitle_visual, dict):
        if subtitle_visual.get("status") != "available":
            return (
                "final composed video rendered subtitle visibility evidence is unavailable: "
                f"{subtitle_visual.get('error') or subtitle_visual.get('status') or 'unknown'}"
            )
        if (
            isinstance(subtitle_visual.get("score"), (int, float))
            and subtitle_visual["score"] < 0.2
        ):
            return "final composed video rendered subtitles are not visibly integrated"
    boundary = report.get("technical_boundary_report")
    if isinstance(boundary, dict) and boundary.get("status") == "unavailable":
        return (
            "final composed video shot-boundary metrics are unavailable: "
            f"{boundary.get('error') or 'OpenCV could not inspect adjacent shot boundaries'}"
        )
    if isinstance(boundary, dict) and boundary.get("status") == "available":
        severe_transition_count = int(boundary.get("severe_transition_count") or 0)
        if severe_transition_count > 0:
            return (
                "final composed video has severe exposure/black transitions across "
                f"{severe_transition_count} shot boundary(s)"
            )
        severe_style_transition_count = int(boundary.get("severe_style_transition_count") or 0)
        if severe_style_transition_count > 0:
            return (
                "final composed video has severe color-grade/contrast transitions across "
                f"{severe_style_transition_count} shot boundary(s)"
            )
        geometry_mismatch_count = int(boundary.get("geometry_mismatch_count") or 0)
        if geometry_mismatch_count > 0:
            return (
                "final composed video has mismatched geometry across "
                f"{geometry_mismatch_count} shot boundary(s)"
            )
        fps_mismatch_count = int(boundary.get("fps_mismatch_count") or 0)
        if fps_mismatch_count > 0:
            return (
                "final composed video has mismatched frame rates across "
                f"{fps_mismatch_count} shot boundary(s)"
            )
        pixel_format_mismatch_count = int(boundary.get("pixel_format_mismatch_count") or 0)
        if pixel_format_mismatch_count > 0:
            return (
                "final composed video has mismatched pixel formats across "
                f"{pixel_format_mismatch_count} shot boundary(s)"
            )
        audio_format_mismatch_count = int(boundary.get("audio_format_mismatch_count") or 0)
        if audio_format_mismatch_count > 0:
            return (
                "final composed video has mismatched audio formats across "
                f"{audio_format_mismatch_count} shot boundary(s)"
            )
    technical = report.get("final_technical_metrics")
    temporal_error = temporal_sample_evidence_error(technical, context="final composed video")
    if temporal_error:
        return temporal_error
    if isinstance(technical, dict) and technical.get("status") == "unavailable":
        return (
            "final composed video technical metrics are unavailable: "
            f"{technical.get('error') or 'ffprobe/OpenCV could not inspect the video'}"
        )
    if isinstance(technical, dict) and technical.get("status") == "available":
        if int(technical.get("width") or 0) <= 0 or int(technical.get("height") or 0) <= 0:
            return "final composed video has no readable video geometry"
        max_black_run_seconds = technical.get("max_black_run_seconds")
        if (
            isinstance(max_black_run_seconds, (int, float))
            and max_black_run_seconds > settings.GENERATION_VIDEO_MAX_BLACK_SECONDS
        ):
            return (
                "final composed video contains a black-frame run of "
                f"{max_black_run_seconds:.3f}s, above "
                f"{settings.GENERATION_VIDEO_MAX_BLACK_SECONDS}s"
            )
        black_frame_ratio = technical.get("black_frame_ratio")
        if (
            isinstance(black_frame_ratio, (int, float))
            and black_frame_ratio > settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO
        ):
            return (
                "final composed video contains too many black frames: "
                f"black_frame_ratio={black_frame_ratio:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO:.3f}"
            )
        max_static_run_seconds = technical.get("max_static_run_seconds")
        motion_energy = technical.get("motion_energy")
        if (
            isinstance(max_static_run_seconds, (int, float))
            and max_static_run_seconds > settings.GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS
            and isinstance(motion_energy, (int, float))
            and motion_energy < 0.4
        ):
            return (
                "final composed video contains a frozen/static run of "
                f"{max_static_run_seconds:.3f}s with motion_energy={motion_energy:.3f}"
            )
        brightness_step_p95 = technical.get("brightness_step_p95")
        if (
            isinstance(brightness_step_p95, (int, float))
            and brightness_step_p95 > settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95
        ):
            return (
                "final composed video has temporal exposure jumps: "
                f"brightness_step_p95={brightness_step_p95:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95:.3f}"
            )
        motion_jitter_ratio = technical.get("motion_jitter_ratio")
        if (
            isinstance(motion_jitter_ratio, (int, float))
            and motion_jitter_ratio > settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO
        ):
            return (
                "final composed video has unstable motion cadence: "
                f"motion_jitter_ratio={motion_jitter_ratio:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO:.3f}"
            )
        temporal_jump_ratio = technical.get("temporal_jump_ratio")
        if (
            isinstance(temporal_jump_ratio, (int, float))
            and temporal_jump_ratio > settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO
        ):
            return (
                "final composed video has repeated temporal visual resets: "
                f"temporal_jump_ratio={temporal_jump_ratio:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO:.3f}"
            )
        temporal_jump_p95 = technical.get("temporal_jump_p95")
        if (
            isinstance(temporal_jump_p95, (int, float))
            and temporal_jump_p95 > settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95
        ):
            return (
                "final composed video has an extreme temporal visual reset: "
                f"temporal_jump_p95={temporal_jump_p95:.3f}, "
                f"limit={settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95:.3f}"
            )
        audio_present = technical.get("audio_present") is True
        if audio_present:
            true_peak_db = technical.get("audio_true_peak_db")
            if (
                isinstance(true_peak_db, (int, float))
                and math.isfinite(float(true_peak_db))
                and true_peak_db > settings.GENERATION_VIDEO_AUDIO_TRUE_PEAK_MAX_DB
            ):
                return (
                    "final composed video true peak is too hot: "
                    f"audio_true_peak_db={true_peak_db:.2f}, maximum="
                    f"{settings.GENERATION_VIDEO_AUDIO_TRUE_PEAK_MAX_DB:.2f}"
                )
            integrated_lufs = technical.get("audio_integrated_lufs")
            if isinstance(integrated_lufs, (int, float)) and math.isfinite(float(integrated_lufs)):
                if integrated_lufs < settings.GENERATION_VIDEO_AUDIO_INTEGRATED_LUFS_MIN:
                    return (
                        "final composed video integrated loudness is too quiet: "
                        f"audio_integrated_lufs={integrated_lufs:.2f}, minimum="
                        f"{settings.GENERATION_VIDEO_AUDIO_INTEGRATED_LUFS_MIN:.2f}"
                    )
                if integrated_lufs > settings.GENERATION_VIDEO_AUDIO_INTEGRATED_LUFS_MAX:
                    return (
                        "final composed video integrated loudness is too loud: "
                        f"audio_integrated_lufs={integrated_lufs:.2f}, maximum="
                        f"{settings.GENERATION_VIDEO_AUDIO_INTEGRATED_LUFS_MAX:.2f}"
                    )
            audio_rms_db = technical.get("audio_rms_db")
            if isinstance(audio_rms_db, (int, float)) and math.isfinite(float(audio_rms_db)):
                if audio_rms_db < settings.GENERATION_VIDEO_AUDIO_RMS_MIN_DB:
                    return (
                        "final composed video audio mix is too quiet: "
                        f"audio_rms_db={audio_rms_db:.2f}, minimum="
                        f"{settings.GENERATION_VIDEO_AUDIO_RMS_MIN_DB:.2f}"
                    )
                if audio_rms_db > settings.GENERATION_VIDEO_AUDIO_RMS_MAX_DB:
                    return (
                        "final composed video audio mix is too loud: "
                        f"audio_rms_db={audio_rms_db:.2f}, maximum="
                        f"{settings.GENERATION_VIDEO_AUDIO_RMS_MAX_DB:.2f}"
                    )
        if audio_present and report.get("final_audio_expected") is not True:
            audio_signal_status = technical.get("audio_signal_status")
            if audio_signal_status in {"near_silent", "unavailable"}:
                return (
                    "final composed video audio signal is not usable: "
                    f"{audio_signal_status}"
                )
            if technical.get("audio_clipping_status") == "clipped":
                return "final composed video audio signal is clipped at digital full scale"
            audio_start_delta = technical.get("audio_video_start_delta_seconds")
            if (
                isinstance(audio_start_delta, (int, float))
                and abs(float(audio_start_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
            ):
                return (
                    "final composed video audio/video start offset is out of sync by "
                    f"{abs(float(audio_start_delta)):.3f}s"
                )
            audio_delta = technical.get("audio_duration_delta_seconds")
            if (
                isinstance(audio_delta, (int, float))
                and abs(float(audio_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
            ):
                return (
                    "final composed video audio duration is out of sync by "
                    f"{abs(float(audio_delta)):.3f}s"
                )
        if report.get("final_audio_expected") is True:
            if not technical.get("audio_present"):
                return "final composed video is missing the expected audio stream"
            audio_signal_status = technical.get("audio_signal_status")
            if audio_signal_status == "near_silent":
                return "final composed video audio signal is near-silent despite the expected audio track"
            if audio_signal_status == "unavailable":
                return "final composed video audio signal is not measurable for the expected audio track"
            if technical.get("audio_clipping_status") == "clipped":
                return "final composed video audio signal is clipped at digital full scale"
            audio_start_delta = technical.get("audio_video_start_delta_seconds")
            if (
                isinstance(audio_start_delta, (int, float))
                and abs(float(audio_start_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
            ):
                return (
                    "final composed video audio/video start offset is out of sync by "
                    f"{abs(float(audio_start_delta)):.3f}s"
                )
            audio_delta = technical.get("audio_duration_delta_seconds")
            if not isinstance(audio_delta, (int, float)):
                return "final composed video audio duration is not measurable"
            if abs(float(audio_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS:
                return (
                    "final composed video audio duration is out of sync by "
                    f"{audio_delta:.3f}s"
                )
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
            if not isinstance(value, dict) or not isinstance(value.get("score"), (int, float)):
                return f"composition review batch {index} {key} evidence is missing"
            if float(value["score"]) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
                return f"composition review batch {index} {key} gate failed"
        value = review.get("temporal_consistency")
        if not isinstance(value, dict) or not isinstance(value.get("score"), (int, float)):
            return f"composition review batch {index} temporal_consistency evidence is missing"
        if float(value["score"]) < settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE:
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


def _review_final_composed_video(
    project: Project,
    scenes: list[Scene],
    final_video_path: str,
    *,
    add_bgm: bool = False,
    bgm_path: str | Path | None = None,
    bgm_volume: float = 0.3,
    native_audio_expected: bool = False,
) -> dict | None:
    if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        return None
    report_path = Path(final_video_path).with_suffix(".composition_review.json")
    scene_video_paths = [
        scene.video_path
        for scene in scenes
        if isinstance(scene.video_path, (str, Path)) and str(scene.video_path).strip()
    ]
    technical_boundary_report = video_boundary_continuity(scene_video_paths)
    final_technical_metrics = video_candidate_metrics(final_video_path)
    audio_expected = native_audio_expected or any(_scene_audio_expected(scene) for scene in scenes)
    if isinstance(final_technical_metrics, dict) and final_technical_metrics.get("status") == "available":
        _apply_audio_quality_contract(
            final_technical_metrics,
            {"requested_generate_audio": audio_expected},
        )
    review_payload = _project_final_review_payload(project, scenes)
    # Give the VLM concrete media evidence so it can distinguish an intended
    # dramatic hard cut from an accidental black/exposure/geometry break.
    review_payload["technical_boundary_report"] = technical_boundary_report
    review_payload["final_technical_metrics"] = final_technical_metrics
    review_payload["final_audio_expected"] = audio_expected
    rendered_subtitle_visual = _final_rendered_subtitle_visual_audit(final_video_path)
    if rendered_subtitle_visual is not None:
        review_payload["rendered_subtitle_visual"] = rendered_subtitle_visual
    report = GenerationReviewService().review_video(
        final_video_path,
        review_payload,
        report_path,
    )
    report["path"] = str(report_path)
    report["video_path"] = str(final_video_path)
    report["video_sha256"] = file_hash(Path(final_video_path))
    report["video_signature"] = _video_version_signature(final_video_path)
    report["composition_input_signature"] = composition_input_signature(
        project,
        scenes,
        add_bgm=add_bgm,
        bgm_path=bgm_path,
        bgm_volume=bgm_volume,
    )
    report["audio_mix"] = {
        "add_bgm": bool(add_bgm),
        "bgm_path": str(bgm_path) if bgm_path else None,
        "bgm_volume": round(float(bgm_volume), 4),
        "source_audio_expected": bool(audio_expected),
        "dialogue_ducking": bool(add_bgm and audio_expected),
        "strategy": "sidechain_ducking" if add_bgm and audio_expected else ("music_only" if add_bgm else "none"),
    }
    report["stage"] = "final_composition"
    report["technical_boundary_report"] = technical_boundary_report
    report["final_technical_metrics"] = final_technical_metrics
    report["final_audio_expected"] = audio_expected
    if rendered_subtitle_visual is not None:
        report["rendered_subtitle_visual"] = rendered_subtitle_visual
    style_gate = _episode_style_consistency_gate(scenes)
    if style_gate:
        report["episode_style_consistency_gate"] = style_gate
    error = _composition_review_error(report)
    if error:
        report["error"] = error
        attach_repair_queue(report, "video")
        write_report(report_path, report)
        _persist_failed_composition_review(project.id, report)
        raise ValueError("Final composed video is not production-ready: " + error)
    write_report(report_path, report)
    return report


def _final_rendered_subtitle_visual_audit(final_video_path: str) -> dict | None:
    """Audit burned subtitles in the final composition when its merged SRT exists."""
    subtitle_path = Path(final_video_path).with_suffix(".srt")
    if not subtitle_path.is_file():
        return None
    try:
        timeline = assess_subtitle_timeline(subtitle_path.read_text(encoding="utf-8"))
        segments = [
            ASRSegment(
                start=float(entry["start"]),
                end=float(entry["end"]),
                text=str(entry.get("text") or ""),
                source="rendered_subtitle",
            )
            for entry in timeline.get("entries", [])
            if isinstance(entry, dict)
        ]
        return LocalizationQualityService().inspect_rendered_subtitles(final_video_path, segments)
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "issues": []}


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
        if report.get("status") != "passed":
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
        missing_features = [feature for feature in style_features if feature not in feature_scores]
        if feature_scores or missing_features:
            scene_scores.append({
                "scene_number": getattr(scene, "scene_number", None),
                "features": feature_scores,
                "missing_features": missing_features,
                "average": round(
                    sum(item["score"] for item in feature_scores.values()) / max(len(feature_scores), 1),
                    2,
                ),
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
        for feature in item.get("missing_features", []):
            low[f"scene_{scene_number}_missing_{feature}"] = {
                "score": 0.0,
                "evidence": f"scene {scene_number} image style evidence is missing: {feature}",
                "scene_number": scene_number,
                "dimension": feature,
            }
    for scene_number in missing_reports:
        report_status = None
        if scene_number is not None:
            scene = next(
                (item for item in scenes if getattr(item, "scene_number", None) == scene_number),
                None,
            )
            report = _read_scene_image_quality_report(scene) if scene is not None else None
            report_status = report.get("status") if isinstance(report, dict) else None
        low[f"scene_{scene_number}_missing_style_report"] = {
            "score": 0.0,
            "evidence": (
                (
                    f"style drift cannot be ruled out because scene {scene_number} has no image quality report"
                    if report_status is None
                    else (
                        f"scene {scene_number} image quality report status={report_status}; "
                        "style consistency cannot be accepted"
                    )
                )
            ),
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
    if not isinstance(report, dict):
        return None
    reported_hash = report.get("image_sha256")
    try:
        current_hash = file_hash(Path(image_path))
    except (OSError, ValueError):
        return None
    if not isinstance(reported_hash, str) or reported_hash.strip().lower() != current_hash:
        return None
    return report


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
    total_milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1_000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
