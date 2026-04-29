"""
字幕生成服务单元测试

测试 SubtitleGenerator 的核心功能
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.services.subtitle_generator import (
    SubtitleGenerator,
    SubtitleError,
    get_subtitle_generator,
    cleanup_subtitle_generator
)


class TestSubtitleGenerator:
    """字幕生成服务测试类"""
    
    @pytest.fixture
    def service(self):
        """创建字幕生成服务实例"""
        return SubtitleGenerator()
    
    @pytest.fixture
    def sample_dialogues(self):
        """创建示例对话列表"""
        return [
            {"text": "你好，世界！", "start_time": 0.0, "duration": 2.0},
            {"text": "这是第二句话", "start_time": 2.0, "duration": 3.0},
            {"text": "这是一句很长很长很长很长很长的话，需要分行显示", "start_time": 5.0, "duration": 4.0}
        ]
    
    def test_init_success(self):
        """测试：成功初始化服务"""
        service = SubtitleGenerator(
            max_chars_per_line=30,
            max_lines=3,
            font_size=28
        )
        
        assert service.max_chars_per_line == 30
        assert service.max_lines == 3
        assert service.font_size == 28
    
    def test_generate_srt_success(self, service, sample_dialogues, tmp_path):
        """测试：成功生成 SRT 字幕"""
        output_path = str(tmp_path / "test.srt")
        
        result_path = service.generate_srt(sample_dialogues, output_path)
        
        assert result_path == output_path
        assert os.path.exists(output_path)
        
        # 验证文件内容
        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        assert "1" in content
        assert "00:00:00,000 --> 00:00:02,000" in content
        assert "你好，世界！" in content
        assert "2" in content
        assert "这是第二句话" in content
    
    def test_generate_srt_empty_dialogues(self, service):
        """测试：空对话列表时抛出异常"""
        with pytest.raises(ValueError, match="对话列表不能为空"):
            service.generate_srt([])
    
    def test_generate_srt_skip_empty_text(self, service, tmp_path):
        """测试：跳过空文本对话"""
        dialogues = [
            {"text": "第一句", "start_time": 0.0, "duration": 2.0},
            {"text": "", "start_time": 2.0, "duration": 2.0},  # 空文本
            {"text": "第三句", "start_time": 4.0, "duration": 2.0}
        ]
        
        output_path = str(tmp_path / "test.srt")
        service.generate_srt(dialogues, output_path)
        
        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 应该只有 2 个字幕条目（跳过了空文本）
        assert "第一句" in content
        assert "第三句" in content
        # 验证序号是 1 和 3（因为跳过了 2）
        assert content.startswith("1\n")
        assert "\n3\n" in content
    
    def test_split_text_short(self, service):
        """测试：短文本不分行"""
        text = "短文本"
        lines = service._split_text(text)
        
        assert len(lines) == 1
        assert lines[0] == text
    
    def test_split_text_long(self, service):
        """测试：长文本自动分行"""
        text = "这是一句很长很长很长很长很长的话，需要分行显示"
        lines = service._split_text(text)
        
        assert len(lines) > 1
        # 验证每行长度不超过限制（除了最后一行）
        for i, line in enumerate(lines[:-1]):
            assert len(line) <= service.max_chars_per_line
    
    def test_split_text_max_lines(self, service):
        """测试：超过最大行数限制"""
        text = "这" * 100  # 很长的文本
        lines = service._split_text(text)
        
        assert len(lines) <= service.max_lines
    
    def test_format_time(self, service):
        """测试：时间格式化"""
        # 测试 0 秒
        assert service._format_time(0.0) == "00:00:00,000"
        
        # 测试 1.5 秒
        assert service._format_time(1.5) == "00:00:01,500"
        
        # 测试 65.123 秒
        assert service._format_time(65.123) == "00:01:05,123"
        
        # 测试 3661.456 秒
        assert service._format_time(3661.456) == "01:01:01,456"
    
    def test_calculate_timing_success(self, service, tmp_path):
        """测试：成功计算时间轴"""
        # 创建临时音频文件
        audio_files = []
        for i in range(3):
            audio_file = tmp_path / f"audio_{i}.mp3"
            audio_file.write_text("fake audio")
            audio_files.append(str(audio_file))
        
        # Mock _get_audio_duration
        with patch.object(service, '_get_audio_duration', side_effect=[2.0, 3.0, 2.5]):
            timings = service.calculate_timing(audio_files)
        
        assert len(timings) == 3
        assert timings[0]["start_time"] == 0.0
        assert timings[0]["duration"] == 2.0
        assert timings[1]["start_time"] == 2.0
        assert timings[1]["duration"] == 3.0
        assert timings[2]["start_time"] == 5.0
        assert timings[2]["duration"] == 2.5
    
    def test_calculate_timing_invalid_duration(self, service, tmp_path):
        """测试：音频时长无效时使用默认值"""
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_text("fake audio")
        
        # Mock _get_audio_duration 返回 0
        with patch.object(service, '_get_audio_duration', return_value=0.0):
            timings = service.calculate_timing([str(audio_file)], base_duration=2.5)
        
        assert len(timings) == 1
        assert timings[0]["duration"] == 2.5
    
    def test_get_audio_duration_file_not_exists(self, service):
        """测试：音频文件不存在时返回 0"""
        duration = service._get_audio_duration("nonexistent.mp3")
        
        assert duration == 0.0
    
    def test_get_audio_duration_ffprobe_error(self, service, tmp_path):
        """测试：FFprobe 执行失败时返回 0"""
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_text("fake audio")
        
        with patch('subprocess.run', side_effect=Exception("FFprobe error")):
            duration = service._get_audio_duration(str(audio_file))
        
        assert duration == 0.0
    
    def test_burn_subtitle_video_not_exists(self, service):
        """测试：视频文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError, match="视频文件不存在"):
            service.burn_subtitle("nonexistent.mp4", "subtitle.srt")
    
    def test_burn_subtitle_subtitle_not_exists(self, service, tmp_path):
        """测试：字幕文件不存在时抛出异常"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        
        with pytest.raises(FileNotFoundError, match="字幕文件不存在"):
            service.burn_subtitle(str(video_file), "nonexistent.srt")
    
    def test_burn_subtitle_success(self, service, tmp_path):
        """测试：成功烧录字幕"""
        # 创建临时文件
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        subtitle_file = tmp_path / "subtitle.srt"
        subtitle_file.write_text("fake subtitle")
        output_file = tmp_path / "output.mp4"
        
        # Mock subprocess.run
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result_path = service.burn_subtitle(
                str(video_file),
                str(subtitle_file),
                str(output_file)
            )
        
        assert result_path == str(output_file)
        mock_run.assert_called_once()
    
    def test_burn_subtitle_ffmpeg_error(self, service, tmp_path):
        """测试：FFmpeg 执行失败时抛出异常"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        subtitle_file = tmp_path / "subtitle.srt"
        subtitle_file.write_text("fake subtitle")
        
        # Mock subprocess.run 抛出异常
        with patch('subprocess.run', side_effect=Exception("FFmpeg error")):
            with pytest.raises(SubtitleError, match="烧录字幕失败"):
                service.burn_subtitle(str(video_file), str(subtitle_file))
    
    def test_color_to_ass(self, service):
        """测试：颜色转换为 ASS 格式"""
        assert service._color_to_ass("white") == "&H00FFFFFF"
        assert service._color_to_ass("black") == "&H00000000"
        assert service._color_to_ass("red") == "&H000000FF"
        assert service._color_to_ass("unknown") == "&H00FFFFFF"  # 默认白色


class TestGlobalSubtitleGenerator:
    """全局字幕生成服务测试类"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        cleanup_subtitle_generator()
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        cleanup_subtitle_generator()
    
    def test_get_subtitle_generator_singleton(self):
        """测试：全局服务实例是单例"""
        service1 = get_subtitle_generator()
        service2 = get_subtitle_generator()
        
        assert service1 is service2
    
    def test_cleanup_subtitle_generator(self):
        """测试：清理全局服务实例"""
        service = get_subtitle_generator()
        assert service is not None
        
        cleanup_subtitle_generator()
        
        service2 = get_subtitle_generator()
        assert service2 is not service


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
