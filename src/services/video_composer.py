"""
视频合成服务（Video Composer）

负责视频拼接、音视频同步、背景音乐添加、视频合成
"""

import os
import subprocess
from typing import List, Optional, Tuple
from pathlib import Path

from src.utils.logger import logger


class VideoComposerError(Exception):
    """视频合成错误"""
    pass


class VideoComposer:
    """视频合成服务"""
    
    def __init__(self):
        """
        初始化视频合成服务
        """
        logger.info("视频合成服务初始化完成")
    
    def concat_videos(
        self,
        video_files: List[str],
        output_path: Optional[str] = None
    ) -> str:
        """
        拼接多个视频
        
        Args:
            video_files: 视频文件列表
            output_path: 输出路径（可选）
            
        Returns:
            拼接后的视频文件路径
            
        Raises:
            VideoComposerError: 如果拼接失败
        """
        if not video_files:
            raise ValueError("视频文件列表不能为空")
        
        if len(video_files) == 1:
            logger.info("只有一个视频文件，无需拼接")
            return video_files[0]
        
        logger.info(f"开始拼接视频: {len(video_files)} 个文件")
        
        # 验证所有文件存在
        for video_file in video_files:
            if not os.path.exists(video_file):
                raise FileNotFoundError(f"视频文件不存在: {video_file}")
        
        try:
            # 确定输出路径
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / "concatenated.mp4")
            
            # 创建文件列表
            concat_list_path = Path(output_path).parent / "concat_list.txt"
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video_file in video_files:
                    # 使用绝对路径
                    abs_path = os.path.abspath(video_file)
                    f.write(f"file '{abs_path}'\n")
            
            # 使用 FFmpeg concat demuxer 拼接视频
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list_path),
                "-c", "copy",  # 直接复制流，不重新编码
                "-y",
                output_path
            ]
            
            logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # 清理临时文件
            concat_list_path.unlink()
            
            logger.info(f"视频拼接成功: {output_path}")
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_msg = f"FFmpeg 执行失败: {e.stderr}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
            
        except Exception as e:
            error_msg = f"视频拼接失败: {e}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
    
    def sync_audio_video(
        self,
        video_path: str,
        audio_path: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        同步音视频（替换视频的音轨）
        
        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            output_path: 输出路径（可选）
            
        Returns:
            同步后的视频文件路径
            
        Raises:
            VideoComposerError: 如果同步失败
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        logger.info(f"开始同步音视频: video={video_path}, audio={audio_path}")
        
        try:
            # 确定输出路径
            if not output_path:
                video_dir = Path(video_path).parent
                video_name = Path(video_path).stem
                output_path = str(video_dir / f"{video_name}_synced.mp4")
            
            # 获取视频和音频时长
            video_duration = self._get_duration(video_path)
            audio_duration = self._get_duration(audio_path)
            
            logger.debug(
                f"时长: video={video_duration:.2f}s, audio={audio_duration:.2f}s"
            )
            
            # 使用 FFmpeg 替换音轨
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",  # 视频流直接复制
                "-c:a", "aac",   # 音频重新编码为 AAC
                "-map", "0:v:0", # 使用第一个输入的视频流
                "-map", "1:a:0", # 使用第二个输入的音频流
                "-shortest",     # 以最短的流为准
                "-y",
                output_path
            ]
            
            logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"音视频同步成功: {output_path}")
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_msg = f"FFmpeg 执行失败: {e.stderr}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
            
        except Exception as e:
            error_msg = f"音视频同步失败: {e}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
    
    def add_bgm(
        self,
        video_path: str,
        bgm_path: str,
        output_path: Optional[str] = None,
        bgm_volume: float = 0.3
    ) -> str:
        """
        添加背景音乐
        
        Args:
            video_path: 视频文件路径
            bgm_path: 背景音乐文件路径
            output_path: 输出路径（可选）
            bgm_volume: 背景音乐音量（默认 0.3，范围 0.0-1.0）
            
        Returns:
            添加背景音乐后的视频文件路径
            
        Raises:
            VideoComposerError: 如果添加失败
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        if not os.path.exists(bgm_path):
            raise FileNotFoundError(f"背景音乐文件不存在: {bgm_path}")
        
        if not 0.0 <= bgm_volume <= 1.0:
            raise ValueError("背景音乐音量必须在 0.0-1.0 之间")
        
        logger.info(f"开始添加背景音乐: video={video_path}, bgm={bgm_path}")
        
        try:
            # 确定输出路径
            if not output_path:
                video_dir = Path(video_path).parent
                video_name = Path(video_path).stem
                output_path = str(video_dir / f"{video_name}_with_bgm.mp4")
            
            # 使用 FFmpeg 混合音频
            # amix 滤镜混合原音频和背景音乐
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", bgm_path,
                "-filter_complex",
                f"[0:a]volume=1.0[a1];[1:a]volume={bgm_volume}[a2];[a1][a2]amix=inputs=2:duration=first[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-y",
                output_path
            ]
            
            logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"背景音乐添加成功: {output_path}")
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_msg = f"FFmpeg 执行失败: {e.stderr}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
            
        except Exception as e:
            error_msg = f"添加背景音乐失败: {e}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
    
    def compose_video(
        self,
        video_files: List[str],
        audio_files: Optional[List[str]] = None,
        bgm_path: Optional[str] = None,
        output_path: Optional[str] = None,
        bgm_volume: float = 0.3
    ) -> str:
        """
        合成视频（完整流程：拼接 → 同步音频 → 添加背景音乐）
        
        Args:
            video_files: 视频文件列表
            audio_files: 音频文件列表（可选）
            bgm_path: 背景音乐文件路径（可选）
            output_path: 输出路径（可选）
            bgm_volume: 背景音乐音量（默认 0.3）
            
        Returns:
            合成后的视频文件路径
            
        Raises:
            VideoComposerError: 如果合成失败
        """
        if not video_files:
            raise ValueError("视频文件列表不能为空")
        
        logger.info(
            f"开始合成视频: videos={len(video_files)}, "
            f"audios={len(audio_files) if audio_files else 0}, "
            f"bgm={'是' if bgm_path else '否'}"
        )
        
        try:
            # 确定输出路径
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / "composed.mp4")
            
            current_video = None
            
            # 步骤 1：拼接视频
            if len(video_files) > 1:
                logger.info("步骤 1/3: 拼接视频")
                current_video = self.concat_videos(
                    video_files,
                    str(Path(output_path).parent / "temp_concat.mp4")
                )
            else:
                current_video = video_files[0]
            
            # 步骤 2：同步音频（如果提供了音频文件）
            if audio_files:
                logger.info("步骤 2/3: 同步音频")
                
                # 如果有多个音频文件，先拼接
                if len(audio_files) > 1:
                    merged_audio = self._concat_audio(
                        audio_files,
                        str(Path(output_path).parent / "temp_audio.mp3")
                    )
                else:
                    merged_audio = audio_files[0]
                
                current_video = self.sync_audio_video(
                    current_video,
                    merged_audio,
                    str(Path(output_path).parent / "temp_synced.mp4")
                )
            
            # 步骤 3：添加背景音乐（如果提供了）
            if bgm_path:
                logger.info("步骤 3/3: 添加背景音乐")
                current_video = self.add_bgm(
                    current_video,
                    bgm_path,
                    output_path,
                    bgm_volume
                )
            else:
                # 没有背景音乐，直接移动到输出路径
                if current_video != output_path:
                    import shutil
                    shutil.move(current_video, output_path)
            
            # 清理临时文件
            self._cleanup_temp_files(Path(output_path).parent)
            
            logger.info(f"视频合成成功: {output_path}")
            
            return output_path
            
        except Exception as e:
            error_msg = f"视频合成失败: {e}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
    
    def _get_duration(self, file_path: str) -> float:
        """
        获取媒体文件时长
        
        Args:
            file_path: 文件路径
            
        Returns:
            时长（秒）
        """
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            return float(result.stdout.strip())
            
        except Exception as e:
            logger.warning(f"获取文件时长失败: {e}")
            return 0.0
    
    def _concat_audio(
        self,
        audio_files: List[str],
        output_path: str
    ) -> str:
        """
        拼接多个音频文件
        
        Args:
            audio_files: 音频文件列表
            output_path: 输出路径
            
        Returns:
            拼接后的音频文件路径
        """
        try:
            # 创建文件列表
            concat_list_path = Path(output_path).parent / "audio_concat_list.txt"
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for audio_file in audio_files:
                    abs_path = os.path.abspath(audio_file)
                    f.write(f"file '{abs_path}'\n")
            
            # 拼接音频
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list_path),
                "-c", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # 清理临时文件
            concat_list_path.unlink()
            
            return output_path
            
        except Exception as e:
            raise VideoComposerError(f"音频拼接失败: {e}") from e
    
    def _cleanup_temp_files(self, temp_dir: Path):
        """
        清理临时文件
        
        Args:
            temp_dir: 临时文件目录
        """
        try:
            temp_patterns = ["temp_*.mp4", "temp_*.mp3", "*_concat_list.txt"]
            
            for pattern in temp_patterns:
                for temp_file in temp_dir.glob(pattern):
                    try:
                        temp_file.unlink()
                        logger.debug(f"清理临时文件: {temp_file}")
                    except Exception as e:
                        logger.warning(f"清理临时文件失败: {temp_file}, {e}")
                        
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")


# 全局视频合成服务实例（单例模式）
_video_composer_instance: Optional[VideoComposer] = None


def get_video_composer() -> VideoComposer:
    """
    获取全局视频合成服务实例（单例模式）
    
    Returns:
        视频合成服务实例
    """
    global _video_composer_instance
    
    if _video_composer_instance is None:
        _video_composer_instance = VideoComposer()
        logger.info("全局视频合成服务实例创建成功")
    
    return _video_composer_instance


def cleanup_video_composer():
    """
    清理全局视频合成服务实例
    """
    global _video_composer_instance
    
    if _video_composer_instance is not None:
        _video_composer_instance = None
        logger.info("全局视频合成服务实例已清理")
