"""
角色管理服务
处理角色面部一致性相关功能
"""

import hashlib
import json
import os
from datetime import datetime, timezone
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
    
    def __init__(self, base_dir: Optional[str] = None):
        from src.utils.storage import storage_manager
        self.base_dir = Path(base_dir) if base_dir else storage_manager.base_path / "characters"
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

    def freeze_character_asset_pack(
        self,
        character_id: int,
        project_id: int,
        identity_spec: dict,
        distinctiveness: dict,
        notes: str = "",
    ) -> dict:
        """
        Freeze the approved character bible and reference images for production.

        The manifest intentionally stores hashes. Production readiness can then
        detect stale packs after a reference image or identity bible changes.
        """
        references = self.get_character_references(character_id, project_id)
        if not identity_spec:
            raise ValueError("character identity bible is required before freezing")
        if not references:
            raise ValueError("at least one character reference image is required before freezing")
        char_dir = self.base_dir / str(project_id) / str(character_id)
        manifest = {
            "version": 1,
            "status": "frozen",
            "project_id": project_id,
            "character_id": character_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "identity_spec_hash": self._json_hash(identity_spec),
            "identity_anchor": identity_spec.get("identity_anchor", ""),
            "reference_paths": references,
            "reference_hashes": {path: self._file_hash(Path(path)) for path in references},
            "distinctiveness": distinctiveness,
            "notes": notes,
        }
        path = char_dir / "asset_pack.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def get_character_asset_pack(self, character_id: int, project_id: int) -> Optional[dict]:
        path = self.base_dir / str(project_id) / str(character_id) / "asset_pack.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "invalid", "path": str(path)}

    def validate_character_asset_pack(
        self,
        character_id: int,
        project_id: int,
        identity_spec: dict,
    ) -> dict:
        manifest = self.get_character_asset_pack(character_id, project_id)
        references = self.get_character_references(character_id, project_id)
        if not manifest:
            return {"status": "missing", "missing": ["asset_pack"]}
        if manifest.get("status") != "frozen":
            return {"status": "invalid", "missing": ["frozen_status"], "manifest": manifest}
        missing = []
        stale = []
        if manifest.get("identity_spec_hash") != self._json_hash(identity_spec):
            stale.append("identity_spec")
        manifest_paths = manifest.get("reference_paths") if isinstance(manifest.get("reference_paths"), list) else []
        if sorted(manifest_paths) != sorted(references):
            stale.append("reference_set")
        hashes = manifest.get("reference_hashes") if isinstance(manifest.get("reference_hashes"), dict) else {}
        for path in manifest_paths:
            ref = Path(path)
            if not ref.is_file():
                missing.append(path)
            elif hashes.get(path) != self._file_hash(ref):
                stale.append(path)
        status = "valid" if not missing and not stale else "stale"
        return {
            "status": status,
            "missing": missing,
            "stale": sorted(set(stale)),
            "manifest": manifest,
        }
    
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

    def _json_hash(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _file_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


# 全局角色管理器实例
_character_manager = None


def get_character_manager() -> CharacterManager:
    """获取全局角色管理器实例"""
    global _character_manager
    if _character_manager is None:
        _character_manager = CharacterManager()
    return _character_manager
