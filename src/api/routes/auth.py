"""
认证路由

实现用户登录、注册、令牌刷新等功能
"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy.orm import Session

from src.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from src.api.dependencies import get_current_user
from src.database.models import User
from src.database.session import get_db_session
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["认证"])


# ==================== Pydantic 模型 ====================

class UserRegister(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """令牌响应"""
    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")


class TokenRefresh(BaseModel):
    """令牌刷新请求"""
    refresh_token: str = Field(..., description="刷新令牌")


class UserResponse(BaseModel):
    """用户响应"""
    id: int
    username: str
    email: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ==================== API 端点 ====================

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: Session = Depends(get_db_session)
):
    """
    用户注册

    Args:
        user_data: 用户注册数据
        db: 数据库会话

    Returns:
        创建的用户信息

    Raises:
        HTTPException: 如果用户名或邮箱已存在
    """
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        logger.warning(f"用户名已存在：{user_data.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    existing_email = db.query(User).filter(User.email == user_data.email).first()
    if existing_email:
        logger.warning(f"邮箱已存在：{user_data.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已存在"
        )
    
    # 创建用户
    hashed_pwd = hash_password(user_data.password)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_pwd,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"用户注册成功：{new_user.username} (ID: {new_user.id})")
    return new_user


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: UserLogin,
    db: Session = Depends(get_db_session)
):
    """
    用户登录

    Args:
        login_data: 登录数据
        db: 数据库会话

    Returns:
        访问令牌和刷新令牌

    Raises:
        HTTPException: 如果用户名或密码错误
    """
    # 查询用户
    user = db.query(User).filter(User.username == login_data.username).first()
    if not user:
        logger.warning(f"用户不存在：{login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 验证密码
    if not verify_password(login_data.password, user.hashed_password):
        logger.warning(f"密码错误：{login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 检查用户是否激活
    if not user.is_active:
        logger.warning(f"用户已禁用：{login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用"
        )
    
    # 创建令牌
    access_token = create_access_token(data={"sub": user.id, "username": user.username})
    refresh_token = create_refresh_token(data={"sub": user.id})
    
    logger.info(f"用户登录成功：{user.username} (ID: {user.id})")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    token_data: TokenRefresh,
    db: Session = Depends(get_db_session)
):
    """
    刷新访问令牌

    Args:
        token_data: 刷新令牌数据
        db: 数据库会话

    Returns:
        新的访问令牌和刷新令牌

    Raises:
        HTTPException: 如果刷新令牌无效
    """
    # 解码刷新令牌
    payload = decode_access_token(token_data.refresh_token)
    if payload is None:
        logger.warning("无效的刷新令牌")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    # 获取用户 ID（JWT sub 字段是字符串）
    user_id_str: Optional[str] = payload.get("sub")
    if user_id_str is None:
        logger.warning("刷新令牌中缺少用户 ID")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    # 转换为整数
    try:
        user_id = int(user_id_str)
    except ValueError:
        logger.warning(f"无效的用户 ID 格式：{user_id_str}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    # 查询用户
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"用户不存在：{user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )
    
    # 检查用户是否激活
    if not user.is_active:
        logger.warning(f"用户已禁用：{user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用"
        )
    
    # 创建新令牌
    access_token = create_access_token(data={"sub": user.id, "username": user.username})
    refresh_token = create_refresh_token(data={"sub": user.id})
    
    logger.info(f"令牌刷新成功：{user.username} (ID: {user.id})")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户信息

    Args:
        current_user: 当前认证用户

    Returns:
        当前用户信息
    """
    return current_user
