"""
文件存储管理模块
管理项目文件的存储、路径生成和清理
"""

import os
import shutil
from pathlib import Path
from typing import Optional
import psutil


# 存储配置
STORAGE_PATH = os.getenv("STORAGE_PATH", "./storage")
MAX_STORAGE_SIZE_GB = int(os.getenv("MAX_STORAGE_SIZE_GB", "500"))


class StorageManager:
    """文件存储管理器"""
    
    def __init__(self, base_path: str = STORAGE_PATH):
        """
        初始化存储管理器
        
        Args:
            base_path: 存储根目录
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def get_project_path(self, project_id: int) -> Path:
        """
        获取项目存储路径
        
        Args:
            project_id: 项目ID
        
        Returns:
            Path: 项目存储路径
        """
        project_path = self.base_path / f"projects/{project_id}"
        project_path.mkdir(parents=True, exist_ok=True)
        return project_path
    
    def get_image_path(self, project_id: int, scene_id: int, filename: Optional[str] = None) -> Path:
        """
        获取图像文件路径
        
        Args:
            project_id: 项目ID
            scene_id: 分镜ID
            filename: 文件名（可选）
        
        Returns:
            Path: 图像文件路径
        """
        image_dir = self.get_project_path(project_id) / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        
        if filename:
            return image_dir / filename
        else:
            return image_dir / f"scene_{scene_id}.png"
    
    def get_video_path(self, project_id: int, scene_id: int, filename: Optional[str] = None) -> Path:
        """
        获取视频文件路径
        
        Args:
            project_id: 项目ID
            scene_id: 分镜ID
            filename: 文件名（可选）
        
        Returns:
            Path: 视频文件路径
        """
        video_dir = self.get_project_path(project_id) / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        
        if filename:
            return video_dir / filename
        else:
            return video_dir / f"scene_{scene_id}.mp4"
    
    def get_audio_path(self, project_id: int, scene_id: int, filename: Optional[str] = None) -> Path:
        """
        获取音频文件路径
        
        Args:
            project_id: 项目ID
            scene_id: 分镜ID
            filename: 文件名（可选）
        
        Returns:
            Path: 音频文件路径
        """
        audio_dir = self.get_project_path(project_id) / "audios"
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        if filename:
            return audio_dir / filename
        else:
            return audio_dir / f"scene_{scene_id}.wav"
    
    def get_subtitle_path(self, project_id: int, scene_id: int, filename: Optional[str] = None) -> Path:
        """
        获取字幕文件路径
        
        Args:
            project_id: 项目ID
            scene_id: 分镜ID
            filename: 文件名（可选）
        
        Returns:
            Path: 字幕文件路径
        """
        subtitle_dir = self.get_project_path(project_id) / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        
        if filename:
            return subtitle_dir / filename
        else:
            return subtitle_dir / f"scene_{scene_id}.srt"
    
    def get_final_video_path(self, project_id: int, filename: Optional[str] = None) -> Path:
        """
        获取最终视频文件路径
        
        Args:
            project_id: 项目ID
            filename: 文件名（可选）
        
        Returns:
            Path: 最终视频文件路径
        """
        project_path = self.get_project_path(project_id)
        
        if filename:
            return project_path / filename
        else:
            return project_path / f"final_video_{project_id}.mp4"
    
    def delete_project_files(self, project_id: int) -> bool:
        """
        删除项目的所有文件
        
        Args:
            project_id: 项目ID
        
        Returns:
            bool: 删除成功返回 True，否则返回 False
        """
        try:
            project_path = self.get_project_path(project_id)
            if project_path.exists():
                shutil.rmtree(project_path)
                return True
            return False
        except Exception as e:
            print(f"删除项目文件失败: {e}")
            return False
    
    def get_project_size(self, project_id: int) -> int:
        """
        获取项目文件总大小
        
        Args:
            project_id: 项目ID
        
        Returns:
            int: 文件总大小（字节）
        """
        project_path = self.get_project_path(project_id)
        total_size = 0
        
        for dirpath, dirnames, filenames in os.walk(project_path):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                total_size += filepath.stat().st_size
        
        return total_size
    
    def check_disk_space(self) -> dict:
        """
        检查磁盘空间
        
        Returns:
            dict: 包含磁盘空间信息的字典
        """
        disk_usage = psutil.disk_usage(str(self.base_path))
        
        return {
            "total_gb": disk_usage.total / (1024 ** 3),
            "used_gb": disk_usage.used / (1024 ** 3),
            "free_gb": disk_usage.free / (1024 ** 3),
            "percent": disk_usage.percent,
            "available": disk_usage.free / (1024 ** 3) > 10  # 至少保留 10GB
        }
    
    def cleanup_old_files(self, days: int = 30) -> int:
        """
        清理旧文件
        
        Args:
            days: 保留天数
        
        Returns:
            int: 清理的文件数
        """
        import time
        
        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 60 * 60)
        cleaned_count = 0
        
        for dirpath, dirnames, filenames in os.walk(self.base_path):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                if filepath.stat().st_mtime < cutoff_time:
                    try:
                        filepath.unlink()
                        cleaned_count += 1
                    except Exception:
                        pass
        
        return cleaned_count


# 创建全局存储管理器实例
storage_manager = StorageManager()


# 导出便捷函数
def get_project_storage_path(project_id: int) -> str:
    """
    获取项目存储路径（字符串格式）
    
    Args:
        project_id: 项目ID
        
    Returns:
        项目存储路径
    """
    return str(storage_manager.get_project_path(project_id))


def cleanup_project_files(storage_path: str) -> bool:
    """
    清理项目文件
    
    Args:
        storage_path: 项目存储路径
        
    Returns:
        是否清理成功
    """
    try:
        if os.path.exists(storage_path):
            shutil.rmtree(storage_path)
            return True
        return False
    except Exception as e:
        print(f"清理项目文件失败: {e}")
        return False


# 导出
__all__ = [
    "StorageManager",
    "storage_manager",
    "get_project_storage_path",
    "cleanup_project_files"
]


def get_scene_image_path(project_id: int, scene_id: int) -> str:
    """
    获取分镜图像路径
    
    Args:
        project_id: 项目ID
        scene_id: 分镜ID
    
    Returns:
        str: 图像文件路径
    """
    return str(storage_manager.get_image_path(project_id, scene_id))


def get_scene_video_path(project_id: int, scene_id: int) -> str:
    """
    获取分镜视频路径
    
    Args:
        project_id: 项目ID
        scene_id: 分镜ID
    
    Returns:
        str: 视频文件路径
    """
    return str(storage_manager.get_video_path(project_id, scene_id))


def get_scene_audio_path(project_id: int, scene_id: int) -> str:
    """
    获取分镜音频路径
    
    Args:
        project_id: 项目ID
        scene_id: 分镜ID
    
    Returns:
        str: 音频文件路径
    """
    return str(storage_manager.get_audio_path(project_id, scene_id))


def get_scene_subtitle_path(project_id: int, scene_id: int) -> str:
    """
    获取分镜字幕路径
    
    Args:
        project_id: 项目ID
        scene_id: 分镜ID
    
    Returns:
        str: 字幕文件路径
    """
    return str(storage_manager.get_subtitle_path(project_id, scene_id))


def get_project_final_video_path(project_id: int) -> str:
    """
    获取项目最终视频路径
    
    Args:
        project_id: 项目ID
    
    Returns:
        str: 最终视频文件路径
    """
    return str(storage_manager.get_final_video_path(project_id))
