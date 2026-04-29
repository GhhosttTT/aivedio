"""
数据库模块

导出所有数据库相关的类和函数
"""

# 先导入 Base 和所有模型（确保模型注册到 metadata）
from src.database.models import (
    Base,
    User,
    Project,
    Character,
    Scene,
    Task,
    ProjectStatus,
    TaskStatus,
)

# 再导入数据库连接和会话
from src.database.database import (
    engine,
    SessionLocal,
    get_db,
    get_db_context,
    create_tables,
    drop_tables,
    init_database,
    check_database_connection,
)

from src.database.session import get_db_session

__all__ = [
    # 模型
    "Base",
    "User",
    "Project",
    "Character",
    "Scene",
    "Task",
    "ProjectStatus",
    "TaskStatus",
    # 数据库连接和会话
    "engine",
    "SessionLocal",
    "get_db",
    "get_db_session",
    "get_db_context",
    "create_tables",
    "drop_tables",
    "init_database",
    "check_database_connection",
]
