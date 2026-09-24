"""
任务编排服务
负责创建、管理和调度短剧生产任务链
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import uuid4
from celery import chain, group
from celery.result import AsyncResult, GroupResult
from sqlalchemy.orm import Session

from src.config import settings
from src.database.models import Project, Scene, Task as TaskModel, TaskStatus, ProjectStatus
from src.services.script_generator import MIN_PRODUCTION_SCENES
from src.services.production_readiness import ProductionReadinessService
from src.services.video_engine_preflight import preflight_production_video_engine
from src.tasks.celery_app import celery_app
from src.tasks.image_tasks import generate_image_task, prepare_generation_task
from src.tasks.review_tasks import review_generation_task
from src.tasks.video_tasks import generate_video_task
from src.tasks.audio_tasks import generate_audio_task
from src.tasks.subtitle_tasks import generate_subtitle_task
from src.tasks.composition_tasks import compose_final_video_task
from src.utils.logger import get_logger

logger = get_logger(__name__)


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
        bgm_path: Optional[str] = None
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
            raise ValueError("项目正在制作，请等待当前任务结束")
        if generate_videos and not settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK:
            readiness = ProductionReadinessService(self.db).build_report(
                project_id,
                include_engine_preflight=True,
            )
            if readiness.get("status") != "ready":
                details = "; ".join(readiness.get("action_items") or [])
                raise ValueError(
                    "Production readiness is not ready. Resolve blockers and warnings before final generation. "
                    f"{details}"
                )
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
        # Persist the real task ID before a worker can consume the first step.
        task_model = TaskModel(
            project_id=project_id, celery_task_id=str(uuid4()),
            status=TaskStatus.PENDING, progress=0.0,
            total_steps=self._calculate_total_steps(
                len(scenes), generate_images, generate_videos,
                generate_audios, generate_subtitles,
            ),
        )
        self.db.add(task_model)
        self.db.flush()
        task_chain = self._build_task_chain(
            project_id, task_model.id, scenes, generate_images, generate_videos,
            generate_audios, generate_subtitles, add_bgm, bgm_path,
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
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        if project.status == ProjectStatus.IN_PRODUCTION:
            raise ValueError("项目正在制作，请等待当前任务结束")
        scene = self.db.query(Scene).filter(
            Scene.project_id == project_id,
            Scene.scene_number == scene_number,
        ).first()
        if not scene:
            raise ValueError(f"分镜不存在: {scene_number}")

        image_actions = {"regenerate_keyframe_with_prop_constraints", "refine_prompt_composition"}
        video_actions = {"lower_motion_and_regenerate_video"}
        blocked_actions = {
            "regenerate_character_identity": "请先在角色参考页重新生成身份方案和参考图，再重做关键帧。",
            "split_scene": "请先把该分镜拆成更简单的原子镜头，再重新生成。",
            "start_local_reviewer": "请先启动 llama.cpp 视觉审核服务，再重跑审核或生成。",
            "manual_review": "该问题需要人工复核后再选择具体返工动作。",
        }
        if action in blocked_actions:
            raise ValueError(blocked_actions[action])
        if action not in image_actions | video_actions:
            raise ValueError(f"不支持的返工动作: {action}")
        if action in video_actions and not scene.image_path:
            raise ValueError("视频返工需要先有已通过的关键帧，请先重做关键帧。")

        task_model = TaskModel(
            project_id=project_id,
            celery_task_id=str(uuid4()),
            status=TaskStatus.PENDING,
            progress=0.0,
            total_steps=1,
            current_step=0,
        )
        self.db.add(task_model)
        self.db.flush()

        project.final_video_path = None
        if action in image_actions:
            scene.image_path = None
            scene.video_path = None
            task = generate_image_task.si(
                scene.id,
                scene.image_prompt or scene.visual_description,
                project_id,
                task_model.id,
                repair_action=action,
            )
        else:
            scene.video_path = None
            task = generate_video_task.si(
                scene.id,
                project_id,
                task_model.id,
                repair_action=action,
            )

        result = task.freeze()
        task_model.celery_task_id = result.id
        self.db.commit()
        try:
            task.apply_async()
        except Exception as exc:
            task_model.status = TaskStatus.FAILED
            task_model.error_message = f"返工任务投递失败: {exc}"
            self.db.commit()
            raise
        return result.id

    def _calculate_total_steps(
        self,
        scene_count: int,
        generate_images: bool,
        generate_videos: bool,
        generate_audios: bool,
        generate_subtitles: bool
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
            steps += scene_count
        if generate_audios:
            steps += scene_count
        if generate_subtitles:
            steps += scene_count
        steps += 3  # Preparation, sampled-frame review, final composition.
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
        bgm_path: Optional[str]
    ) -> chain:
        """
        构建任务链
        
        任务链结构：
        1. 并行生成所有分镜的图像
        2. 并行生成所有分镜的视频（依赖图像）
        3. 并行生成所有分镜的音频
        4. 并行生成所有分镜的字幕（依赖音频）
        5. 合成最终视频
        
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
        
        # 2. 视频生成任务（并行，依赖图像）
        if generate_videos:
            video_tasks = chain(*[
                generate_video_task.si(
                    scene.id,
                    project_id,
                    task_id
                )
                for scene in scenes
            ])
            tasks.append(video_tasks)
        
        # 3. 音频生成任务（并行）
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
        
        # 5. 最终合成任务
        tasks.append(review_generation_task.si(project_id, task_id))
        compose_task = compose_final_video_task.si(
            project_id,
            task_id,
            add_bgm=add_bgm,
            bgm_path=bgm_path
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
        return {
            "task_id": task_model.id, "celery_task_id": celery_task_id,
            "project_id": task_model.project_id,
            "status": task_model.status.value,
            "progress": task_model.progress,
            "current_step": task_model.current_step,
            "total_steps": task_model.total_steps,
            "error_message": task_model.error_message,
            "error": task_model.error_message,
            "created_at": task_model.created_at.isoformat() if task_model.created_at else None,
            "updated_at": task_model.updated_at.isoformat() if task_model.updated_at else None,
        }

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
        
        # 撤销 Celery 任务
        celery_app.control.revoke(celery_task_id, terminate=False)
        
        # 更新任务状态
        was_pending = task_model.status == TaskStatus.PENDING
        task_model.status = TaskStatus.CANCELLED
        if was_pending:
            task_model.project.status = ProjectStatus.FAILED
        task_model.error_message = "已请求取消，当前步骤结束后停止后续生成"
        self.db.commit()
        
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
            new_task_id = self.create_production_task(
                project_id=task_model.project_id
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
