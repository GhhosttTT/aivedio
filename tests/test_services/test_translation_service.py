import json
from pathlib import Path

from src.services.asr_service import ASRSegment
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
    assert (tmp_path / "out" / "story_context.json").exists()
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


def test_translation_context_extracts_domain_terms():
    service = SubtitleTranslationService()
    context = service._build_deterministic_context(
        [
            ASRSegment(start=0.0, end=1.0, text="\u4e0a\u754c\u6765\u4eba\u4e86", source="ocr"),
            ASRSegment(start=1.0, end=2.0, text="\u4ed6\u662f\u4ed9\u5c0a", source="asr"),
        ]
    )

    assert "\u4e0a\u754c" in context.glossary
    assert "\u4ed9\u5c0a" in context.glossary
    assert context.story_summary
    assert context.translation_style
    assert context.source_summary["ocr"] == 1


def test_translation_prompt_includes_story_package():
    service = SubtitleTranslationService()
    segments = [ASRSegment(start=0.0, end=1.0, text="\u4e0a\u754c\u6765\u4eba\u4e86", source="ocr")]
    context = service._build_deterministic_context(segments)

    prompt = service._build_translation_prompt(segments, "en", context)

    assert "Global context" in prompt
    assert "story_summary" in prompt
    assert "worldbuilding" in prompt
    assert "\u4e0a\u754c" in prompt
    assert "OCR-visible subtitle text" in prompt


def test_context_payload_overrides_story_package():
    service = SubtitleTranslationService()
    fallback = service._build_deterministic_context(
        [ASRSegment(start=0.0, end=1.0, text="\u4e0a\u754c\u6765\u4eba\u4e86", source="ocr")]
    )

    context = service._context_from_payload(
        {
            "story_summary": "A betrayed heroine faces a celestial power struggle.",
            "characters": ["heroine: betrayed but resilient"],
            "relationships": ["heroine and male lead: estranged spouses"],
            "conflicts": ["forced marriage and revenge"],
            "worldbuilding": ["\u4e0a\u754c is a celestial realm/order, not a normal location"],
            "emotional_arc": ["humiliation to defiance"],
            "glossary": {"\u4e0a\u754c": "celestial upper realm"},
            "translation_style": "tense, concise revenge drama subtitles",
        },
        fallback,
    )

    assert "betrayed heroine" in context.story_summary
    assert context.characters == ["heroine: betrayed but resilient"]
    assert context.worldbuilding == ["\u4e0a\u754c is a celestial realm/order, not a normal location"]
    assert context.glossary["\u4e0a\u754c"] == "celestial upper realm"
