"""
提示词优化引擎（PromptOptimizer）单元测试
"""

import pytest
from unittest.mock import patch

from src.services.prompt_optimizer import (
    PromptOptimizer,
    OptimizationMode,
    OptimizedPrompt,
    get_prompt_optimizer,
    cleanup_prompt_optimizer
)


class TestOptimizationMode:
    """测试优化模式枚举"""
    
    def test_optimization_mode_values(self):
        """测试优化模式枚举值"""
        assert OptimizationMode.QUALITY == "quality"
        assert OptimizationMode.REALISM == "realism"
        assert OptimizationMode.ARTISTIC == "artistic"
        assert OptimizationMode.BALANCED == "balanced"


class TestOptimizedPrompt:
    """测试优化提示词数据类"""
    
    def test_create_optimized_prompt(self):
        """测试创建优化提示词"""
        prompt = OptimizedPrompt(
            positive_prompt="best quality, a beautiful woman",
            negative_prompt="low quality, blurry",
            original_prompt="a beautiful woman",
            added_keywords=["best quality"],
            optimization_mode=OptimizationMode.QUALITY,
            word_count=5
        )
        
        assert prompt.positive_prompt == "best quality, a beautiful woman"
        assert prompt.negative_prompt == "low quality, blurry"
        assert prompt.original_prompt == "a beautiful woman"
        assert prompt.added_keywords == ["best quality"]
        assert prompt.optimization_mode == OptimizationMode.QUALITY
        assert prompt.word_count == 5


