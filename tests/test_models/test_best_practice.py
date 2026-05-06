"""
最佳实践数据模型单元测试
"""

import pytest
from datetime import datetime
from src.models.best_practice import (
    BestPractice,
    PracticeSource,
    SceneCategory
)


class TestBestPractice:
    """测试 BestPractice 数据类"""
    
    def test_create_basic_practice(self):
        """测试创建基本最佳实践"""
        practice = BestPractice(
            id="test-001",
            name="测试实践",
            description="这是一个测试实践",
            source=PracticeSource.CUSTOM
        )
        
        assert practice.id == "test-001"
        assert practice.name == "测试实践"
        assert practice.description == "这是一个测试实践"
        assert practice.source == PracticeSource.CUSTOM
        assert practice.created_at is not None
        assert practice.updated_at is not None
    
    def test_create_full_practice(self):
        """测试创建完整最佳实践"""
        practice = BestPractice(
            id="test-002",
            name="完整实践",
            description="完整的最佳实践配置",
            source=PracticeSource.CIVITAI,
            source_url="https://civitai.com/models/12345",
            author="测试作者",
            applicable_scenes=[SceneCategory.PORTRAIT, SceneCategory.CLOSE_UP],
            tags=["真实感", "高质量"],
            workflow_type="ipadapter",
            checkpoint="RealVisXL_V4.0",
            lora_models=["FilmGrain.safetensors"],
            sampling_steps=30,
            cfg_scale=6.5,
            sampler="dpmpp_2m",
            scheduler="karras",
            resolution="1024x1024",
            ipadapter_weight=0.85,
            prompt_template="a beautiful {subject}",
            negative_prompt="CGI, 3D render",
            quality_score=95.0,
            realism_score=90.0,
            consistency_score=88.0,
            speed_score=75.0
        )
        
        assert practice.id == "test-002"
        assert practice.source == PracticeSource.CIVITAI
        assert practice.author == "测试作者"
        assert len(practice.applicable_scenes) == 2
        assert SceneCategory.PORTRAIT in practice.applicable_scenes
        assert len(practice.tags) == 2
        assert practice.checkpoint == "RealVisXL_V4.0"
        assert practice.sampling_steps == 30
        assert practice.cfg_scale == 6.5
    
    def test_calculate_overall_score(self):
        """测试计算综合评分"""
        practice = BestPractice(
            id="test-003",
            name="评分测试",
            description="测试评分计算",
            source=PracticeSource.CUSTOM,
            quality_score=90.0,
            realism_score=85.0,
            consistency_score=80.0,
            speed_score=70.0
        )
        
        # 综合评分 = 90*0.4 + 85*0.3 + 80*0.2 + 70*0.1 = 36 + 25.5 + 16 + 7 = 84.5
        expected_score = 84.5
        assert abs(practice.overall_score - expected_score) < 0.01
    
    def test_calculate_overall_score_manual(self):
        """测试手动计算综合评分"""
        practice = BestPractice(
            id="test-004",
            name="手动评分测试",
            description="测试手动评分计算",
            source=PracticeSource.CUSTOM,
            quality_score=80.0,
            realism_score=75.0,
            consistency_score=70.0,
            speed_score=90.0,
            overall_score=0.0  # 初始为 0
        )
        
        # 手动计算
        score = practice.calculate_overall_score()
        
        # 综合评分 = 80*0.4 + 75*0.3 + 70*0.2 + 90*0.1 = 32 + 22.5 + 14 + 9 = 77.5
        expected_score = 77.5
        assert abs(score - expected_score) < 0.01
        assert abs(practice.overall_score - expected_score) < 0.01
    
    def test_is_applicable_for_scene_specific(self):
        """测试场景适用性检查 - 特定场景"""
        practice = BestPractice(
            id="test-005",
            name="场景测试",
            description="测试场景适用性",
            source=PracticeSource.CUSTOM,
            applicable_scenes=[SceneCategory.PORTRAIT, SceneCategory.CLOSE_UP]
        )
        
        assert practice.is_applicable_for_scene(SceneCategory.PORTRAIT) is True
        assert practice.is_applicable_for_scene(SceneCategory.CLOSE_UP) is True
        assert practice.is_applicable_for_scene(SceneCategory.LANDSCAPE) is False
        assert practice.is_applicable_for_scene(SceneCategory.ACTION) is False
    
    def test_is_applicable_for_scene_general(self):
        """测试场景适用性检查 - 通用场景"""
        practice = BestPractice(
            id="test-006",
            name="通用场景测试",
            description="测试通用场景适用性",
            source=PracticeSource.CUSTOM,
            applicable_scenes=[SceneCategory.GENERAL]
        )
        
        # GENERAL 适用于所有场景
        assert practice.is_applicable_for_scene(SceneCategory.PORTRAIT) is True
        assert practice.is_applicable_for_scene(SceneCategory.LANDSCAPE) is True
        assert practice.is_applicable_for_scene(SceneCategory.ACTION) is True
    
    def test_is_applicable_for_scene_empty(self):
        """测试场景适用性检查 - 空场景列表"""
        practice = BestPractice(
            id="test-007",
            name="空场景测试",
            description="测试空场景列表",
            source=PracticeSource.CUSTOM,
            applicable_scenes=[]
        )
        
        # 空列表适用于所有场景
        assert practice.is_applicable_for_scene(SceneCategory.PORTRAIT) is True
        assert practice.is_applicable_for_scene(SceneCategory.LANDSCAPE) is True
        assert practice.is_applicable_for_scene(SceneCategory.ACTION) is True
    
    def test_to_dict(self):
        """测试转换为字典"""
        practice = BestPractice(
            id="test-008",
            name="字典测试",
            description="测试转换为字典",
            source=PracticeSource.GITHUB,
            applicable_scenes=[SceneCategory.PORTRAIT],
            tags=["测试"],
            quality_score=85.0
        )
        
        data = practice.to_dict()
        
        assert data["id"] == "test-008"
        assert data["name"] == "字典测试"
        assert data["source"] == "github"
        assert data["applicable_scenes"] == ["portrait"]
        assert data["tags"] == ["测试"]
        assert data["quality_score"] == 85.0
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "id": "test-009",
            "name": "从字典创建",
            "description": "测试从字典创建实例",
            "source": "civitai",
            "applicable_scenes": ["portrait", "close_up"],
            "tags": ["测试"],
            "quality_score": 90.0,
            "realism_score": 85.0,
            "consistency_score": 80.0,
            "speed_score": 75.0,
        }
        
        practice = BestPractice.from_dict(data)
        
        assert practice.id == "test-009"
        assert practice.name == "从字典创建"
        assert practice.source == PracticeSource.CIVITAI
        assert len(practice.applicable_scenes) == 2
        assert SceneCategory.PORTRAIT in practice.applicable_scenes
        assert SceneCategory.CLOSE_UP in practice.applicable_scenes
        assert practice.quality_score == 90.0
    
    def test_from_dict_with_datetime(self):
        """测试从字典创建（包含时间）"""
        now = datetime.now()
        data = {
            "id": "test-010",
            "name": "时间测试",
            "description": "测试时间字段",
            "source": "custom",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        
        practice = BestPractice.from_dict(data)
        
        assert practice.created_at is not None
        assert practice.updated_at is not None
        assert abs((practice.created_at - now).total_seconds()) < 1
    
    def test_update_usage_stats_first_time(self):
        """测试更新使用统计 - 首次使用"""
        practice = BestPractice(
            id="test-011",
            name="统计测试",
            description="测试使用统计",
            source=PracticeSource.CUSTOM
        )
        
        # 首次使用，成功
        practice.update_usage_stats(success=True, generation_time=10.5)
        
        assert practice.usage_count == 1
        assert practice.success_rate == 1.0
        assert practice.average_generation_time == 10.5
    
    def test_update_usage_stats_multiple_times(self):
        """测试更新使用统计 - 多次使用"""
        practice = BestPractice(
            id="test-012",
            name="多次统计测试",
            description="测试多次使用统计",
            source=PracticeSource.CUSTOM
        )
        
        # 第一次：成功，10秒
        practice.update_usage_stats(success=True, generation_time=10.0)
        assert practice.usage_count == 1
        assert practice.success_rate == 1.0
        assert practice.average_generation_time == 10.0
        
        # 第二次：成功，20秒
        practice.update_usage_stats(success=True, generation_time=20.0)
        assert practice.usage_count == 2
        assert practice.success_rate == 1.0
        assert practice.average_generation_time == 15.0
        
        # 第三次：失败，30秒
        practice.update_usage_stats(success=False, generation_time=30.0)
        assert practice.usage_count == 3
        assert abs(practice.success_rate - 0.6667) < 0.01  # 2/3
        assert practice.average_generation_time == 20.0  # (10+20+30)/3
    
    def test_update_usage_stats_failure_first(self):
        """测试更新使用统计 - 首次失败"""
        practice = BestPractice(
            id="test-013",
            name="失败统计测试",
            description="测试首次失败统计",
            source=PracticeSource.CUSTOM
        )
        
        # 首次使用，失败
        practice.update_usage_stats(success=False, generation_time=5.0)
        
        assert practice.usage_count == 1
        assert practice.success_rate == 0.0
        assert practice.average_generation_time == 5.0


class TestPracticeSource:
    """测试 PracticeSource 枚举"""
    
    def test_practice_source_values(self):
        """测试来源枚举值"""
        assert PracticeSource.CIVITAI.value == "civitai"
        assert PracticeSource.GITHUB.value == "github"
        assert PracticeSource.COMMUNITY.value == "community"
        assert PracticeSource.OFFICIAL.value == "official"
        assert PracticeSource.CUSTOM.value == "custom"


class TestSceneCategory:
    """测试 SceneCategory 枚举"""
    
    def test_scene_category_values(self):
        """测试场景分类枚举值"""
        assert SceneCategory.PORTRAIT.value == "portrait"
        assert SceneCategory.FULL_BODY.value == "full_body"
        assert SceneCategory.CLOSE_UP.value == "close_up"
        assert SceneCategory.WIDE_SHOT.value == "wide_shot"
        assert SceneCategory.ACTION.value == "action"
        assert SceneCategory.INDOOR.value == "indoor"
        assert SceneCategory.OUTDOOR.value == "outdoor"
        assert SceneCategory.NIGHT.value == "night"
        assert SceneCategory.LANDSCAPE.value == "landscape"
        assert SceneCategory.GENERAL.value == "general"
