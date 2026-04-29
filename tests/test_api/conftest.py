"""
API 测试的共享 fixtures
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.api.app import app
from src.database.session import get_db_session
from src.database import Base


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


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    提供数据库会话 fixture

    每个测试函数都会创建新的数据库会话
    """
    # 创建表
    Base.metadata.create_all(bind=test_engine)
    
    # 创建会话
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # 删除表
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session) -> TestClient:
    """
    提供 FastAPI 测试客户端 fixture

    依赖于 db_session fixture，确保每个测试都有干净的数据库
    """
    return TestClient(app)
