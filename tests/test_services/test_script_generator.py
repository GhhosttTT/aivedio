"""
剧本生成服务单元测试

测试 ScriptGenerator 的核心功能
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, Character, Scene, ProjectStatus
from src.services.script_generator import ScriptGenerator, ScriptParseError


class TestScriptGenerator:
    """剧本生成服务测试类"""
    
    @pytest.fixture
    def db_session(self):
        """创建测试数据库会话"""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
    
    @pytest.fixture
    def test_user(self, db_session):
        """创建测试用户"""
        from src.database.models import User
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_password_here"
        )
        db_session.add(user)
        db_session.commit()
        return user
    
    @pytest.fixture
    def mock_llm_service(self):
        """创建 Mock LLM 服务"""
        mock_service = MagicMock()
        return mock_service
    
    @pytest.fixture
    def script_generator(self, db_session, mock_llm_service):
        """创建剧本生成服务实例"""
        return ScriptGenerator(db=db_session, llm_service=mock_llm_service)
    
    @pytest.fixture
    def sample_project(self, db_session, test_user):
        """创建示例项目"""
        project = Project(
            name="测试项目",
            theme="爱情故事",
            outline="一个关于爱情的故事",
            status=ProjectStatus.DRAFT,
            user_id=test_user.id
        )
        db_session.add(project)
        db_session.commit()
        return project
    
    def test_generate_script_success(
        self,
        script_generator,
        sample_project,
        mock_llm_service
    ):
        """测试：成功生成剧本"""
        # Mock LLM 输出
        mock_script = """
【剧本】
这是一个关于爱情的故事。

【角色】
- 小明：男主角，阳光开朗
- 小红：女主角，温柔善良

【分镜】
分镜1：
- 场景描述：公园里，阳光明媚
- 出现角色：[小明, 小红]
- 对话：你好，很高兴认识你
- 说话人：小明
- 情感：开心

分镜2：
- 场景描述：咖啡厅，温馨的氛围
- 出现角色：[小明, 小红]
- 对话：我也很高兴认识你
- 说话人：小红
- 情感：温柔
"""
        
        mock_llm_service.generate_script_prompt.return_value = "test prompt"
        mock_llm_service.generate.return_value = mock_script
        
        # 生成剧本
        result = script_generator.generate_script(
            project_id=sample_project.id,
            theme="爱情故事",
            num_scenes=2
        )
        
        # 验证
        assert "characters" in result
        assert "scenes" in result
        assert len(result["characters"]) == 2
        assert len(result["scenes"]) == 2
        assert result["characters"][0]["name"] == "小明"
        assert result["scenes"][0]["scene_number"] == 1
        assert result["scenes"][0]["description"] == "公园里，阳光明媚"
        
        # 验证 LLM 服务被调用
        mock_llm_service.generate_script_prompt.assert_called_once()
        mock_llm_service.generate.assert_called_once()
    
    def test_generate_script_no_theme_or_outline(
        self,
        script_generator,
        sample_project
    ):
        """测试：主题和大纲都为空时抛出异常"""
        with pytest.raises(ValueError, match="主题和大纲至少需要提供一个"):
            script_generator.generate_script(
                project_id=sample_project.id,
                theme=None,
                outline=None
            )
    
    def test_generate_script_project_not_found(
        self,
        script_generator
    ):
        """测试：项目不存在时抛出异常"""
        with pytest.raises(ValueError, match="项目不存在"):
            script_generator.generate_script(
                project_id=99999,
                theme="测试主题"
            )
    
    def test_parse_script_success(self, script_generator):
        """测试：成功解析剧本"""
        script_text = """
【剧本】
这是一个测试剧本。

【角色】
- 角色A：描述A
- 角色B：描述B

【分镜】
分镜1：
- 场景描述：场景1描述
- 出现角色：[角色A]
- 对话：对话1
- 说话人：角色A
- 情感：开心

分镜2：
- 场景描述：场景2描述
- 出现角色：[角色B]
- 对话：对话2
- 说话人：角色B
- 情感：悲伤
"""
        
        result = script_generator.parse_script(script_text)
        
        # 验证
        assert "characters" in result
        assert "scenes" in result
        assert len(result["characters"]) == 2
        assert len(result["scenes"]) == 2
        assert result["characters"][0]["name"] == "角色A"
        assert result["scenes"][0]["scene_number"] == 1
        assert result["scenes"][0]["dialogue"] == "对话1"
    
    def test_parse_script_empty_text(self, script_generator):
        """测试：空文本时抛出异常"""
        with pytest.raises(ScriptParseError, match="剧本文本为空"):
            script_generator.parse_script("")
    
    def test_parse_script_no_scenes(self, script_generator):
        """测试：没有分镜时抛出异常"""
        script_text = """
【剧本】
测试剧本

【角色】
- 角色A：描述A
"""
        
        with pytest.raises(ScriptParseError, match="未找到分镜部分"):
            script_generator.parse_script(script_text)
    
    def test_parse_characters(self, script_generator):
        """测试：解析角色信息"""
        script_text = """
【角色】
- 小明：男主角
- 小红：女主角
- 小刚：配角

【分镜】
分镜1：
- 场景描述：测试
"""
        
        characters = script_generator._parse_characters(script_text)
        
        assert len(characters) == 3
        assert characters[0]["name"] == "小明"
        assert characters[0]["description"] == "男主角"
        assert characters[1]["name"] == "小红"
        assert characters[2]["name"] == "小刚"
    
    def test_parse_scenes(self, script_generator):
        """测试：解析分镜信息"""
        script_text = """
【分镜】
分镜1：
- 场景描述：公园
- 出现角色：[小明]
- 对话：你好
- 说话人：小明
- 情感：开心

