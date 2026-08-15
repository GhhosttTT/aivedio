"""Local ASR service for source-video localization."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from src.config import settings


class ASRError(RuntimeError):
    """Raised when ASR cannot produce a timed transcript."""


@dataclass(frozen=True)
class ASRSegment:
    start: float
    end: float
    text: str
    source: str = "asr"
    confidence: Optional[float] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class ASRResult:
    audio_path: str
    transcript_json_path: str
    srt_path: str
    language: str
    segments: List[ASRSegment]


class LocalASRService:
    """Transcribe source-video audio into timed Chinese subtitles."""

    def transcribe_video(self, video_path: str, output_dir: str) -> ASRResult:
        source = Path(video_path)
        if not source.exists():
            raise FileNotFoundError(f"source video does not exist: {video_path}")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_path = out_dir / f"{source.stem}.wav"
        transcript_path = out_dir / "transcript.json"
        srt_path = out_dir / "transcript.zh.srt"

        self.extract_audio(str(source), str(audio_path))

        if settings.ASR_BACKEND == "faster_whisper":
            segments = self._transcribe_with_faster_whisper(str(audio_path))
        elif settings.ASR_BACKEND == "command":
            segments = self._transcribe_with_command(str(audio_path), str(transcript_path))
        else:
            raise ASRError(f"unsupported ASR backend: {settings.ASR_BACKEND}")

        if not segments:
            raise ASRError("ASR produced no transcript segments")

        from src.services.subtitle_ocr_service import SubtitleOCRService, TranscriptFusionService

        ocr_segments = SubtitleOCRService().extract_video_subtitles(str(source), str(out_dir))
        if ocr_segments:
            segments = TranscriptFusionService().fuse(segments, ocr_segments)
            TranscriptFusionService().write_transcript(transcript_path, settings.ASR_LANGUAGE, segments)
        else:
            self._write_transcript_json(transcript_path, segments)

        self._write_srt(srt_path, segments)
        return ASRResult(
            audio_path=str(audio_path),
            transcript_json_path=str(transcript_path),
            srt_path=str(srt_path),
            language=settings.ASR_LANGUAGE,
            segments=segments,
        )

    def extract_audio(self, video_path: str, audio_path: str) -> None:
        if not shutil.which("ffmpeg"):
            raise ASRError("ffmpeg executable not found; install ffmpeg before running ASR")

        command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            audio_path,
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.ASR_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise ASRError(f"ffmpeg audio extraction failed: {completed.stderr}")
        if not Path(audio_path).exists():
            raise ASRError(f"ffmpeg did not create audio file: {audio_path}")

    def _transcribe_with_faster_whisper(self, audio_path: str) -> List[ASRSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRError(
                "faster-whisper is not installed. Install it or set ASR_BACKEND=command."
            ) from exc

        configured_model = Path(settings.ASR_MODEL_PATH)
        model_name_or_path = (
            str(configured_model)
            if configured_model.exists()
            else settings.ASR_MODEL_SIZE
        )

        model = WhisperModel(
            model_name_or_path,
            device=settings.ASR_DEVICE,
            compute_type=settings.ASR_COMPUTE_TYPE,
        )
        raw_segments, _info = model.transcribe(
            audio_path,
            language=settings.ASR_LANGUAGE,
            vad_filter=True,
            beam_size=5,
        )
        return [
            ASRSegment(start=float(segment.start), end=float(segment.end), text=segment.text.strip())
            for segment in raw_segments
            if segment.text and segment.text.strip()
        ]

    def _transcribe_with_command(self, audio_path: str, transcript_path: str) -> List[ASRSegment]:
        if not settings.ASR_COMMAND:
            raise ASRError("ASR_COMMAND is not configured")

        command = settings.ASR_COMMAND.format(
            audio=audio_path,
            output=transcript_path,
            language=settings.ASR_LANGUAGE,
            model=settings.ASR_MODEL_PATH,
        )
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.ASR_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise ASRError(f"ASR command failed with code {completed.returncode}: {completed.stderr}")
        if not Path(transcript_path).exists():
            raise ASRError(f"ASR command did not create transcript: {transcript_path}")

        payload = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
        return self._segments_from_payload(payload)

    def _segments_from_payload(self, payload: object) -> List[ASRSegment]:
        if isinstance(payload, dict):
            items = payload.get("segments", [])
        else:
            items = payload
        if not isinstance(items, list):
            raise ASRError("ASR transcript JSON must be a list or contain a segments list")

        segments: List[ASRSegment] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            start = float(item.get("start", item.get("start_time", 0.0)))
            if "end" in item:
                end = float(item["end"])
            else:
                end = start + float(item.get("duration", 0.0))
            if end <= start:
                raise ASRError(f"invalid ASR segment timing: start={start}, end={end}")
            segments.append(ASRSegment(start=start, end=end, text=text))
        return segments

    def _write_transcript_json(self, transcript_path: Path, segments: Iterable[ASRSegment]) -> None:
        payload = {
            "language": settings.ASR_LANGUAGE,
            "segments": [asdict(segment) for segment in segments],
        }
        transcript_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_srt(self, srt_path: Path, segments: Iterable[ASRSegment]) -> None:
        lines: List[str] = []
        for index, segment in enumerate(segments, start=1):
            lines.extend(
                [
                    str(index),
                    f"{self._format_srt_time(segment.start)} --> {self._format_srt_time(segment.end)}",
                    segment.text,
                    "",
                ]
            )
        srt_path.write_text("\n".join(lines), encoding="utf-8")

    def _format_srt_time(self, seconds: float) -> str:
        milliseconds = int(round(max(0.0, seconds) * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
