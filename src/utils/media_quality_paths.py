"""Stable, collision-free paths for media quality evidence sidecars."""

from __future__ import annotations

from pathlib import Path


def _legacy_quality_path(media_path: str | Path) -> Path:
    return Path(media_path).with_suffix(".quality.json")


def audio_quality_report_path(media_path: str | Path) -> Path:
    path = Path(media_path)
    return path.with_name(f"{path.stem}.audio.quality.json")


def subtitle_quality_report_path(media_path: str | Path) -> Path:
    path = Path(media_path)
    return path.with_name(f"{path.stem}.subtitle.quality.json")


def existing_audio_quality_report_path(media_path: str | Path) -> Path:
    preferred = audio_quality_report_path(media_path)
    return preferred if preferred.is_file() else _legacy_quality_path(media_path)


def existing_subtitle_quality_report_path(media_path: str | Path) -> Path:
    preferred = subtitle_quality_report_path(media_path)
    return preferred if preferred.is_file() else _legacy_quality_path(media_path)
