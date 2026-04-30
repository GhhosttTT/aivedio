"""
剧本生成服务属性测试

使用 Hypothesis 进行基于属性的测试，验证 ScriptGenerator 的正确性属性
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, Scene, ProjectStatus, User
from src.services.script_generator import ScriptGenerator


# 策略定义
project_names = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=('L', 'N'),
    whitelist_characters=' '
))

scene_descriptions = st.text(min_size=5, max_size=200, alphabet=st.characters(
    whitelist_categories=('L', 'N', 'P'),
    whitelist_characters=' ，。！？'
))

dialogues = st.text(min_size=1, max_size=100, alphabet=st.characters(
    whitelist_categories=('L', 'N', 'P'),
    whitelist_characters=' ，。！？'
))

character_names = st.text(min_size=1, max_size=20, alphabet=st.characters(
    whitelist_categories=('L',)
))

emotions = st.sampled_from(['开心', '悲伤', '愤怒', '惊讶', '平静', '紧张'])


def create_test_db_and_generator():
    """创建测试数据库和生成器"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # 创建测试用户
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password="hashed_password"
    )
    session.add(user)
    session.commit()
    
    # 创建 Mock LLM 服务
    mock_llm = MagicMock()
    
    generator = ScriptGenerator(db=session, llm_service=mock_llm)
    
    return session, generator, mock_llm, user


