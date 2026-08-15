"""OCR subtitle extraction and OCR/ASR transcript fusion."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List

from src.config import settings
from src.services.asr_service import ASRSegment


class SubtitleOCRError(RuntimeError):
    """Raised when OCR subtitle extraction fails."""


class SubtitleOCRService:
    """Extract burned-in source subtitles through a configured OCR command."""

    def extract_video_subtitles(self, video_path: str, output_dir: str) -> List[ASRSegment]:
        if settings.OCR_BACKEND == "disabled":
            return []
        if settings.OCR_BACKEND != "command":
            raise SubtitleOCRError(f"unsupported OCR backend: {settings.OCR_BACKEND}")
        if not settings.OCR_COMMAND:
            raise SubtitleOCRError("OCR_COMMAND is not configured")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "ocr_transcript.json"
        command = settings.OCR_COMMAND.format(
            input=video_path,
            output=str(output_path),
        )
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.OCR_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise SubtitleOCRError(f"OCR command failed with code {completed.returncode}: {completed.stderr}")
        if not output_path.exists():
            raise SubtitleOCRError(f"OCR command did not create transcript: {output_path}")

        return self._load_segments(output_path)

    def _load_segments(self, path: Path) -> List[ASRSegment]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("segments", payload if isinstance(payload, list) else [])
        if not isinstance(items, list):
            raise SubtitleOCRError("OCR transcript JSON must be a list or contain a segments list")

        segments: List[ASRSegment] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            confidence = item.get("confidence")
            confidence_value = None if confidence is None else float(confidence)
            if confidence_value is not None and confidence_value < settings.OCR_MIN_CONFIDENCE:
                continue

            start = float(item.get("start", item.get("start_time", 0.0)))
            if "end" in item:
                end = float(item["end"])
            else:
                end = start + float(item.get("duration", 0.0))
            if end <= start:
                raise SubtitleOCRError(f"invalid OCR segment timing: start={start}, end={end}")
            segments.append(
                ASRSegment(
                    start=start,
                    end=end,
                    text=text,
                    source="ocr",
                    confidence=confidence_value,
                )
            )
        return segments


class TranscriptFusionService:
    """Fuse OCR subtitles with ASR transcript segments.

    OCR is preferred for visible subtitle text and timing. ASR remains useful for
    filling gaps when OCR misses a line or when the source video has no subtitle.
    """

    def fuse(self, asr_segments: Iterable[ASRSegment], ocr_segments: Iterable[ASRSegment]) -> List[ASRSegment]:
        asr = sorted(asr_segments, key=lambda segment: (segment.start, segment.end))
        ocr = sorted(ocr_segments, key=lambda segment: (segment.start, segment.end))
        if not ocr:
            return asr

        fused: List[ASRSegment] = []
        used_asr = set()
        for ocr_segment in ocr:
            match_index = self._best_matching_asr_index(ocr_segment, asr)
            if match_index is not None:
                used_asr.add(match_index)
                asr_text = asr[match_index].text
                source = "ocr_asr_fused" if asr_text and asr_text != ocr_segment.text else "ocr"
            else:
                source = "ocr"
            fused.append(
                ASRSegment(
                    start=ocr_segment.start,
                    end=ocr_segment.end,
                    text=ocr_segment.text,
                    source=source,
                    confidence=ocr_segment.confidence,
                )
            )

        for index, asr_segment in enumerate(asr):
            if index in used_asr:
                continue
            if self._is_close_to_any_ocr(asr_segment, ocr):
                continue
            fused.append(asr_segment)

        return sorted(fused, key=lambda segment: (segment.start, segment.end))

    def write_transcript(self, path: Path, language: str, segments: Iterable[ASRSegment]) -> None:
        payload = {
            "language": language,
            "source": "ocr_asr_fusion",
            "segments": [asdict(segment) for segment in segments],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _best_matching_asr_index(self, ocr_segment: ASRSegment, asr_segments: List[ASRSegment]) -> int | None:
        best_index = None
        best_overlap = 0.0
        for index, asr_segment in enumerate(asr_segments):
            overlap = self._overlap_seconds(ocr_segment, asr_segment)
            if overlap > best_overlap:
                best_overlap = overlap
                best_index = index
        return best_index if best_overlap > 0 else None

    def _is_close_to_any_ocr(self, asr_segment: ASRSegment, ocr_segments: List[ASRSegment]) -> bool:
        for ocr_segment in ocr_segments:
            if self._overlap_seconds(asr_segment, ocr_segment) > 0:
                return True
            gap = min(
                abs(asr_segment.end - ocr_segment.start),
                abs(ocr_segment.end - asr_segment.start),
            )
            if gap <= settings.OCR_ASR_MAX_GAP_SECONDS:
                return True
        return False

    @staticmethod
    def _overlap_seconds(left: ASRSegment, right: ASRSegment) -> float:
        return max(0.0, min(left.end, right.end) - max(left.start, right.start))
