"""
项目管理 API 路由

提供项目的 CRUD 操作和剧本生成功能
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends
from typing import Optional
from sqlalchemy.orm import Session

from src.api.schemas import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    GenerateScriptRequest,
    RegenerateSceneRequest,
    MessageResponse,
    ProductionTaskResponse
)
from src.api.dependencies import get_current_user, require_project_access
from src.services.project_manager import ProjectManager, get_project_manager
from src.services.script_generator import ScriptGenerator, get_script_generator
from src.services.task_orchestrator import TaskOrchestrator, get_task_orchestrator
from src.database.session import get_db_session
from src.database.models import ProjectStatus
from src.services.llm_service import get_llm_service
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["项目管理"], dependencies=[Depends(require_project_access)])


@router.get("/{project_id}/generation-review")
async def get_generation_review(
    project_id: int,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    import json
    from src.database.models import Project
    from src.utils.storage import storage_manager
    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    root = storage_manager.get_project_path(project_id) / "reviews"
    reports = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*.json"))
    }
    from src.tasks.review_tasks import current_story, generation_signature
    from src.services.generation_review import fingerprint
    for name in ("production_story", "generation"):
        report = reports.get(name)
        if report and report.get("status") == "passed":
            try:
                scenes = sorted(project.scenes, key=lambda scene: scene.scene_number)
                expected = fingerprint(current_story(project, scenes)) if name == "production_story" else generation_signature(project, scenes)
                if report.get("input_hash") != expected:
                    report["status"] = "stale"
            except (OSError, TypeError, ValueError):
                report["status"] = "stale"
    summary = _generation_review_summary(reports)
    return {"project_id": project_id, "reports": reports, "summary": summary}


def _generation_review_summary(reports: dict) -> dict:
    action_items = []
    statuses = {name: report.get("status") for name, report in reports.items() if isinstance(report, dict)}
    stale = sorted(name for name, status_value in statuses.items() if status_value == "stale")
    if stale:
        action_items.append("Story or media changed; rerun the stale reviews before composing.")

    complexity = reports.get("shot_complexity", {}) if isinstance(reports.get("shot_complexity"), dict) else {}
    complexity_summary = complexity.get("summary", {}) if isinstance(complexity.get("summary"), dict) else {}
    needs_split = int(complexity_summary.get("needs_split") or 0)
    warn = int(complexity_summary.get("warn") or 0)
    if needs_split:
        action_items.append("Split or simplify scenes marked needs_split in shot_complexity.json before GPU generation.")
    elif warn:
        action_items.append("Review warning scenes in shot_complexity.json; keep one action and static camera.")

    production_story = statuses.get("production_story")
    generation = statuses.get("generation")
    if production_story != "passed":
        action_items.append("Run production story review before generating final assets.")
    if generation != "passed":
        action_items.append("Run sampled-frame generation review before final composition.")

    blocking = bool(stale or needs_split or production_story != "passed" or generation != "passed")
    return {
        "status": "blocked" if blocking else "ready",
        "reports": statuses,
        "stale_reports": stale,
        "shot_complexity": {
            "status": complexity.get("status"),
            "needs_split": needs_split,
            "warn": warn,
        },
        "action_items": action_items,
    }


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    current_user = Depends(get_current_user),
    db_session: Session = Depends(get_db_session)
):
    """
    创建新项目
    
    Args:
        project: 项目创建请求
        current_user: 当前用户
        db_session: 数据库会话
    
    Returns:
        创建的项目信息
    
    Raises:
        HTTPException: 创建失败时抛出
    """
    try:
        logger.info(f"创建项目: {project.name}")
        
        project_manager = ProjectManager(db_session)
        db_project = project_manager.create_project(
            name=project.name,
            description=project.description,
            theme=project.theme,
            outline=project.outline,
            user_id=current_user.id
        )
        
        logger.info(f"项目创建成功: id={db_project.id}, name={db_project.name}")
        return db_project
    
    except ValueError as e:
        logger.warning(f"项目创建失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"项目创建失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建项目时发生错误"
        )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db_session: Session = Depends(get_db_session)):
    """
    获取项目详情
    
    Args:
        project_id: 项目 ID
    
    Returns:
        项目详细信息
    
    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    try:
        logger.info(f"获取项目详情: project_id={project_id}")
        
        project_manager = ProjectManager(db_session)
        db_project = project_manager.get_project(project_id)
        
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        return db_project
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取项目详情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取项目详情时发生错误"
        )


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, project: ProjectUpdate, db_session: Session = Depends(get_db_session)):
    """
    更新项目信息
    
    Args:
        project_id: 项目 ID
        project: 项目更新请求
    
    Returns:
        更新后的项目信息
    
    Raises:
        HTTPException: 项目不存在或更新失败时抛出
    """
    try:
        logger.info(f"更新项目: project_id={project_id}")
        
        project_manager = ProjectManager(db_session)
        
        # 构建更新数据（只包含非 None 的字段）
        update_data = {}
        if project.name is not None:
            update_data["name"] = project.name
        if project.description is not None:
            update_data["description"] = project.description
        if project.theme is not None:
            update_data["theme"] = project.theme
        if project.outline is not None:
            update_data["outline"] = project.outline
        if project.status is not None:
            raise ValueError("生产状态由任务系统管理")
        
        db_project = project_manager.update_project(project_id, **update_data)
        
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        logger.info(f"项目更新成功: project_id={project_id}")
        return db_project
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"项目更新失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"项目更新失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新项目时发生错误"
        )


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(project_id: int, db_session: Session = Depends(get_db_session)):
    """
    删除项目
    
    Args:
        project_id: 项目 ID
    
    Returns:
        删除成功消息
    
    Raises:
        HTTPException: 项目不存在或删除失败时抛出
    """
    try:
        logger.info(f"删除项目: project_id={project_id}")
        
        project_manager = ProjectManager(db_session)
        success = project_manager.delete_project(project_id)
        
        if not success:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        logger.info(f"项目删除成功: project_id={project_id}")
        return MessageResponse(
            message="项目删除成功",
            detail=f"项目 {project_id} 及其关联文件已删除"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"项目删除失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除项目时发生错误"
        )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    status_filter: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session)
):
    """
    列出项目
    
    Args:
        status_filter: 状态过滤（可选）
        page: 页码（从 1 开始）
        page_size: 每页数量
    
    Returns:
        项目列表和分页信息
    """
    try:
        logger.info(f"列出项目: status={status_filter}, page={page}, page_size={page_size}")
        
        project_manager = ProjectManager(db_session)
        
        from src.database.models import Project
        query = db_session.query(Project).filter(Project.user_id == current_user.id)
        if status_filter:
            query = query.filter(Project.status == status_filter)
        total = query.count()
        projects = query.order_by(Project.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return ProjectListResponse(
            total=total,
            page=page,
            page_size=page_size,
            projects=projects
        )
    
    except Exception as e:
        logger.error(f"列出项目失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="列出项目时发生错误"
        )


@router.post("/{project_id}/generate-script", response_model=ProjectResponse)
def generate_script(project_id: int, request: GenerateScriptRequest, db_session: Session = Depends(get_db_session)):
    """
    生成剧本
    
    Args:
        project_id: 项目 ID
        request: 剧本生成请求
    
    Returns:
        更新后的项目信息（包含角色和分镜）
    
    Raises:
        HTTPException: 项目不存在或生成失败时抛出
    """
    try:
        logger.info(f"生成剧本: project_id={project_id}")
        
        project_manager = ProjectManager(db_session)
        script_generator = ScriptGenerator(db_session)
        
        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        # 使用请求中的主题和大纲，如果没有提供则使用项目中的
        theme = request.theme if request.theme else db_project.theme
        outline = request.outline if request.outline else db_project.outline
        
        # 生成剧本（使用增强版参数）
        logger.info(f"开始生成剧本: project_id={project_id}")
        script_generator.generate_script(
            project_id=project_id,
            theme=theme,
            outline=outline,
            num_scenes=request.num_scenes,
            num_characters=request.num_characters,
            style=request.style,
            num_chapters=request.num_chapters,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        
        # 更新项目状态
        project_manager.update_project(project_id, status="script_generated")
        
        # 返回更新后的项目信息
        db_project = project_manager.get_project(project_id)
        logger.info(f"剧本生成成功: project_id={project_id}, characters={len(db_project.characters)}, scenes={len(db_project.scenes)}")
        
        return db_project
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"剧本生成失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"剧本生成失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"剧本生成与情节复审失败: {e}"
        )


@router.post("/{project_id}/regenerate-scene", response_model=ProjectResponse)
def regenerate_scene(project_id: int, request: RegenerateSceneRequest, db_session: Session = Depends(get_db_session)):
    """
    重新生成指定分镜
    
    Args:
        project_id: 项目 ID
        request: 重新生成分镜请求
    
    Returns:
        更新后的项目信息
    
    Raises:
        HTTPException: 项目不存在或分镜不存在时抛出
    """
    try:
        logger.info(f"重新生成分镜: project_id={project_id}, scene_number={request.scene_number}")
        
        project_manager = ProjectManager(db_session)
        script_generator = ScriptGenerator(db_session)
        
        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        # 重新生成分镜
        script_generator.regenerate_scene(project_id, request.scene_number, request.new_description)
        
        # 返回更新后的项目信息
        db_project = project_manager.get_project(project_id)
        logger.info(f"分镜重新生成成功: project_id={project_id}, scene_number={request.scene_number}")
        
        return db_project
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"分镜重新生成失败（输入验证）: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"分镜重新生成失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分镜重新生成失败: {e}"
        )


