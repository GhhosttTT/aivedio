"""
项目管理服务测试

测试 ProjectManager 的所有功能
"""

import pytest
import os
import tempfile
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, Character, Scene, ProjectStatus
from src.services.project_manager import ProjectManager


@pytest.fixture
def db_session():
    """创建测试数据库会话"""
    # 使用内存数据库
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()


@pytest.fixture
def project_manager(db_session):
    """创建 ProjectManager 实例"""
    return ProjectManager(db_session)


@pytest.fixture
def temp_storage():
    """创建临时存储目录"""
    temp_dir = tempfile.mkdtemp()
    
    # 设置环境变量
    os.environ["STORAGE_PATH"] = temp_dir
    
    yield temp_dir
    
    # 清理
    import shutil
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


class TestProjectManager:
    """项目管理服务测试类"""
    
    def test_create_project_success(self, project_manager, temp_storage):
        """测试创建项目（成功）"""
        project = project_manager.create_project(
            name="测试项目",
            description="这是一个测试项目",
            theme="科幻",
            outline="一个关于未来的故事"
        )
        
        assert project.id is not None
        assert project.name == "测试项目"
        assert project.description == "这是一个测试项目"
        assert project.theme == "科幻"
        assert project.outline == "一个关于未来的故事"
        assert project.status == ProjectStatus.DRAFT
        assert project.total_scenes == 0
        assert project.created_at is not None
        assert project.updated_at is not None
    
    def test_create_project_empty_name(self, project_manager):
        """测试创建项目（名称为空）"""
        with pytest.raises(ValueError, match="项目名称不能为空"):
            project_manager.create_project(name="")
    
    def test_create_project_name_too_long(self, project_manager):
        """测试创建项目（名称过长）"""
        long_name = "A" * 101
        with pytest.raises(ValueError, match="项目名称不能超过100个字符"):
            project_manager.create_project(name=long_name)
    
    def test_create_project_invalid_characters(self, project_manager):
        """测试创建项目（包含非法字符）"""
        with pytest.raises(ValueError, match="项目名称只能包含"):
            project_manager.create_project(name="测试@#$%项目")
    
    def test_get_project_success(self, project_manager, temp_storage):
        """测试获取项目（成功）"""
        # 先创建项目
        created_project = project_manager.create_project(name="测试项目")
        
        # 获取项目
        project = project_manager.get_project(created_project.id)
        
        assert project is not None
        assert project.id == created_project.id
        assert project.name == "测试项目"
    
    def test_get_project_not_found(self, project_manager):
        """测试获取项目（不存在）"""
        project = project_manager.get_project(99999)
        
        assert project is None
    
    def test_update_project_success(self, project_manager, temp_storage):
        """测试更新项目（成功）"""
        # 先创建项目
        project = project_manager.create_project(name="原始名称")
        original_updated_at = project.updated_at
        
        # 更新项目
        import time
        time.sleep(0.1)  # 确保时间戳不同
        
        updated_project = project_manager.update_project(
            project.id,
            name="新名称",
            description="新描述",
            theme="新主题"
        )
        
        assert updated_project.name == "新名称"
        assert updated_project.description == "新描述"
        assert updated_project.theme == "新主题"
        assert updated_project.updated_at > original_updated_at
    
    def test_update_project_status(self, project_manager, temp_storage):
        """测试更新项目状态"""
        project = project_manager.create_project(name="测试项目")
        
        # 更新为完成状态
        updated_project = project_manager.update_project(
            project.id,
            status=ProjectStatus.COMPLETED
        )
        
        assert updated_project.status == ProjectStatus.COMPLETED
        assert updated_project.completed_at is not None
    
    def test_update_project_not_found(self, project_manager):
        """测试更新项目（不存在）"""
        with pytest.raises(ValueError, match="项目不存在"):
            project_manager.update_project(99999, name="新名称")
    
    def test_delete_project_success(self, project_manager, temp_storage):
        """测试删除项目（成功）"""
        # 先创建项目
        project = project_manager.create_project(name="待删除项目")
        project_id = project.id
        
        # 删除项目
        result = project_manager.delete_project(project_id)
        
        assert result is True
        
        # 验证项目已删除
        deleted_project = project_manager.get_project(project_id)
        assert deleted_project is None
    
    def test_delete_project_not_found(self, project_manager):
        """测试删除项目（不存在）"""
        with pytest.raises(ValueError, match="项目不存在"):
            project_manager.delete_project(99999)
    
    def test_list_projects_all(self, project_manager, temp_storage):
        """测试列出所有项目"""
        # 创建多个项目
        project_manager.create_project(name="项目1")
        project_manager.create_project(name="项目2")
        project_manager.create_project(name="项目3")
        
        # 列出所有项目
        projects = project_manager.list_projects()
        
        assert len(projects) == 3
        # 默认按创建时间倒序
        assert projects[0].name == "项目3"
        assert projects[1].name == "项目2"
        assert projects[2].name == "项目1"
    
    def test_list_projects_with_status_filter(self, project_manager, temp_storage):
        """测试列出项目（状态过滤）"""
        # 创建不同状态的项目
        p1 = project_manager.create_project(name="草稿项目")
        p2 = project_manager.create_project(name="完成项目")
        project_manager.update_project(p2.id, status=ProjectStatus.COMPLETED)
        
        # 只列出草稿项目
        draft_projects = project_manager.list_projects(status=ProjectStatus.DRAFT)
        
        assert len(draft_projects) == 1
        assert draft_projects[0].name == "草稿项目"
    
    def test_list_projects_with_pagination(self, project_manager, temp_storage):
        """测试列出项目（分页）"""
        # 创建多个项目
        for i in range(5):
            project_manager.create_project(name=f"项目{i+1}")
        
        # 第一页（2条）
        page1 = project_manager.list_projects(limit=2, offset=0)
        assert len(page1) == 2
        assert page1[0].name == "项目5"
        assert page1[1].name == "项目4"
        
        # 第二页（2条）
        page2 = project_manager.list_projects(limit=2, offset=2)
        assert len(page2) == 2
        assert page2[0].name == "项目3"
        assert page2[1].name == "项目2"
    
    def test_count_projects(self, project_manager, temp_storage):
        """测试统计项目数量"""
        # 创建项目
        project_manager.create_project(name="项目1")
        project_manager.create_project(name="项目2")
        
        # 统计总数
        total_count = project_manager.count_projects()
        assert total_count == 2
        
        # 统计草稿项目
        draft_count = project_manager.count_projects(status=ProjectStatus.DRAFT)
        assert draft_count == 2
    
    def test_add_character(self, project_manager, temp_storage):
        """测试添加角色"""
        # 先创建项目
        project = project_manager.create_project(name="测试项目")
        
        # 添加角色
        character = project_manager.add_character(
            project_id=project.id,
            name="主角",
            description="勇敢的冒险家",
            appearance="高大威猛",
            personality="正义勇敢",
            voice_speaker="male_1",
            voice_emotion="坚定"
        )
        
        assert character.id is not None
        assert character.project_id == project.id
        assert character.name == "主角"
        assert character.description == "勇敢的冒险家"
        assert character.voice_speaker == "male_1"
    
    def test_add_character_project_not_found(self, project_manager):
        """测试添加角色（项目不存在）"""
        with pytest.raises(ValueError, match="项目不存在"):
            project_manager.add_character(
                project_id=99999,
                name="角色"
            )
    
    def test_add_character_empty_name(self, project_manager, temp_storage):
        """测试添加角色（名称为空）"""
        project = project_manager.create_project(name="测试项目")
        
        with pytest.raises(ValueError, match="角色名称不能为空"):
            project_manager.add_character(
                project_id=project.id,
                name=""
            )
    
    def test_add_scene(self, project_manager, temp_storage):
        """测试添加分镜"""
        # 先创建项目
        project = project_manager.create_project(name="测试项目")
        
        # 添加分镜
        scene = project_manager.add_scene(
            project_id=project.id,
            scene_number=1,
            title="开场",
            description="阳光明媚的早晨",
            dialogue="你好，世界！",
            character_name="主角",
            visual_prompt="sunny morning, bright sky"
        )
        
        assert scene.id is not None
        assert scene.project_id == project.id
        assert scene.scene_number == 1
        assert scene.title == "开场"
        assert scene.description == "阳光明媚的早晨"
        assert scene.dialogue == "你好，世界！"
        assert scene.character_name == "主角"
        
        # 验证项目的总分镜数已更新
        updated_project = project_manager.get_project(project.id)
        assert updated_project.total_scenes == 1
    
    def test_add_scene_project_not_found(self, project_manager):
        """测试添加分镜（项目不存在）"""
        with pytest.raises(ValueError, match="项目不存在"):
            project_manager.add_scene(
                project_id=99999,
                scene_number=1,
                description="场景描述"
            )
    
    def test_add_scene_empty_description(self, project_manager, temp_storage):
        """测试添加分镜（描述为空）"""
        project = project_manager.create_project(name="测试项目")
        
        with pytest.raises(ValueError, match="场景描述不能为空"):
            project_manager.add_scene(
                project_id=project.id,
                scene_number=1,
                description=""
            )
    
    def test_get_project_scenes(self, project_manager, temp_storage):
        """测试获取项目分镜"""
        # 创建项目并添加分镜
        project = project_manager.create_project(name="测试项目")
        
        project_manager.add_scene(project.id, 1, "场景1")
        project_manager.add_scene(project.id, 2, "场景2")
        project_manager.add_scene(project.id, 3, "场景3")
        
        # 获取分镜
        scenes = project_manager.get_project_scenes(project.id)
        
        assert len(scenes) == 3
        assert scenes[0].scene_number == 1
        assert scenes[1].scene_number == 2
        assert scenes[2].scene_number == 3
    
    def test_get_project_characters(self, project_manager, temp_storage):
        """测试获取项目角色"""
        # 创建项目并添加角色
        project = project_manager.create_project(name="测试项目")
        
        project_manager.add_character(project.id, "角色1")
        project_manager.add_character(project.id, "角色2")
        
        # 获取角色
        characters = project_manager.get_project_characters(project.id)
        
        assert len(characters) == 2
        assert characters[0].name == "角色1"
        assert characters[1].name == "角色2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
