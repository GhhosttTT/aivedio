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
from src.api.dependencies import get_current_user
from src.services.project_manager import ProjectManager, get_project_manager
from src.services.script_generator import ScriptGenerator, get_script_generator
from src.services.task_orchestrator import TaskOrchestrator, get_task_orchestrator
from src.database.session import get_db_session
from src.database.models import ProjectStatus
from src.services.llm_service import get_llm_service
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


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
async def get_project(project_id: int):
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
        
        project_manager = get_project_manager()
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
async def update_project(project_id: int, project: ProjectUpdate):
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
        
        project_manager = get_project_manager()
        
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
            update_data["status"] = project.status
        
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
async def delete_project(project_id: int):
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
        
        project_manager = get_project_manager()
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
    page_size: int = Query(10, ge=1, le=100, description="每页数量")
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
        
        project_manager = get_project_manager()
        
        # 获取项目列表
        projects = project_manager.list_projects(
            status=status_filter,
            offset=(page - 1) * page_size,
            limit=page_size
        )
        
        # 获取总数
        total = project_manager.count_projects(status=status_filter)
        
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
async def generate_script(project_id: int, request: GenerateScriptRequest):
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
        
        project_manager = get_project_manager()
        script_generator = get_script_generator()
        
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
        
        # 生成剧本
        logger.info(f"开始生成剧本: project_id={project_id}")
        script_generator.generate_script(project_id, theme=theme, outline=outline)
        
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
            detail="生成剧本时发生错误"
        )


@router.post("/{project_id}/regenerate-scene", response_model=ProjectResponse)
async def regenerate_scene(project_id: int, request: RegenerateSceneRequest):
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
        
        project_manager = get_project_manager()
        script_generator = get_script_generator()
        
        # 检查项目是否存在
        db_project = project_manager.get_project(project_id)
        if db_project is None:
            logger.warning(f"项目不存在: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        # 重新生成分镜
        script_generator.regenerate_scene(project_id, request.scene_number)
        
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
            detail="重新生成分镜时发生错误"
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
        
        project_manager = get_project_manager()
        task_orchestrator = get_task_orchestrator()
        
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
        project_manager.update_project(project_id, status=ProjectStatus.IN_PRODUCTION)
        
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
            task_id=str(task_record.id),
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
        
        project_manager = get_project_manager()
        task_orchestrator = get_task_orchestrator()
        
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
        
        # 检查是否有角色（图像生成需要角色参考图）
        if not db_project.characters:
            logger.warning(f"项目没有角色: project_id={project_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目没有角色，无法生成图像"
            )
        
        # 清除所有场景的图像路径（准备重新生成）
        for scene in db_project.scenes:
            scene.image_path = None
        db_session.commit()
        logger.info(f"已清除 {len(db_project.scenes)} 个场景的图像路径")
        
        # 创建生产任务（只生成图像和视频）
        celery_task_id = task_orchestrator.create_production_task(project_id)
        
        # 更新项目状态
        project_manager.update_project(project_id, status=ProjectStatus.IN_PRODUCTION)
        
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
            task_id=str(task_record.id),
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