分镜2：
- 场景描述：咖啡厅
- 出现角色：[小红]
- 对话：再见
- 说话人：小红
- 情感：悲伤
"""
        
        scenes = script_generator._parse_scenes(script_text)
        
        assert len(scenes) == 2
        assert scenes[0]["scene_number"] == 1
        assert scenes[0]["description"] == "公园"
        assert scenes[0]["dialogue"] == "你好"
        assert scenes[0]["speaker"] == "小明"
        assert scenes[1]["scene_number"] == 2
    
    def test_parse_scene_fields(self, script_generator):
        """测试：解析分镜字段"""
        scene_content = """
- 场景描述：测试场景
- 出现角色：[角色A, 角色B]
- 对话：测试对话
- 说话人：角色A
- 情感：开心
"""
        
        result = script_generator._parse_scene_fields(scene_content)
        
        assert result["description"] == "测试场景"
        assert result["characters"] == ["角色A", "角色B"]
        assert result["dialogue"] == "测试对话"
        assert result["speaker"] == "角色A"
        assert result["emotion"] == "开心"
    
    def test_regenerate_scene_success(
        self,
        script_generator,
        sample_project,
        db_session,
        mock_llm_service
    ):
        """测试：成功重新生成分镜"""
        # 创建分镜
        scene = Scene(
            project_id=sample_project.id,
            scene_number=1,
            visual_description="原始描述",
            dialogue="原始对话",
            character_name="小明"
        )
        db_session.add(scene)
        db_session.commit()
        
        # Mock LLM 输出
        mock_output = """
- 对话：新对话
- 说话人：小红
- 情感：开心
"""
        mock_llm_service.generate.return_value = mock_output
        
        # 重新生成分镜
        result = script_generator.regenerate_scene(
            project_id=sample_project.id,
            scene_number=1,
            new_description="新描述"
        )
        
        # 验证
        assert result["scene_number"] == 1
        assert result["description"] == "新描述"
        assert result["dialogue"] == "新对话"
        assert result["speaker"] == "小红"
        
        # 验证数据库更新
        updated_scene = db_session.query(Scene).filter(
            Scene.id == scene.id
        ).first()
        assert updated_scene.visual_description == "新描述"
        assert updated_scene.dialogue == "新对话"
    
    def test_regenerate_scene_project_not_found(
        self,
        script_generator
    ):
        """测试：项目不存在时抛出异常"""
        with pytest.raises(ValueError, match="项目不存在"):
            script_generator.regenerate_scene(
                project_id=99999,
                scene_number=1
            )
    
    def test_regenerate_scene_scene_not_found(
        self,
        script_generator,
        sample_project
    ):
        """测试：分镜不存在时抛出异常"""
        with pytest.raises(ValueError, match="分镜不存在"):
            script_generator.regenerate_scene(
                project_id=sample_project.id,
                scene_number=99
            )
    
    def test_generate_visual_prompt(
        self,
        script_generator,
        sample_project,
        db_session
    ):
        """测试：生成视觉提示词"""
        # 创建分镜
        scene = Scene(
            project_id=sample_project.id,
            scene_number=1,
            visual_description="公园里，阳光明媚，两个人在散步",
            dialogue="你好",
            character_name="小明"
        )
        db_session.add(scene)
        db_session.commit()
        
        # 生成视觉提示词
        positive, negative = script_generator.generate_visual_prompt(
            scene=scene,
            style="电影级画质",
            additional_tags=["自然光", "广角镜头"]
        )
        
        # 验证
        assert "公园里，阳光明媚，两个人在散步" in positive
        assert "电影级画质" in positive
        assert "自然光" in positive
        assert "广角镜头" in positive
        assert "低质量" in negative
        assert "模糊" in negative
    
    def test_save_script_to_db(
        self,
        script_generator,
        sample_project,
        db_session
    ):
        """测试：保存剧本到数据库"""
        parsed_script = {
            "script": "测试剧本",
            "characters": [
                {"name": "角色A", "description": "描述A"},
                {"name": "角色B", "description": "描述B"}
            ],
            "scenes": [
                {
                    "scene_number": 1,
                    "description": "场景1",
                    "dialogue": "对话1",
                    "speaker": "角色A"
                },
                {
                    "scene_number": 2,
                    "description": "场景2",
                    "dialogue": "对话2",
                    "speaker": "角色B"
                }
            ]
        }
        
        # 保存到数据库
        script_generator._save_script_to_db(sample_project, parsed_script)
        
        # 验证角色
        characters = db_session.query(Character).filter(
            Character.project_id == sample_project.id
        ).all()
        assert len(characters) == 2
        assert characters[0].name == "角色A"
        assert characters[1].name == "角色B"
        
        # 验证分镜
        scenes = db_session.query(Scene).filter(
            Scene.project_id == sample_project.id
        ).all()
        assert len(scenes) == 2
        assert scenes[0].scene_number == 1
        assert scenes[0].visual_description == "场景1"
        assert scenes[1].scene_number == 2
    
    def test_parse_script_with_colon_variants(self, script_generator):
        """测试：解析使用不同冒号的剧本"""
        # 测试中文冒号和英文冒号混用
        script_text = """
【剧本】
测试

【角色】
- 角色A：描述A
- 角色B: 描述B

【分镜】
分镜1:
- 场景描述：场景1
- 对话: 对话1
- 说话人：角色A
"""
        
        result = script_generator.parse_script(script_text)
        
        assert len(result["characters"]) == 2
        assert len(result["scenes"]) == 1
        assert result["scenes"][0]["dialogue"] == "对话1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
