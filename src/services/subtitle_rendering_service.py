"""Render translated subtitles onto a clean master video."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from src.config import settings


class SubtitleRenderingError(RuntimeError):
    """Raised when multilingual subtitle rendering fails."""


RTL_LANGUAGES = {"ar"}


@dataclass(frozen=True)
class RenderedSubtitleVideo:
    language: str
    subtitle_path: str
    video_path: str


class SubtitleRenderingService:
    """Burn translated SRT subtitles into per-language MP4 files."""

    def render_all(
        self,
        clean_video_path: str,
        translated_subtitle_dir: str,
        output_dir: str,
        target_languages: Iterable[str],
    ) -> Dict[str, RenderedSubtitleVideo]:
        clean_video = Path(clean_video_path)
        if not clean_video.exists():
            raise FileNotFoundError(f"clean master video does not exist: {clean_video_path}")

        subtitle_dir = Path(translated_subtitle_dir)
        if not subtitle_dir.exists():
            raise FileNotFoundError(f"translated subtitle dir does not exist: {translated_subtitle_dir}")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        results: Dict[str, RenderedSubtitleVideo] = {}
        for language in target_languages:
            code = language.strip().lower()
            if not code:
                continue
            subtitle_path = subtitle_dir / f"{code}.srt"
            if not subtitle_path.exists():
                raise SubtitleRenderingError(f"missing translated subtitle for {code}: {subtitle_path}")

            video_path = out_dir / f"{code}.mp4"
            self.render_one(str(clean_video), str(subtitle_path), str(video_path), code)
            results[code] = RenderedSubtitleVideo(
                language=code,
                subtitle_path=str(subtitle_path),
                video_path=str(video_path),
            )

        if not results:
            raise SubtitleRenderingError("no target languages were rendered")

        manifest_path = out_dir / "rendered_videos.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "clean_video_path": str(clean_video),
                    "videos": {language: asdict(result) for language, result in results.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return results

    def render_one(
        self,
        clean_video_path: str,
        subtitle_path: str,
        output_path: str,
        language: str,
    ) -> str:
        if not shutil.which("ffmpeg"):
            raise SubtitleRenderingError("ffmpeg executable not found")

        filter_expr = self._build_subtitle_filter(subtitle_path, language)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            clean_video_path,
            "-vf",
            filter_expr,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "copy",
            output_path,
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.SUBTITLE_RENDER_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise SubtitleRenderingError(
                f"ffmpeg subtitle rendering failed with code {completed.returncode}: {completed.stderr}"
            )
        if not Path(output_path).exists():
            raise SubtitleRenderingError(f"ffmpeg did not create rendered video: {output_path}")
        return output_path

    def _build_subtitle_filter(self, subtitle_path: str, language: str) -> str:
        escaped_path = self._escape_subtitle_path(subtitle_path)
        style_parts: List[str] = [
            f"FontName={settings.SUBTITLE_RENDER_FONT}",
            f"FontSize={settings.SUBTITLE_RENDER_FONT_SIZE}",
            "PrimaryColour=&H00FFFFFF",
            "OutlineColour=&H00000000",
            "BorderStyle=1",
            "Outline=2",
            "Shadow=0",
            "Alignment=2",
            f"MarginV={settings.SUBTITLE_RENDER_MARGIN_V}",
        ]
        if language in RTL_LANGUAGES:
            style_parts.extend(["Encoding=1", "Alignment=2"])
        style = ",".join(style_parts)
        return f"subtitles='{escaped_path}':force_style='{style}'"

    def _escape_subtitle_path(self, subtitle_path: str) -> str:
        path = Path(subtitle_path).resolve().as_posix()
        return path.replace(":", "\\:").replace("'", "\\'")