class TestScriptGeneratorProperties:
    """剧本生成服务属性测试类"""
    
    @given(
        project_name=project_names,
        num_characters=st.integers(min_value=1, max_value=5),
        num_scenes=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=20, deadline=2000)
    def test_property_5_script_parsing_structure_integrity(
        self,
        project_name,
        num_characters,
        num_scenes
    ):
        """
        属性 5：剧本解析结构完整性
        
        验证需求：2.2
        
        属性：对于任何有效的剧本文本，解析后的结果必须包含完整的结构：
        1. 包含 characters 和 scenes 字段
        2. 每个角色包含 name 和 description
        3. 每个分镜包含 scene_number、description、dialogue、speaker
        4. 分镜编号连续且从 1 开始
        5. 角色名称唯一
        """
        session, generator, mock_llm, user = create_test_db_and_generator()
        
        try:
            # 生成有效的剧本文本
            characters_text = "\n".join([
                f"- 角色{i}：描述{i}" for i in range(1, num_characters + 1)
            ])
            
            scenes_text = "\n\n".join([
                f"""分镜{i}：
- 场景描述：场景{i}描述
- 出现角色：[角色1]
- 对话：对话{i}
- 说话人：角色1
- 情感：开心"""
                for i in range(1, num_scenes + 1)
            ])
            
            script_text = f"""
【剧本】
{project_name}的故事

【角色】
{characters_text}

【分镜】
{scenes_text}
"""
            
            # 解析剧本
            result = generator.parse_script(script_text)
            
            # 验证结构完整性
            assert "characters" in result, "缺少 characters 字段"
            assert "scenes" in result, "缺少 scenes 字段"
            
            # 验证角色结构
            assert len(result["characters"]) == num_characters
            for char in result["characters"]:
                assert "name" in char, "角色缺少 name 字段"
                assert "description" in char, "角色缺少 description 字段"
                assert char["name"], "角色名称不能为空"
            
            # 验证角色名称唯一性
            char_names = [c["name"] for c in result["characters"]]
            assert len(char_names) == len(set(char_names)), "角色名称不唯一"
            
            # 验证分镜结构
            assert len(result["scenes"]) == num_scenes
            for i, scene in enumerate(result["scenes"], 1):
                assert "scene_number" in scene, "分镜缺少 scene_number 字段"
                assert "description" in scene, "分镜缺少 description 字段"
                assert "dialogue" in scene, "分镜缺少 dialogue 字段"
                assert "speaker" in scene, "分镜缺少 speaker 字段"
                
                # 验证分镜编号连续
                assert scene["scene_number"] == i, f"分镜编号不连续：期望 {i}，实际 {scene['scene_number']}"
        
        finally:
            session.close()
    
    @given(
        scene_number=st.integers(min_value=1, max_value=5),
        new_description=scene_descriptions,
        new_dialogue=dialogues,
        new_speaker=character_names,
        new_emotion=emotions
    )
    @settings(max_examples=15, deadline=2000)
    def test_property_6_scene_regeneration_isolation(
        self,
        scene_number,
        new_description,
        new_dialogue,
        new_speaker,
        new_emotion
    ):
        """
        属性 6：分镜重新生成隔离性
        
        验证需求：2.4
        
        属性：重新生成某个分镜时，不应影响其他分镜：
        1. 只有指定的分镜被修改
        2. 其他分镜的内容保持不变
        3. 分镜总数不变
        4. 分镜编号不变
        """
        # 过滤无效输入
        assume(len(new_description.strip()) > 0)
        assume(len(new_dialogue.strip()) > 0)
        assume(len(new_speaker.strip()) > 0)
        
        session, generator, mock_llm, user = create_test_db_and_generator()
        
        try:
            # 创建项目
            project = Project(
                name="测试项目",
                theme="测试主题",
                status=ProjectStatus.DRAFT,
                user_id=user.id
            )
            session.add(project)
            session.commit()
            
            # 创建多个分镜
            num_scenes = 5
            original_scenes = []
            for i in range(1, num_scenes + 1):
                scene = Scene(
                    project_id=project.id,
                    scene_number=i,
                    visual_description=f"原始场景{i}",
                    dialogue=f"原始对话{i}",
                    character_name=f"角色{i}"
                )
                session.add(scene)
                original_scenes.append({
                    "scene_number": i,
                    "description": f"原始场景{i}",
                    "dialogue": f"原始对话{i}",
                    "speaker": f"角色{i}"
                })
            session.commit()
            
            # Mock LLM 输出
            mock_output = f"""
- 对话：{new_dialogue}
- 说话人：{new_speaker}
- 情感：{new_emotion}
"""
            mock_llm.generate.return_value = mock_output
            
            # 重新生成指定分镜
            result = generator.regenerate_scene(
                project_id=project.id,
                scene_number=scene_number,
                new_description=new_description
            )
            
            # 验证返回结果
            assert result["scene_number"] == scene_number
            assert result["description"] == new_description
            assert result["dialogue"] == new_dialogue
            
            # 查询所有分镜
            all_scenes = session.query(Scene).filter(
                Scene.project_id == project.id
            ).order_by(Scene.scene_number).all()
            
            # 验证分镜总数不变
            assert len(all_scenes) == num_scenes, "分镜总数改变"
            
            # 验证每个分镜
            for scene in all_scenes:
                if scene.scene_number == scene_number:
                    # 验证目标分镜被修改
                    assert scene.visual_description == new_description, "目标分镜未被修改"
                    assert scene.dialogue == new_dialogue, "目标分镜对话未被修改"
                else:
                    # 验证其他分镜未被修改
                    original = original_scenes[scene.scene_number - 1]
                    assert scene.visual_description == original["description"], \
                        f"分镜 {scene.scene_number} 的描述被意外修改"
                    assert scene.dialogue == original["dialogue"], \
                        f"分镜 {scene.scene_number} 的对话被意外修改"
                    assert scene.character_name == original["speaker"], \
                        f"分镜 {scene.scene_number} 的说话人被意外修改"
        
        finally:
            session.close()
    
    @given(
        num_scenes=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=10, deadline=1000)
    def test_property_extra_scene_numbers_are_unique_and_sequential(
        self,
        num_scenes
    ):
        """
        额外属性：分镜编号唯一性和连续性
        
        属性：解析后的分镜编号必须：
        1. 唯一（没有重复）
        2. 连续（从 1 开始，无间隔）
        3. 有序（按编号升序排列）
        """
        session, generator, mock_llm, user = create_test_db_and_generator()
        
        try:
            # 生成剧本文本
            scenes_text = "\n\n".join([
                f"""分镜{i}：
- 场景描述：场景{i}
- 出现角色：[角色1]
- 对话：对话{i}
- 说话人：角色1
- 情感：开心"""
                for i in range(1, num_scenes + 1)
            ])
            
            script_text = f"""
【剧本】
测试剧本

【角色】
- 角色1：测试角色

【分镜】
{scenes_text}
"""
            
            # 解析剧本
            result = generator.parse_script(script_text)
            
            # 提取分镜编号
            scene_numbers = [s["scene_number"] for s in result["scenes"]]
            
            # 验证唯一性
            assert len(scene_numbers) == len(set(scene_numbers)), "分镜编号不唯一"
            
            # 验证连续性（从 1 开始，无间隔）
            expected_numbers = list(range(1, num_scenes + 1))
            assert scene_numbers == expected_numbers, \
                f"分镜编号不连续：期望 {expected_numbers}，实际 {scene_numbers}"
        
        finally:
            session.close()
    
    @given(
        description=scene_descriptions,
        style=st.sampled_from(['电影级画质', '动漫风格', '写实风格', '油画风格']),
        num_tags=st.integers(min_value=0, max_value=5)
    )
    @settings(max_examples=10, deadline=1000)
    def test_property_extra_visual_prompt_contains_all_elements(
        self,
        description,
        style,
        num_tags
    ):
        """
        额外属性：视觉提示词包含所有元素
        
        属性：生成的视觉提示词必须包含：
        1. 场景描述
        2. 风格标签
        3. 所有附加标签
        4. 负面提示词包含质量控制关键词
        """
        assume(len(description.strip()) > 0)
        
        session, generator, mock_llm, user = create_test_db_and_generator()
        
        try:
            # 创建项目和分镜
            project = Project(
                name="测试项目",
                theme="测试",
                status=ProjectStatus.DRAFT,
                user_id=user.id
            )
            session.add(project)
            session.commit()
            
            scene = Scene(
                project_id=project.id,
                scene_number=1,
                visual_description=description,
                dialogue="测试对话",
                character_name="测试角色"
            )
            session.add(scene)
            session.commit()
            
            # 生成附加标签
            additional_tags = [f"标签{i}" for i in range(num_tags)]
            
            # 生成视觉提示词
            positive, negative = generator.generate_visual_prompt(
                scene=scene,
                style=style,
                additional_tags=additional_tags
            )
            
            # 验证正面提示词包含所有元素
            assert description in positive, "正面提示词缺少场景描述"
            assert style in positive, "正面提示词缺少风格标签"
            for tag in additional_tags:
                assert tag in positive, f"正面提示词缺少附加标签：{tag}"
            
            # 验证负面提示词包含质量控制关键词
            quality_keywords = ['低质量', '模糊', '变形', '扭曲']
            assert any(kw in negative for kw in quality_keywords), \
                "负面提示词缺少质量控制关键词"
        
        finally:
            session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
