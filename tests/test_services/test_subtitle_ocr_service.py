import json
from pathlib import Path

from src.services.asr_service import ASRSegment
from src.services.subtitle_ocr_service import SubtitleOCRService, TranscriptFusionService


def test_ocr_command_loads_timed_segments(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")

    def fake_run(command, shell, check, capture_output, text, timeout):
        output = command.split("--output ", 1)[1]
        Path(output).write_text(
            json.dumps(
                {
                    "segments": [
                        {"start": 1.0, "end": 2.0, "text": "你醒了", "confidence": 0.91},
                        {"start": 2.1, "end": 3.0, "text": "低置信", "confidence": 0.2},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.services.subtitle_ocr_service.settings.OCR_BACKEND", "command")
    monkeypatch.setattr("src.services.subtitle_ocr_service.settings.OCR_COMMAND", "fake-ocr --output {output}")
    monkeypatch.setattr("src.services.subtitle_ocr_service.settings.OCR_MIN_CONFIDENCE", 0.55)
    monkeypatch.setattr("src.services.subtitle_ocr_service.subprocess.run", fake_run)

    segments = SubtitleOCRService().extract_video_subtitles(str(video), str(tmp_path / "ocr"))

    assert len(segments) == 1
    assert segments[0].text == "你醒了"
    assert segments[0].start == 1.0
    assert segments[0].end == 2.0
    assert segments[0].source == "ocr"


def test_fusion_prefers_ocr_text_and_duration_when_overlapping():
    asr_segments = [
        ASRSegment(start=0.8, end=2.4, text="你笑了", source="asr"),
        ASRSegment(start=5.0, end=6.0, text="没有字幕的旁白", source="asr"),
    ]
    ocr_segments = [
        ASRSegment(start=1.0, end=2.0, text="你醒了", source="ocr", confidence=0.9),
    ]

    fused = TranscriptFusionService().fuse(asr_segments, ocr_segments)

    assert fused[0].text == "你醒了"
    assert fused[0].start == 1.0
    assert fused[0].end == 2.0
    assert fused[0].source == "ocr_asr_fused"
    assert fused[1].text == "没有字幕的旁白"
