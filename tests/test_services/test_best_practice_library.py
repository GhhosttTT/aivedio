"""
最佳实践库服务单元测试
"""

import pytest
import json
import tempfile
from pathlib import Path
from src.services.best_practice_library import BestPracticeLibrary, get_best_practice_library
from src.models.best_practice import BestPractice, PracticeSource, SceneCategory


@pytest.fixture
def library():
    """创建测试用的最佳实践库实例"""
    lib = BestPracticeLibrary()
    lib.clear()  # 清空缓存
    return lib


@pytest.fixture
def sample_practices():
    """创建示例最佳实践列表"""
    return [
        BestPractice(
            id="practice-001",
            name="人物特写高质量",
            description="适用于人物特写的高质量配置",
            source=PracticeSource.CIVITAI,
            applicable_scenes=[SceneCategory.PORTRAIT, SceneCategory.CLOSE_UP],
            tags=["高质量", "人物"],
            quality_score=95.0,
            realism_score=90.0,
            consistency_score=88.0,
            speed_score=70.0,
            overall_score=88.9
        ),
        BestPractice(
            id="practice-002",
            name="风景快速生成",
            description="适用于风景的快速生成配置",
            source=PracticeSource.GITHUB,
            applicable_scenes=[SceneCategory.LANDSCAPE, SceneCategory.OUTDOOR],
            tags=["快速", "风景"],
            quality_score=75.0,
            realism_score=70.0,
            consistency_score=72.0,
            speed_score=95.0,
            overall_score=77.1
        ),
        BestPractice(
            id="practice-003",
            name="通用真实感",
            description="通用的真实感配置",
            source=PracticeSource.OFFICIAL,
            applicable_scenes=[SceneCategory.GENERAL],
            tags=["真实感", "通用"],
            quality_score=85.0,
            realism_score=92.0,
            consistency_score=80.0,
            speed_score=75.0,
            overall_score=84.1
        ),
        BestPractice(
            id="practice-004",
            name="动作场景",
            description="适用于动作场景的配置",
            source=PracticeSource.COMMUNITY,
            applicable_scenes=[SceneCategory.ACTION],
            tags=["动作"],
            quality_score=80.0,
            realism_score=75.0,
            consistency_score=78.0,
            speed_score=85.0,
            overall_score=79.1
        ),
    ]


