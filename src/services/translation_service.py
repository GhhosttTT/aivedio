"""Local subtitle translation service for source-video localization."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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


@dataclass(frozen=True)
class TranslationContext:
    story_summary: str
    characters: List[str]
    relationships: List[str]
    conflicts: List[str]
    worldbuilding: List[str]
    emotional_arc: List[str]
    glossary: Dict[str, str]
    translation_style: str
    source_summary: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
        context = self._build_context_for_backend(segments)
        self._write_story_context(out_dir / "story_context.json", context)

        results: Dict[str, TranslationResult] = {}
        for language in target_languages:
            code = language.strip().lower()
            if not code:
                continue
            translated = self._translate_language(segments, code, out_dir, context)
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
        context: TranslationContext,
    ) -> List[ASRSegment]:
        if settings.TRANSLATION_BACKEND == "command":
            return self._translate_with_command(segments, language, output_dir)
        if settings.TRANSLATION_BACKEND == "deepseek":
            return self._translate_with_deepseek(segments, language, context)
        if settings.TRANSLATION_BACKEND == "local_llm":
            return self._translate_with_local_llm(segments, language, context)
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

    def _translate_with_deepseek(
        self,
        segments: List[ASRSegment],
        language: str,
        context: TranslationContext,
    ) -> List[ASRSegment]:
        if not settings.DEEPSEEK_API_KEY:
            raise TranslationError("DEEPSEEK_API_KEY is not configured")

        translated: List[ASRSegment] = []
        batch_size = max(1, settings.TRANSLATION_MAX_SEGMENTS_PER_BATCH)
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            prompt = self._build_translation_prompt(batch, language, context)
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

    def _translate_with_local_llm(
        self,
        segments: List[ASRSegment],
        language: str,
        context: TranslationContext,
    ) -> List[ASRSegment]:
        from src.services.llm_service import get_llm_service

        translated: List[ASRSegment] = []
        batch_size = max(1, settings.TRANSLATION_MAX_SEGMENTS_PER_BATCH)
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            prompt = self._build_translation_prompt(batch, language, context)
            response = get_llm_service().generate(
                prompt,
                max_tokens=4096,
                temperature=0.2,
                top_p=0.8,
                stop=None,
            )
            translated.extend(self._parse_llm_response(response, batch))
        return translated

    def _build_context_for_backend(self, segments: List[ASRSegment]) -> TranslationContext:
        if settings.TRANSLATION_BACKEND == "deepseek":
            return self._build_translation_context(segments, provider="deepseek")
        if settings.TRANSLATION_BACKEND == "local_llm":
            return self._build_translation_context(segments, provider="local_llm")
        return self._build_deterministic_context(segments)

    def _build_translation_context(self, segments: List[ASRSegment], provider: str) -> TranslationContext:
        fallback = self._build_deterministic_context(segments)
        prompt = self._build_context_prompt(segments)
        try:
            if provider == "deepseek":
                response = self._call_deepseek(prompt)
            elif provider == "local_llm":
                from src.services.llm_service import get_llm_service

                response = get_llm_service().generate(
                    prompt,
                    max_tokens=2048,
                    temperature=0.1,
                    top_p=0.8,
                    stop=None,
                )
            else:
                return fallback
            payload = self._extract_json(response)
            return self._context_from_payload(payload, fallback)
        except Exception:
            return fallback

    def _context_from_payload(self, payload: Dict[str, Any], fallback: TranslationContext) -> TranslationContext:
        glossary = dict(fallback.glossary)
        glossary.update(self._normalize_glossary(payload.get("glossary", {})))
        return TranslationContext(
            story_summary=self._first_text(payload, ["story_summary", "story_context"], fallback.story_summary),
            characters=self._string_list(payload.get("characters")) or fallback.characters,
            relationships=self._string_list(payload.get("relationships")) or fallback.relationships,
            conflicts=self._string_list(payload.get("conflicts")) or fallback.conflicts,
            worldbuilding=self._string_list(payload.get("worldbuilding")) or fallback.worldbuilding,
            emotional_arc=self._string_list(payload.get("emotional_arc")) or fallback.emotional_arc,
            glossary=glossary,
            translation_style=self._first_text(
                payload,
                ["translation_style", "style"],
                fallback.translation_style,
            ),
            source_summary=fallback.source_summary,
        )

    def _first_text(self, payload: Dict[str, Any], keys: List[str], fallback: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback

    def _string_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, str):
                    text = item.strip()
                elif isinstance(item, dict):
                    text = "; ".join(
                        f"{key}: {raw_value}"
                        for key, raw_value in item.items()
                        if raw_value is not None and str(raw_value).strip()
                    )
                else:
                    text = str(item).strip()
                if text:
                    items.append(text)
            return items
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _normalize_glossary(self, value: Any) -> Dict[str, str]:
        glossary: Dict[str, str] = {}
        if isinstance(value, dict):
            for term, note in value.items():
                clean_term = str(term).strip()
                clean_note = str(note).strip()
                if clean_term and clean_note:
                    glossary[clean_term] = clean_note
        elif isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                clean_term = str(item.get("term", "")).strip()
                clean_note = str(item.get("note", item.get("meaning", ""))).strip()
                if clean_term and clean_note:
                    glossary[clean_term] = clean_note
        return glossary

    def _build_deterministic_context(self, segments: List[ASRSegment]) -> TranslationContext:
        source_summary = Counter(segment.source for segment in segments)
        text = "\n".join(segment.text for segment in segments)
        terms = self._extract_candidate_terms(text)
        glossary = {
            term: (
                "Candidate recurring source term. Preserve its drama/fantasy meaning consistently; "
                "do not translate it as a random literal place or common noun without context."
            )
            for term in terms
        }
        return TranslationContext(
            story_summary=(
                "Use OCR-visible subtitles as the primary source when present. "
                "Use ASR only to recover missing narration or spoken context."
            ),
            characters=[],
            relationships=[],
            conflicts=[],
            worldbuilding=[],
            emotional_arc=[],
            glossary=glossary,
            translation_style=(
                "Natural short-drama subtitle localization. Keep lines concise, emotional, "
                "and readable within the original timing."
            ),
            source_summary=dict(source_summary),
        )

    def _extract_candidate_terms(self, text: str) -> List[str]:
        known_domain_terms = [
            "上界",
            "下界",
            "天庭",
            "仙界",
            "魔界",
            "神界",
            "灵根",
            "灵力",
            "渡劫",
            "飞升",
            "宗门",
            "师尊",
            "仙尊",
            "魔尊",
            "沈总",
        ]
        candidates: Counter[str] = Counter()
        for term in known_domain_terms:
            if term in text:
                candidates[term] += text.count(term) + 3
        for match in re.finditer(r"[\u4e00-\u9fff]{2,8}", text):
            token = match.group(0)
            if len(token) <= 1:
                continue
            candidates[token] += 1
        return [
            term
            for term, _count in candidates.most_common(24)
            if not self._looks_like_common_sentence(term)
        ][:16]

    def _looks_like_common_sentence(self, term: str) -> bool:
        common_fragments = ("这个", "那个", "什么", "不是", "没有", "可以", "就是", "因为", "所以")
        return any(fragment in term for fragment in common_fragments) and len(term) > 3

    def _build_context_prompt(self, segments: List[ASRSegment]) -> str:
        payload = [
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "source": segment.source,
                "text": segment.text,
            }
            for segment in segments
        ]
        return (
            "Analyze this Chinese short-drama transcript before subtitle translation.\n"
            "OCR-visible subtitle text is the primary source when present; ASR may contain background narration, "
            "quiet dialogue, or recognition mistakes.\n"
            "Build a story-understanding package first. Identify plot, characters, relationships, conflicts, "
            "worldbuilding rules, emotional progression, and special terms. "
            "For fantasy/drama terms such as 上界, explain the concept instead of treating it as a normal place name. "
            "Prefer the interpretation that best fits the full story, not a single isolated sentence.\n"
            "Return strict JSON only in this format: "
            '{"story_summary":"...","characters":["..."],"relationships":["..."],'
            '"conflicts":["..."],"worldbuilding":["..."],"emotional_arc":["..."],'
            '"glossary":{"source term":"meaning and translation guidance"},'
            '"translation_style":"..."}.\n'
            f"Transcript:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_translation_prompt(
        self,
        segments: List[ASRSegment],
        language: str,
        context: Optional[TranslationContext] = None,
    ) -> str:
        language_name = LANGUAGE_NAMES.get(language, language)
        payload = [
            {
                "index": index,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "duration": round(segment.duration, 3),
                "source": segment.source,
                "text": segment.text,
            }
            for index, segment in enumerate(segments, start=1)
        ]
        context_payload = (
            {
                **context.to_dict(),
            }
            if context
            else {}
        )
        return (
            "You are a professional short-drama localization translator.\n"
            f"Translate the Chinese dialogue into {language_name}.\n"
            "Use the timing metadata to keep each translated line concise enough "
            "to read within its original subtitle duration.\n"
            "Preserve emotion, relationship tension, speaker intent, and genre tone. "
            "If OCR and ASR disagree, trust OCR-visible subtitle text more than ASR.\n"
            "Use the full story package to translate the line in context. "
            "Preserve plot facts, character relationships, worldbuilding, emotional intent, and term consistency. "
            "Do not flatten fantasy titles, realms, organizations, or relationship terms into generic literal words. "
            "If one line is ambiguous, choose the meaning that fits the story package.\n"
            "Keep the same number of items, do not split or merge subtitles, "
            "do not change start/end times, preserve meaning, make dialogue natural, "
            "and return strict JSON only in this format: "
            '{"segments":[{"index":1,"text":"translated text"}]}.\n'
            f"Global context:\n{json.dumps(context_payload, ensure_ascii=False)}\n"
            f"Source segments:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _write_story_context(self, path: Path, context: TranslationContext) -> None:
        path.write_text(json.dumps(context.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

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
