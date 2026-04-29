"""
项目管理 API 测试

测试项目相关的 API 端点
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from datetime import datetime

from src.api.app import create_app
from src.database.models import Project, Character, Scene


@pytest.fixture
def client():
    """
    创建测试客户端
    
    Returns:
        TestClient 实例
    """
    app = create_app()
    return TestClient(app)


@pytest.fixture
def mock_project():
    """
    创建模拟项目对象
    
    Returns:
        Mock Project 对象
    """
    project = Mock(spec=Project)
    project.id = 1
    project.name = "测试项目"
    project.description = "这是一个测试项目"
    project.theme = "科幻"
    project.outline = "一个关于未来的故事"
    project.status = "draft"
    project.created_at = datetime.now()
    project.updated_at = datetime.now()
    project.characters = []
    project.scenes = []
    return project


def test_create_project_success(client):
    """
    测试创建项目成功
    """
    with patch("src.api.routes.projects.ProjectManager") as mock_pm_class, \
         patch("src.api.routes.projects.get_db_session") as mock_get_db:
        
        mock_pm = Mock()
        mock_pm_class.return_value = mock_pm
        mock_get_db.return_value = iter([Mock()])  # Mock 数据库会话
        
        # 模拟创建项目
        mock_project = Mock(spec=Project)
        mock_project.id = 1
        mock_project.name = "新项目"
        mock_project.description = "项目描述"
        mock_project.theme = None
        mock_project.outline = None
        mock_project.status = "draft"
        mock_project.created_at = datetime.now()
        mock_project.updated_at = datetime.now()
        mock_project.characters = []
        mock_project.scenes = []
        
        mock_pm.create_project.return_value = mock_project
        
        # 发送请求
        response = client.post(
            "/api/projects",
            json={
                "name": "新项目",
                "description": "项目描述"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "新项目"
        assert data["status"] == "draft"


def test_create_project_invalid_name(client):
    """
    测试创建项目时名称包含非法字符
    """
    response = client.post(
        "/api/projects",
        json={
            "name": "项目/名称",  # 包含非法字符
            "description": "项目描述"
        }
    )
    
    assert response.status_code == 422  # Pydantic 验证错误


def test_create_project_empty_name(client):
    """
    测试创建项目时名称为空
    """
    response = client.post(
        "/api/projects",
        json={
            "name": "",
            "description": "项目描述"
        }
    )
    
    assert response.status_code == 422  # Pydantic 验证错误


def test_get_project_success(client, mock_project):
    """
    测试获取项目成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.get_project.return_value = mock_project
        
        response = client.get("/api/projects/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "测试项目"


def test_get_project_not_found(client):
    """
    测试获取不存在的项目
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.get_project.return_value = None
        
        response = client.get("/api/projects/999")
        
        assert response.status_code == 404


def test_update_project_success(client, mock_project):
    """
    测试更新项目成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        
        # 更新后的项目
        updated_project = Mock(spec=Project)
        updated_project.id = 1
        updated_project.name = "更新后的项目"
        updated_project.description = "更新后的描述"
        updated_project.theme = None
        updated_project.outline = None
        updated_project.status = "draft"
        updated_project.created_at = datetime.now()
        updated_project.updated_at = datetime.now()
        updated_project.characters = []
        updated_project.scenes = []
        
        mock_pm.update_project.return_value = updated_project
        
        response = client.put(
            "/api/projects/1",
            json={
                "name": "更新后的项目",
                "description": "更新后的描述"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "更新后的项目"


def test_update_project_not_found(client):
    """
    测试更新不存在的项目
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.update_project.return_value = None
        
        response = client.put(
            "/api/projects/999",
            json={"name": "新名称"}
        )
        
        assert response.status_code == 404


def test_delete_project_success(client):
    """
    测试删除项目成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.delete_project.return_value = True
        
        response = client.delete("/api/projects/1")
        
        assert response.status_code == 200
        data = response.json()
        assert "删除成功" in data["message"]


def test_delete_project_not_found(client):
    """
    测试删除不存在的项目
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.delete_project.return_value = False
        
        response = client.delete("/api/projects/999")
        
        assert response.status_code == 404


def test_list_projects_success(client, mock_project):
    """
    测试列出项目成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.list_projects.return_value = [mock_project]
        mock_pm.count_projects.return_value = 1
        
        response = client.get("/api/projects?page=1&page_size=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["projects"]) == 1


def test_list_projects_with_status_filter(client, mock_project):
    """
    测试按状态过滤项目列表
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        mock_pm.list_projects.return_value = [mock_project]
        mock_pm.count_projects.return_value = 1
        
        response = client.get("/api/projects?status_filter=draft&page=1&page_size=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1


def test_generate_script_success(client, mock_project):
    """
    测试生成剧本成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm, \
         patch("src.api.routes.projects.get_script_generator") as mock_get_sg:
        
        mock_pm = Mock()
        mock_sg = Mock()
        mock_get_pm.return_value = mock_pm
        mock_get_sg.return_value = mock_sg
        
        # 模拟项目存在
        mock_pm.get_project.return_value = mock_project
        
        # 模拟生成剧本
        mock_sg.generate_script.return_value = None
        
        # 模拟更新后的项目（包含角色和分镜）
        updated_project = Mock(spec=Project)
        updated_project.id = 1
        updated_project.name = "测试项目"
        updated_project.description = "这是一个测试项目"
        updated_project.theme = "科幻"
        updated_project.outline = "一个关于未来的故事"
        updated_project.status = "script_generated"
        updated_project.created_at = datetime.now()
        updated_project.updated_at = datetime.now()
        
        # 正确设置角色和分镜的属性
        mock_character = Mock(spec=Character)
        mock_character.id = 1
        mock_character.name = "角色1"
        mock_character.description = "角色描述"
        
        mock_scene = Mock(spec=Scene)
        mock_scene.id = 1
        mock_scene.scene_number = 1
        mock_scene.location = "地点"
        mock_scene.time_period = "时间"
        mock_scene.characters = "角色1"
        mock_scene.dialogue = "对话"
        mock_scene.visual_description = "视觉描述"
        mock_scene.duration = 10.0
        mock_scene.image_path = None
        mock_scene.video_path = None
        mock_scene.audio_path = None
        
        updated_project.characters = [mock_character]
        updated_project.scenes = [mock_scene]
        
        mock_pm.get_project.side_effect = [mock_project, updated_project]
        
        response = client.post(
            "/api/projects/1/generate-script",
            json={
                "theme": "科幻",
                "outline": "一个关于未来的故事"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "script_generated"


def test_generate_script_project_not_found(client):
    """
    测试生成剧本时项目不存在
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm, \
         patch("src.api.routes.projects.get_script_generator") as mock_get_sg:
        
        mock_pm = Mock()
        mock_sg = Mock()
        mock_get_pm.return_value = mock_pm
        mock_get_sg.return_value = mock_sg
        mock_pm.get_project.return_value = None
        
        response = client.post(
            "/api/projects/999/generate-script",
            json={
                "theme": "科幻"
            }
        )
        
        assert response.status_code == 404


def test_generate_script_missing_theme_and_outline(client):
    """
    测试生成剧本时主题和大纲都为空
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm, \
         patch("src.api.routes.projects.get_script_generator") as mock_get_sg:
        
        mock_pm = Mock()
        mock_sg = Mock()
        mock_get_pm.return_value = mock_pm
        mock_get_sg.return_value = mock_sg
        
        # 模拟项目存在但没有主题和大纲
        mock_project = Mock(spec=Project)
        mock_project.theme = None
        mock_project.outline = None
        mock_pm.get_project.return_value = mock_project
        
        # 模拟生成剧本时抛出 ValueError
        mock_sg.generate_script.side_effect = ValueError("主题和大纲至少需要提供一个")
        
        response = client.post(
            "/api/projects/1/generate-script",
            json={}
        )
        
        assert response.status_code == 400  # 输入验证错误


def test_regenerate_scene_success(client, mock_project):
    """
    测试重新生成分镜成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm, \
         patch("src.api.routes.projects.get_script_generator") as mock_get_sg:
        
        mock_pm = Mock()
        mock_sg = Mock()
        mock_get_pm.return_value = mock_pm
        mock_get_sg.return_value = mock_sg
        
        mock_pm.get_project.return_value = mock_project
        mock_sg.regenerate_scene.return_value = None
        
        response = client.post(
            "/api/projects/1/regenerate-scene",
            json={"scene_number": 1}
        )
        
        assert response.status_code == 200


def test_produce_video_success(client, mock_project):
    """
    测试提交生产任务成功
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm, \
         patch("src.api.routes.projects.get_task_orchestrator") as mock_get_to:
        
        mock_pm = Mock()
        mock_to = Mock()
        mock_get_pm.return_value = mock_pm
        mock_get_to.return_value = mock_to
        
        # 模拟项目有分镜
        mock_project.scenes = [Mock(spec=Scene)]
        mock_pm.get_project.return_value = mock_project
        
        # 模拟创建任务
        mock_task = Mock()
        mock_task.task_id = "task-123"
        mock_task.project_id = 1
        mock_task.status = "pending"
        mock_task.progress = 0.0
        mock_task.current_step = "初始化"
        mock_task.total_steps = 10
        mock_task.created_at = datetime.now()
        mock_task.updated_at = datetime.now()
        mock_task.error_message = None
        
        mock_to.create_production_task.return_value = mock_task
        
        response = client.post("/api/projects/1/produce")
        
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-123"
        assert data["status"] == "pending"


def test_produce_video_no_scenes(client, mock_project):
    """
    测试提交生产任务时项目没有分镜
    """
    with patch("src.api.routes.projects.get_project_manager") as mock_get_pm:
        mock_pm = Mock()
        mock_get_pm.return_value = mock_pm
        
        # 模拟项目没有分镜
        mock_project.scenes = []
        mock_pm.get_project.return_value = mock_project
        
        response = client.post("/api/projects/1/produce")
        
        assert response.status_code == 400
