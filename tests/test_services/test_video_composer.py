"""
视频合成服务单元测试

测试 VideoComposer 的核心功能
"""

import pytest
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace

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
    
    def test_concat_videos_single_file(self, service, tmp_path):
        """测试：单个视频文件时直接返回"""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"video")
        result = service.concat_videos([str(video_file)])
        
        assert result == str(video_file)
    
    def test_concat_videos_file_not_exists(self, service):
        """测试：视频文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError, match="视频文件不存在"):
            service.concat_videos(["nonexistent1.mp4", "nonexistent2.mp4"])

    def test_concat_videos_single_missing_file_does_not_bypass_validation(self, service):
        with pytest.raises(FileNotFoundError, match="视频文件不存在"):
            service.concat_videos(["missing-single.mp4"])
    
    def test_concat_videos_success(self, service, tmp_path):
        """测试：成功拼接视频"""
        # 创建临时视频文件
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        
        output_path = tmp_path / "output.mp4"
        
        # Mock duration, stream inspection, and ffmpeg.
        with patch.object(service, "_get_duration", return_value=10.0), patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result = service.concat_videos(
                [str(video1), str(video2)],
                str(output_path)
            )
        
        assert result == str(output_path)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "-filter_complex" in cmd
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "scale=768:1344:force_original_aspect_ratio=increase" in filter_complex
        assert "crop=768:1344:(iw-ow)/2:(ih-oh)/2" in filter_complex
        assert "fps=24" in filter_complex
        assert "format=yuv420p" in filter_complex
        assert "concat=n=2:v=1:a=0" in filter_complex
        assert "-c:v" in cmd
        assert cmd[cmd.index("-c:v") + 1] == "libx264"
        assert "-movflags" in cmd
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

    def test_concat_videos_single_file_with_output_normalizes(self, service, tmp_path):
        """测试：单个视频有输出路径时也归一化为生产格式"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        output_path = tmp_path / "output.mp4"

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = service.concat_videos([str(video_file)], str(output_path))

        assert result == str(output_path)
        cmd = mock_run.call_args[0][0]
        assert "-vf" in cmd
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=768:1344:force_original_aspect_ratio=increase" in vf
        assert "crop=768:1344:(iw-ow)/2:(ih-oh)/2" in vf
        assert "fps=24" in vf
        assert "format=yuv420p" in vf
        assert "-an" in cmd

    def test_concat_videos_normalizes_single_native_audio(self, service, tmp_path):
        video_file = tmp_path / "video.mp4"
        output_path = tmp_path / "output.mp4"
        video_file.write_text("fake video")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            service.concat_videos([str(video_file)], str(output_path), preserve_audio=True)

        cmd = mock_run.call_args.args[0]
        assert "-map" in cmd
        assert "0:a:0" in cmd
        assert "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true" in cmd

    def test_concat_videos_can_preserve_native_audio(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        output_path = tmp_path / "output.mp4"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            service.concat_videos([str(video1), str(video2)], str(output_path), preserve_audio=True)
        cmd = mock_run.call_args.args[0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "concat=n=2:v=1:a=1[vout][aout_raw]" in filter_complex
        assert "[aout_raw]loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[aout]" in filter_complex
        assert "-map" in cmd
        assert "[aout]" in cmd
        assert "-an" not in cmd
        assert cmd[cmd.index("-c:a") + 1] == "aac"

    def test_concat_videos_fills_missing_audio_with_silence(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        output_path = tmp_path / "output.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")

        service.has_audio_stream = Mock(side_effect=[True, False])
        service._get_duration = Mock(return_value=2.75)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            service.concat_videos([str(video1), str(video2)], str(output_path), preserve_audio=True)
        cmd = mock_run.call_args.args[0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "[0:a]aresample=48000" in filter_complex
        assert "anullsrc=channel_layout=stereo:sample_rate=48000" in filter_complex
        assert "atrim=duration=2.750000" in filter_complex
        assert "concat=n=2:v=1:a=1[vout][aout_raw]" in filter_complex
        assert "[aout_raw]loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[aout]" in filter_complex

    def test_concat_videos_uses_reviewed_transition_plan(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        output_path = tmp_path / "output.mp4"
        service._get_duration = Mock(side_effect=[2.0, 3.0])
        with patch.object(service, "has_audio_stream", return_value=False), patch(
            "src.services.video_composer.subprocess.run"
        ) as run:
            service.concat_videos(
                [str(video1), str(video2)],
                str(output_path),
                editing_plan=[
                    {"scene_number": 1, "transition": {"video": "none", "duration_seconds": 0.0}},
                    {"scene_number": 2, "transition": {"video": "crossfade", "duration_seconds": 0.12}},
                ],
            )
        command = run.call_args.args[0]
        filter_graph = command[command.index("-filter_complex") + 1]
        assert "xfade=transition=fade" in filter_graph
        assert "duration=0.120000" in filter_graph
        assert "offset=1.880000" in filter_graph

    def test_concat_videos_applies_dialogue_prelap_to_audio_only(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        output_path = tmp_path / "output.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        service._get_duration = Mock(side_effect=[2.0, 2.0])
        service.has_audio_stream = Mock(return_value=True)
        with patch("src.services.video_composer.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            service.concat_videos(
                [str(video1), str(video2)],
                str(output_path),
                preserve_audio=True,
                editing_plan=[
                    {"scene_number": 1, "audio_strategy": "start_at_zero", "transition": {"video": "none", "duration_seconds": 0.0}},
                    {"scene_number": 2, "audio_strategy": "dialogue_pre_lap", "transition": {"video": "hard_cut", "duration_seconds": 0.0}},
                ],
            )
        command = run.call_args.args[0]
        filter_graph = command[command.index("-filter_complex") + 1]
        assert "xfade=transition=fade:duration=0.001000" in filter_graph
        assert "acrossfade=d=0.080000" in filter_graph
        assert "apad,atrim=duration=3.999000" in filter_graph

    def test_concat_videos_preserves_high_bit_depth_when_requested(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        output_path = tmp_path / "output.mp4"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            service.concat_videos(
                [str(video1), str(video2)], str(output_path), preserve_provider_quality=True,
            )

        cmd = mock_run.call_args.args[0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "format=yuv420p10le" in filter_complex
        assert cmd[cmd.index("-c:v") + 1] == "libx265"
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"
        assert cmd[cmd.index("-tag:v") + 1] == "hvc1"

    @pytest.mark.parametrize("pixel_format,expected", [
        ("yuv420p10le", "yuv420p10le"),
        ("yuv422p12le", "yuv422p10le"),
        ("yuv444p14le", "yuv444p10le"),
    ])
    def test_provider_high_bit_depth_formats_are_preserved(self, service, pixel_format, expected):
        geometry = (1920, 1080, 24.0, pixel_format)

        video_filter = service._production_video_filter(True, geometry)
        encode_args = service._production_video_encode_args(False, True, geometry)

        assert f"format={expected}" in video_filter
        assert encode_args[encode_args.index("-c:v") + 1] == "libx265"
        assert encode_args[encode_args.index("-pix_fmt") + 1] == expected

    def test_provider_8_bit_format_stays_8_bit(self, service):
        geometry = (1920, 1080, 24.0, "yuv420p")

        video_filter = service._production_video_filter(True, geometry)
        encode_args = service._production_video_encode_args(False, True, geometry)

        assert "format=yuv420p10le" not in video_filter
        assert encode_args[encode_args.index("-c:v") + 1] == "libx264"
        assert encode_args[encode_args.index("-pix_fmt") + 1] == "yuv420p"

    @pytest.mark.parametrize("pixel_format,expected", [
        ("yuv444p", "yuv444p"),
        ("yuv444p10le", "yuv444p10le"),
        ("yuv422p10le", "yuv422p10le"),
    ])
    def test_provider_chroma_subsampling_is_preserved(self, service, pixel_format, expected):
        geometry = (1920, 1080, 24.0, pixel_format)

        video_filter = service._production_video_filter(True, geometry)
        encode_args = service._production_video_encode_args(False, True, geometry)

        assert f"format={expected}" in video_filter
        assert encode_args[encode_args.index("-pix_fmt") + 1] == expected

    def test_provider_chroma_fidelity_detects_8_bit_yuv444(self, service, monkeypatch):
        class Result:
            stdout = "yuv444p\n"

        monkeypatch.setattr("src.services.video_composer.subprocess.run", lambda *args, **kwargs: Result())
        assert service.has_provider_chroma_fidelity("provider.mov") is True

    def test_seedance_composition_preserves_provider_geometry_and_fps(self, service, tmp_path):
        video1 = tmp_path / "seedance-landscape.mp4"
        video2 = tmp_path / "seedance-landscape-2.mp4"
        output_path = tmp_path / "output.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                SimpleNamespace(
                    stdout='{"streams":[{"width":1920,"height":1080,"avg_frame_rate":"24/1","pix_fmt":"yuv420p"}]}'
                ),
                MagicMock(returncode=0),
            ]
            service.concat_videos(
                [str(video1), str(video2)], str(output_path),
                preserve_provider_quality=True,
            )

        cmd = mock_run.call_args.args[0]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        assert "scale=1920:1080:force_original_aspect_ratio=increase" in filter_complex
        assert "crop=1920:1080:(iw-ow)/2:(ih-oh)/2" in filter_complex
        assert "fps=24" in filter_complex
        assert "scale=768:1344" not in filter_complex
        assert cmd[cmd.index("-c:v") + 1] == "libx264"
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    
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
        
        # Mock duration, stream inspection, and ffmpeg.
        with patch.object(service, "_get_duration", return_value=10.0), patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result = service.add_bgm(
                str(video_file),
                str(bgm_file),
                str(output_path),
                bgm_volume=0.5
            )
        
        assert result == str(output_path)
        assert mock_run.call_count == 2  # ffprobe + ffmpeg
        command = mock_run.call_args_list[-1].args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        assert "sidechaincompress" in filter_complex
        assert "amix=inputs=2:duration=longest" in filter_complex
        assert "alimiter=limit=0.95" in filter_complex
        assert "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true" in filter_complex
        assert command[command.index("-stream_loop") + 1] == "-1"
        assert command[command.index("-t") + 1] == "10.000000"
        assert "-shortest" not in command
    
    def test_compose_video_empty_list(self, service):
        """测试：空视频列表时抛出异常"""
        with pytest.raises(ValueError, match="视频文件列表不能为空"):
            service.compose_video([])

    def test_compose_video_validates_all_media_inputs_before_processing(self, service, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"video")
        with pytest.raises(FileNotFoundError, match="音频文件不存在"):
            service.compose_video([str(video)], audio_files=[str(tmp_path / "missing.mp3")])
    
    def test_compose_video_single_video_no_audio_no_bgm(self, service, tmp_path):
        """测试：单个视频，无音频，无背景音乐"""
        video_file = tmp_path / "video.mp4"
        video_file.write_text("fake video")
        output_path = tmp_path / "output.mp4"
        
        result = service.compose_video(
            [str(video_file)],
            output_path=str(output_path)
        )
        
        assert result == str(output_path)
        assert output_path.read_text() == "fake video"
        assert video_file.read_text() == "fake video"
        assert not list(tmp_path.glob("*.compose.tmp"))
    
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

    def test_compose_video_uses_isolated_intermediate_paths(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")
        output_one = tmp_path / "output-one.mp4"
        output_two = tmp_path / "output-two.mp4"

        with patch.object(service, "has_audio_stream", return_value=False), patch.object(
            service, "concat_videos", return_value=str(video1)
        ) as concat:
            service.compose_video([str(video1), str(video2)], output_path=str(output_one))
            service.compose_video([str(video1), str(video2)], output_path=str(output_two))

        first_intermediate = concat.call_args_list[0].args[1]
        second_intermediate = concat.call_args_list[1].args[1]
        assert first_intermediate != second_intermediate
        assert "temp_concat.mp4" not in first_intermediate
        assert "temp_concat.mp4" not in second_intermediate
        assert not list(tmp_path.glob(".*.concat.mp4"))

    def test_compose_video_default_outputs_are_isolated(self, service, tmp_path, monkeypatch):
        video = tmp_path / "video.mp4"
        video.write_text("fake video")
        monkeypatch.chdir(tmp_path)

        first = service.compose_video([str(video)])
        second = service.compose_video([str(video)])

        assert first != second
        assert Path(first).is_file()
        assert Path(second).is_file()
        assert Path(first).read_text() == "fake video"
        assert Path(second).read_text() == "fake video"

    def test_compose_video_preserves_native_audio_without_external_dialogue(self, service, tmp_path):
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        output_path = tmp_path / "output.mp4"
        video1.write_text("fake video 1")
        video2.write_text("fake video 2")

        with patch.object(service, "has_audio_stream", return_value=True), patch.object(
            service, "concat_videos", return_value=str(output_path)
        ) as concat:
            with patch("shutil.move"):
                result = service.compose_video(
                    [str(video1), str(video2)],
                    output_path=str(output_path),
                )

        assert result == str(output_path)
        assert concat.call_args.kwargs["preserve_audio"] is True

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