@router.post("/{project_id}/produce", response_model=ProductionTaskResponse)
async def produce_video(
    project_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    提交视频生产任务
    
    Args:
        project_id: 项目 ID
    
    Returns:
        生产任务信息
    
    Raises:
        HTTPException: 项目不存在或提交失败时抛出
    """
    try:
        logger.info(f"提交生产任务: project_id={project_id}")
        
        project_manager = ProjectManager(db_session)
        task_orchestrator = TaskOrchestrator(db_session)
        
        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        # 检查项目是否有分镜
        if not db_project.scenes:
            logger.warning(f"项目没有分镜: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目没有分镜，请先生成剧本"
            )
        
        # 创建生产任务
        celery_task_id = task_orchestrator.create_production_task(project_id)
        
        # 更新项目状态
        
        # 查询任务记录
        from src.database.models import Task as TaskModel
        task_record = db_session.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        
        if not task_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="任务记录创建失败"
            )
        
        logger.info(f"生产任务创建成功: task_id={task_record.id}, project_id={project_id}")
        
        return ProductionTaskResponse(
            task_id=task_record.celery_task_id,
            project_id=task_record.project_id,
            status=task_record.status.value,
            progress=task_record.progress,
            current_step=str(task_record.current_step),
            total_steps=task_record.total_steps,
            created_at=task_record.created_at,
            updated_at=task_record.updated_at,
            error_message=task_record.error_message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交生产任务失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="提交生产任务时发生错误"
        )


@router.post("/{project_id}/regenerate-images", response_model=ProductionTaskResponse)
async def regenerate_images(
    project_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    重新生成图像（不重新生成剧本）
    
    当图像生成出错时，可以只重新生成图像而不需要重新生成剧本。
    此操作会清除所有已生成的图像，然后根据现有的剧本和分镜重新生成。
    
    Args:
        project_id: 项目 ID
    
    Returns:
        生产任务信息
    
    Raises:
        HTTPException: 项目不存在或提交失败时抛出
    """
    try:
        logger.info(f"重新生成图像: project_id={project_id}")
        
        project_manager = ProjectManager(db_session)
        task_orchestrator = TaskOrchestrator(db_session)
        
        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        # 检查项目是否有分镜
        if not db_project.scenes:
            logger.warning(f"项目没有分镜: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目没有分镜，请先生成剧本"
            )
        
        # 创建生产任务（只生成图像和视频）
        celery_task_id = task_orchestrator.create_production_task(project_id)
        
        # 更新项目状态
        
        # 查询任务记录
        from src.database.models import Task as TaskModel
        task_record = db_session.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        
        if not task_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="任务记录创建失败"
            )
        
        logger.info(f"重新生成图像任务创建成功: task_id={task_record.id}, project_id={project_id}")
        
        return ProductionTaskResponse(
            task_id=task_record.celery_task_id,
            project_id=task_record.project_id,
            status=task_record.status.value,
            progress=task_record.progress,
            current_step=str(task_record.current_step),
            total_steps=task_record.total_steps,
            created_at=task_record.created_at,
            updated_at=task_record.updated_at,
            error_message=task_record.error_message
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重新生成图像失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="重新生成图像时发生错误"
        )


