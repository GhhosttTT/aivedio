"""
认证和授权模块

实现 JWT Token 生成、验证和密码哈希功能
"""
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def hash_password(password: str) -> str:
    """
    哈希密码

    Args:
        password: 明文密码

    Returns:
        哈希后的密码
    """
    # 将密码转换为字节
    password_bytes = password.encode('utf-8')
    # 生成盐并哈希密码
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    # 返回字符串形式
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        密码是否匹配
    """
    # 将密码转换为字节
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    # 验证密码
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT 访问令牌

    Args:
        data: 要编码的数据（通常包含用户 ID 和用户名）
        expires_delta: 过期时间增量，默认使用配置中的值

    Returns:
        JWT 令牌字符串
    """
    to_encode = data.copy()
    
    # 确保 sub 字段是字符串（JWT 标准要求）
    if "sub" in to_encode and not isinstance(to_encode["sub"], str):
        to_encode["sub"] = str(to_encode["sub"])
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    logger.info(f"创建访问令牌，过期时间：{expire}")
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    解码 JWT 访问令牌

    Args:
        token: JWT 令牌字符串

    Returns:
        解码后的数据，如果令牌无效则返回 None
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT 解码失败：{e}")
        return None


def create_refresh_token(data: dict) -> str:
    """
    创建 JWT 刷新令牌

    Args:
        data: 要编码的数据（通常包含用户 ID）

    Returns:
        JWT 刷新令牌字符串
    """
    to_encode = data.copy()
    
    # 确保 sub 字段是字符串（JWT 标准要求）
    if "sub" in to_encode and not isinstance(to_encode["sub"], str):
        to_encode["sub"] = str(to_encode["sub"])
    
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS)
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    logger.info(f"创建刷新令牌，过期时间：{expire}")
    return encoded_jwt
