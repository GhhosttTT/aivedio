import json
from pathlib import Path

from src.services.asr_service import LocalASRService


def test_command_asr_writes_transcript_and_srt(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")

    def fake_extract_audio(_self, _video_path, audio_path):
        Path(audio_path).write_bytes(b"fake-audio")

    def fake_run(command, shell, check, capture_output, text, timeout):
        output = command.split("--output ", 1)[1].split(" ", 1)[0]
        Path(output).write_text(
            json.dumps(
                {
                    "segments": [
                        {"start": 0.0, "end": 1.25, "text": "你好"},
                        {"start": 1.5, "duration": 2.0, "text": "这是测试"},
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

    monkeypatch.setattr("src.services.asr_service.settings.ASR_BACKEND", "command")
    monkeypatch.setattr("src.services.asr_service.settings.ASR_COMMAND", "fake-asr --audio {audio} --output {output}")
    monkeypatch.setattr(LocalASRService, "extract_audio", fake_extract_audio)
    monkeypatch.setattr("src.services.asr_service.subprocess.run", fake_run)

    result = LocalASRService().transcribe_video(str(video), str(tmp_path / "asr"))

    assert Path(result.audio_path).exists()
    assert Path(result.transcript_json_path).exists()
    assert Path(result.srt_path).exists()
    assert len(result.segments) == 2
    assert "00:00:00,000 --> 00:00:01,250" in Path(result.srt_path).read_text(encoding="utf-8")
    assert "这是测试" in Path(result.srt_path).read_text(encoding="utf-8")


def test_srt_time_format_rounds_to_milliseconds():
    service = LocalASRService()

    assert service._format_srt_time(3661.2345) == "01:01:01,234"