class TestPromptOptimizer:
    """测试提示词优化器"""
    
    @pytest.fixture
    def optimizer(self):
        """创建提示词优化器实例"""
        return PromptOptimizer()
    
    # ==================== 测试基本功能 ====================
    
    def test_optimizer_initialization(self, optimizer):
        """测试优化器初始化"""
        assert optimizer is not None
        assert len(optimizer.QUALITY_TAGS) > 0
        assert len(optimizer.REALISM_KEYWORDS) > 0
        assert len(optimizer.NEGATIVE_COMMON) > 0
    
    def test_clean_prompt(self, optimizer):
        """测试清理提示词"""
        # 测试移除多余空格
        cleaned = optimizer._clean_prompt("a  beautiful   woman")
        assert cleaned == "a beautiful woman"
        
        # 测试移除开头和结尾的逗号
        cleaned = optimizer._clean_prompt(", a beautiful woman ,")
        assert cleaned == "a beautiful woman"
        
        # 测试组合清理
        cleaned = optimizer._clean_prompt(",  a  beautiful   woman  ,")
        assert cleaned == "a beautiful woman"
    
    def test_optimize_empty_prompt(self, optimizer):
        """测试空提示词"""
        with pytest.raises(ValueError, match="提示词不能为空"):
            optimizer.optimize("")
        
        with pytest.raises(ValueError, match="提示词不能为空"):
            optimizer.optimize("   ")
    
    def test_optimize_invalid_word_count(self, optimizer):
        """测试无效的目标单词数量"""
        # 目标单词数量过小
        result = optimizer.optimize("a beautiful woman", target_word_count=10)
        assert result is not None
        
        # 目标单词数量过大
        result = optimizer.optimize("a beautiful woman", target_word_count=300)
        assert result is not None
    
    # ==================== 测试质量标签选择 ====================
    
    def test_select_quality_tags_quality_mode(self, optimizer):
        """测试质量模式的质量标签选择"""
        tags = optimizer._select_quality_tags(OptimizationMode.QUALITY)
        assert len(tags) == 5
        assert "masterpiece" in tags or "best quality" in tags
    
    def test_select_quality_tags_realism_mode(self, optimizer):
        """测试真实感模式的质量标签选择"""
        tags = optimizer._select_quality_tags(OptimizationMode.REALISM)
        assert len(tags) == 3
        assert "best quality" in tags
        assert "high resolution" in tags
    
    def test_select_quality_tags_artistic_mode(self, optimizer):
        """测试艺术模式的质量标签选择"""
        tags = optimizer._select_quality_tags(OptimizationMode.ARTISTIC)
        assert len(tags) == 3
        assert "masterpiece" in tags or "best quality" in tags
    
    def test_select_quality_tags_balanced_mode(self, optimizer):
        """测试平衡模式的质量标签选择"""
        tags = optimizer._select_quality_tags(OptimizationMode.BALANCED)
        assert len(tags) == 3
        assert "best quality" in tags
    
    # ==================== 测试模式关键词选择 ====================
    
    def test_select_mode_keywords_quality(self, optimizer):
        """测试质量模式的关键词选择"""
        keywords = optimizer._select_mode_keywords(OptimizationMode.QUALITY)
        assert "ultra-detailed" in keywords
        assert "sharp focus" in keywords
    
    def test_select_mode_keywords_realism(self, optimizer):
        """测试真实感模式的关键词选择"""
        keywords = optimizer._select_mode_keywords(OptimizationMode.REALISM)
        assert len(keywords) == 6
        assert any("photo" in k.lower() for k in keywords)
    
    def test_select_mode_keywords_artistic(self, optimizer):
        """测试艺术模式的关键词选择"""
        keywords = optimizer._select_mode_keywords(OptimizationMode.ARTISTIC)
        assert len(keywords) == 5
        assert any("cinematic" in k.lower() for k in keywords)
    
    def test_select_mode_keywords_balanced(self, optimizer):
        """测试平衡模式的关键词选择"""
        keywords = optimizer._select_mode_keywords(OptimizationMode.BALANCED)
        assert len(keywords) == 4
        assert "photorealistic" in keywords
    
    # ==================== 测试光影术语选择 ====================
    
    def test_select_lighting_terms_realism(self, optimizer):
        """测试真实感模式的光影术语选择"""
        terms = optimizer._select_lighting_terms(OptimizationMode.REALISM)
        assert "natural light" in terms
        assert "soft lighting" in terms
    
    def test_select_lighting_terms_artistic(self, optimizer):
        """测试艺术模式的光影术语选择"""
        terms = optimizer._select_lighting_terms(OptimizationMode.ARTISTIC)
        assert "dramatic lighting" in terms
    
    def test_select_lighting_terms_other(self, optimizer):
        """测试其他模式的光影术语选择"""
        terms = optimizer._select_lighting_terms(OptimizationMode.QUALITY)
        assert len(terms) == 2
    
    # ==================== 测试摄影术语选择 ====================
    
    def test_select_photography_terms_realism(self, optimizer):
        """测试真实感模式的摄影术语选择"""
        terms = optimizer._select_photography_terms(OptimizationMode.REALISM)
        assert "professional photography" in terms
        assert "DSLR" in terms
    
    def test_select_photography_terms_artistic(self, optimizer):
        """测试艺术模式的摄影术语选择"""
        terms = optimizer._select_photography_terms(OptimizationMode.ARTISTIC)
        assert "shallow depth of field" in terms or "bokeh" in terms
    
    def test_select_photography_terms_other(self, optimizer):
        """测试其他模式的摄影术语选择"""
        terms = optimizer._select_photography_terms(OptimizationMode.QUALITY)
        assert "professional photography" in terms
    
    # ==================== 测试正面提示词构建 ====================
    
    def test_build_positive_prompt_basic(self, optimizer):
        """测试基本正面提示词构建"""
        base_prompt = "a beautiful woman"
        keywords = ["best quality", "high resolution"]
        
        result = optimizer._build_positive_prompt(base_prompt, keywords, 100)
        
        assert "best quality" in result
        assert "high resolution" in result
        assert "a beautiful woman" in result
    
    def test_build_positive_prompt_word_limit(self, optimizer):
        """测试单词数量限制"""
        base_prompt = "a beautiful woman"
        keywords = ["best quality", "high resolution", "ultra-detailed", "sharp focus"]
        
        # 目标单词数量较小，应该只添加部分关键词
        result = optimizer._build_positive_prompt(base_prompt, keywords, 10)
        
        word_count = len(result.split())
        assert word_count <= 10
    
    def test_build_positive_prompt_no_keywords(self, optimizer):
        """测试没有关键词的情况"""
        base_prompt = "a beautiful woman"
        keywords = []
        
        result = optimizer._build_positive_prompt(base_prompt, keywords, 100)
        
        assert result == base_prompt
    
    # ==================== 测试负面提示词构建 ====================
    
    def test_build_negative_prompt_quality_mode(self, optimizer):
        """测试质量模式的负面提示词"""
        negative = optimizer._build_negative_prompt(OptimizationMode.QUALITY)
        
        assert "low quality" in negative
        assert "blurry" in negative
    
    def test_build_negative_prompt_realism_mode(self, optimizer):
        """测试真实感模式的负面提示词"""
        negative = optimizer._build_negative_prompt(OptimizationMode.REALISM)
        
        assert "low quality" in negative
        assert "CGI" in negative
        assert "3D render" in negative
    
    def test_build_negative_prompt_artistic_mode(self, optimizer):
        """测试艺术模式的负面提示词"""
        negative = optimizer._build_negative_prompt(OptimizationMode.ARTISTIC)
        
        assert "low quality" in negative
        assert "amateur" in negative
    
    def test_build_negative_prompt_with_custom(self, optimizer):
        """测试自定义负面提示词"""
        custom_negative = ["custom1", "custom2"]
        negative = optimizer._build_negative_prompt(
            OptimizationMode.QUALITY,
            custom_negative
        )
        
        assert "custom1" in negative
        assert "custom2" in negative
    
    # ==================== 测试完整优化流程 ====================
    
    def test_optimize_quality_mode(self, optimizer):
        """测试质量模式优化"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY
        )
        
        assert result.positive_prompt is not None
        assert result.negative_prompt is not None
        assert result.original_prompt == "a beautiful woman"
        assert result.optimization_mode == OptimizationMode.QUALITY
        assert len(result.added_keywords) > 0
        assert result.word_count > 0
        
        # 验证包含质量标签
        assert any(tag in result.positive_prompt for tag in ["quality", "detailed"])
    
    def test_optimize_realism_mode(self, optimizer):
        """测试真实感模式优化"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.REALISM
        )
        
        assert result.optimization_mode == OptimizationMode.REALISM
        
        # 验证包含真实感关键词
        positive_lower = result.positive_prompt.lower()
        assert any(keyword in positive_lower for keyword in ["photo", "natural", "realistic"])
        
        # 验证负面提示词包含 CGI 等
        negative_lower = result.negative_prompt.lower()
        assert "cgi" in negative_lower or "3d render" in negative_lower
    
    def test_optimize_artistic_mode(self, optimizer):
        """测试艺术模式优化"""
        result = optimizer.optimize(
            prompt="a beautiful landscape",
            mode=OptimizationMode.ARTISTIC
        )
        
        assert result.optimization_mode == OptimizationMode.ARTISTIC
        
        # 验证包含艺术关键词
        positive_lower = result.positive_prompt.lower()
        assert any(keyword in positive_lower for keyword in ["cinematic", "dramatic", "artistic"])
    
    def test_optimize_balanced_mode(self, optimizer):
        """测试平衡模式优化"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.BALANCED
        )
        
        assert result.optimization_mode == OptimizationMode.BALANCED
        assert len(result.added_keywords) > 0
    
    def test_optimize_with_custom_keywords(self, optimizer):
        """测试自定义关键词"""
        custom_keywords = ["custom keyword 1", "custom keyword 2"]
        
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            custom_keywords=custom_keywords
        )
        
        assert "custom keyword 1" in result.added_keywords
        assert "custom keyword 2" in result.added_keywords
    
    def test_optimize_with_custom_negative(self, optimizer):
        """测试自定义负面提示词"""
        custom_negative = ["custom negative 1", "custom negative 2"]
        
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            custom_negative=custom_negative
        )
        
        assert "custom negative 1" in result.negative_prompt
        assert "custom negative 2" in result.negative_prompt
    
    def test_optimize_without_quality_tags(self, optimizer):
        """测试不添加质量标签"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            add_quality_tags=False
        )
        
        # 添加的关键词应该较少
        assert len(result.added_keywords) < 10
    
    def test_optimize_without_lighting_terms(self, optimizer):
        """测试不添加光影术语"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            add_lighting_terms=False
        )
        
        assert result is not None
    
    def test_optimize_without_photography_terms(self, optimizer):
        """测试不添加摄影术语"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            add_photography_terms=False
        )
        
        assert result is not None
    
    def test_optimize_target_word_count(self, optimizer):
        """测试目标单词数量"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            target_word_count=80
        )
        
        # 单词数量应该大于原始提示词
        original_word_count = len("a beautiful woman".split())
        assert result.word_count > original_word_count
        
        # 验证添加了关键词
        assert len(result.added_keywords) > 0
    
    def test_optimize_long_prompt(self, optimizer):
        """测试长提示词"""
        long_prompt = "a beautiful woman with long hair, wearing a red dress, standing in a garden"
        
        result = optimizer.optimize(
            prompt=long_prompt,
            mode=OptimizationMode.QUALITY
        )
        
        assert long_prompt in result.positive_prompt
        assert result.word_count > len(long_prompt.split())
    
    @patch('src.services.prompt_optimizer.logger')
    def test_optimize_logs_result(self, mock_logger, optimizer):
        """测试优化结果日志记录"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY
        )
        
        # 验证日志记录被调用
        assert mock_logger.info.called
        assert mock_logger.debug.called
    
    # ==================== 测试场景优化 ====================
    
    def test_optimize_for_scene_portrait(self, optimizer):
        """测试人物场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a beautiful woman",
            scene_type="portrait"
        )
        
        assert result.optimization_mode == OptimizationMode.BALANCED
        
        # 验证包含人物相关关键词
        positive_lower = result.positive_prompt.lower()
        assert "portrait" in positive_lower or "face" in positive_lower
    
    def test_optimize_for_scene_landscape(self, optimizer):
        """测试风景场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a beautiful mountain",
            scene_type="landscape"
        )
        
        assert result.optimization_mode == OptimizationMode.ARTISTIC
        
        # 验证包含风景相关关键词
        positive_lower = result.positive_prompt.lower()
        assert "landscape" in positive_lower or "wide" in positive_lower
    
    def test_optimize_for_scene_action(self, optimizer):
        """测试动作场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a person running",
            scene_type="action"
        )
        
        assert result.optimization_mode == OptimizationMode.QUALITY
        
        # 验证包含动作相关关键词
        positive_lower = result.positive_prompt.lower()
        assert "action" in positive_lower or "dynamic" in positive_lower
    
    def test_optimize_for_scene_with_realism(self, optimizer):
        """测试启用真实感的场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a beautiful woman",
            scene_type="portrait",
            enable_realism=True
        )
        
        assert result.optimization_mode == OptimizationMode.REALISM
        
        # 验证包含真实感关键词
        positive_lower = result.positive_prompt.lower()
        assert any(keyword in positive_lower for keyword in ["photo", "natural", "realistic"])
    
    def test_optimize_for_scene_close_up(self, optimizer):
        """测试特写场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a beautiful face",
            scene_type="close_up"
        )
        
        assert result.optimization_mode == OptimizationMode.BALANCED
    
    def test_optimize_for_scene_full_body(self, optimizer):
        """测试全身照场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a person standing",
            scene_type="full_body"
        )
        
        assert result.optimization_mode == OptimizationMode.BALANCED
    
    def test_optimize_for_scene_wide_shot(self, optimizer):
        """测试广角场景优化"""
        result = optimizer.optimize_for_scene(
            prompt="a city view",
            scene_type="wide_shot"
        )
        
        assert result.optimization_mode == OptimizationMode.ARTISTIC


