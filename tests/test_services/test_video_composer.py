"""
视频合成服务单元测试

测试 VideoComposer 的核心功能
"""

import pytest
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.services.video_composer import (
    VideoComposer,
    VideoComposerError,
    get_video_composer,
    cleanup_video_composer
)


class TestVideoComposer:
    """视频合成服务测试类"""
    
    @pytest.fixture
    def service(self):
        """创建视频合成服务实例"""
        return VideoComposer()
    
    def test_init_success(self):
        """测试：成功初始化服务"""
        service = VideoComposer()
        assert service is not None
    
    def test_concat_videos_empty_list(self, service):
        """测试：空视频列表时抛出异常"""
        with pytest.raises(ValueError, match="视频文件列表不能为空"):
            service.concat_videos([])
    
    def test_concat_videos_single_file(self, service):
        """测试：单个视频文件时直接返回"""
        video_file = "video.mp4"
        result = service.concat_videos([video_file])
        
        assert result == video_file
    
    def test_concat_videos_file_not_exists(self, service):
        """测试：视频文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError, match="视频文件不存在"):
            service.concat_videos(["nonexistent1.mp4", "nonexistent2.mp4"])
    
    def test_concat_videos_success(self, service, tmp_path):
        """测试：成功拼接视频"""
        # 创建临时视频文件
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        
        output_path = tmp_path / "output.mp4"
        
        # Mock subprocess.run
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result = service.concat_videos(
                [str(video1), str(video2)],
                str(output_path)
            )
        
        assert result == str(output_path)
        mock_run.assert_called_once()
    
    def test_sync_audio_video_video_not_exists(self, service):
        """测试：视频文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError, match="视频文件不存在"):
            service.sync_audio_video("nonexistent.mp4", "audio.mp3")
    
    def test_sync_audio_video_audio_not_exists(self, service, tmp_path):
        """测试：音频文件不存在时抛出异常"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        
        with pytest.raises(FileNotFoundError, match="音频文件不存在"):
            service.sync_audio_video(str(video_file), "nonexistent.mp3")
    
    def test_sync_audio_video_success(self, service, tmp_path):
        """测试：成功同步音视频"""
        video_file = tmp_path / "video.mp4"
        audio_file = tmp_path / "audio.mp3"
        video_file.write_text("fake video")
        audio_file.write_text("fake audio")
        
        output_path = tmp_path / "output.mp4"
        
        # Mock _get_duration 和 subprocess.run
        with patch.object(service, '_get_duration', side_effect=[10.0, 10.0]):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                
                result = service.sync_audio_video(
                    str(video_file),
                    str(audio_file),
                    str(output_path)
                )
        
        assert result == str(output_path)
        mock_run.assert_called_once()
    
    def test_add_bgm_video_not_exists(self, service):
        """测试：视频文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError, match="视频文件不存在"):
            service.add_bgm("nonexistent.mp4", "bgm.mp3")
    
    def test_add_bgm_bgm_not_exists(self, service, tmp_path):
        """测试：背景音乐文件不存在时抛出异常"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        
        with pytest.raises(FileNotFoundError, match="背景音乐文件不存在"):
            service.add_bgm(str(video_file), "nonexistent.mp3")
    
    def test_add_bgm_invalid_volume(self, service, tmp_path):
        """测试：无效音量时抛出异常"""
        video_file = tmp_path / "video.mp4"
        bgm_file = tmp_path / "bgm.mp3"
        video_file.write_text("fake video")
        bgm_file.write_text("fake bgm")
        
        with pytest.raises(ValueError, match="背景音乐音量必须在 0.0-1.0 之间"):
            service.add_bgm(str(video_file), str(bgm_file), bgm_volume=1.5)
    
    def test_add_bgm_success(self, service, tmp_path):
        """测试：成功添加背景音乐"""
        video_file = tmp_path / "video.mp4"
        bgm_file = tmp_path / "bgm.mp3"
        video_file.write_text("fake video")
        bgm_file.write_text("fake bgm")
        
        output_path = tmp_path / "output.mp4"
        
        # Mock subprocess.run
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result = service.add_bgm(
                str(video_file),
                str(bgm_file),
                str(output_path),
                bgm_volume=0.5
            )
        
        assert result == str(output_path)
        mock_run.assert_called_once()
    
    def test_compose_video_empty_list(self, service):
        """测试：空视频列表时抛出异常"""
        with pytest.raises(ValueError, match="视频文件列表不能为空"):
            service.compose_video([])
    
    def test_compose_video_single_video_no_audio_no_bgm(self, service, tmp_path):
        """测试：单个视频，无音频，无背景音乐"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        output_path = tmp_path / "output.mp4"
        
        # Mock shutil.move
        with patch('shutil.move') as mock_move:
            result = service.compose_video(
                [str(video_file)],
                output_path=str(output_path)
            )
        
        assert result == str(output_path)
        mock_move.assert_called_once()
    
    def test_compose_video_with_concat(self, service, tmp_path):
        """测试：多个视频拼接"""
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        output_path = tmp_path / "output.mp4"
        
        # Mock concat_videos
        with patch.object(service, 'concat_videos', return_value=str(output_path)):
            with patch('shutil.move'):
                result = service.compose_video(
                    [str(video1), str(video2)],
                    output_path=str(output_path)
                )
        
        assert result == str(output_path)
    
    def test_compose_video_with_audio(self, service, tmp_path):
        """测试：合成视频和音频"""
        video_file = tmp_path / "video.mp4"
        audio_file = tmp_path / "audio.mp3"
        video_file.write_text("fake video")
        audio_file.write_text("fake audio")
        output_path = tmp_path / "output.mp4"
        
        # Mock sync_audio_video
        with patch.object(service, 'sync_audio_video', return_value=str(output_path)):
            with patch('shutil.move'):
                result = service.compose_video(
                    [str(video_file)],
                    audio_files=[str(audio_file)],
                    output_path=str(output_path)
                )
        
        assert result == str(output_path)
    
    def test_compose_video_with_bgm(self, service, tmp_path):
        """测试：添加背景音乐"""
        video_file = tmp_path / "video.mp4"
        bgm_file = tmp_path / "bgm.mp3"
        video_file.write_text("fake video")
        bgm_file.write_text("fake bgm")
        output_path = tmp_path / "output.mp4"
        
        # Mock add_bgm
        with patch.object(service, 'add_bgm', return_value=str(output_path)):
            result = service.compose_video(
                [str(video_file)],
                bgm_path=str(bgm_file),
                output_path=str(output_path)
            )
        
        assert result == str(output_path)
    
    def test_get_duration_success(self, service, tmp_path):
        """测试：成功获取时长"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        
        # Mock subprocess.run
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="10.5\n"
            )
            
            duration = service._get_duration(str(video_file))
        
        assert duration == 10.5
    
    def test_get_duration_error(self, service, tmp_path):
        """测试：获取时长失败时返回 0"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        
        # Mock subprocess.run 抛出异常
        with patch('subprocess.run', side_effect=Exception("FFprobe error")):
            duration = service._get_duration(str(video_file))
        
        assert duration == 0.0
    
    def test_concat_audio_success(self, service, tmp_path):
        """测试：成功拼接音频"""
        audio1 = tmp_path / "audio1.mp3"
        audio2 = tmp_path / "audio2.mp3"
        audio1.write_text("fake audio 1")
        audio2.write_text("fake audio 2")
        output_path = tmp_path / "output.mp3"
        
        # Mock subprocess.run
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result = service._concat_audio(
                [str(audio1), str(audio2)],
                str(output_path)
            )
        
        assert result == str(output_path)
        mock_run.assert_called_once()


class TestGlobalVideoComposer:
    """全局视频合成服务测试类"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        cleanup_video_composer()
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        cleanup_video_composer()
    
    def test_get_video_composer_singleton(self):
        """测试：全局服务实例是单例"""
        service1 = get_video_composer()
        service2 = get_video_composer()
        
        assert service1 is service2
    
    def test_cleanup_video_composer(self):
        """测试：清理全局服务实例"""
        service = get_video_composer()
        assert service is not None
        
        cleanup_video_composer()
        
        service2 = get_video_composer()
        assert service2 is not service


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
