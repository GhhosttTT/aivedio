"""
最佳实践配置加载集成测试
"""

import pytest
from pathlib import Path
from src.services.best_practice_library import get_best_practice_library
from src.models.best_practice import SceneCategory, PracticeSource


class TestBestPracticeLoading:
    """测试最佳实践配置加载"""
    
    def test_load_all_practices(self):
        """测试加载所有最佳实践配置"""
        library = get_best_practice_library()
        library.clear()
        
        # 从配置目录加载
        config_dir = Path("configs/best_practices")
        count = library.load_from_directory(config_dir)
        
        # 应该加载至少 10 个配置
        assert count >= 10
        print(f"已加载 {count} 个最佳实践配置")
    
    def test_loaded_practices_valid(self):
        """测试加载的配置是否有效"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        practices = library.get_all_practices()
        assert len(practices) >= 10
        
        # 验证每个配置的基本字段
        for practice in practices:
            assert practice.id is not None
            assert practice.name is not None
            assert practice.description is not None
            assert practice.source is not None
            assert practice.overall_score > 0
            print(f"✓ {practice.name}: {practice.overall_score}")
    
    def test_get_practices_by_scene(self):
        """测试根据场景获取实践"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        # 测试人物特写场景
        portrait_practices = library.get_practices_by_scene(SceneCategory.PORTRAIT)
        assert len(portrait_practices) > 0
        print(f"人物特写场景: {len(portrait_practices)} 个实践")
        
        # 测试风景场景
        landscape_practices = library.get_practices_by_scene(SceneCategory.LANDSCAPE)
        assert len(landscape_practices) > 0
        print(f"风景场景: {len(landscape_practices)} 个实践")
        
        # 测试通用场景
        general_practices = library.get_practices_by_scene(SceneCategory.GENERAL)
        assert len(general_practices) > 0
        print(f"通用场景: {len(general_practices)} 个实践")
    
    def test_get_top_practices(self):
        """测试获取评分最高的实践"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        # 获取前 5 个最高评分的实践
        top_practices = library.get_top_practices(limit=5)
        assert len(top_practices) == 5
        
        # 验证按评分降序排列
        for i in range(len(top_practices) - 1):
            assert top_practices[i].overall_score >= top_practices[i + 1].overall_score
        
        print("评分最高的 5 个实践:")
        for i, practice in enumerate(top_practices, 1):
            print(f"{i}. {practice.name}: {practice.overall_score}")
    
    def test_get_recommended_practice(self):
        """测试获取推荐实践"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        # 获取人物特写场景的推荐实践（优先质量）
        recommended = library.get_recommended_practice(
            SceneCategory.PORTRAIT,
            prefer_quality=True
        )
        
        assert recommended is not None
        assert recommended.is_applicable_for_scene(SceneCategory.PORTRAIT)
        print(f"推荐实践（人物特写，优先质量）: {recommended.name}")
        print(f"  质量评分: {recommended.quality_score}")
        print(f"  综合评分: {recommended.overall_score}")
    
    def test_search_practices(self):
        """测试搜索实践"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        # 搜索包含"真实"的实践
        results = library.search_practices(keyword="真实")
        assert len(results) > 0
        print(f"搜索'真实': {len(results)} 个结果")
        
        # 搜索高质量的人物实践
        results = library.search_practices(
            keyword="人物",
            scene=SceneCategory.PORTRAIT,
            min_score=85.0
        )
        assert len(results) > 0
        print(f"搜索'人物'（评分>=85）: {len(results)} 个结果")
    
    def test_get_statistics(self):
        """测试获取统计信息"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        stats = library.get_statistics()
        
        assert stats["total_count"] >= 10
        assert stats["average_score"] > 0
        
        print(f"统计信息:")
        print(f"  总数量: {stats['total_count']}")
        print(f"  平均评分: {stats['average_score']}")
        print(f"  按来源: {stats['by_source']}")
        print(f"  按场景: {stats['by_scene']}")
    
    def test_specific_practices(self):
        """测试特定的最佳实践配置"""
        library = get_best_practice_library()
        library.clear()
        
        config_dir = Path("configs/best_practices")
        library.load_from_directory(config_dir)
        
        # 测试 RealVisXL 人物特写高质量配置
        practice = library.get_practice("realvisxl-portrait-hq-001")
        assert practice is not None
        assert practice.name == "RealVisXL 人物特写高质量"
        assert practice.source == PracticeSource.CIVITAI
        assert practice.checkpoint == "RealVisXL_V4.0.safetensors"
        assert practice.sampling_steps == 30
        assert practice.cfg_scale == 6.5
        print(f"✓ {practice.name} 配置正确")
        
        # 测试 SDXL Turbo 快速生成配置
        practice = library.get_practice("sdxl-turbo-fast-002")
        assert practice is not None
        assert practice.name == "SDXL Turbo 快速生成"
        assert practice.source == PracticeSource.OFFICIAL
        assert practice.sampling_steps == 4
        assert practice.speed_score >= 95.0
        print(f"✓ {practice.name} 配置正确")
        
        # 测试 IP-Adapter FaceID 配置
        practice = library.get_practice("ipadapter-faceid-portrait-005")
        assert practice is not None
        assert practice.name == "IP-Adapter FaceID 人物一致性"
        assert practice.source == PracticeSource.GITHUB
        assert practice.consistency_score >= 95.0
        assert practice.ipadapter_weight == 0.90
        print(f"✓ {practice.name} 配置正确")
