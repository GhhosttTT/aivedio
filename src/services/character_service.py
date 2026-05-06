"""
角色管理服务
处理角色面部一致性相关功能
"""

import os
from typing import Optional, List
from pathlib import Path
from loguru import logger


class CharacterManager:
    """
    角色管理器
    
    负责：
    1. 管理角色参考图像
    2. 生成角色 Embedding/LoRA
    3. 提供角色特征给图像生成流程
    """
    
    def __init__(self, base_dir: str = "./storage/characters"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"CharacterManager 初始化: {self.base_dir}")
    
    def save_character_reference(
        self,
        character_id: int,
        project_id: int,
        image_path: str,
        description: str = ""
    ) -> str:
        """
        保存角色参考图像
        
        Args:
            character_id: 角色ID
            project_id: 项目ID
            image_path: 参考图像路径
            description: 角色描述
        
        Returns:
            保存后的图像路径
        """
        # 创建角色目录
        char_dir = self.base_dir / str(project_id) / str(character_id)
        char_dir.mkdir(parents=True, exist_ok=True)
        
        # 复制参考图像
        from shutil import copy2
        existing_refs = list(char_dir.glob('*.png'))
        ref_number = len(existing_refs) + 1
        dest_path = char_dir / f"reference_{ref_number}.png"
        copy2(image_path, dest_path)
        
        logger.info(f"角色参考图像已保存: {dest_path}")
        return str(dest_path)
    
    def get_character_references(self, character_id: int, project_id: int) -> List[str]:
        """
        获取角色的所有参考图像
        
        Args:
            character_id: 角色ID
            project_id: 项目ID
        
        Returns:
            参考图像路径列表
        """
        char_dir = self.base_dir / str(project_id) / str(character_id)
        if not char_dir.exists():
            return []
        
        references = sorted(char_dir.glob("reference_*.png"))
        return [str(ref) for ref in references]
    
    def get_character_embedding_path(self, character_id: int, project_id: int) -> Optional[str]:
        """
        获取角色 Embedding 文件路径
        
        Args:
            character_id: 角色ID
            project_id: 项目ID
        
        Returns:
            Embedding 文件路径，如果不存在则返回 None
        """
        embedding_path = self.base_dir / str(project_id) / str(character_id) / "embedding.pt"
        if embedding_path.exists():
            return str(embedding_path)
        return None


# 全局角色管理器实例
_character_manager = None


def get_character_manager() -> CharacterManager:
    """获取全局角色管理器实例"""
    global _character_manager
    if _character_manager is None:
        _character_manager = CharacterManager()
    return _character_manager
