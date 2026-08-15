import json
from pathlib import Path

from src.services.translation_service import SubtitleTranslationService


def _write_source_transcript(path: Path):
    path.write_text(
        json.dumps(
            {
                "language": "zh",
                "segments": [
                    {"start": 0.0, "end": 1.0, "text": "你好"},
                    {"start": 1.5, "end": 3.0, "text": "这是测试"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_command_translation_writes_language_outputs(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    _write_source_transcript(transcript)

    def fake_run(command, shell, check, capture_output, text, timeout):
        output = command.split("--output ", 1)[1].split(" ", 1)[0]
        Path(output).write_text(
            json.dumps(
                {
                    "segments": [
                        {"start": 0.0, "end": 1.0, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "This is a test"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.services.translation_service.settings.TRANSLATION_BACKEND", "command")
    monkeypatch.setattr(
        "src.services.translation_service.settings.TRANSLATION_COMMAND",
        "fake-translate --input {input} --output {output} --language {language}",
    )
    monkeypatch.setattr("src.services.translation_service.subprocess.run", fake_run)

    results = SubtitleTranslationService().translate_transcript(str(transcript), ["en"], str(tmp_path / "out"))

    assert set(results) == {"en"}
    assert Path(results["en"].json_path).exists()
    assert Path(results["en"].srt_path).exists()
    assert "This is a test" in Path(results["en"].srt_path).read_text(encoding="utf-8")
    assert "00:00:01,500 --> 00:00:03,000" in Path(results["en"].srt_path).read_text(encoding="utf-8")


def test_local_llm_translation_preserves_timing(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    _write_source_transcript(transcript)

    class FakeLLM:
        def generate(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "segments": [
                        {"index": 1, "text": "Hello"},
                        {"index": 2, "text": "This is a test"},
                    ]
                }
            )

    monkeypatch.setattr("src.services.translation_service.settings.TRANSLATION_BACKEND", "local_llm")
    monkeypatch.setattr("src.services.llm_service.get_llm_service", lambda: FakeLLM())

    results = SubtitleTranslationService().translate_transcript(str(transcript), ["en"], str(tmp_path / "out"))

    assert results["en"].segments[0].start == 0.0
    assert results["en"].segments[0].end == 1.0
    assert results["en"].segments[0].text == "Hello"


def test_deepseek_translation_preserves_timing(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.json"
    _write_source_transcript(transcript)

    monkeypatch.setattr("src.services.translation_service.settings.TRANSLATION_BACKEND", "deepseek")
    monkeypatch.setattr("src.services.translation_service.settings.DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.services.translation_service.SubtitleTranslationService._call_deepseek",
        lambda _self, _prompt: json.dumps(
            {
                "segments": [
                    {"index": 1, "text": "Hello"},
                    {"index": 2, "text": "This is a test"},
                ]
            }
        ),
    )

    results = SubtitleTranslationService().translate_transcript(str(transcript), ["en"], str(tmp_path / "out"))

    assert results["en"].segments[0].start == 0.0
    assert results["en"].segments[0].end == 1.0
    assert results["en"].segments[0].text == "Hello"
