"""Extract burned-in subtitles from a video into timed JSON segments.

The script is designed for OCR_COMMAND integration:

    OCR_BACKEND=command
    OCR_COMMAND=python scripts/ocr_subtitles.py --input {input} --output {output}

Output format:
{
  "segments": [
    {"start": 1.0, "end": 2.4, "text": "source subtitle", "confidence": 0.92}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Protocol, Tuple

from PIL import Image, ImageOps


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: Optional[float] = None


@dataclass
class TimedSubtitle:
    start: float
    end: float
    text: str
    confidence: Optional[float]


class OCREngine(Protocol):
    def recognize(self, image_path: Path) -> List[OCRLine]:
        ...


class RapidOCREngine:
    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self.engine = RapidOCR()

    def recognize(self, image_path: Path) -> List[OCRLine]:
        result, _elapsed = self.engine(str(image_path))
        if not result:
            return []
        lines = []
        for item in result:
            text = str(item[1]).strip()
            confidence = float(item[2]) if len(item) > 2 and item[2] is not None else None
            if text:
                lines.append(OCRLine(text=text, confidence=confidence))
        return lines


class EasyOCREngine:
    def __init__(self) -> None:
        import easyocr

        self.reader = easyocr.Reader(["ch_sim", "en"], gpu=False)

    def recognize(self, image_path: Path) -> List[OCRLine]:
        result = self.reader.readtext(str(image_path), detail=1, paragraph=False)
        lines = []
        for item in result:
            text = str(item[1]).strip()
            confidence = float(item[2]) if len(item) > 2 and item[2] is not None else None
            if text:
                lines.append(OCRLine(text=text, confidence=confidence))
        return lines


class PaddleOCREngine:
    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self.engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)

    def recognize(self, image_path: Path) -> List[OCRLine]:
        result = self.engine.ocr(str(image_path), cls=True)
        lines = []
        for page in result or []:
            for item in page or []:
                text = str(item[1][0]).strip()
                confidence = float(item[1][1]) if item[1][1] is not None else None
                if text:
                    lines.append(OCRLine(text=text, confidence=confidence))
        return lines


class TesseractEngine:
    def __init__(self) -> None:
        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract executable not found")

    def recognize(self, image_path: Path) -> List[OCRLine]:
        command = [
            "tesseract",
            str(image_path),
            "stdout",
            "-l",
            "chi_sim+eng",
            "--psm",
            "6",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"tesseract failed: {completed.stderr}")
        text = normalize_text(completed.stdout)
        return [OCRLine(text=text, confidence=None)] if text else []


def build_engine(name: str) -> OCREngine:
    errors = []
    candidates = [name] if name != "auto" else ["rapidocr", "easyocr", "paddleocr", "tesseract"]
    for candidate in candidates:
        try:
            if candidate == "rapidocr":
                return RapidOCREngine()
            if candidate == "easyocr":
                return EasyOCREngine()
            if candidate == "paddleocr":
                return PaddleOCREngine()
            if candidate == "tesseract":
                return TesseractEngine()
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError(
        "No OCR engine is available. Install one of: rapidocr-onnxruntime, easyocr, paddleocr, or tesseract.\n"
        + "\n".join(errors)
    )


def extract_frames(video_path: Path, frame_dir: Path, fps: float) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg executable not found")
    frame_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps}",
        str(frame_dir / "frame_%06d.jpg"),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {completed.stderr}")


def crop_subtitle_region(
    frame_path: Path,
    output_path: Path,
    crop_top: float,
    crop_bottom: float,
    crop_left: float,
    crop_right: float,
    scale: int,
) -> None:
    image = Image.open(frame_path).convert("RGB")
    width, height = image.size
    left = int(width * crop_left)
    right = int(width * crop_right)
    top = int(height * crop_top)
    bottom = int(height * crop_bottom)
    cropped = image.crop((left, top, right, bottom))
    if scale > 1:
        cropped = cropped.resize((cropped.width * scale, cropped.height * scale))
    gray = ImageOps.grayscale(cropped)
    enhanced = ImageOps.autocontrast(gray)
    enhanced.save(output_path)


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").replace("\r", " ").split()).strip()


def average_confidence(lines: Iterable[OCRLine]) -> Optional[float]:
    values = [line.confidence for line in lines if line.confidence is not None]
    if not values:
        return None
    return sum(values) / len(values)


def same_text(left: str, right: str) -> bool:
    return normalize_text(left).replace(" ", "") == normalize_text(right).replace(" ", "")


def merge_frame_results(
    frame_results: Iterable[Tuple[float, str, Optional[float]]],
    frame_duration: float,
    merge_gap: float,
    min_duration: float,
) -> List[TimedSubtitle]:
    segments: List[TimedSubtitle] = []
    current: Optional[TimedSubtitle] = None
    last_timestamp = 0.0

    for timestamp, text, confidence in frame_results:
        if not text:
            if current and timestamp - last_timestamp > merge_gap:
                current.end = max(current.end, last_timestamp + frame_duration)
                if current.end - current.start >= min_duration:
                    segments.append(current)
                current = None
            continue

        if current and same_text(current.text, text) and timestamp - last_timestamp <= merge_gap:
            current.end = timestamp + frame_duration
            if current.confidence is None:
                current.confidence = confidence
            elif confidence is not None:
                current.confidence = max(current.confidence, confidence)
        else:
            if current and current.end - current.start >= min_duration:
                segments.append(current)
            current = TimedSubtitle(
                start=timestamp,
                end=timestamp + frame_duration,
                text=text,
                confidence=confidence,
            )
        last_timestamp = timestamp

    if current and current.end - current.start >= min_duration:
        segments.append(current)
    return segments


def run(args: argparse.Namespace) -> None:
    video_path = Path(args.input)
    output_path = Path(args.output)
    if not video_path.exists():
        raise FileNotFoundError(f"input video does not exist: {video_path}")

    engine = build_engine(args.engine)
    with tempfile.TemporaryDirectory(prefix="subtitle_ocr_") as temp:
        temp_dir = Path(temp)
        frame_dir = temp_dir / "frames"
        crop_dir = temp_dir / "crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        extract_frames(video_path, frame_dir, args.fps)

        frame_paths = sorted(frame_dir.glob("frame_*.jpg"))
        frame_results = []
        for index, frame_path in enumerate(frame_paths):
            timestamp = index / args.fps
            crop_path = crop_dir / frame_path.name
            crop_subtitle_region(
                frame_path,
                crop_path,
                args.crop_top,
                args.crop_bottom,
                args.crop_left,
                args.crop_right,
                args.scale,
            )
            lines = engine.recognize(crop_path)
            text = normalize_text(" ".join(line.text for line in lines))
            confidence = average_confidence(lines)
            if confidence is not None and confidence < args.min_confidence:
                text = ""
            frame_results.append((timestamp, text, confidence))

    segments = merge_frame_results(
        frame_results,
        frame_duration=1.0 / args.fps,
        merge_gap=args.merge_gap,
        min_duration=args.min_duration,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "source_video": str(video_path),
                "engine": args.engine,
                "fps": args.fps,
                "crop": {
                    "top": args.crop_top,
                    "bottom": args.crop_bottom,
                    "left": args.crop_left,
                    "right": args.crop_right,
                },
                "segments": [
                    {
                        "start": round(segment.start, 3),
                        "end": round(segment.end, 3),
                        "text": segment.text,
                        "confidence": segment.confidence,
                    }
                    for segment in segments
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract hard subtitles from video frames with OCR.")
    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument("--output", required=True, help="Output JSON transcript path")
    parser.add_argument("--engine", default="auto", choices=["auto", "rapidocr", "easyocr", "paddleocr", "tesseract"])
    parser.add_argument("--fps", type=float, default=2.0, help="Frame sampling rate for OCR")
    parser.add_argument("--crop-top", type=float, default=0.68, help="Normalized top crop boundary")
    parser.add_argument("--crop-bottom", type=float, default=0.94, help="Normalized bottom crop boundary")
    parser.add_argument("--crop-left", type=float, default=0.02, help="Normalized left crop boundary")
    parser.add_argument("--crop-right", type=float, default=0.98, help="Normalized right crop boundary")
    parser.add_argument("--scale", type=int, default=2, help="Upscale cropped subtitle region before OCR")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--merge-gap", type=float, default=0.85)
    parser.add_argument("--min-duration", type=float, default=0.35)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        run(parse_args())
    except Exception as exc:
        print(f"OCR subtitle extraction failed: {exc}", file=sys.stderr)
        sys.exit(1)
