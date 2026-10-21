"""
任务管理 API 测试
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from src.api.app import create_app
from src.api.dependencies import get_current_user, require_task_access
from src.database.models import User


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    user = User(id=1, username="testuser", email="test@example.com", hashed_password="x", is_active=True)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_task_access] = lambda: None
    return TestClient(app)


def test_get_task_status_success(client):
    """测试查询任务状态成功"""
    with patch("src.api.routes.tasks.TaskOrchestrator") as mock_get_to:
        mock_to_instance = Mock()
        mock_get_to.return_value = mock_to_instance
        mock_to_instance.get_task_status.return_value = {
            "status": "running",
            "progress": 0.5,
            "current_step": "生成图像",
            "provider_progress": 42,
            "provider_stage": "provider_processing",
            "provider_state": "PROGRESS",
            "provider_task_id": "ark-task-42",
            "provider_status": "running",
            "provider_error": "",
            "production_options": {
                "provider": "seedance_api",
                "model": "doubao-seedance-2-5-260628",
                "resolution": "1080p",
                "output_format": "mp4",
                "native_audio": True,
            },
        }
        
        response = client.get("/api/tasks/task-123/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["provider_progress"] == 42
        assert payload["provider_stage"] == "provider_processing"
        assert payload["provider_state"] == "PROGRESS"
        assert payload["provider_task_id"] == "ark-task-42"
        assert payload["provider_status"] == "running"
        assert payload["production_options"]["model"] == "doubao-seedance-2-5-260628"
        assert payload["production_options"]["native_audio"] is True


def test_cancel_task_success(client):
    """测试取消任务成功"""
    with patch("src.api.routes.tasks.TaskOrchestrator") as mock_get_to:
        mock_to_instance = Mock()
        mock_get_to.return_value = mock_to_instance
        mock_to_instance.cancel_task.return_value = True
        
        response = client.post("/api/tasks/task-123/cancel")
        assert response.status_code == 200


def test_retry_task_success(client):
    """测试重试任务成功"""
    with patch("src.api.routes.tasks.TaskOrchestrator") as mock_get_to:
        mock_to_instance = Mock()
        mock_get_to.return_value = mock_to_instance
        mock_to_instance.retry_failed_task.return_value = True
        
        response = client.post("/api/tasks/task-123/retry")
        assert response.status_code == 200


def test_task_routes_are_sync_so_fastapi_uses_the_threadpool():
    """Sync endpoints keep SQLite waits (busy timeout) off the event loop."""
    import inspect

    from src.api.routes import tasks as task_routes

    for endpoint in (
        task_routes.get_task_status,
        task_routes.cancel_task,
        task_routes.retry_task,
    ):
        assert not inspect.iscoroutinefunction(endpoint)
