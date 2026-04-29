"""
任务管理 API 路由

提供任务状态查询、取消和重试功能
"""

from fastapi import APIRouter, HTTPException, status

from src.api.schemas import TaskStatusResponse, MessageResponse
from src.services.task_orchestrator import get_task_orchestrator
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["任务管理"])


@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    查询任务状态
    
    Args:
        task_id: 任务 ID
    
    Returns:
        任务状态信息
    
    Raises:
        HTTPException: 任务不存在时抛出 404
    """
    try:
        logger.info(f"查询任务状态: task_id={task_id}")
        
        task_orchestrator = get_task_orchestrator()
        task_info = task_orchestrator.get_task_status(task_id)
        
        if task_info is None:
            logger.warning(f"任务不存在: task_id={task_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在: {task_id}"
            )
        
        return TaskStatusResponse(
            task_id=task_id,
            status=task_info["status"],
            progress=task_info.get("progress", 0.0),
            current_step=task_info.get("current_step", ""),
            result=task_info.get("result"),
            error=task_info.get("error")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询任务状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查询任务状态时发生错误"
        )


@router.post("/{task_id}/cancel", response_model=MessageResponse)
async def cancel_task(task_id: str):
    """
    取消任务
    
    Args:
        task_id: 任务 ID
    
    Returns:
        取消成功消息
    
    Raises:
        HTTPException: 任务不存在或取消失败时抛出
    """
    try:
        logger.info(f"取消任务: task_id={task_id}")
        
        task_orchestrator = get_task_orchestrator()
        success = task_orchestrator.cancel_task(task_id)
        
        if not success:
            logger.warning(f"任务不存在或无法取消: task_id={task_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在或无法取消: {task_id}"
            )
        
        logger.info(f"任务取消成功: task_id={task_id}")
        return MessageResponse(
            message="任务取消成功",
            detail=f"任务 {task_id} 已取消"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取消任务时发生错误"
        )


@router.post("/{task_id}/retry", response_model=MessageResponse)
async def retry_task(task_id: str):
    """
    重试失败的任务
    
    Args:
        task_id: 任务 ID
    
    Returns:
        重试成功消息
    
    Raises:
        HTTPException: 任务不存在或重试失败时抛出
    """
    try:
        logger.info(f"重试任务: task_id={task_id}")
        
        task_orchestrator = get_task_orchestrator()
        success = task_orchestrator.retry_failed_task(task_id)
        
        if not success:
            logger.warning(f"任务不存在或无法重试: task_id={task_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"任务不存在或无法重试（可能已超过最大重试次数）: {task_id}"
            )
        
        logger.info(f"任务重试成功: task_id={task_id}")
        return MessageResponse(
            message="任务重试成功",
            detail=f"任务 {task_id} 已重新提交"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试任务失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="重试任务时发生错误"
        )
