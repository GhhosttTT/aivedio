"""Deterministic draft media generation for end-to-end pipeline validation."""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw


def draft_fallback_enabled() -> bool:
    return os.getenv("ENABLE_DRAFT_MEDIA_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}


class DraftMediaService:
    """Create low-fidelity assets when production providers are unavailable.

    These outputs are intentionally plain and deterministic. They keep the
    pipeline testable without pretending to be final-quality generation.
    """

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        width: int = 1024,
        height: int = 576,
        scene_number: Optional[int] = None,
    ) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256((prompt or "draft").encode("utf-8")).digest()
        base = tuple(40 + b % 140 for b in digest[:3])
        accent = tuple(100 + b % 120 for b in digest[3:6])

        img = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(img)

        for i in range(12):
            x0 = int(width * i / 12)
            x1 = int(width * (i + 1) / 12)
            shade = tuple(min(255, max(0, c + (i - 6) * 6)) for c in base)
            draw.rectangle([x0, 0, x1, height], fill=shade)

        horizon = int(height * 0.62)
        draw.rectangle([0, horizon, width, height], fill=tuple(max(0, c - 28) for c in base))
        radius = max(60, min(width, height) // 5)
        cx = int(width * (0.32 + (digest[6] / 255) * 0.36))
        cy = int(height * 0.35)
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=accent)

        panel_h = max(72, height // 7)
        draw.rectangle([0, height - panel_h, width, height], fill=(10, 12, 20))
        label = f"DRAFT SCENE {scene_number}" if scene_number else "DRAFT SCENE"
        draw.text((32, height - panel_h + 24), label, fill=(245, 245, 245))
        draw.text((32, height - panel_h + 48), "Provider unavailable; pipeline fallback asset", fill=(180, 190, 205))

        img.save(output_path)
        return output_path

    def estimate_dialogue_duration(self, text: str, minimum: float = 2.2, maximum: float = 12.0) -> float:
        text = (text or "").strip()
        if not text:
            return minimum
        # Chinese short-drama narration is usually readable around 4 chars/sec.
        return max(minimum, min(maximum, math.ceil(len(text) / 4.0 * 10) / 10.0))

    def generate_silent_audio(self, text: str, output_path: str, duration: Optional[float] = None) -> tuple[str, float]:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        duration = duration or self.estimate_dialogue_duration(text)
        cmd = [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            "-y",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_path, duration

    def generate_video_from_image(self, image_path: str, output_path: str, duration: float = 4.0, fps: int = 24) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-loop",
            "1",
            "-i",
            image_path,
            "-t",
            f"{duration:.3f}",
            "-vf",
            f"scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-y",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_path


_draft_media_service: Optional[DraftMediaService] = None


def get_draft_media_service() -> DraftMediaService:
    global _draft_media_service
    if _draft_media_service is None:
        _draft_media_service = DraftMediaService()
    return _draft_media_service
