"""Technical publishability checks for generated mobile-drama covers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


def audit_cover(path: str | Path, *, expected_width: int, expected_height: int) -> dict[str, Any]:
    cover = Path(path)
    if not cover.is_file() or cover.stat().st_size <= 0:
        return {"status": "unavailable", "path": str(cover), "error": "cover file is missing or empty"}
    try:
        with Image.open(cover) as image:
            image = image.convert("RGB")
            width, height = image.size
            gray = image.convert("L")
            stats = ImageStat.Stat(gray)
            brightness = float(stats.mean[0])
            contrast = float(stats.stddev[0])
    except (OSError, ValueError):
        return {"status": "unavailable", "path": str(cover), "error": "cover is not a readable raster image"}
    issues = []
    if width != expected_width or height != expected_height:
        issues.append({"code": "cover_geometry_mismatch", "message": f"expected {expected_width}x{expected_height}, got {width}x{height}"})
    if brightness < 12:
        issues.append({"code": "cover_nearly_black", "message": f"cover brightness {brightness:.1f} is too low for a mobile thumbnail"})
    if brightness > 245:
        issues.append({"code": "cover_overexposed", "message": f"cover brightness {brightness:.1f} is too high for a mobile thumbnail"})
    if contrast < 14:
        issues.append({"code": "cover_low_contrast", "message": f"cover contrast {contrast:.1f} is too low for subject readability"})
    return {
        "status": "needs_review" if issues else "passed",
        "path": str(cover),
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 5) if height else None,
        "brightness": round(brightness, 3),
        "contrast": round(contrast, 3),
        "issues": issues,
    }