class TestGlobalPromptOptimizer:
    """测试全局提示词优化器实例"""
    
    def test_get_prompt_optimizer_singleton(self):
        """测试单例模式"""
        # 清理现有实例
        cleanup_prompt_optimizer()
        
        # 获取第一个实例
        optimizer1 = get_prompt_optimizer()
        assert optimizer1 is not None
        
        # 获取第二个实例，应该是同一个对象
        optimizer2 = get_prompt_optimizer()
        assert optimizer2 is optimizer1
    
    def test_cleanup_prompt_optimizer(self):
        """测试清理全局实例"""
        # 获取实例
        optimizer1 = get_prompt_optimizer()
        assert optimizer1 is not None
        
        # 清理实例
        cleanup_prompt_optimizer()
        
        # 再次获取应该是新实例
        optimizer2 = get_prompt_optimizer()
        assert optimizer2 is not None
        assert optimizer2 is not optimizer1


class TestPromptOptimizerEdgeCases:
    """测试提示词优化器边界情况"""
    
    @pytest.fixture
    def optimizer(self):
        """创建提示词优化器实例"""
        return PromptOptimizer()
    
    def test_optimize_with_special_characters(self, optimizer):
        """测试包含特殊字符的提示词"""
        result = optimizer.optimize(
            prompt="a beautiful woman, smiling :)",
            mode=OptimizationMode.QUALITY
        )
        
        assert result is not None
        assert "woman" in result.positive_prompt
    
    def test_optimize_with_numbers(self, optimizer):
        """测试包含数字的提示词"""
        result = optimizer.optimize(
            prompt="2 beautiful women",
            mode=OptimizationMode.QUALITY
        )
        
        assert result is not None
        assert "2" in result.positive_prompt or "two" in result.positive_prompt.lower()
    
    def test_optimize_very_short_prompt(self, optimizer):
        """测试非常短的提示词"""
        result = optimizer.optimize(
            prompt="woman",
            mode=OptimizationMode.QUALITY
        )
        
        assert result is not None
        assert "woman" in result.positive_prompt
        assert result.word_count > 1
    
    def test_optimize_with_commas(self, optimizer):
        """测试包含多个逗号的提示词"""
        result = optimizer.optimize(
            prompt="a woman, beautiful, smiling, happy",
            mode=OptimizationMode.QUALITY
        )
        
        assert result is not None
        assert "woman" in result.positive_prompt
    
    def test_optimize_all_options_disabled(self, optimizer):
        """测试禁用所有选项"""
        result = optimizer.optimize(
            prompt="a beautiful woman",
            mode=OptimizationMode.QUALITY,
            add_quality_tags=False,
            add_lighting_terms=False,
            add_photography_terms=False
        )
        
        assert result is not None
        # 应该只有模式关键词
        assert len(result.added_keywords) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
