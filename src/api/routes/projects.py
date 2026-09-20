"""
项目管理 API 路由

提供项目的 CRUD 操作和剧本生成功能
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends, UploadFile, File
from typing import Optional
from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import Session
import shutil

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
from src.services.production_readiness import ProductionReadinessService
from src.database.session import get_db_session
from src.database.models import ProjectStatus
from src.services.llm_service import get_llm_service
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["项目管理"], dependencies=[Depends(require_project_access)])

class SeedDanceBaselineRequest(BaseModel):
    baseline_path: str
    candidate_path: Optional[str] = None


def _production_error_status(message: str) -> int:
    if "正在制作" in message or "IN_PRODUCTION" in message:
        return status.HTTP_409_CONFLICT
    if (
        "Production video engine is not ready" in message
        or "Short-drama production requires" in message
        or "项目不存在" in message
        or "项目没有分镜" in message
        or "短剧" in message
        or "not ready" in message
    ):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


@router.post("/{project_id}/seed-dance-baseline")
async def compare_seed_dance_baseline(
    project_id: int,
    request: SeedDanceBaselineRequest,
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project
    from src.services.generation_review import write_report
    from src.utils.storage import storage_manager

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    candidate = Path(request.candidate_path or project.final_video_path or "")
    baseline = Path(request.baseline_path)
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Candidate video does not exist; generate the project video first")
    if not baseline.is_file():
        raise HTTPException(status_code=400, detail="Seed Dance baseline video does not exist")

    review_root = storage_manager.get_project_path(project_id) / "reviews"
    from scripts.compare_video_baseline import compare
    report = compare(candidate, baseline, artifact_dir=review_root)
    report["candidate_video_path"] = str(candidate)
    report["baseline_video_path"] = str(baseline)
    write_report(review_root / "seed_dance_baseline_comparison.json", report)
    return report


@router.post("/{project_id}/seed-dance-baseline/upload")
async def upload_seed_dance_baseline(
    project_id: int,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project
    from src.services.generation_review import write_report
    from src.utils.storage import storage_manager
    from scripts.compare_video_baseline import compare

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    candidate = Path(project.final_video_path or "")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Candidate video does not exist; generate the project video first")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Baseline must be a video file")

    from scripts.compare_video_baseline import compare

    review_root = storage_manager.get_project_path(project_id) / "reviews"
    baseline_dir = review_root / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline = baseline_dir / f"seed_dance_baseline{suffix}"
    with baseline.open("wb") as stream:
        shutil.copyfileobj(file.file, stream)
    if baseline.stat().st_size <= 0:
        baseline.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Baseline video is empty")

    report = compare(candidate, baseline, artifact_dir=review_root)
    report["candidate_video_path"] = str(candidate)
    report["baseline_video_path"] = str(baseline)
    report["uploaded_baseline_path"] = str(baseline)
    write_report(review_root / "seed_dance_baseline_comparison.json", report)
    return report



@router.get("/video-engine/preflight")
async def get_video_engine_preflight(current_user=Depends(get_current_user)):
    from src.services.video_engine_preflight import preflight_production_video_engine
    return preflight_production_video_engine()


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
    project_root = storage_manager.get_project_path(project_id)
    for path in sorted(project_root.rglob("*.quality.json")):
        try:
            key = "quality_" + "_".join(path.relative_to(project_root).with_suffix("").parts)
            reports[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            logger.warning("Cannot read quality report: {}", path)
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


@router.get("/{project_id}/production-readiness")
async def get_production_readiness(
    project_id: int,
    include_engine_preflight: bool = Query(True, description="是否执行视频引擎预检"),
    current_user=Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
):
    from src.database.models import Project

    project = db_session.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ProductionReadinessService(db_session).build_report(
        project_id,
        include_engine_preflight=include_engine_preflight,
    )


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
    baseline = statuses.get("seed_dance_baseline_comparison")
    if production_story != "passed":
        action_items.append("Run production story review before generating final assets.")
    if generation != "passed":
        action_items.append("Run sampled-frame generation review before final composition.")
    if baseline != "passed":
        action_items.append("Run Seed Dance baseline comparison before claiming replacement quality.")

    repair_queue = _repair_queue_summary(reports)
    if repair_queue["total"]:
        action_items.append(f"Repair queue has {repair_queue['total']} targeted actions from failed generation reports.")

    blocking = bool(stale or needs_split or production_story != "passed" or generation != "passed" or baseline != "passed")
    return {
        "status": "blocked" if blocking else "ready",
        "reports": statuses,
        "stale_reports": stale,
        "shot_complexity": {
            "status": complexity.get("status"),
            "needs_split": needs_split,
            "warn": warn,
        },
        "repair_queue": repair_queue,
        "action_items": action_items,
    }


def _repair_queue_summary(reports: dict) -> dict:
    items = []
    actions = {}
    for name, report in reports.items():
        if not isinstance(report, dict):
            continue
        for item in report.get("repair_queue") or []:
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            copied["source_report"] = name
            items.append(copied)
            action = copied.get("action") or "unknown"
            actions[action] = actions.get(action, 0) + 1
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (priority_rank.get(item.get("priority"), 9), item.get("stage") or "", item.get("action") or ""))
    return {
        "total": len(items),
        "actions": actions,
        "items": items[:20],
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

        # 使用请求中的主题和大纲，如果没有提供或为空字符串则使用项目中的
        theme = request.theme.strip() if request.theme and request.theme.strip() else db_project.theme
        outline = request.outline.strip() if request.outline and request.outline.strip() else db_project.outline

        # 如果仍然没有theme和outline，抛出错误
        if not theme and not outline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="主题(theme)和大纲(outline)至少需要提供一个。请在项目设置中添加主题或大纲。"
            )

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
        error_msg = str(e)
        # 使用%s而不是f-string避免JSON中的花括号导致KeyError
        logger.error("剧本生成失败: %s", error_msg, exc_info=True)

        # 检查是否是LLM服务相关错误
        if "llama-cpp-python" in error_msg or "LLM 服务初始化失败" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="剧本生成功能需要LLM服务,但当前未配置。请手动创建剧本或联系管理员配置LLM服务。"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"剧本生成失败: {error_msg}"
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
    except ValueError as e:
        detail = str(e)
        logger.warning(f"提交生产任务被阻断: {detail}")
        raise HTTPException(
            status_code=_production_error_status(detail),
            detail=detail,
        )
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
    except ValueError as e:
        detail = str(e)
        logger.warning(f"重新生成图像被阻断: {detail}")
        raise HTTPException(
            status_code=_production_error_status(detail),
            detail=detail,
        )
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
