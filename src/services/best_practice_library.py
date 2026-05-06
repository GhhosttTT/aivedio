"""
最佳实践库服务

管理和查询最佳实践配置，支持从配置文件加载、内存缓存和多种查询方式。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from threading import Lock

from src.models.best_practice import BestPractice, PracticeSource, SceneCategory


logger = logging.getLogger(__name__)


class BestPracticeLibrary:
    """
    最佳实践库
    
    单例类，管理所有最佳实践配置，支持加载、缓存和查询。
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化最佳实践库"""
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._practices: Dict[str, BestPractice] = {}  # ID -> BestPractice
        self._practices_by_scene: Dict[SceneCategory, List[str]] = {}  # Scene -> Practice IDs
        self._practices_by_source: Dict[PracticeSource, List[str]] = {}  # Source -> Practice IDs
        self._config_dir = Path("configs/best_practices")
        
        logger.info("最佳实践库已初始化")
    
    def load_from_directory(self, directory: Optional[Path] = None) -> int:
        """
        从目录加载所有最佳实践配置
        
        Args:
            directory: 配置目录路径，默认为 configs/best_practices
            
        Returns:
            加载的配置数量
        """
        if directory is None:
            directory = self._config_dir
        
        if not directory.exists():
            logger.warning(f"最佳实践配置目录不存在: {directory}")
            return 0
        
        loaded_count = 0
        
        # 遍历目录中的所有 JSON 文件
        for config_file in directory.glob("*.json"):
            try:
                practice = self.load_from_file(config_file)
                if practice:
                    self.add_practice(practice)
                    loaded_count += 1
                    logger.info(f"已加载最佳实践: {practice.name} (ID: {practice.id})")
            except Exception as e:
                logger.error(f"加载最佳实践配置失败 {config_file}: {e}")
        
        logger.info(f"从 {directory} 加载了 {loaded_count} 个最佳实践配置")
        return loaded_count
    
    def load_from_file(self, file_path: Path) -> Optional[BestPractice]:
        """
        从文件加载最佳实践配置
        
        Args:
            file_path: 配置文件路径
            
        Returns:
            BestPractice 实例，加载失败返回 None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            practice = BestPractice.from_dict(data)
            return practice
        except Exception as e:
            logger.error(f"从文件加载最佳实践失败 {file_path}: {e}")
            return None
    
    def add_practice(self, practice: BestPractice):
        """
        添加最佳实践到库中
        
        Args:
            practice: BestPractice 实例
        """
        # 添加到主字典
        self._practices[practice.id] = practice
        
        # 添加到场景索引
        for scene in practice.applicable_scenes:
            if scene not in self._practices_by_scene:
                self._practices_by_scene[scene] = []
            if practice.id not in self._practices_by_scene[scene]:
                self._practices_by_scene[scene].append(practice.id)
        
        # 如果没有指定场景，添加到 GENERAL
        if not practice.applicable_scenes:
            if SceneCategory.GENERAL not in self._practices_by_scene:
                self._practices_by_scene[SceneCategory.GENERAL] = []
            if practice.id not in self._practices_by_scene[SceneCategory.GENERAL]:
                self._practices_by_scene[SceneCategory.GENERAL].append(practice.id)
        
        # 添加到来源索引
        if practice.source not in self._practices_by_source:
            self._practices_by_source[practice.source] = []
        if practice.id not in self._practices_by_source[practice.source]:
            self._practices_by_source[practice.source].append(practice.id)
        
        logger.debug(f"已添加最佳实践: {practice.name} (ID: {practice.id})")
    
    def get_practice(self, practice_id: str) -> Optional[BestPractice]:
        """
        根据 ID 获取最佳实践
        
        Args:
            practice_id: 实践 ID
            
        Returns:
            BestPractice 实例，不存在返回 None
        """
        return self._practices.get(practice_id)
    
    def get_all_practices(self) -> List[BestPractice]:
        """
        获取所有最佳实践
        
        Returns:
            所有最佳实践列表
        """
        return list(self._practices.values())
    
    def get_practices_by_scene(
        self, 
        scene: SceneCategory,
        min_score: float = 0.0,
        limit: Optional[int] = None
    ) -> List[BestPractice]:
        """
        根据场景类型获取最佳实践
        
        Args:
            scene: 场景类型
            min_score: 最低综合评分（0-100）
            limit: 返回数量限制
            
        Returns:
            最佳实践列表，按综合评分降序排列
        """
        # 获取场景对应的实践 ID
        practice_ids = self._practices_by_scene.get(scene, [])
        
        # 如果没有找到，尝试使用 GENERAL
        if not practice_ids:
            practice_ids = self._practices_by_scene.get(SceneCategory.GENERAL, [])
        
        # 获取实践对象
        practices = [
            self._practices[pid] 
            for pid in practice_ids 
            if pid in self._practices
        ]
        
        # 过滤评分
        practices = [p for p in practices if p.overall_score >= min_score]
        
        # 按综合评分降序排序
        practices.sort(key=lambda p: p.overall_score, reverse=True)
        
        # 限制数量
        if limit is not None:
            practices = practices[:limit]
        
        return practices
    
    def get_practices_by_source(
        self, 
        source: PracticeSource,
        min_score: float = 0.0,
        limit: Optional[int] = None
    ) -> List[BestPractice]:
        """
        根据来源获取最佳实践
        
        Args:
            source: 来源类型
            min_score: 最低综合评分（0-100）
            limit: 返回数量限制
            
        Returns:
            最佳实践列表，按综合评分降序排列
        """
        # 获取来源对应的实践 ID
        practice_ids = self._practices_by_source.get(source, [])
        
        # 获取实践对象
        practices = [
            self._practices[pid] 
            for pid in practice_ids 
            if pid in self._practices
        ]
        
        # 过滤评分
        practices = [p for p in practices if p.overall_score >= min_score]
        
        # 按综合评分降序排序
        practices.sort(key=lambda p: p.overall_score, reverse=True)
        
        # 限制数量
        if limit is not None:
            practices = practices[:limit]
        
        return practices
    
    def get_top_practices(
        self, 
        limit: int = 10,
        min_score: float = 0.0
    ) -> List[BestPractice]:
        """
        获取评分最高的最佳实践
        
        Args:
            limit: 返回数量限制
            min_score: 最低综合评分（0-100）
            
        Returns:
            最佳实践列表，按综合评分降序排列
        """
        # 获取所有实践
        practices = list(self._practices.values())
        
        # 过滤评分
        practices = [p for p in practices if p.overall_score >= min_score]
        
        # 按综合评分降序排序
        practices.sort(key=lambda p: p.overall_score, reverse=True)
        
        # 限制数量
        return practices[:limit]
    
    def search_practices(
        self,
        keyword: Optional[str] = None,
        scene: Optional[SceneCategory] = None,
        source: Optional[PracticeSource] = None,
        min_score: float = 0.0,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[BestPractice]:
        """
        搜索最佳实践
        
        Args:
            keyword: 关键词（搜索名称和描述）
            scene: 场景类型
            source: 来源类型
            min_score: 最低综合评分（0-100）
            tags: 标签列表（必须包含所有标签）
            limit: 返回数量限制
            
        Returns:
            最佳实践列表，按综合评分降序排列
        """
        practices = list(self._practices.values())
        
        # 关键词过滤
        if keyword:
            keyword_lower = keyword.lower()
            practices = [
                p for p in practices
                if keyword_lower in p.name.lower() or keyword_lower in p.description.lower()
            ]
        
        # 场景过滤
        if scene:
            practices = [p for p in practices if p.is_applicable_for_scene(scene)]
        
        # 来源过滤
        if source:
            practices = [p for p in practices if p.source == source]
        
        # 评分过滤
        practices = [p for p in practices if p.overall_score >= min_score]
        
        # 标签过滤
        if tags:
            practices = [
                p for p in practices
                if all(tag in p.tags for tag in tags)
            ]
        
        # 按综合评分降序排序
        practices.sort(key=lambda p: p.overall_score, reverse=True)
        
        # 限制数量
        if limit is not None:
            practices = practices[:limit]
        
        return practices
    
    def get_recommended_practice(
        self,
        scene: SceneCategory,
        prefer_quality: bool = True,
        prefer_speed: bool = False
    ) -> Optional[BestPractice]:
        """
        获取推荐的最佳实践
        
        Args:
            scene: 场景类型
            prefer_quality: 优先考虑质量
            prefer_speed: 优先考虑速度
            
        Returns:
            推荐的最佳实践，没有找到返回 None
        """
        practices = self.get_practices_by_scene(scene, min_score=70.0)
        
        if not practices:
            return None
        
        # 根据偏好排序
        if prefer_speed:
            # 优先速度：速度评分 * 0.6 + 综合评分 * 0.4
            practices.sort(
                key=lambda p: p.speed_score * 0.6 + p.overall_score * 0.4,
                reverse=True
            )
        elif prefer_quality:
            # 优先质量：质量评分 * 0.6 + 综合评分 * 0.4
            practices.sort(
                key=lambda p: p.quality_score * 0.6 + p.overall_score * 0.4,
                reverse=True
            )
        else:
            # 默认按综合评分
            practices.sort(key=lambda p: p.overall_score, reverse=True)
        
        return practices[0]
    
    def save_practice(self, practice: BestPractice, directory: Optional[Path] = None):
        """
        保存最佳实践到文件
        
        Args:
            practice: BestPractice 实例
            directory: 保存目录，默认为 configs/best_practices
        """
        if directory is None:
            directory = self._config_dir
        
        # 确保目录存在
        directory.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名
        file_path = directory / f"{practice.id}.json"
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(practice.to_dict(), f, indent=2, ensure_ascii=False)
            
            logger.info(f"已保存最佳实践到文件: {file_path}")
        except Exception as e:
            logger.error(f"保存最佳实践到文件失败 {file_path}: {e}")
            raise
    
    def clear(self):
        """清空所有缓存"""
        self._practices.clear()
        self._practices_by_scene.clear()
        self._practices_by_source.clear()
        logger.info("已清空最佳实践库缓存")
    
    def get_statistics(self) -> Dict[str, any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        practices = list(self._practices.values())
        
        if not practices:
            return {
                "total_count": 0,
                "average_score": 0.0,
                "by_source": {},
                "by_scene": {},
            }
        
        # 计算平均评分
        total_score = sum(p.overall_score for p in practices)
        average_score = total_score / len(practices)
        
        # 按来源统计
        by_source = {}
        for source in PracticeSource:
            count = len(self._practices_by_source.get(source, []))
            if count > 0:
                by_source[source.value] = count
        
        # 按场景统计
        by_scene = {}
        for scene in SceneCategory:
            count = len(self._practices_by_scene.get(scene, []))
            if count > 0:
                by_scene[scene.value] = count
        
        return {
            "total_count": len(practices),
            "average_score": round(average_score, 2),
            "by_source": by_source,
            "by_scene": by_scene,
        }


# 全局单例实例
_library_instance = None


def get_best_practice_library() -> BestPracticeLibrary:
    """
    获取最佳实践库单例实例
    
    Returns:
        BestPracticeLibrary 实例
    """
    global _library_instance
    if _library_instance is None:
        _library_instance = BestPracticeLibrary()
    return _library_instance
