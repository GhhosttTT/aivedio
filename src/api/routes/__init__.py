"""
API 路由模块
"""

from src.api.routes.projects import router as projects_router
from src.api.routes.tasks import router as tasks_router
from src.api.routes.seedance_callback import router as seedance_callback_router

__all__ = ["projects_router", "tasks_router", "seedance_callback_router"]
