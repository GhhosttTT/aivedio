"""
数据库连接和会话管理
提供数据库连接、会话创建和管理功能
"""

import os
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager

from src.database.models import Base


# 从环境变量获取数据库 URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./short_drama.db")

# 创建数据库引擎
if DATABASE_URL.startswith("sqlite"):
    # SQLite 配置
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False  # 设置为 True 可以看到 SQL 日志
    )
    
    # 启用 SQLite 外键约束
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    # PostgreSQL 或其他数据库配置
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # 连接前检查连接是否有效
        pool_size=10,  # 连接池大小
        max_overflow=20,  # 最大溢出连接数
        echo=False
    )

# 创建会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def create_tables():
    """
    创建所有数据库表
    在应用启动时调用
    """
    Base.metadata.create_all(bind=engine)
    print("✓ 数据库表创建完成")


def drop_tables():
    """
    删除所有数据库表
    警告：此操作会删除所有数据！
    """
    Base.metadata.drop_all(bind=engine)
    print("✓ 数据库表删除完成")


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话（依赖注入）
    用于 FastAPI 的依赖注入
    
    使用示例:
        @app.get("/projects")
        def get_projects(db: Session = Depends(get_db)):
            return db.query(Project).all()
    
    Yields:
        Session: 数据库会话对象
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    获取数据库会话（上下文管理器）
    用于非 FastAPI 环境
    
    使用示例:
        with get_db_context() as db:
            project = db.query(Project).first()
    
    Yields:
        Session: 数据库会话对象
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_database():
    """
    初始化数据库
    创建所有表并执行初始化操作
    """
    print("初始化数据库...")
    
    # 创建表
    create_tables()
    
    # 可以在这里添加初始数据
    # with get_db_context() as db:
    #     # 添加默认数据
    #     pass
    
    print("✓ 数据库初始化完成")


def check_database_connection() -> bool:
    """
    检查数据库连接是否正常
    
    Returns:
        bool: 连接正常返回 True，否则返回 False
    """
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return False


# 导出常用对象
__all__ = [
    "engine",
    "SessionLocal",
    "get_db",
    "get_db_context",
    "create_tables",
    "drop_tables",
    "init_database",
    "check_database_connection",
]