@router.get("/{project_id}/production-task")
def latest_production_task(project_id: int, db_session: Session = Depends(get_db_session)):
    from src.database.models import Task
    task = db_session.query(Task).filter(Task.project_id == project_id).order_by(Task.id.desc()).first()
    if task is None:
        return None
    import json
    from src.utils.storage import storage_manager
    result = TaskOrchestrator(db_session).get_task_status(task.celery_task_id)
    path = storage_manager.get_project_path(project_id) / "production_progress.json"
    if path.is_file():
        progress = json.loads(path.read_text(encoding="utf-8"))
        if progress.get("celery_task_id") == task.celery_task_id:
            result["live_step"] = progress
    return result


from src.api.schemas import SceneUpdate


@router.put("/{project_id}/scenes/{scene_number}", response_model=ProjectResponse)
def update_scene(project_id: int, scene_number: int, request: SceneUpdate, db_session: Session = Depends(get_db_session)):
    import json
    from src.database.models import Scene, Project
    project = db_session.query(Project).filter(Project.id == project_id).first()
    scene = db_session.query(Scene).filter(Scene.project_id == project_id, Scene.scene_number == scene_number).first()
    if not scene or not request.visual_description.strip():
        raise HTTPException(400, "分镜不存在或描述为空")
    scene.visual_description = request.visual_description.strip()
    scene.dialogue = request.dialogue
    scene.character_name = request.character_name
    scene.image_prompt = scene.image_path = scene.video_path = None
    scene.audio_path = scene.subtitle_path = None
    project.final_video_path = None
    project.status = ProjectStatus.SCRIPT_GENERATED
    if project.script:
        script = json.loads(project.script)
        for item in script.get("scenes", []):
            if item.get("scene_number") == scene_number:
                item.update(description=scene.visual_description, dialogue=scene.dialogue, speaker=scene.character_name)
        project.script = json.dumps(script, ensure_ascii=False)
    db_session.commit()
    return project
