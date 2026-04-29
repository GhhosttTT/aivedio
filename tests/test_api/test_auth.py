"""
认证 API 测试

测试用户注册、登录、令牌刷新等功能
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from src.api.app import app
from src.api.auth import hash_password, verify_password, create_access_token, decode_access_token
from src.database.session import get_db_session

# 导入所有模型以确保它们注册到 Base.metadata
from src.database import Base, User, Project, Character, Scene, Task


# 创建测试数据库（使用文件数据库而不是内存数据库）
TEST_DATABASE_URL = "sqlite:///./test_short_drama.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    """覆盖数据库依赖"""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# 覆盖依赖
app.dependency_overrides[get_db_session] = override_get_db

# 创建测试客户端
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """每个测试前创建表，测试后删除表"""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# ==================== 密码哈希测试 ====================

def test_hash_password():
    """测试密码哈希"""
    password = "test_password_123"
    hashed = hash_password(password)
    
    # 哈希后的密码应该不同于原密码
    assert hashed != password
    # 哈希后的密码应该是字符串
    assert isinstance(hashed, str)
    # 哈希后的密码应该有一定长度
    assert len(hashed) > 20


def test_verify_password():
    """测试密码验证"""
    password = "test_password_123"
    hashed = hash_password(password)
    
    # 正确的密码应该验证通过
    assert verify_password(password, hashed) is True
    # 错误的密码应该验证失败
    assert verify_password("wrong_password", hashed) is False


# ==================== JWT 令牌测试 ====================

def test_create_and_decode_access_token():
    """测试创建和解码访问令牌"""
    data = {"sub": 1, "username": "testuser"}
    token = create_access_token(data)
    
    # 令牌应该是字符串
    assert isinstance(token, str)
    # 令牌应该有一定长度
    assert len(token) > 20
    
    # 解码令牌
    payload = decode_access_token(token)
    assert payload is not None
    # sub 字段会被转换为字符串
    assert payload["sub"] == "1"
    assert payload["username"] == "testuser"
    assert "exp" in payload


def test_decode_invalid_token():
    """测试解码无效令牌"""
    invalid_token = "invalid.token.here"
    payload = decode_access_token(invalid_token)
    
    # 无效令牌应该返回 None
    assert payload is None


# ==================== 用户注册测试 ====================

def test_register_success():
    """测试用户注册成功"""
    response = client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"
    assert data["is_active"] is True
    assert "id" in data
    assert "hashed_password" not in data  # 不应该返回密码


def test_register_duplicate_username():
    """测试注册重复用户名"""
    # 第一次注册
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test1@example.com",
            "password": "password123"
        }
    )
    
    # 第二次注册相同用户名
    response = client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test2@example.com",
            "password": "password123"
        }
    )
    
    assert response.status_code == 400
    assert "用户名已存在" in response.json()["detail"]


def test_register_duplicate_email():
    """测试注册重复邮箱"""
    # 第一次注册
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser1",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    # 第二次注册相同邮箱
    response = client.post(
        "/api/auth/register",
        json={
            "username": "testuser2",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    assert response.status_code == 400
    assert "邮箱已存在" in response.json()["detail"]


def test_register_invalid_email():
    """测试注册无效邮箱"""
    response = client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "invalid-email",
            "password": "password123"
        }
    )
    
    assert response.status_code == 422  # Pydantic 验证错误


def test_register_short_password():
    """测试注册过短密码"""
    response = client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "12345"  # 少于 6 个字符
        }
    )
    
    assert response.status_code == 422  # Pydantic 验证错误


# ==================== 用户登录测试 ====================

def test_login_success():
    """测试登录成功"""
    # 先注册用户
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    # 登录
    response = client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "password123"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_username():
    """测试登录错误用户名"""
    response = client.post(
        "/api/auth/login",
        json={
            "username": "nonexistent",
            "password": "password123"
        }
    )
    
    assert response.status_code == 401
    assert "用户名或密码错误" in response.json()["detail"]


def test_login_wrong_password():
    """测试登录错误密码"""
    # 先注册用户
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    # 使用错误密码登录
    response = client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "wrongpassword"
        }
    )
    
    assert response.status_code == 401
    assert "用户名或密码错误" in response.json()["detail"]


def test_login_inactive_user():
    """测试登录已禁用用户"""
    # 先注册用户
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    # 禁用用户
    db = TestSessionLocal()
    user = db.query(User).filter(User.username == "testuser").first()
    user.is_active = False
    db.commit()
    db.close()
    
    # 尝试登录
    response = client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "password123"
        }
    )
    
    assert response.status_code == 403
    assert "用户已禁用" in response.json()["detail"]


# ==================== 令牌刷新测试 ====================

def test_refresh_token_success():
    """测试刷新令牌成功"""
    # 先注册并登录
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    login_response = client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "password123"
        }
    )
    
    refresh_token = login_response.json()["refresh_token"]
    
    # 刷新令牌
    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_refresh_token_invalid():
    """测试刷新无效令牌"""
    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "invalid.token.here"}
    )
    
    assert response.status_code == 401
    assert "无效的刷新令牌" in response.json()["detail"]


# ==================== 获取当前用户测试 ====================

def test_get_current_user_success():
    """测试获取当前用户成功"""
    # 先注册并登录
    client.post(
        "/api/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "password123"
        }
    )
    
    login_response = client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "password123"
        }
    )
    
    access_token = login_response.json()["access_token"]
    
    # 获取当前用户信息
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"
    assert data["is_active"] is True


def test_get_current_user_no_token():
    """测试获取当前用户无令牌"""
    response = client.get("/api/auth/me")
    
    # HTTPBearer 在没有令牌时返回 401
    assert response.status_code == 401


def test_get_current_user_invalid_token():
    """测试获取当前用户无效令牌"""
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.token.here"}
    )
    
    assert response.status_code == 401
    assert "无效的认证凭证" in response.json()["detail"]
