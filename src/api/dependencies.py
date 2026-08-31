"""
API 依赖项

定义 FastAPI 依赖项，用于认证、授权等
"""
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from src.api.auth import decode_access_token
from src.database.models import User
from src.database.session import get_db_session
from src.utils.logger import get_logger

logger = get_logger(__name__)

# HTTP Bearer 认证方案
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db_session)
) -> User:
    """
    获取当前认证用户

    Args:
        credentials: HTTP Bearer 凭证
        db: 数据库会话

    Returns:
        当前用户对象

    Raises:
        HTTPException: 如果令牌无效或用户不存在
    """
    token = credentials.credentials
    
    # 解码令牌
    payload = decode_access_token(token)
    if payload is None:
        logger.warning("无效的访问令牌")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 获取用户 ID（JWT sub 字段是字符串）
    user_id_str: Optional[str] = payload.get("sub")
    if user_id_str is None:
        logger.warning("令牌中缺少用户 ID")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 转换为整数
    try:
        user_id = int(user_id_str)
    except ValueError:
        logger.warning(f"无效的用户 ID 格式：{user_id_str}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 查询用户
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        logger.warning(f"用户不存在：{user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 检查用户是否激活
    if not user.is_active:
        logger.warning(f"用户已禁用：{user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用"
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    获取当前激活用户（别名，用于更清晰的语义）

    Args:
        current_user: 当前用户

    Returns:
        当前激活用户
    """
    return current_user


async def require_project_access(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db_session)):
    from src.database.models import Project, ProjectStatus
    project_id = request.path_params.get("project_id")
    if project_id is None:
        return
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user.id).first()
    if project is None:
        raise HTTPException(404, "项目不存在")
    if request.method in {"POST", "PUT", "DELETE", "PATCH"} and project.status == ProjectStatus.IN_PRODUCTION:
        raise HTTPException(409, "项目正在制作，请等待当前任务结束")


async def require_task_access(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db_session)):
    from src.database.models import Task, Project
    task = db.query(Task).join(Project).filter(Task.celery_task_id == request.path_params["task_id"], Project.user_id == user.id).first()
    if task is None:
        raise HTTPException(404, "任务不存在")
