"""
任务管理 API 测试
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from src.api.app import create_app


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    return TestClient(app)


def test_get_task_status_success(client):
    """测试查询任务状态成功"""
    with patch("src.api.routes.tasks.get_task_orchestrator") as mock_get_to:
        mock_to_instance = Mock()
        mock_get_to.return_value = mock_to_instance
        mock_to_instance.get_task_status.return_value = {
            "status": "running",
            "progress": 0.5,
            "current_step": "生成图像"
        }
        
        response = client.get("/api/tasks/task-123/status")
        assert response.status_code == 200


def test_cancel_task_success(client):
    """测试取消任务成功"""
    with patch("src.api.routes.tasks.get_task_orchestrator") as mock_get_to:
        mock_to_instance = Mock()
        mock_get_to.return_value = mock_to_instance
        mock_to_instance.cancel_task.return_value = True
        
        response = client.post("/api/tasks/task-123/cancel")
        assert response.status_code == 200


def test_retry_task_success(client):
    """测试重试任务成功"""
    with patch("src.api.routes.tasks.get_task_orchestrator") as mock_get_to:
        mock_to_instance = Mock()
        mock_get_to.return_value = mock_to_instance
        mock_to_instance.retry_failed_task.return_value = True
        
        response = client.post("/api/tasks/task-123/retry")
        assert response.status_code == 200
