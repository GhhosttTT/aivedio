"""Media operations for splitting one sequence-level generation into shots."""

from __future__ import annotations

import json
import shutil
import subprocess
import math
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from src.services.sequence_plan import SequenceSegment


class SequenceVideoError(RuntimeError):
    """Raised when a sequence cannot be split into valid shot assets."""


def _probe_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        duration = float(result.stdout.strip())
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def _source_pixel_format(path: Path) -> str | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=pix_fmt", "-of", "json", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            return False
        streams = payload.get("streams") or []
        if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
            return None
        pixel_format = str(streams[0].get("pix_fmt") or "").lower().strip()
        return pixel_format or None
    except (OSError, TypeError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return None


def _source_is_high_bit_depth(path: Path) -> bool:
    pixel_format = _source_pixel_format(path) or ""
    return any(token in pixel_format for token in ("p10", "p12", "10le", "12le"))


def _probe_stream_types(path: Path) -> set[str] | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}
    except (OSError, subprocess.SubprocessError):
        return None
def split_sequence_video(
    input_path: str | Path,
    segments: Iterable[SequenceSegment],
    output_paths: Iterable[str | Path],
) -> list[str]:
    """Split a generated sequence into atomic shot files.

    Each segment is re-encoded deliberately: this makes cut points accurate,
    keeps audio timestamps stable, and preserves the provider's bit depth for
    10/12-bit sources.
    The temporary file and atomic replace prevent a partially written shot from
    being published to the composition task.
    """
    source = Path(input_path)
    segment_list = list(segments)
    destination_list = [Path(path) for path in output_paths]
    if not source.is_file() or source.stat().st_size <= 0:
        raise SequenceVideoError(f"Sequence video is missing or empty: {source}")
    if not segment_list or len(segment_list) != len(destination_list):
        raise SequenceVideoError("Sequence segments and output paths must have the same non-zero length")
    if any(
        not all(
            math.isfinite(value)
            for value in (
                segment.start_seconds,
                segment.end_seconds,
                segment.duration_seconds,
            )
        )
        or segment.start_seconds < 0
        or segment.end_seconds <= segment.start_seconds
        or segment.duration_seconds <= 0
        for segment in segment_list
    ):
        raise SequenceVideoError("Sequence segments must have positive, non-overlapping time ranges")
    if any(
        current.end_seconds > following.start_seconds + 0.001
        for current, following in zip(segment_list, segment_list[1:])
    ):
        raise SequenceVideoError("Sequence segments must be ordered and non-overlapping")
    if not shutil.which("ffmpeg"):
        raise SequenceVideoError("ffmpeg is required to split a sequence video")
    if not shutil.which("ffprobe"):
        raise SequenceVideoError(
            "ffprobe is required to validate sequence duration and audio continuity"
        )

    outputs: list[str] = []
    prepared: list[tuple[Path, Path]] = []
    current_scene_number: int | str = "unknown"
    source_duration = _probe_duration(source)
    if source_duration is None:
        raise SequenceVideoError(
            "Could not determine generated source duration; refusing to split without timing evidence"
        )
    if any(segment.end_seconds > source_duration + 0.12 for segment in segment_list):
        raise SequenceVideoError(
            "Sequence segment extends beyond the generated source duration: "
            f"source={source_duration:.3f}s"
        )
    source_stream_types = _probe_stream_types(source)
    if source_stream_types is None:
        raise SequenceVideoError(
            "Could not inspect source stream types; refusing to split without audio continuity evidence"
        )
    source_has_audio = source_stream_types is not None and "audio" in source_stream_types
    source_pixel_format = _source_pixel_format(source) or ""
    high_bit_depth = any(token in source_pixel_format for token in ("p10", "p12", "10le", "12le"))
    if "444" in source_pixel_format:
        output_pixel_format = "yuv444p10le" if high_bit_depth else "yuv444p"
    elif "422" in source_pixel_format:
        output_pixel_format = "yuv422p10le" if high_bit_depth else "yuv422p"
    else:
        output_pixel_format = "yuv420p10le" if high_bit_depth else "yuv420p"
    try:
        for segment, destination in zip(segment_list, destination_list):
            current_scene_number = segment.scene_number
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Keep the container suffix so ffmpeg can infer the muxer while
            # the leading dot and .part marker keep the file unpublished.
            temporary = destination.with_name(f".{destination.stem}.part{destination.suffix}")
            command = [
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-ss", f"{segment.start_seconds:.3f}",
                "-t", f"{segment.duration_seconds:.3f}",
                "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx265" if high_bit_depth else "libx264",
                "-preset", "medium", "-crf", "18",
                "-pix_fmt", output_pixel_format,
                *( ["-tag:v", "hvc1"] if high_bit_depth else [] ),
                "-c:a", "aac", "-b:a", "192k", "-avoid_negative_ts", "make_zero",
                str(temporary),
            ]
            prepared.append((temporary, destination))
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise SequenceVideoError(f"ffmpeg produced an empty segment for scene {segment.scene_number}")
            actual_duration = _probe_duration(temporary)
            tolerance = max(0.12, segment.duration_seconds * 0.05)
            if actual_duration is None or abs(actual_duration - segment.duration_seconds) > tolerance:
                raise SequenceVideoError(
                    f"ffmpeg produced an invalid or duration-drifted segment for scene {segment.scene_number}: "
                    f"expected {segment.duration_seconds:.3f}s, got {actual_duration or 0:.3f}s"
                )
            if source_has_audio:
                output_stream_types = _probe_stream_types(temporary)
                if output_stream_types is not None and "audio" not in output_stream_types:
                    raise SequenceVideoError(
                        f"ffmpeg dropped the source audio stream for scene {segment.scene_number}"
                    )
        # Publish the complete batch as a small filesystem transaction. A
        # replacement can fail after an earlier destination was promoted
        # (disk pressure, permissions, network filesystem hiccup, ...); keep
        # the previous batch recoverable until every replacement succeeds.
        backups: list[tuple[Path | None, Path]] = []
        promoted: list[Path] = []
        try:
            for temporary, destination in prepared:
                backup = None
                if destination.exists():
                    backup = destination.with_name(
                        f".{destination.name}.{uuid4().hex}.bak"
                    )
                    destination.replace(backup)
                backups.append((backup, destination))
                temporary.replace(destination)
                promoted.append(destination)
            outputs = [str(destination) for _temporary, destination in prepared]
        except Exception as exc:
            for destination in reversed(promoted):
                destination.unlink(missing_ok=True)
            for backup, destination in reversed(backups):
                if backup is not None and backup.exists():
                    backup.replace(destination)
            raise SequenceVideoError(
                f"Could not publish the complete sequence batch: {exc}"
            ) from exc
        finally:
            for backup, destination in backups:
                # If restoration itself failed, leave the backup in place so
                # the previous published batch remains recoverable.
                if backup is not None and backup.exists() and destination.exists():
                    backup.unlink(missing_ok=True)
    except SequenceVideoError:
        for temporary, _destination in prepared:
            temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        for temporary, _destination in prepared:
            temporary.unlink(missing_ok=True)
        raise SequenceVideoError(
            f"Could not split scene {current_scene_number} from sequence video: {exc}"
        ) from exc
    return outputs
