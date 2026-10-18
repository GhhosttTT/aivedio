"""Auditable quality checks for generated SRT subtitle timelines."""

from __future__ import annotations

import re
from typing import Any


_TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})$"
)
_BLOCK_RE = re.compile(r"(?:^|\n\s*\n)(?:\d+\s*\n)?(?P<body>.*?)(?=\n\s*\n|\Z)", re.S)


def assess_subtitle_timeline(
    content: str,
    expected_text: str | None = None,
    *,
    max_cjk_chars_per_second: float = 12.0,
    max_latin_words_per_second: float = 4.5,
) -> dict[str, Any]:
    """Validate SRT structure, timing, overlap, reading speed, and text coverage."""
    issues: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for index, match in enumerate(_BLOCK_RE.finditer(content or ""), start=1):
        lines = [line.strip() for line in match.group("body").splitlines() if line.strip()]
        if not lines:
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None or timing_index + 1 >= len(lines):
            issues.append({"code": "invalid_entry", "entry": index, "message": "missing timing or text"})
            continue
        timing = _TIMING_RE.match(lines[timing_index])
        if not timing:
            issues.append({"code": "invalid_timing", "entry": index, "message": lines[timing_index]})
            continue
        start = _parse_time(timing.group("start"))
        end = _parse_time(timing.group("end"))
        text = " ".join(lines[timing_index + 1:]).strip()
        if end <= start:
            issues.append({"code": "non_positive_duration", "entry": index})
            continue
        if entries and start < entries[-1]["end"] - 0.001:
            issues.append({"code": "overlap", "entry": index})
        reading_speed = _reading_speed(text, end - start)
        if reading_speed["kind"] == "cjk" and reading_speed["value"] > max_cjk_chars_per_second:
            issues.append({"code": "reading_speed", "entry": index, "value": reading_speed["value"]})
        if reading_speed["kind"] == "latin" and reading_speed["value"] > max_latin_words_per_second:
            issues.append({"code": "reading_speed", "entry": index, "value": reading_speed["value"]})
        entries.append({
            "index": index,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "text": text,
            "reading_speed": reading_speed,
        })

    if not entries:
        issues.append({"code": "empty_timeline", "message": "no valid subtitle entries"})
    if expected_text and not _normalized(expected_text) in _normalized(" ".join(item["text"] for item in entries)):
        issues.append({"code": "text_coverage", "message": "subtitle text does not cover expected dialogue"})

    total_duration = entries[-1]["end"] if entries else 0.0
    return {
        "schema_version": 1,
        "status": "passed" if not issues else "needs_review",
        "entry_count": len(entries),
        "total_duration_seconds": total_duration,
        "entries": entries,
        "issues": issues,
    }


def _parse_time(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _normalized(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def _reading_speed(text: str, duration: float) -> dict[str, Any]:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk:
        return {"kind": "cjk", "value": round(cjk / duration, 3), "unit": "chars_per_second"}
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    return {"kind": "latin", "value": round(words / duration, 3), "unit": "words_per_second"}
