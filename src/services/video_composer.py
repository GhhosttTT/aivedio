"""
视频合成服务（Video Composer）

负责视频拼接、音视频同步、背景音乐添加、视频合成
"""

import json
import os
import math
import subprocess
import tempfile
from typing import List, Optional, Tuple
from pathlib import Path
from uuid import uuid4

from src.config import settings
from src.utils.logger import logger


class VideoComposerError(Exception):
    """视频合成错误"""
    pass


def _is_high_bit_depth_pixel_format(pixel_format: str) -> bool:
    """识别 FFmpeg 常见的 10/12/14-bit 像素格式。"""
    normalized = str(pixel_format or "").strip().lower()
    return any(token in normalized for token in ("p10", "p12", "p14", "10le", "12le", "14le"))


def _provider_output_pixel_format(pixel_format: str, *, high_bit_depth: bool) -> str:
    """Keep provider chroma fidelity while normalizing to a playable format."""
    normalized = str(pixel_format or "").strip().lower()
    depth = "10le" if high_bit_depth else ""
    if "444" in normalized:
        return f"yuv444p{depth}"
    if "422" in normalized:
        return f"yuv422p{depth}"
    return f"yuv420p{depth}"


class VideoComposer:
    """视频合成服务"""
    
    def __init__(self):
        """
        初始化视频合成服务
        """
        logger.info("视频合成服务初始化完成")

    @staticmethod
    def _require_output_file(output_path: str | Path, operation: str) -> None:
        """Fail closed when an external media command did not publish output."""
        path = Path(output_path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise VideoComposerError(
                f"{operation} did not produce an output file: {path}"
            ) from exc
        if not path.is_file() or size <= 0:
            raise VideoComposerError(
                f"{operation} produced an empty output file: {path}"
            )
    
    def concat_videos(
        self,
        video_files: List[str],
        output_path: Optional[str] = None,
        preserve_audio: bool = False,
        preserve_provider_quality: bool = False,
        editing_plan: Optional[List[dict]] = None,
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

        # 验证所有文件存在
        for video_file in video_files:
            if not os.path.exists(video_file):
                raise FileNotFoundError(f"视频文件不存在: {video_file}")

        if len(video_files) == 1 and not output_path:
            logger.info("只有一个视频文件，无需拼接")
            return video_files[0]

        logger.info(f"开始拼接视频: {len(video_files)} 个文件")

        
        try:
            # 确定输出路径
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / "concatenated.mp4")

            provider_geometry = (
                self._probe_provider_geometry(video_files[0])
                if preserve_provider_quality else None
            )

            if len(video_files) == 1:
                cmd = self._build_single_video_normalize_cmd(
                    video_files[0], output_path, preserve_audio, preserve_provider_quality,
                    provider_geometry,
                )
            else:
                cmd = self._build_video_concat_cmd(
                    video_files, output_path, preserve_audio, preserve_provider_quality,
                    provider_geometry, editing_plan,
                )
            
            logger.debug(f"FFmpeg 命令: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            self._require_output_file(output_path, "视频拼接")
            
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
            if not all(math.isfinite(value) and value > 0 for value in (video_duration, audio_duration)):
                raise ValueError("Cannot synchronize media with unreadable durations")
            frame_tolerance = 1.0 / max(int(settings.GENERATION_VIDEO_OUTPUT_FPS), 1)
            if audio_duration > video_duration + frame_tolerance:
                raise ValueError("Dialogue is longer than the video; regenerate or split the scene")
            
            # 使用 FFmpeg 替换音轨
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",  # 视频流直接复制
                "-c:a", "aac",   # 音频重新编码为 AAC
                "-map", "0:v:0", # 使用第一个输入的视频流
                "-map", "1:a:0", # 使用第二个输入的音频流
                "-af", "apad,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true",
                "-t", f"{video_duration:.6f}",
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
            self._require_output_file(output_path, "音视频同步")
            
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

            video_duration = self._get_duration(video_path)
            if not math.isfinite(video_duration) or video_duration <= 0:
                raise ValueError("Cannot add background music to a video with unreadable duration")

            # Duck the music under dialogue/effects instead of relying on a
            # fixed mix ratio. This keeps speech intelligible when the
            # provider returns native audio and avoids clipping on loud cuts.
            bgm_volume = max(0.0, min(1.0, float(bgm_volume)))
            source_has_audio = self.has_audio_stream(video_path)
            if source_has_audio:
                audio_filter = (
                    f"[0:a]aresample=48000,volume=1.0[dialogue];"
                    f"[1:a]aresample=48000,volume={bgm_volume}[music];"
                    "[music][dialogue]sidechaincompress=threshold=0.08:ratio=8:"
                    "attack=20:release=250:makeup=1[ducked];"
                    "[dialogue][ducked]amix=inputs=2:duration=longest:"
                    "dropout_transition=2:normalize=0,alimiter=limit=0.95,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[aout]"
                )
            else:
                audio_filter = (
                    f"[1:a]aresample=48000,volume={bgm_volume},"
                    "alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[aout]"
                )
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-stream_loop", "-1",
                "-i", bgm_path,
                "-filter_complex",
                audio_filter,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-t", f"{video_duration:.6f}",
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
            self._require_output_file(output_path, "背景音乐添加")
            
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

        for video_file in video_files:
            if not os.path.exists(video_file):
                raise FileNotFoundError(f"视频文件不存在: {video_file}")
        for audio_file in audio_files or []:
            if not os.path.exists(audio_file):
                raise FileNotFoundError(f"音频文件不存在: {audio_file}")
        if bgm_path and not os.path.exists(bgm_path):
            raise FileNotFoundError(f"背景音乐文件不存在: {bgm_path}")
        
        logger.info(
            f"开始合成视频: videos={len(video_files)}, "
            f"audios={len(audio_files) if audio_files else 0}, "
            f"bgm={'是' if bgm_path else '否'}"
        )

        temporary_paths: list[Path] = []
        
        try:
            compose_token = uuid4().hex
            # 确定输出路径
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / f"composed-{compose_token}.mp4")
            else:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            def temporary_output(suffix: str) -> str:
                path = Path(output_path).parent / f".{Path(output_path).stem}.{compose_token}.{suffix}"
                temporary_paths.append(path)
                return str(path)
            
            current_video = None
            
            # 步骤 1：拼接视频
            if len(video_files) > 1:
                logger.info("步骤 1/3: 拼接视频")
                # Native Seedance audio is the authoritative track when no
                # separate dialogue timeline was supplied.  Do not silently
                # strip it during concat; if a later scene lacks audio,
                # concat_videos will synthesize a matching silent segment.
                preserve_native_audio = not audio_files and any(
                    self.has_audio_stream(video_file) for video_file in video_files
                )
                current_video = self.concat_videos(
                    video_files,
                    temporary_output("concat.mp4"),
                    preserve_audio=preserve_native_audio,
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
                        temporary_output("audio.mp3")
                    )
                else:
                    merged_audio = audio_files[0]
                
                current_video = self.sync_audio_video(
                    current_video,
                    merged_audio,
                    temporary_output("synced.mp4")
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
                # 没有背景音乐，安全复制到输出路径并保留源文件
                if current_video != output_path:
                    import shutil
                    # Keep the scene source available for review, repair, and
                    # future re-composition; finalization must not consume it.
                    finalization_path = Path(output_path).with_name(
                        f".{Path(output_path).name}.compose.tmp"
                    )
                    try:
                        shutil.copyfile(current_video, finalization_path)
                        os.replace(finalization_path, output_path)
                    finally:
                        finalization_path.unlink(missing_ok=True)

            self._require_output_file(output_path, "视频合成")
            
            logger.info(f"视频合成成功: {output_path}")
            
            return output_path
            
        except Exception as e:
            error_msg = f"视频合成失败: {e}"
            logger.error(error_msg)
            raise VideoComposerError(error_msg) from e
        finally:
            for temporary_path in temporary_paths:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.warning("清理合成临时文件失败: %s (%s)", temporary_path, cleanup_error)
    
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

    def has_audio_stream(self, video_path: str) -> bool:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", video_path],
                capture_output=True,
                text=True,
                check=True,
            )
            return bool(result.stdout.strip())
        except Exception as exc:
            logger.warning("Cannot inspect audio stream for %s: %s", video_path, exc)
            return False

    def _build_single_video_normalize_cmd(
        self,
        video_path: str,
        output_path: str,
        preserve_audio: bool = False,
        preserve_provider_quality: bool = False,
        target_geometry: tuple[int, int, float, str] | None = None,
    ) -> list[str]:
        command = [
            "ffmpeg",
            "-i", os.path.abspath(video_path),
            "-vf", self._production_video_filter(preserve_provider_quality, target_geometry),
            "-map", "0:v:0",
            *self._production_video_encode_args(preserve_audio, preserve_provider_quality, target_geometry),
            "-y",
            output_path,
        ]
        if preserve_audio:
            command[command.index("-y"):command.index("-y")] = [
                "-map", "0:a:0",
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true",
            ]
        return command

    def _build_video_concat_cmd(
        self,
        video_files: List[str],
        output_path: str,
        preserve_audio: bool = False,
        preserve_provider_quality: bool = False,
        target_geometry: tuple[int, int, float, str] | None = None,
        editing_plan: Optional[List[dict]] = None,
    ) -> list[str]:
        if editing_plan:
            return self._build_video_transition_cmd(
                video_files,
                output_path,
                preserve_audio,
                preserve_provider_quality,
                target_geometry,
                editing_plan,
            )
        inputs: list[str] = []
        filter_parts: list[str] = []
        labels: list[str] = []

        for index, video_file in enumerate(video_files):
            inputs.extend(["-i", os.path.abspath(video_file)])
            label = f"v{index}"
            labels.append(f"[{label}]")
            if preserve_audio:
                video_filter = self._production_video_filter(preserve_provider_quality, target_geometry)
                if self.has_audio_stream(video_file):
                    audio_filter = (
                        f"[{index}:a]aresample=48000,aformat=sample_rates=48000:"
                        f"channel_layouts=stereo,asetpts=PTS-STARTPTS[{label}a]"
                    )
                else:
                    duration = self._get_duration(video_file)
                    if not math.isfinite(duration) or duration <= 0:
                        raise ValueError(f"Cannot synthesize silent audio for unreadable video: {video_file}")
                    audio_filter = (
                        f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                        f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[{label}a]"
                    )
                filter_parts.append(
                    f"[{index}:v]{video_filter}[{label}v];{audio_filter}"
                )
            else:
                filter_parts.append(f"[{index}:v]{self._production_video_filter(preserve_provider_quality, target_geometry)}[{label}]")

        if preserve_audio:
            video_labels = "".join(f"[{index}v]" for index in range(len(video_files)))
            audio_labels = "".join(f"[{index}a]" for index in range(len(video_files)))
            filter_parts.append(
                video_labels + audio_labels
                + f"concat=n={len(video_files)}:v=1:a=1[vout][aout_raw]"
            )
            filter_parts.append(
                "[aout_raw]loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[aout]"
            )
        else:
            filter_parts.append("".join(labels) + f"concat=n={len(video_files)}:v=1:a=0[vout]")

        command = [
            "ffmpeg",
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vout]",
            *self._production_video_encode_args(preserve_audio, preserve_provider_quality, target_geometry),
            "-y",
            output_path,
        ]
        if preserve_audio:
            command[command.index("-y"):command.index("-y")] = ["-map", "[aout]"]
        return command

    def _build_video_transition_cmd(
        self,
        video_files: List[str],
        output_path: str,
        preserve_audio: bool,
        preserve_provider_quality: bool,
        target_geometry: tuple[int, int, float, str] | None,
        editing_plan: List[dict],
    ) -> list[str]:
        """Build a timeline-aware concat command from the reviewed edit plan."""
        if len(editing_plan) != len(video_files):
            raise ValueError("Editing plan must contain one entry per video input")
        durations = [self._get_duration(path) for path in video_files]
        if any(not math.isfinite(value) or value <= 0 for value in durations):
            raise ValueError("Cannot apply editing transitions to unreadable video durations")

        inputs: list[str] = []
        filters: list[str] = []
        video_labels: list[str] = []
        audio_labels: list[str] = []
        for index, video_file in enumerate(video_files):
            inputs.extend(["-i", os.path.abspath(video_file)])
            video_label = f"tv{index}"
            video_labels.append(video_label)
            filters.append(
                f"[{index}:v]{self._production_video_filter(preserve_provider_quality, target_geometry)}"
                f",setpts=PTS-STARTPTS[{video_label}]"
            )
            if preserve_audio:
                audio_label = f"ta{index}"
                audio_labels.append(audio_label)
                if self.has_audio_stream(video_file):
                    filters.append(
                        f"[{index}:a]aresample=48000,aformat=sample_rates=48000:"
                        f"channel_layouts=stereo,asetpts=PTS-STARTPTS[{audio_label}]"
                    )
                else:
                    filters.append(
                        f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                        f"atrim=duration={durations[index]:.6f},asetpts=PTS-STARTPTS[{audio_label}]"
                    )

        current_video = video_labels[0]
        current_audio = audio_labels[0] if preserve_audio else None
        elapsed = durations[0]
        for index in range(1, len(video_files)):
            transition = editing_plan[index].get("transition", {})
            mode = transition.get("video")
            requested = float(transition.get("duration_seconds", 0.0) or 0.0)
            # A 1ms xfade is effectively a hard cut, while keeping one stable
            # filter graph for mixed hard-cut/crossfade timelines.
            fade_duration = requested if mode == "crossfade" else 0.001
            fade_duration = max(0.001, min(fade_duration, 0.12, durations[index - 1], durations[index]))
            offset = max(0.0, elapsed - fade_duration)
            next_video = f"txv{index}"
            filters.append(
                f"[{current_video}][{video_labels[index]}]xfade=transition=fade:"
                f"duration={fade_duration:.6f}:offset={offset:.6f}[{next_video}]"
            )
            current_video = next_video
            if preserve_audio:
                next_audio = f"txa{index}"
                audio_fade_duration = self._transition_audio_overlap(editing_plan[index])
                audio_fade_duration = max(
                    0.001,
                    min(audio_fade_duration, durations[index - 1], durations[index]),
                )
                filters.append(
                    f"[{current_audio}][{audio_labels[index]}]acrossfade="
                    f"d={audio_fade_duration:.6f}:c1=tri:c2=tri[{next_audio}]"
                )
                current_audio = next_audio
            elapsed += durations[index] - fade_duration

        if preserve_audio and current_audio:
            normalized_audio = "ta_normalized"
            filters.append(
                f"[{current_audio}]apad,atrim=duration={elapsed:.6f},"
                f"asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true[{normalized_audio}]"
            )
            current_audio = normalized_audio

        command = [
            "ffmpeg", *inputs,
            "-filter_complex", ";".join(filters),
            "-map", f"[{current_video}]",
            *self._production_video_encode_args(preserve_audio, preserve_provider_quality, target_geometry),
            "-y", output_path,
        ]
        if preserve_audio and current_audio:
            command[command.index("-y"):command.index("-y")] = ["-map", f"[{current_audio}]"]
        return command

    def _production_video_filter(
        self,
        preserve_provider_quality: bool = False,
        target_geometry: tuple[int, int, float, str] | None = None,
    ) -> str:
        if preserve_provider_quality and target_geometry:
            width, height, source_fps, pixel_format = target_geometry
            fps = max(1, round(float(source_fps)))
        else:
            width = int(settings.GENERATION_WIDTH)
            height = int(settings.GENERATION_HEIGHT)
            fps = int(settings.GENERATION_VIDEO_OUTPUT_FPS)
            pixel_format = "yuv420p10le" if preserve_provider_quality else "yuv420p"
        high_bit_depth = preserve_provider_quality and (
            not target_geometry or _is_high_bit_depth_pixel_format(pixel_format)
        )
        output_pixel_format = _provider_output_pixel_format(pixel_format, high_bit_depth=high_bit_depth)
        fit_mode = str(getattr(settings, "GENERATION_VIDEO_FRAME_FIT_MODE", "cover")).strip().lower()
        if fit_mode == "contain":
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            )
        else:
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,"
            )
        return (
            framing +
            "setsar=1,"
            f"fps={fps},"
            + f"format={output_pixel_format}"
        )

    @staticmethod
    def _probe_provider_geometry(video_path: str) -> tuple[int, int, float, str] | None:
        """Use the first provider clip as the final composition contract."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,avg_frame_rate,pix_fmt",
                    "-of", "json", video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            probe = json.loads(result.stdout)
            streams = probe.get("streams") or []
            if not streams:
                return None
            stream = streams[0]
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            frame_rate = str(stream.get("avg_frame_rate") or "0/1")
            numerator, denominator = (frame_rate.split("/", 1) + ["1"])[:2]
            fps = float(numerator) / max(float(denominator), 1.0)
            pixel_format = str(stream.get("pix_fmt") or "")
            if width <= 0 or height <= 0 or fps <= 0 or not pixel_format:
                return None
            return width, height, fps, pixel_format
        except (OSError, ValueError, TypeError, ZeroDivisionError, subprocess.SubprocessError):
            logger.debug("Cannot probe provider composition geometry for %s", video_path)
            return None

    def _production_video_encode_args(
        self,
        preserve_audio: bool = False,
        preserve_provider_quality: bool = False,
        target_geometry: tuple[int, int, float, str] | None = None,
    ) -> list[str]:
        high_bit_depth = preserve_provider_quality and (
            not target_geometry
            or _is_high_bit_depth_pixel_format(target_geometry[3])
        )
        output_pixel_format = _provider_output_pixel_format(
            target_geometry[3] if target_geometry else "yuv420p10le",
            high_bit_depth=high_bit_depth,
        )
        args = [
            "-c:v", "libx265" if high_bit_depth else "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", output_pixel_format,
            "-movflags", "+faststart",
        ]
        if high_bit_depth:
            args.extend(["-tag:v", "hvc1"])
        args.extend(["-c:a", "aac"] if preserve_audio else ["-an"])
        return args

    def has_high_bit_depth(self, video_path: str) -> bool:
        """Return whether a video carries a 10/12-bit pixel format."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=pix_fmt", "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            pixel_format = result.stdout.strip().lower()
            return any(token in pixel_format for token in ("p10", "p12", "10le", "12le"))
        except Exception as exc:
            logger.debug("Could not inspect pixel depth for {}: {}", video_path, exc)
            return False

    def has_provider_chroma_fidelity(self, video_path: str) -> bool:
        """Return whether a provider clip needs 4:2:2/4:4:4 or high-bit preservation."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=pix_fmt",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            pixel_format = result.stdout.strip().lower()
            return (
                _is_high_bit_depth_pixel_format(pixel_format)
                or "422" in pixel_format
                or "444" in pixel_format
            )
        except Exception as exc:
            logger.debug("Could not inspect provider chroma format for {}: {}", video_path, exc)
            return False
    
    def compose_scene_audio(
        self,
        segments: List[Tuple[Optional[str], float]],
        output_path: str,
        editing_plan: Optional[List[dict]] = None,
    ) -> str:
        """Preserve scene timing and mirror reviewed transition overlaps."""
        if not segments:
            raise ValueError("Scene audio segments cannot be empty")
        frame_tolerance = 1.0 / max(int(settings.GENERATION_VIDEO_OUTPUT_FPS), 1)
        for audio_path, duration in segments:
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("Scene timeline duration must be finite and positive")
            if audio_path:
                if not Path(audio_path).is_file():
                    raise FileNotFoundError(f"Scene audio file does not exist: {audio_path}")
                audio_duration = self._get_duration(audio_path)
                if not math.isfinite(audio_duration) or audio_duration <= 0:
                    raise ValueError("Scene audio duration is unreadable")
                if audio_duration > duration + frame_tolerance:
                    raise ValueError("Dialogue is longer than its scene; regenerate or split the scene")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="scene_audio_", dir=output.parent) as temp_dir:
            aligned_paths = []
            for index, (audio_path, duration) in enumerate(segments):
                aligned = str(Path(temp_dir) / f"scene_{index:05d}.wav")
                source = ["-i", str(audio_path)] if audio_path else [
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                ]
                cmd = [
                    "ffmpeg", *source, "-map", "0:a:0", "-af", "apad",
                    "-t", f"{duration:.6f}", "-ar", "48000", "-ac", "2",
                    "-c:a", "pcm_s16le", "-y", aligned,
                ]
                try:
                    subprocess.run(cmd, capture_output=True, text=True, check=True)
                except subprocess.CalledProcessError as exc:
                    raise VideoComposerError(f"Scene audio alignment failed: {exc.stderr}") from exc
                aligned_paths.append(aligned)
            transition_durations = None
            if editing_plan:
                if len(editing_plan) != len(aligned_paths):
                    raise ValueError("Editing plan must contain one entry per audio segment")
                transition_durations = [
                    self._transition_audio_overlap(editing_plan[index])
                    for index in range(1, len(editing_plan))
                ]
            return self._concat_audio(
                aligned_paths,
                str(output),
                transition_durations=transition_durations,
            )

    @staticmethod
    def _transition_audio_overlap(plan: dict) -> float:
        transition = plan.get("transition", {}) if isinstance(plan, dict) else {}
        if plan.get("audio_strategy") == "dialogue_pre_lap":
            try:
                return max(
                    0.001,
                    min(0.12, float(settings.GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS)),
                )
            except (TypeError, ValueError):
                return 0.08
        mode = transition.get("video")
        if mode == "crossfade":
            try:
                return max(0.001, min(0.12, float(transition.get("duration_seconds", 0.0) or 0.0)))
            except (TypeError, ValueError):
                return 0.001
        return 0.001 if mode in {"hard_cut", "none"} else 0.0

    def _concat_audio(
        self,
        audio_files: List[str],
        output_path: str,
        transition_durations: Optional[List[float]] = None,
    ) -> str:
        """
        拼接多个音频文件
        
        Args:
            audio_files: 音频文件列表
            output_path: 输出路径
            
        Returns:
            拼接后的音频文件路径
        """
        concat_list_path = None
        try:
            # 创建文件列表
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix="_concat_list.txt",
                dir=Path(output_path).parent, delete=False,
            ) as f:
                concat_list_path = Path(f.name)
                for audio_file in audio_files:
                    abs_path = Path(audio_file).resolve().as_posix().replace("'", "'\\''")
                    f.write(f"file '{abs_path}'\n")
            
            if transition_durations:
                if len(transition_durations) != len(audio_files) - 1:
                    raise ValueError("Transition durations must cover each audio boundary")
                inputs = [argument for audio_file in audio_files for argument in ("-i", audio_file)]
                filters = []
                current = "0:a"
                for index, duration in enumerate(transition_durations, start=1):
                    if not math.isfinite(float(duration)) or not 0 < float(duration) <= 0.12:
                        raise ValueError("Audio transition duration must be finite and within 0-0.12 seconds")
                    output_label = f"af{index}"
                    filters.append(
                        f"[{current}][{index}:a]acrossfade=d={float(duration):.6f}:"
                        f"c1=tri:c2=tri[{output_label}]"
                    )
                    current = output_label
                cmd = [
                    "ffmpeg", *inputs, "-filter_complex", ";".join(filters),
                    "-map", f"[{current}]", "-c:a", "pcm_s16le", "-y", output_path,
                ]
            else:
                # Plain concat remains stream-copy based for the common path.
                cmd = [
                    "ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
                    "-c", "copy", "-y", output_path,
                ]
            
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            return output_path
            
        except Exception as e:
            raise VideoComposerError(f"音频拼接失败: {e}") from e
        finally:
            if concat_list_path:
                concat_list_path.unlink(missing_ok=True)
    
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