class TestBestPracticeLibrary:
    """测试 BestPracticeLibrary 类"""
    
    def test_singleton(self):
        """测试单例模式"""
        lib1 = BestPracticeLibrary()
        lib2 = BestPracticeLibrary()
        assert lib1 is lib2
    
    def test_get_best_practice_library(self):
        """测试获取全局实例"""
        lib1 = get_best_practice_library()
        lib2 = get_best_practice_library()
        assert lib1 is lib2
        assert isinstance(lib1, BestPracticeLibrary)
    
    def test_add_practice(self, library, sample_practices):
        """测试添加最佳实践"""
        practice = sample_practices[0]
        library.add_practice(practice)
        
        # 验证已添加
        retrieved = library.get_practice(practice.id)
        assert retrieved is not None
        assert retrieved.id == practice.id
        assert retrieved.name == practice.name
    
    def test_add_multiple_practices(self, library, sample_practices):
        """测试添加多个最佳实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 验证所有实践都已添加
        all_practices = library.get_all_practices()
        assert len(all_practices) == len(sample_practices)
    
    def test_get_practice_not_found(self, library):
        """测试获取不存在的实践"""
        practice = library.get_practice("non-existent")
        assert practice is None
    
    def test_get_all_practices(self, library, sample_practices):
        """测试获取所有实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        all_practices = library.get_all_practices()
        assert len(all_practices) == len(sample_practices)
        
        # 验证所有 ID 都存在
        ids = {p.id for p in all_practices}
        expected_ids = {p.id for p in sample_practices}
        assert ids == expected_ids
    
    def test_get_practices_by_scene(self, library, sample_practices):
        """测试根据场景获取实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取人物特写场景的实践
        portrait_practices = library.get_practices_by_scene(SceneCategory.PORTRAIT)
        assert len(portrait_practices) >= 1
        assert any(p.id == "practice-001" for p in portrait_practices)
        
        # 获取风景场景的实践
        landscape_practices = library.get_practices_by_scene(SceneCategory.LANDSCAPE)
        assert len(landscape_practices) >= 1
        assert any(p.id == "practice-002" for p in landscape_practices)
    
    def test_get_practices_by_scene_with_general(self, library, sample_practices):
        """测试获取场景实践（包含通用场景）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取室内场景的实践（没有专门的室内实践，应该返回通用实践）
        indoor_practices = library.get_practices_by_scene(SceneCategory.INDOOR)
        assert len(indoor_practices) >= 1
        # 应该包含通用实践
        assert any(p.id == "practice-003" for p in indoor_practices)
    
    def test_get_practices_by_scene_with_min_score(self, library, sample_practices):
        """测试根据场景和最低评分获取实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取评分 >= 85 的人物特写实践
        high_score_practices = library.get_practices_by_scene(
            SceneCategory.PORTRAIT,
            min_score=85.0
        )
        
        assert len(high_score_practices) >= 1
        assert all(p.overall_score >= 85.0 for p in high_score_practices)
    
    def test_get_practices_by_scene_with_limit(self, library, sample_practices):
        """测试根据场景获取实践（限制数量）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取最多 1 个人物特写实践
        practices = library.get_practices_by_scene(
            SceneCategory.PORTRAIT,
            limit=1
        )
        
        assert len(practices) <= 1
    
    def test_get_practices_by_source(self, library, sample_practices):
        """测试根据来源获取实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取 Civitai 来源的实践
        civitai_practices = library.get_practices_by_source(PracticeSource.CIVITAI)
        assert len(civitai_practices) >= 1
        assert all(p.source == PracticeSource.CIVITAI for p in civitai_practices)
        
        # 获取 GitHub 来源的实践
        github_practices = library.get_practices_by_source(PracticeSource.GITHUB)
        assert len(github_practices) >= 1
        assert all(p.source == PracticeSource.GITHUB for p in github_practices)
    
    def test_get_practices_by_source_with_min_score(self, library, sample_practices):
        """测试根据来源和最低评分获取实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取评分 >= 85 的 Civitai 实践
        high_score_practices = library.get_practices_by_source(
            PracticeSource.CIVITAI,
            min_score=85.0
        )
        
        assert len(high_score_practices) >= 1
        assert all(p.source == PracticeSource.CIVITAI for p in high_score_practices)
        assert all(p.overall_score >= 85.0 for p in high_score_practices)
    
    def test_get_top_practices(self, library, sample_practices):
        """测试获取评分最高的实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取前 2 个最高评分的实践
        top_practices = library.get_top_practices(limit=2)
        
        assert len(top_practices) == 2
        # 验证按评分降序排列
        assert top_practices[0].overall_score >= top_practices[1].overall_score
        # 第一个应该是 practice-001（评分 88.9）
        assert top_practices[0].id == "practice-001"
    
    def test_get_top_practices_with_min_score(self, library, sample_practices):
        """测试获取评分最高的实践（最低评分限制）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取评分 >= 80 的实践
        top_practices = library.get_top_practices(min_score=80.0)
        
        assert all(p.overall_score >= 80.0 for p in top_practices)
    
    def test_search_practices_by_keyword(self, library, sample_practices):
        """测试根据关键词搜索实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 搜索包含"人物"的实践
        results = library.search_practices(keyword="人物")
        assert len(results) >= 1
        assert any("人物" in p.name or "人物" in p.description for p in results)
        
        # 搜索包含"快速"的实践
        results = library.search_practices(keyword="快速")
        assert len(results) >= 1
        assert any("快速" in p.name or "快速" in p.description for p in results)
    
    def test_search_practices_by_scene(self, library, sample_practices):
        """测试根据场景搜索实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 搜索人物特写场景的实践
        results = library.search_practices(scene=SceneCategory.PORTRAIT)
        assert len(results) >= 1
        assert all(p.is_applicable_for_scene(SceneCategory.PORTRAIT) for p in results)
    
    def test_search_practices_by_source(self, library, sample_practices):
        """测试根据来源搜索实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 搜索 Civitai 来源的实践
        results = library.search_practices(source=PracticeSource.CIVITAI)
        assert len(results) >= 1
        assert all(p.source == PracticeSource.CIVITAI for p in results)
    
    def test_search_practices_by_tags(self, library, sample_practices):
        """测试根据标签搜索实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 搜索包含"高质量"标签的实践
        results = library.search_practices(tags=["高质量"])
        assert len(results) >= 1
        assert all("高质量" in p.tags for p in results)
        
        # 搜索包含多个标签的实践
        results = library.search_practices(tags=["高质量", "人物"])
        assert len(results) >= 1
        assert all("高质量" in p.tags and "人物" in p.tags for p in results)
    
    def test_search_practices_combined(self, library, sample_practices):
        """测试组合搜索实践"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 组合搜索：关键词 + 场景 + 最低评分
        results = library.search_practices(
            keyword="人物",
            scene=SceneCategory.PORTRAIT,
            min_score=85.0
        )
        
        assert len(results) >= 1
        for p in results:
            assert "人物" in p.name or "人物" in p.description
            assert p.is_applicable_for_scene(SceneCategory.PORTRAIT)
            assert p.overall_score >= 85.0
    
    def test_search_practices_with_limit(self, library, sample_practices):
        """测试搜索实践（限制数量）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 搜索最多 2 个实践
        results = library.search_practices(limit=2)
        assert len(results) <= 2
    
    def test_get_recommended_practice_default(self, library, sample_practices):
        """测试获取推荐实践（默认）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取人物特写场景的推荐实践
        recommended = library.get_recommended_practice(SceneCategory.PORTRAIT)
        assert recommended is not None
        assert recommended.is_applicable_for_scene(SceneCategory.PORTRAIT)
    
    def test_get_recommended_practice_prefer_quality(self, library, sample_practices):
        """测试获取推荐实践（优先质量）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取人物特写场景的推荐实践（优先质量）
        recommended = library.get_recommended_practice(
            SceneCategory.PORTRAIT,
            prefer_quality=True
        )
        assert recommended is not None
        assert recommended.is_applicable_for_scene(SceneCategory.PORTRAIT)
        # 应该是 practice-001（质量评分最高）
        assert recommended.id == "practice-001"
    
    def test_get_recommended_practice_prefer_speed(self, library, sample_practices):
        """测试获取推荐实践（优先速度）"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        # 获取风景场景的推荐实践（优先速度）
        recommended = library.get_recommended_practice(
            SceneCategory.LANDSCAPE,
            prefer_speed=True
        )
        assert recommended is not None
        assert recommended.is_applicable_for_scene(SceneCategory.LANDSCAPE)
        # 应该是 practice-002（速度评分最高）
        assert recommended.id == "practice-002"
    
    def test_get_recommended_practice_not_found(self, library):
        """测试获取推荐实践（未找到）"""
        # 空库，应该返回 None
        recommended = library.get_recommended_practice(SceneCategory.PORTRAIT)
        assert recommended is None
    
    def test_save_and_load_practice(self, library, sample_practices):
        """测试保存和加载实践"""
        practice = sample_practices[0]
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # 保存实践
            library.save_practice(practice, tmpdir_path)
            
            # 验证文件已创建
            file_path = tmpdir_path / f"{practice.id}.json"
            assert file_path.exists()
            
            # 加载实践
            loaded_practice = library.load_from_file(file_path)
            assert loaded_practice is not None
            assert loaded_practice.id == practice.id
            assert loaded_practice.name == practice.name
            assert loaded_practice.source == practice.source
    
    def test_load_from_directory(self, library, sample_practices):
        """测试从目录加载实践"""
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # 保存多个实践
            for practice in sample_practices:
                library.save_practice(practice, tmpdir_path)
            
            # 清空库
            library.clear()
            assert len(library.get_all_practices()) == 0
            
            # 从目录加载
            count = library.load_from_directory(tmpdir_path)
            assert count == len(sample_practices)
            assert len(library.get_all_practices()) == len(sample_practices)
    
    def test_load_from_directory_not_exists(self, library):
        """测试从不存在的目录加载"""
        non_existent_dir = Path("/non/existent/directory")
        count = library.load_from_directory(non_existent_dir)
        assert count == 0
    
    def test_clear(self, library, sample_practices):
        """测试清空缓存"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        assert len(library.get_all_practices()) > 0
        
        library.clear()
        assert len(library.get_all_practices()) == 0
    
    def test_get_statistics(self, library, sample_practices):
        """测试获取统计信息"""
        for practice in sample_practices:
            library.add_practice(practice)
        
        stats = library.get_statistics()
        
        assert stats["total_count"] == len(sample_practices)
        assert stats["average_score"] > 0
        assert "by_source" in stats
        assert "by_scene" in stats
        
        # 验证来源统计
        assert "civitai" in stats["by_source"]
        assert "github" in stats["by_source"]
        
        # 验证场景统计
        assert "portrait" in stats["by_scene"]
        assert "landscape" in stats["by_scene"]
    
    def test_get_statistics_empty(self, library):
        """测试获取统计信息（空库）"""
        stats = library.get_statistics()
        
        assert stats["total_count"] == 0
        assert stats["average_score"] == 0.0
        assert stats["by_source"] == {}
        assert stats["by_scene"] == {}
