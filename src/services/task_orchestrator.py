"""
任务编排服务
负责创建、管理和调度短剧生产任务链
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from uuid import uuid4
from celery import chain, group
from celery.result import AsyncResult
from sqlalchemy.orm import Session

from src.config import settings
from src.database.models import Project, Scene, Task as TaskModel, TaskStatus, ProjectStatus
from src.services.script_generator import MIN_PRODUCTION_SCENES
from src.services.production_readiness import ProductionReadinessService
from src.services.production_workflow_profile import ProductionWorkflowProfileService
from src.services.generation_review import write_report
from src.services.video_engine_preflight import preflight_production_video_engine
from src.services.task_recovery import (
    load_pending_video_options,
    load_production_video_options,
    save_production_video_options,
)
from src.tasks.celery_app import celery_app, _broadcast_task_event, _update_current_project_state
from src.tasks.image_tasks import generate_image_task, prepare_generation_task
from src.tasks.review_tasks import review_generation_task
from src.tasks.video_tasks import generate_video_task, generate_sequence_video_task
from src.tasks.audio_tasks import generate_audio_task
from src.tasks.subtitle_tasks import generate_subtitle_task
from src.tasks.composition_tasks import compose_final_video_task
from src.tasks.draft_tasks import finalize_draft_generation_task
from src.utils.logger import get_logger
from src.utils.storage import storage_manager

logger = get_logger(__name__)


def _persist_production_readiness_snapshot(
    project_id: int,
    readiness: dict,
    generation_options: dict,
    task_record_id: int | None = None,
) -> Path:
    """Persist the exact gate decision used to release a production task."""
    path = storage_manager.get_project_path(project_id) / "reviews" / "production_readiness_latest.json"
    write_report(path, {
        "kind": "production_readiness_snapshot",
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "task_record_id": task_record_id,
        "generation_options": generation_options,
        "readiness": readiness,
    })
    return path


def _task_result_payload(output_path: str) -> dict:
    """Expose the final artifact and its composition gate when available."""
    result = {"output_path": output_path}
    review_path = Path(output_path).with_suffix(".composition_review.json")
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return result
    if isinstance(review, dict):
        result["composition_review"] = {
            key: review[key]
            for key in ("status", "average", "technical_score", "error")
            if key in review
        }
        result["composition_review_path"] = str(review_path)
    return result


class TaskOrchestrator:
    """
    任务编排服务
    负责创建和管理短剧生产任务链
    """
    
    def __init__(self, db_session: Session):
        """
        初始化任务编排服务
        
        Args:
            db_session: 数据库会话
        """
        self.db = db_session
    
    def create_production_task(
        self,
        project_id: int,
        generate_images: bool = True,
        generate_videos: bool = True,
        generate_audios: bool = True,
        generate_subtitles: bool = True,
        add_bgm: bool = False,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.3,
        provider: Optional[str] = None,
        request_mode: Optional[str] = None,
        multi_shot: Optional[bool] = None,
        sequence_level_multi_shot: Optional[bool] = None,
        native_audio: Optional[bool] = None,
        draft: Optional[bool] = None,
        draft_task_id: Optional[str] = None,
        draft_task_ids: Optional[dict[int, str]] = None,
        model: Optional[str] = None,
        resolution: Optional[str] = None,
        output_format: Optional[str] = None,
        return_last_frame: Optional[bool] = None,
        camera_fixed: Optional[bool] = None,
        watermark: Optional[bool] = None,
        duration_seconds: Optional[float] = None,
        sequence_output_path: Optional[str] = None,
    ) -> str:
        """
        创建生产任务链
        
        Args:
            project_id: 项目ID
            generate_images: 是否生成图像
            generate_videos: 是否生成视频
            generate_audios: 是否生成音频
            generate_subtitles: 是否生成字幕
            add_bgm: 是否添加背景音乐
            bgm_path: 背景音乐文件路径
        
        Returns:
            str: 任务链ID
        
        Raises:
            ValueError: 项目不存在或没有分镜
        """
        # 查询项目
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        # 查询项目的所有分镜
        scenes = self.db.query(Scene).filter(
            Scene.project_id == project_id
        ).order_by(Scene.scene_number).all()
        
        if not scenes:
            raise ValueError(f"项目没有分镜: {project_id}")

        logger.info(f"创建生产任务链: project_id={project_id}, scenes={len(scenes)}")
        
        if project.status == ProjectStatus.IN_PRODUCTION:
            active_task = self.db.query(TaskModel).filter(
                TaskModel.project_id == project_id,
                TaskModel.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            ).order_by(TaskModel.created_at.desc()).first()
            if active_task:
                logger.info(
                    "项目已有活动生产任务，幂等返回: project_id=%s, task_id=%s",
                    project_id,
                    active_task.celery_task_id,
                )
                return active_task.celery_task_id
            raise ValueError("项目正在制作，请等待当前任务结束")
        # The video generator applies this same normalization at request time.
        # Do it before readiness/preflight and persistence as well, otherwise
        # the project can be approved as a single-shot request while the
        # worker actually submits the Seedance multi-shot contract.
        effective_request_mode = request_mode
        normalized_mode = str(request_mode or "").strip().lower()
        if multi_shot is True and normalized_mode in {"", "reference", "reference_to_video"}:
            effective_request_mode = "multi_shot"
        # SVD fallback is an explicit draft-only escape hatch. It must never
        # bypass the production readiness and engine contracts for final video.
        fallback_draft = bool(
            settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK
            and (draft or draft_task_id or draft_task_ids)
        )
        readiness_snapshot_data = None
        if generate_videos and not fallback_draft:
            configured_provider = str(
                os.getenv("GENERATION_PROVIDER") or settings.GENERATION_PROVIDER or ""
            ).strip().lower()
            effective_provider = str(provider or configured_provider).strip().lower()
            per_run_provider = bool(provider and effective_provider != configured_provider)
            per_run_model = bool(model and str(model).strip())
            per_run_request_mode = bool(effective_request_mode and str(effective_request_mode).strip())
            per_run_resolution = bool(resolution and str(resolution).strip())
            per_run_output_format = bool(output_format and str(output_format).strip())
            per_run_duration = duration_seconds is not None
            per_run_engine = per_run_provider or per_run_model or per_run_request_mode or per_run_resolution or per_run_output_format or per_run_duration
            readiness_kwargs = {
                "include_engine_preflight": not per_run_engine,
            }
            if per_run_provider:
                readiness_kwargs["provider_override"] = effective_provider
            if per_run_model:
                readiness_kwargs["model_override"] = str(model).strip()
            if per_run_request_mode:
                readiness_kwargs["request_mode_override"] = str(effective_request_mode).strip().lower()
            if per_run_resolution:
                readiness_kwargs["resolution_override"] = str(resolution).strip().lower()
            if per_run_output_format:
                readiness_kwargs["output_format_override"] = str(output_format).strip().lower()
            if per_run_duration:
                readiness_kwargs["duration_override"] = duration_seconds
            readiness = ProductionReadinessService(self.db).build_report(
                project_id,
                **readiness_kwargs,
            )
            if readiness.get("status") != "ready":
                details = "; ".join(readiness.get("action_items") or [])
                raise ValueError(
                    "Production readiness is not ready. Resolve blockers and warnings before final generation. "
                    f"{details}"
                )
            if per_run_engine:
                preflight_kwargs = {}
                if per_run_provider:
                    preflight_kwargs["provider_override"] = effective_provider
                if per_run_model:
                    preflight_kwargs["model_override"] = str(model).strip()
                if per_run_request_mode:
                    preflight_kwargs["request_mode_override"] = str(effective_request_mode).strip().lower()
                if per_run_resolution:
                    preflight_kwargs["resolution_override"] = str(resolution).strip().lower()
                if per_run_output_format:
                    preflight_kwargs["output_format_override"] = str(output_format).strip().lower()
                if per_run_duration:
                    preflight_kwargs["duration_override"] = duration_seconds
                video_engine = preflight_production_video_engine(**preflight_kwargs)
            else:
                video_engine = preflight_production_video_engine()
            if video_engine.get("status") != "ready_for_production_video_test":
                detail = "; ".join(video_engine.get("action_items") or [])
                raise ValueError(
                    "Production video engine is not ready. "
                    "Configure a prompt-aware ComfyUI video workflow or set "
                    "GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK=true for draft-only runs. "
                    f"{detail}"
                )
            if len(scenes) < MIN_PRODUCTION_SCENES:
                raise ValueError(
                    "Short-drama production requires at least "
                    f"{MIN_PRODUCTION_SCENES} atomic scenes; current project has {len(scenes)}. "
                    "Expand the script or split multi-action scenes before production."
                )
            readiness["video_engine"] = video_engine
            readiness_snapshot_data = (readiness, {
                    "provider": effective_provider,
                    "model": str(model).strip() if model else None,
                    "request_mode": effective_request_mode,
                    "multi_shot": bool(multi_shot),
                    "sequence_level_multi_shot": bool(sequence_level_multi_shot),
                    "native_audio": native_audio,
                    "resolution": resolution,
                    "output_format": output_format,
                    "duration_seconds": duration_seconds,
                    "draft": bool(draft),
                })
        # Persist the real task ID before a worker can consume the first step.
        self._reserve_project(project_id)
        task_model = TaskModel(
            project_id=project_id, celery_task_id=str(uuid4()),
            status=TaskStatus.PENDING, progress=0.0,
            total_steps=self._calculate_total_steps(
                len(scenes), generate_images, generate_videos,
                generate_audios, generate_subtitles,
                sequence_level_multi_shot=bool(sequence_level_multi_shot),
                draft_only=bool(draft and generate_videos and not draft_task_id and not draft_task_ids),
            ),
        )
        self.db.add(task_model)
        self.db.flush()
        readiness_snapshot_path = None
        if readiness_snapshot_data:
            readiness, generation_options = readiness_snapshot_data
            readiness_snapshot_path = _persist_production_readiness_snapshot(
                project_id,
                readiness,
                generation_options,
                task_record_id=task_model.id,
            )
            generation_options["readiness_snapshot_path"] = str(readiness_snapshot_path)
            generation_options["readiness_task_record_id"] = task_model.id
        save_production_video_options(
            project_id,
            task_model.id,
            {
                "provider": provider,
                "request_mode": effective_request_mode,
                "multi_shot": multi_shot,
                "sequence_level_multi_shot": sequence_level_multi_shot,
                "native_audio": native_audio,
                "draft": draft,
                "draft_task_id": draft_task_id,
                "draft_task_ids": draft_task_ids,
                "model": model,
                "resolution": resolution,
                "output_format": output_format,
                "return_last_frame": return_last_frame,
                "camera_fixed": camera_fixed,
                "watermark": watermark,
                "duration_seconds": duration_seconds,
                "add_bgm": add_bgm,
                "bgm_path": bgm_path,
                "bgm_volume": bgm_volume,
                "readiness_snapshot_path": str(readiness_snapshot_path) if readiness_snapshot_path else None,
                "readiness_task_record_id": task_model.id if readiness_snapshot_path else None,
            },
        )
        task_chain = self._build_task_chain(
            project_id, task_model.id, scenes, generate_images, generate_videos,
            generate_audios, generate_subtitles, add_bgm, bgm_path,
            provider=provider, request_mode=effective_request_mode,
            multi_shot=multi_shot, native_audio=native_audio,
            sequence_level_multi_shot=sequence_level_multi_shot,
            draft=draft, draft_task_id=draft_task_id,
            draft_task_ids=draft_task_ids,
            model=model,
            resolution=resolution, output_format=output_format,
            return_last_frame=return_last_frame, camera_fixed=camera_fixed,
            watermark=watermark, duration_seconds=duration_seconds,
            sequence_output_path=sequence_output_path,
            bgm_volume=bgm_volume,
        )
        result = task_chain.freeze()
        task_model.celery_task_id = result.id
        project.status = ProjectStatus.IN_PRODUCTION
        project.final_video_path = None
        self.db.commit()
        try:
            task_chain.apply_async()
        except Exception as exc:
            task_model.status = TaskStatus.FAILED
            task_model.error_message = f"任务投递失败: {exc}"
            project.status = ProjectStatus.FAILED
            self.db.commit()
            raise
        return result.id

    def create_scene_repair_task(
        self,
        project_id: int,
        scene_number: int,
        action: str,
    ) -> str:
        return self.create_repair_batch_task(project_id, [{"scene_number": scene_number, "action": action}])

    def create_final_composition_repair_task(self, project_id: int) -> str:
        """Recompose a reviewed episode without regenerating its scene media."""
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if project.status == ProjectStatus.IN_PRODUCTION:
            raise ValueError("项目正在制作，请等待当前任务结束")
        scenes = self.db.query(Scene).filter(Scene.project_id == project_id).all()
        if not scenes:
            raise ValueError("项目没有可合成的分镜")
        inherited_options = load_production_video_options(project_id) or {}
        task_model = TaskModel(
            project_id=project_id,
            celery_task_id=str(uuid4()),
            status=TaskStatus.PENDING,
            progress=0.0,
            total_steps=1,
            current_step=0,
        )
        previous_status, previous_final = project.status, project.final_video_path
        self._reserve_project(project_id)
        self.db.add(task_model)
        self.db.flush()
        save_production_video_options(project_id, task_model.id, inherited_options)
        project.final_video_path = None
        compose = compose_final_video_task.si(
            project_id,
            task_model.id,
            add_bgm=bool(inherited_options.get("add_bgm", False)),
            bgm_path=inherited_options.get("bgm_path"),
            bgm_volume=float(inherited_options.get("bgm_volume", 0.3)),
        )
        task = chain(compose)
        result = task.freeze()
        task_model.celery_task_id = result.id
        self.db.commit()
        try:
            task.apply_async()
        except Exception as exc:
            task_model.status = TaskStatus.FAILED
            task_model.error_message = f"最终合成返工投递失败: {exc}"
            project.status, project.final_video_path = previous_status, previous_final
            self.db.commit()
            raise
        return result.id

    def create_repair_batch_task(self, project_id: int, items: list[dict]) -> str:
        """Run one review after all selected repairs, with audio before dependent video."""
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if project.status == ProjectStatus.IN_PRODUCTION:
            raise ValueError("项目正在制作，请等待当前任务结束")
        if not items:
            raise ValueError("返工动作不能为空")
        inherited_video_options = load_production_video_options(project_id) or {}
        # Scene repairs are atomic; a project-level sequence request must not
        # accidentally turn one repaired shot into another full sequence job.
        inherited_video_options["sequence_level_multi_shot"] = False
        inherited_video_options["draft"] = False
        image_actions = {
            "regenerate_keyframe_with_identity_lock",
            "regenerate_keyframe_with_role_separation",
            "regenerate_keyframe_with_prop_constraints",
            "refine_prompt_composition",
            "refine_project_style_consistency",
            "refine_face_aesthetic_detail",
        }
        video_actions = {
            "lower_motion_and_regenerate_video",
            "increase_motion_and_regenerate_video",
            "regenerate_video_with_performance_direction",
            "refine_video_commercial_aesthetic",
            "refine_final_composition_finish",
            "fix_video_output_contract",
        }
        audio_actions = {
            "refine_dialogue_audio_delivery",
        }
        blocked_actions = {
            "regenerate_character_identity": "请先在角色参考页重新生成身份方案和参考图，再重做关键帧。",
            "rewrite_short_drama_story_rhythm": "请先重写短剧剧本节奏：开头钩子、冲突升级、反转、结尾钩子、情绪递进和原子镜头，再重新生成。",
            "split_scene": "请先把该分镜拆成更简单的原子镜头，再重新生成。",
            "start_local_reviewer": "请先启动 llama.cpp 视觉审核服务，再重跑审核或生成。",
            "manual_review": "该问题需要人工复核后再选择具体返工动作。",
        }
        entries = []
        scene_stages = set()
        for item in items:
            scene_number, action = item.get("scene_number"), item.get("action")
            if isinstance(scene_number, bool) or not isinstance(scene_number, int) or scene_number <= 0:
                raise ValueError("返工分镜编号必须为正整数")
            if action in blocked_actions:
                raise ValueError(blocked_actions[action])
            if action not in image_actions | video_actions | audio_actions:
                raise ValueError(f"不支持的返工动作: {action}")
            scene = self.db.query(Scene).filter(
                Scene.project_id == project_id, Scene.scene_number == scene_number,
            ).first()
            if not scene:
                raise ValueError(f"分镜不存在: {scene_number}")
            stage = "audio" if action in audio_actions else "visual"
            if (scene_number, stage) in scene_stages:
                raise ValueError("同一分镜每轮仅支持一个画面返工和一个音频返工")
            scene_stages.add((scene_number, stage))
            if action in video_actions and not scene.image_path:
                raise ValueError("视频返工需要先有已通过的关键帧，请先重做关键帧。")
            if action in audio_actions and not scene.dialogue:
                raise ValueError("音频返工需要分镜有对白。")
            entries.append((scene, action))
        has_visual = any(action not in audio_actions for _scene, action in entries)
        review_after_repair = has_visual or bool(entries and all(
            scene.video_path for scene in self.db.query(Scene).filter(Scene.project_id == project_id).all()
        ))
        if has_visual:
            profile_report = ProductionWorkflowProfileService().validate_profile()
            if profile_report.get("status") != "valid":
                details = []
                if profile_report.get("missing"):
                    details.append("missing=" + ",".join(profile_report["missing"]))
                if profile_report.get("stale"):
                    details.append("stale=" + ",".join(profile_report["stale"]))
                if profile_report.get("missing_capabilities"):
                    details.append("capabilities=" + ",".join(profile_report["missing_capabilities"]))
                raise ValueError(
                    "返工生成需要先通过本机 ComfyUI 生产 workflow profile 校验"
                    + (": " + "; ".join(details) if details else "")
                )

        # Every repair is followed by a fresh review and a final composition.
        # Without the latter, repaired scene assets never reach the deliverable.
        total_steps = sum(2 if action in image_actions | audio_actions else 1 for _scene, action in entries)
        if review_after_repair:
            total_steps += 2  # generation review + final composition
        task_model = TaskModel(
            project_id=project_id,
            celery_task_id=str(uuid4()),
            status=TaskStatus.PENDING,
            progress=0.0,
            total_steps=total_steps,
            current_step=0,
        )
        previous_status, previous_final = project.status, project.final_video_path
        self._reserve_project(project_id)
        self.db.add(task_model)
        self.db.flush()
        save_production_video_options(project_id, task_model.id, inherited_video_options)

        project.final_video_path = None
        previous_assets = {
            scene.id: (scene, {key: getattr(scene, key) for key in (
                "image_path", "video_path", "audio_path", "audio_duration", "subtitle_path",
            )}) for scene, _action in entries
        }
        steps = []
        for scene, action in sorted(entries, key=lambda entry: entry[1] not in audio_actions):
            if action in audio_actions:
                scene.audio_path = None
                scene.audio_duration = None
                scene.subtitle_path = None
                steps.extend([
                    generate_audio_task.si(scene.id, scene.dialogue, scene.character_name or "default", project_id, task_model.id, repair_action=action),
                    generate_subtitle_task.si(scene.id, project_id, task_model.id),
                ])
            elif action in image_actions:
                scene.image_path = None
                scene.video_path = None
                steps.extend([
                    generate_image_task.si(scene.id, scene.image_prompt or scene.visual_description, project_id, task_model.id, repair_action=action),
                    generate_video_task.si(scene.id, project_id, task_model.id, **inherited_video_options),
                ])
            else:
                scene.video_path = None
                steps.append(generate_video_task.si(
                    scene.id, project_id, task_model.id,
                    **inherited_video_options, repair_action=action,
                ))
        if review_after_repair:
            steps.append(review_generation_task.si(project_id, task_model.id))
            steps.append(compose_final_video_task.si(
                project_id,
                task_model.id,
                add_bgm=bool(inherited_video_options.get("add_bgm", False)),
                bgm_path=inherited_video_options.get("bgm_path"),
                bgm_volume=float(inherited_video_options.get("bgm_volume", 0.3)),
            ))
        task = chain(*steps)
        result = task.freeze()
        task_model.celery_task_id = result.id
        self.db.commit()
        try:
            task.apply_async()
        except Exception as exc:
            task_model.status = TaskStatus.FAILED
            task_model.error_message = f"返工任务投递失败: {exc}"
            project.status, project.final_video_path = previous_status, previous_final
            for scene, values in previous_assets.values():
                for key, value in values.items():
                    setattr(scene, key, value)
            self.db.commit()
            raise
        return result.id

    def _reserve_project(self, project_id: int) -> None:
        reserved = self.db.query(Project).filter(
            Project.id == project_id, Project.status != ProjectStatus.IN_PRODUCTION,
        ).update({Project.status: ProjectStatus.IN_PRODUCTION}, synchronize_session="fetch")
        if reserved == 0:
            raise ValueError("项目正在制作，请等待当前任务结束")

    @staticmethod
    def _repair_total_steps(
        action: str,
        image_actions: set[str],
        video_actions: set[str],
        audio_actions: set[str],
    ) -> int:
        if action in image_actions:
            return 3  # keyframe, dependent video, sampled-frame review
        if action in video_actions:
            return 2  # video, sampled-frame review
        if action in audio_actions:
            return 2  # dialogue audio, dependent subtitle
        return 1

    def _calculate_total_steps(
        self,
        scene_count: int,
        generate_images: bool,
        generate_videos: bool,
        generate_audios: bool,
        generate_subtitles: bool,
        sequence_level_multi_shot: bool = False,
        draft_only: bool = False,
    ) -> int:
        """
        计算总步骤数
        
        Args:
            scene_count: 分镜数量
            generate_images: 是否生成图像
            generate_videos: 是否生成视频
            generate_audios: 是否生成音频
            generate_subtitles: 是否生成字幕
        
        Returns:
            int: 总步骤数
        """
        steps = 0
        if generate_images:
            steps += scene_count
        if generate_videos:
            steps += 1 if sequence_level_multi_shot and scene_count > 1 else scene_count
        if generate_audios:
            steps += scene_count
        if generate_subtitles:
            steps += scene_count
        steps += 1 if draft_only else 3  # Draft finalizer, or review + composition.
        return steps
    
    def _build_task_chain(
        self,
        project_id: int,
        task_id: int,
        scenes: List[Scene],
        generate_images: bool,
        generate_videos: bool,
        generate_audios: bool,
        generate_subtitles: bool,
        add_bgm: bool,
        bgm_path: Optional[str],
        provider: Optional[str] = None,
        request_mode: Optional[str] = None,
        multi_shot: Optional[bool] = None,
        sequence_level_multi_shot: Optional[bool] = None,
        native_audio: Optional[bool] = None,
        draft: Optional[bool] = None,
        draft_task_id: Optional[str] = None,
        draft_task_ids: Optional[dict[int, str]] = None,
        model: Optional[str] = None,
        resolution: Optional[str] = None,
        output_format: Optional[str] = None,
        return_last_frame: Optional[bool] = None,
        camera_fixed: Optional[bool] = None,
        watermark: Optional[bool] = None,
        duration_seconds: Optional[float] = None,
        sequence_output_path: Optional[str] = None,
        bgm_volume: float = 0.3,
    ) -> chain:
        """
        构建任务链
        
        任务链结构：
        1. 并行生成所有分镜的图像
        2. 并行生成所有分镜的音频，确定实测对白时长
        3. 串行生成所有分镜的视频（依赖图像与对白时长）
        4. 并行生成所有分镜的字幕（依赖音频）
        5. 整批采样复审，然后合成最终视频
        
        Args:
            project_id: 项目ID
            task_id: 任务ID
            scenes: 分镜列表
            generate_images: 是否生成图像
            generate_videos: 是否生成视频
            generate_audios: 是否生成音频
            generate_subtitles: 是否生成字幕
            add_bgm: 是否添加背景音乐
            bgm_path: 背景音乐文件路径
        
        Returns:
            chain: Celery 任务链
        """
        tasks = [prepare_generation_task.si(project_id, task_id, generate_images)]
        video_options = {
            key: value for key, value in {
                "provider": provider,
                "request_mode": request_mode,
                "multi_shot": multi_shot,
                "sequence_level_multi_shot": sequence_level_multi_shot,
                "SEQUENCE_LEVEL_MULTI_SHOT": sequence_level_multi_shot,
                "native_audio": native_audio,
                "draft": draft,
                "draft_task_id": draft_task_id,
                "MODEL": model,
                "RESOLUTION": resolution,
                "OUTPUT_FORMAT": output_format,
                "RETURN_LAST_FRAME": return_last_frame,
                "CAMERA_FIXED": camera_fixed,
                "WATERMARK": watermark,
                "DURATION_SECONDS": duration_seconds,
                "SEQUENCE_OUTPUT_PATH": sequence_output_path,
            }.items() if value is not None
        }
        
        # 1. 图像生成任务（并行）
        if generate_images:
            image_tasks = chain(*[
                generate_image_task.si(
                    scene.id,
                    scene.image_prompt or scene.visual_description,
                    project_id,
                    task_id
                )
                for scene in scenes
            ])
            tasks.append(image_tasks)
        
        # Measure speech before planning video duration.
        if generate_audios:
            audio_tasks = group([
                generate_audio_task.si(
                    scene.id,
                    scene.dialogue or "",
                    scene.character_name or "default",
                    project_id,
                    task_id
                )
                for scene in scenes
            ])
            tasks.append(audio_tasks)

        # GPU video generation remains serialized after keyframes and dialogue audio.
        if generate_videos:
            if sequence_level_multi_shot and len(scenes) > 1:
                video_tasks = generate_sequence_video_task.si(
                    [scene.id for scene in scenes],
                    project_id,
                    task_id,
                    **video_options,
                )
            else:
                video_tasks = chain(*[
                    generate_video_task.si(
                        scene.id,
                        project_id,
                        task_id,
                        **{
                            **video_options,
                            **({"draft_task_id": draft_task_ids[scene.id]} if draft_task_ids and scene.id in draft_task_ids else {}),
                        },
                    )
                    for scene in scenes
                ])
            tasks.append(video_tasks)
        
        # 4. 字幕生成任务（并行，依赖音频）
        if generate_subtitles:
            subtitle_tasks = group([
                generate_subtitle_task.si(
                    scene.id,
                    project_id,
                    task_id
                )
                for scene in scenes
            ])
            tasks.append(subtitle_tasks)
        
        draft_only = bool(draft and generate_videos and not draft_task_id and not draft_task_ids)
        if draft_only:
            tasks.append(finalize_draft_generation_task.si(project_id, task_id))
            return chain(*tasks)

        # 5. Final production review and composition.
        tasks.append(review_generation_task.si(project_id, task_id))
        compose_task = compose_final_video_task.si(
            project_id,
            task_id,
            add_bgm=add_bgm,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
        )
        tasks.append(compose_task)
        
        # 构建任务链
        return chain(*tasks)
    
    def get_task_status(self, celery_task_id: str) -> Dict[str, Any]:
        """
        获取任务状态
        
        Args:
            celery_task_id: Celery 任务ID
        
        Returns:
            dict: 任务状态信息
        """
        task_model = self.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        if not task_model:
            return {"status": "unknown", "message": "任务不存在"}
        result = {
            "task_id": task_model.id, "celery_task_id": celery_task_id,
            "project_id": task_model.project_id,
            "status": task_model.status.value,
            "progress": task_model.progress,
            "current_step": task_model.current_step,
            "total_steps": task_model.total_steps,
            "error_message": task_model.error_message,
            "error": task_model.error_message,
            "result": _task_result_payload(task_model.result_path) if task_model.result_path else None,
            "created_at": task_model.created_at.isoformat() if task_model.created_at else None,
            "updated_at": task_model.updated_at.isoformat() if task_model.updated_at else None,
        }
        production_options = load_production_video_options(
            task_model.project_id,
            task_id=task_model.id,
        )
        if production_options:
            result["production_options"] = production_options
        # Provider polling progress lives in Celery metadata while the
        # production task counters live in the database. Expose both so the
        # workbench can show a live Seedance stage without corrupting the
        # overall completed-step counter.
        try:
            async_result = AsyncResult(celery_task_id, app=celery_app)
            info = async_result.info
            if isinstance(info, dict):
                if async_result.state == "PROGRESS" and isinstance(info.get("current"), (int, float)):
                    result["provider_progress"] = max(0, min(99, float(info["current"])))
                stage = info.get("step") or info.get("stage")
                if stage:
                    result["provider_stage"] = str(stage)
                result["provider_state"] = async_result.state
                if info.get("provider_task_id"):
                    result["provider_task_id"] = str(info["provider_task_id"])
                if info.get("provider_request_submitted") is True:
                    result["provider_request_submitted"] = True
                if info.get("provider_status"):
                    result["provider_status"] = str(info["provider_status"])
                if info.get("provider_error"):
                    result["provider_error"] = str(info["provider_error"])
        except Exception as exc:
            logger.debug("Could not read live provider progress for {}: {}", celery_task_id, exc)
        return result

    def cancel_task(self, celery_task_id: str) -> bool:
        """
        取消任务
        
        Args:
            celery_task_id: Celery 任务ID
        
        Returns:
            bool: 是否成功取消
        """
        # 查询任务记录
        task_model = self.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        
        if not task_model:
            logger.warning(f"任务不存在: {celery_task_id}")
            return False
        
        # 检查任务状态
        if task_model.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            logger.warning(f"任务已结束，无法取消: {celery_task_id}, status={task_model.status}")
            return False
        
        # Claim cancellation against the durable state, not this request's
        # cached ORM status. A worker may have started or finished meanwhile.
        cancellation = {
            TaskModel.status: TaskStatus.CANCELLED,
            TaskModel.error_message: "已请求取消，当前步骤结束后停止后续生成",
        }
        task_query = self.db.query(TaskModel).filter(TaskModel.id == task_model.id)
        was_pending = task_query.filter(TaskModel.status == TaskStatus.PENDING).update(
            cancellation, synchronize_session=False,
        )
        if not was_pending:
            cancelled_running = task_query.filter(TaskModel.status == TaskStatus.RUNNING).update(
                cancellation, synchronize_session=False,
            )
            if not cancelled_running:
                self.db.refresh(task_model)
                return False
        self.db.refresh(task_model)
        if was_pending:
            _update_current_project_state(self.db, task_model, ProjectStatus.SCRIPT_GENERATED)
        event = {
            "type": "status_update", "project_id": task_model.project_id,
            "task_id": str(task_model.celery_task_id), "status": "cancelled",
            "progress": float(task_model.progress or 0.0) / 100.0,
        }
        self.db.commit()

        # The database gate also stops queued workers and provider polling.
        # A broker outage must not erase an already accepted cancellation.
        try:
            celery_app.control.revoke(celery_task_id, terminate=False)
        except Exception as exc:
            logger.warning("Task cancellation persisted but broker revoke failed: {}: {}", celery_task_id, exc)
        _broadcast_task_event(event["project_id"], event)

        logger.info(f"任务已取消: {celery_task_id}")
        
        return True
    
    def retry_failed_task(self, celery_task_id: str) -> Optional[str]:
        """
        重试失败的任务
        
        Args:
            celery_task_id: Celery 任务ID
        
        Returns:
            Optional[str]: 新任务的 Celery 任务ID，如果无法重试则返回 None
        """
        # 查询任务记录
        task_model = self.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        
        if not task_model:
            logger.warning(f"任务不存在: {celery_task_id}")
            return None
        
        # 检查任务状态
        if task_model.status != TaskStatus.FAILED:
            logger.warning(f"任务未失败，无法重试: {celery_task_id}, status={task_model.status}")
            return None
        
        # 检查重试次数
        if task_model.retry_count >= 3:
            logger.warning(f"任务重试次数已达上限: {celery_task_id}, retry_count={task_model.retry_count}")
            return None
        
        logger.info(f"重试任务: {celery_task_id}, retry_count={task_model.retry_count}")
        
        # 创建新的生产任务
        try:
            scenes = self.db.query(Scene).filter(
                Scene.project_id == task_model.project_id,
            ).order_by(Scene.scene_number).all()
            pending_options = load_pending_video_options(
                task_model.project_id,
                [scene.id for scene in scenes],
                task_model.id,
            )
            retry_options = load_production_video_options(
                task_model.project_id,
                task_id=task_model.id,
            ) or {}
            # Audit bindings belong to the old task, not the new request.
            # create_production_task builds a fresh readiness snapshot and
            # does not accept these internal metadata fields as arguments.
            retry_options.pop("readiness_snapshot_path", None)
            retry_options.pop("readiness_task_record_id", None)
            if pending_options:
                # The remote task is already paid/accepted. Re-run only the
                # video stage so the original image/audio mtimes and request
                # fingerprint remain intact; the provider adapter will resume
                # the existing task instead of submitting a duplicate.
                # Sidecars describe generation, not the episode's finishing
                # settings. Keep the exact task snapshot's BGM controls.
                retry_options.update({
                    key: value for key, value in pending_options.items()
                    if value is not None and key in {
                        "provider", "request_mode", "multi_shot", "native_audio",
                        "draft", "draft_task_id", "draft_task_ids", "model", "resolution",
                        "output_format", "return_last_frame", "camera_fixed",
                        "watermark", "duration_seconds", "sequence_level_multi_shot",
                        "sequence_output_path", "add_bgm", "bgm_path", "bgm_volume",
                    }
                })
                retry_options.update({
                    "generate_images": False,
                    "generate_audios": False,
                    "generate_subtitles": False,
                    "generate_videos": True,
                })
            new_task_id = self.create_production_task(
                project_id=task_model.project_id,
                **retry_options,
            )
            
            # 更新原任务的重试次数
            task_model.retry_count += 1
            replacement = self.db.query(TaskModel).filter(TaskModel.celery_task_id == new_task_id).first()
            if replacement:
                replacement.retry_count = task_model.retry_count
            self.db.commit()
            
            return new_task_id
        except Exception as e:
            logger.error(f"重试任务失败: {celery_task_id}, error={e}")
            return None
    
    def update_task_progress(self, task_id: int, progress: float) -> None:
        """
        更新任务进度
        
        Args:
            task_id: 任务ID
            progress: 进度（0-100）
        """
        task_model = self.db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if task_model:
            task_model.progress = max(task_model.progress, min(100.0, max(0.0, progress)))
            self.db.commit()
            logger.debug(f"任务进度已更新: task_id={task_id}, progress={progress}")
    
    def mark_task_completed(self, task_id: int, output_path: str) -> None:
        """
        标记任务完成
        
        Args:
            task_id: 任务ID
            output_path: 输出文件路径
        """
        task_model = self.db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if task_model:
            task_model.status = TaskStatus.COMPLETED
            task_model.result_path = output_path
            task_model.progress = 100.0
            self.db.commit()
            logger.info(f"任务已完成: task_id={task_id}, output_path={output_path}")
    
    def mark_task_failed(self, task_id: int, error_message: str) -> None:
        """
        标记任务失败
        
        Args:
            task_id: 任务ID
            error_message: 错误信息
        """
        task_model = self.db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if task_model:
            task_model.status = TaskStatus.FAILED
            task_model.error_message = error_message
            self.db.commit()
            logger.error(f"任务失败: task_id={task_id}, error={error_message}")


# 全局单例
_task_orchestrator: Optional[TaskOrchestrator] = None


def get_task_orchestrator() -> TaskOrchestrator:
    """
    获取任务编排服务实例（单例模式）
    
    Returns:
        TaskOrchestrator: 任务编排服务实例
    """
    global _task_orchestrator
    if _task_orchestrator is None:
        from src.database.session import get_db_session
        db_session = next(get_db_session())
        _task_orchestrator = TaskOrchestrator(db_session)
    return _task_orchestrator


def cleanup_task_orchestrator() -> None:
    """
    清理任务编排服务实例
    """
    global _task_orchestrator
    _task_orchestrator = None
