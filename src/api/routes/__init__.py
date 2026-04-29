"""
API 路由模块
"""

from src.api.routes.projects import router as projects_router
from src.api.routes.tasks import router as tasks_router

__all__ = ["projects_router", "tasks_router"]
