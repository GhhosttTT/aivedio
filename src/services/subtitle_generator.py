"""
字幕生成服务（Subtitle Generator）

负责生成 SRT 字幕文件，计算时间轴，烧录字幕到视频
"""

import os
import subprocess
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from datetime import timedelta

from src.utils.logger import logger


class SubtitleError(Exception):
    """字幕生成错误"""
    pass


class SubtitleGenerator:
    """字幕生成服务"""
    
    def __init__(
        self,
        max_chars_per_line: int = 20,
        max_lines: int = 2,
        font_size: int = 24,
        font_color: str = "white",
        font_name: str = "Arial",
        outline_color: str = "black",
        outline_width: int = 2
    ):
        """
        初始化字幕生成服务
        
        Args:
            max_chars_per_line: 每行最大字符数（默认 20）
            max_lines: 最大行数（默认 2）
            font_size: 字体大小（默认 24）
            font_color: 字体颜色（默认 white）
            font_name: 字体名称（默认 Arial）
            outline_color: 描边颜色（默认 black）
            outline_width: 描边宽度（默认 2）
        """
        self.max_chars_per_line = max_chars_per_line
        self.max_lines = max_lines
        self.font_size = font_size
        self.font_color = font_color
        self.font_name = font_name
        self.outline_color = outline_color
        self.outline_width = outline_width
        
        logger.info("字幕生成服务初始化完成")
    
    def generate_srt(
        self,
        dialogues: List[Dict[str, any]],
        output_path: Optional[str] = None
    ) -> str:
        """
        生成 SRT 字幕文件
        
        Args:
            dialogues: 对话列表，每个元素包含 text、start_time、duration
            output_path: 输出路径（可选）
            
        Returns:
            生成的 SRT 文件路径
            
        Raises:
            SubtitleError: 如果生成失败
        """
        if not dialogues:
            raise ValueError("对话列表不能为空")
        
        logger.info(f"开始生成 SRT 字幕: {len(dialogues)} 条对话")
        
        try:
            # 确定输出路径
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / "subtitle.srt")
            
            # 生成 SRT 内容
            srt_content = []
            
            for i, dialogue in enumerate(dialogues, start=1):
                text = dialogue.get("text", "")
                start_time = dialogue.get("start_time", 0.0)
                duration = dialogue.get("duration", 2.0)
                
                if not text:
                    logger.warning(f"对话 {i} 文本为空，跳过")
                    continue
                
                # 处理超长对话（自动分行）
                lines = self._split_text(text)
                
                # 计算时间轴
                end_time = start_time + duration
                
                # 格式化时间
                start_str = self._format_time(start_time)
                end_str = self._format_time(end_time)
                
                # 添加字幕条目
                srt_content.append(f"{i}")
                srt_content.append(f"{start_str} --> {end_str}")
                srt_content.append("\n".join(lines))
                srt_content.append("")  # 空行分隔
            
            # 写入文件
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(srt_content))
            
            logger.info(f"SRT 字幕生成成功: {output_path}")
            
            return output_path
            
        except Exception as e:
            error_msg = f"生成 SRT 字幕失败: {e}"
            logger.error(error_msg)
            raise SubtitleError(error_msg) from e
    
    def _split_text(self, text: str) -> List[str]:
        """
        分割文本为多行（处理超长对话）
        
        Args:
            text: 输入文本
            
        Returns:
            分割后的文本行列表
        """
        if len(text) <= self.max_chars_per_line:
            return [text]
        
        lines = []
        current_line = ""
        
        for i, char in enumerate(text):
            current_line += char
            
            # 检查是否需要换行
            if len(current_line) >= self.max_chars_per_line:
                # 检查行数限制
                if len(lines) >= self.max_lines - 1:
                    # 已达到最大行数限制，剩余文本全部添加到当前行
                    current_line += text[i + 1:]
                    break
                else:
                    # 添加当前行并开始新行
                    lines.append(current_line)
                    current_line = ""
        
        # 添加最后一行
        if current_line:
            lines.append(current_line)
        
        return lines
    
    def _format_time(self, seconds: float) -> str:
        """
        格式化时间为 SRT 格式（HH:MM:SS,mmm）
        
        Args:
            seconds: 秒数
            
        Returns:
            格式化的时间字符串
        """
        td = timedelta(seconds=seconds)
        hours = int(td.total_seconds() // 3600)
        minutes = int((td.total_seconds() % 3600) // 60)
        secs = int(td.total_seconds() % 60)
        millis = int((td.total_seconds() % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    def calculate_timing(
        self,
        audio_files: List[str],
        base_duration: float = 2.0
    ) -> List[Dict[str, float]]:
        """
        计算字幕时间轴
        
        Args:
            audio_files: 音频文件列表
            base_duration: 基础时长（秒，默认 2.0）
            
        Returns:
            时间轴列表，每个元素包含 start_time、duration
            
        Raises:
            SubtitleError: 如果计算失败
        """
        logger.info(f"开始计算字幕时间轴: {len(audio_files)} 个音频文件")
        
        try:
            timings = []
            current_time = 0.0
            
            for audio_file in audio_files:
                # 获取音频时长
                duration = self._get_audio_duration(audio_file)
                
                if duration <= 0:
                    logger.warning(
                        f"音频文件 {audio_file} 时长无效，使用默认时长 {base_duration}"
                    )
                    duration = base_duration
                
                timings.append({
                    "start_time": current_time,
                    "duration": duration
                })
                
                current_time += duration
            
            logger.info(f"时间轴计算完成: 总时长 {current_time:.2f} 秒")
            
            return timings
            
        except Exception as e:
            error_msg = f"计算字幕时间轴失败: {e}"
            logger.error(error_msg)
            raise SubtitleError(error_msg) from e
    
    def _get_audio_duration(self, audio_file: str) -> float:
        """
        获取音频文件时长
        
        Args:
            audio_file: 音频文件路径
            
        Returns:
            音频时长（秒）
        """
        if not os.path.exists(audio_file):
            logger.warning(f"音频文件不存在: {audio_file}")
            return 0.0
        
        try:
            # 使用 FFprobe 获取音频时长
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_file
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            duration = float(result.stdout.strip())
            
            return duration
            
        except Exception as e:
            logger.warning(f"获取音频时长失败: {e}")
            return 0.0
    
    def burn_subtitle(
        self,
        video_path: str,
        subtitle_path: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        烧录字幕到视频（使用 FFmpeg）
        
        Args:
            video_path: 输入视频路径
            subtitle_path: 字幕文件路径
            output_path: 输出视频路径（可选）
            
        Returns:
            输出视频路径
            
        Raises:
            SubtitleError: 如果烧录失败
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        if not os.path.exists(subtitle_path):
            raise FileNotFoundError(f"字幕文件不存在: {subtitle_path}")
        
        logger.info(f"开始烧录字幕: video={video_path}, subtitle={subtitle_path}")
        
        try:
            # 确定输出路径
            if not output_path:
                video_dir = Path(video_path).parent
                video_name = Path(video_path).stem
                output_path = str(video_dir / f"{video_name}_subtitled.mp4")
            
            # 构建 FFmpeg 命令
            # 使用 subtitles 滤镜烧录字幕
            subtitle_filter = (
                f"subtitles={subtitle_path}:"
                f"force_style='FontName={self.font_name},"
                f"FontSize={self.font_size},"
                f"PrimaryColour={self._color_to_ass(self.font_color)},"
                f"OutlineColour={self._color_to_ass(self.outline_color)},"
                f"Outline={self.outline_width}'"
            )
            
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vf", subtitle_filter,
                "-c:a", "copy",  # 音频直接复制
                "-y",  # 覆盖输出文件
                output_path
            ]
            
            logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")
            
            # 执行 FFmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"字幕烧录成功: {output_path}")
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_msg = f"FFmpeg 执行失败: {e.stderr}"
            logger.error(error_msg)
            raise SubtitleError(error_msg) from e
            
        except Exception as e:
            error_msg = f"烧录字幕失败: {e}"
            logger.error(error_msg)
            raise SubtitleError(error_msg) from e
    
    def _color_to_ass(self, color: str) -> str:
        """
        将颜色名称转换为 ASS 格式
        
        Args:
            color: 颜色名称（如 white、black）
            
        Returns:
            ASS 格式颜色代码
        """
        color_map = {
            "white": "&H00FFFFFF",
            "black": "&H00000000",
            "red": "&H000000FF",
            "green": "&H0000FF00",
            "blue": "&H00FF0000",
            "yellow": "&H0000FFFF"
        }
        
        return color_map.get(color.lower(), "&H00FFFFFF")


# 全局字幕生成服务实例（单例模式）
_subtitle_generator_instance: Optional[SubtitleGenerator] = None


def get_subtitle_generator() -> SubtitleGenerator:
    """
    获取全局字幕生成服务实例（单例模式）
    
    Returns:
        字幕生成服务实例
    """
    global _subtitle_generator_instance
    
    if _subtitle_generator_instance is None:
        _subtitle_generator_instance = SubtitleGenerator()
        logger.info("全局字幕生成服务实例创建成功")
    
    return _subtitle_generator_instance


def cleanup_subtitle_generator():
    """
    清理全局字幕生成服务实例
    """
    global _subtitle_generator_instance
    
    if _subtitle_generator_instance is not None:
        _subtitle_generator_instance = None
        logger.info("全局字幕生成服务实例已清理")
