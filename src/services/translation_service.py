"""Local subtitle translation service for source-video localization."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from src.config import settings
from src.services.asr_service import ASRSegment


class TranslationError(RuntimeError):
    """Raised when subtitle localization cannot produce translated subtitles."""


LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "ar": "Arabic",
    "id": "Indonesian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ja": "Japanese",
    "ko": "Korean",
}


@dataclass(frozen=True)
class TranslationResult:
    language: str
    json_path: str
    srt_path: str
    segments: List[ASRSegment]


class SubtitleTranslationService:
    """Translate Chinese timed subtitles while preserving segment timings."""

    def translate_transcript(
        self,
        transcript_path: str,
        target_languages: Iterable[str],
        output_dir: str,
    ) -> Dict[str, TranslationResult]:
        source = Path(transcript_path)
        if not source.exists():
            raise FileNotFoundError(f"transcript does not exist: {transcript_path}")

        segments = self._load_segments(source)
        if not segments:
            raise TranslationError("source transcript has no segments")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        results: Dict[str, TranslationResult] = {}
        for language in target_languages:
            code = language.strip().lower()
            if not code:
                continue
            translated = self._translate_language(segments, code, out_dir)
            json_path = out_dir / f"{code}.json"
            srt_path = out_dir / f"{code}.srt"
            self._write_json(json_path, code, translated)
            self._write_srt(srt_path, translated)
            results[code] = TranslationResult(
                language=code,
                json_path=str(json_path),
                srt_path=str(srt_path),
                segments=translated,
            )

        if not results:
            raise TranslationError("target languages cannot be empty")
        return results

    def _translate_language(
        self,
        segments: List[ASRSegment],
        language: str,
        output_dir: Path,
    ) -> List[ASRSegment]:
        if settings.TRANSLATION_BACKEND == "command":
            return self._translate_with_command(segments, language, output_dir)
        if settings.TRANSLATION_BACKEND == "deepseek":
            return self._translate_with_deepseek(segments, language)
        if settings.TRANSLATION_BACKEND == "local_llm":
            return self._translate_with_local_llm(segments, language)
        raise TranslationError(f"unsupported translation backend: {settings.TRANSLATION_BACKEND}")

    def _translate_with_command(
        self,
        segments: List[ASRSegment],
        language: str,
        output_dir: Path,
    ) -> List[ASRSegment]:
        if not settings.TRANSLATION_COMMAND:
            raise TranslationError("TRANSLATION_COMMAND is not configured")

        input_path = output_dir / f"{language}.source.json"
        output_path = output_dir / f"{language}.translated.json"
        self._write_json(input_path, "zh", segments)

        command = settings.TRANSLATION_COMMAND.format(
            input=str(input_path),
            output=str(output_path),
            language=language,
            language_name=LANGUAGE_NAMES.get(language, language),
        )
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.TRANSLATION_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise TranslationError(
                f"translation command failed with code {completed.returncode}: {completed.stderr}"
            )
        if not output_path.exists():
            raise TranslationError(f"translation command did not create output: {output_path}")
        return self._load_segments(output_path)

    def _translate_with_deepseek(self, segments: List[ASRSegment], language: str) -> List[ASRSegment]:
        if not settings.DEEPSEEK_API_KEY:
            raise TranslationError("DEEPSEEK_API_KEY is not configured")

        translated: List[ASRSegment] = []
        batch_size = max(1, settings.TRANSLATION_MAX_SEGMENTS_PER_BATCH)
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            prompt = self._build_translation_prompt(batch, language)
            response = self._call_deepseek(prompt)
            translated.extend(self._parse_llm_response(response, batch))
        return translated

    def _call_deepseek(self, prompt: str) -> str:
        base_url = settings.DEEPSEEK_BASE_URL.rstrip("/")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(
                {
                    "model": settings.DEEPSEEK_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a professional short-drama subtitle translator. "
                                "Return strict JSON only."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "stream": False,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.DEEPSEEK_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TranslationError(f"DeepSeek request failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise TranslationError(f"DeepSeek request failed: {exc}") from exc

        choices = payload.get("choices", [])
        if not choices:
            raise TranslationError("DeepSeek response did not contain choices")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise TranslationError("DeepSeek response message is empty")
        return content

    def _translate_with_local_llm(self, segments: List[ASRSegment], language: str) -> List[ASRSegment]:
        from src.services.llm_service import get_llm_service

        translated: List[ASRSegment] = []
        batch_size = max(1, settings.TRANSLATION_MAX_SEGMENTS_PER_BATCH)
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            prompt = self._build_translation_prompt(batch, language)
            response = get_llm_service().generate(
                prompt,
                max_tokens=4096,
                temperature=0.2,
                top_p=0.8,
                stop=None,
            )
            translated.extend(self._parse_llm_response(response, batch))
        return translated

    def _build_translation_prompt(self, segments: List[ASRSegment], language: str) -> str:
        language_name = LANGUAGE_NAMES.get(language, language)
        payload = [
            {"index": index, "text": segment.text}
            for index, segment in enumerate(segments, start=1)
        ]
        return (
            "You are a professional short-drama localization translator.\n"
            f"Translate the Chinese dialogue into {language_name}.\n"
            "Keep the same number of items, preserve meaning, make dialogue natural, "
            "and return strict JSON only in this format: "
            '{"segments":[{"index":1,"text":"translated text"}]}.\n'
            f"Source segments:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _parse_llm_response(
        self,
        response: str,
        source_segments: List[ASRSegment],
    ) -> List[ASRSegment]:
        payload = self._extract_json(response)
        items = payload.get("segments", [])
        if len(items) != len(source_segments):
            raise TranslationError(
                f"LLM returned {len(items)} translated segments, expected {len(source_segments)}"
            )

        translated: List[ASRSegment] = []
        for source, item in zip(source_segments, items):
            text = str(item.get("text", "")).strip()
            if not text:
                raise TranslationError("LLM returned an empty translated segment")
            translated.append(ASRSegment(start=source.start, end=source.end, text=text))
        return translated

    def _extract_json(self, response: str) -> dict:
        text = response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise TranslationError("LLM response does not contain a JSON object")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise TranslationError(f"LLM response is not valid JSON: {exc}") from exc

    def _load_segments(self, path: Path) -> List[ASRSegment]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("segments", payload if isinstance(payload, list) else [])
        if not isinstance(items, list):
            raise TranslationError("transcript JSON must contain a segments list")
        segments: List[ASRSegment] = []
        for item in items:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start + float(item.get("duration", 0.0))))
            if end <= start:
                raise TranslationError(f"invalid subtitle timing: start={start}, end={end}")
            segments.append(ASRSegment(start=start, end=end, text=text))
        return segments

    def _write_json(self, path: Path, language: str, segments: Iterable[ASRSegment]) -> None:
        payload = {
            "language": language,
            "segments": [asdict(segment) for segment in segments],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_srt(self, path: Path, segments: Iterable[ASRSegment]) -> None:
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
        path.write_text("\n".join(lines), encoding="utf-8")

    def _format_srt_time(self, seconds: float) -> str:
        milliseconds = int(round(max(0.0, seconds) * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
