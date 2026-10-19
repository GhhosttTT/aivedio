"""Quality assessment for localized source-video subtitles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.config import settings
from src.services.asr_service import ASRSegment
from src.services.translation_service import SubtitleTranslationService, TranslationContext


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    category: str
    message: str
    language: Optional[str] = None
    segment_index: Optional[int] = None


@dataclass(frozen=True)
class QualityReport:
    status: str
    score: float
    source_summary: Dict[str, Any]
    target_summary: Dict[str, Any]
    issues: List[QualityIssue]
    llm_review: Dict[str, Any]
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


class LocalizationQualityService:
    """Check source transcript, translation quality, and subtitle timing.

    This is not a replacement for a human reviewer. It is an automated gate that
    combines OCR/ASR metadata, subtitle timing rules, and optional LLM review.
    """

    def assess(
        self,
        transcript_path: str,
        translated_subtitle_dir: str,
        target_languages: Iterable[str],
        output_path: str,
        rendered_video_dir: Optional[str] = None,
    ) -> QualityReport:
        source_segments = self._load_segments(Path(transcript_path))
        translated_dir = Path(translated_subtitle_dir)
        story_context = self._load_story_context(translated_dir / "story_context.json")
        issues: List[QualityIssue] = []
        issues.extend(self._assess_source_segments(source_segments))

        target_summary: Dict[str, Any] = {}
        translations: Dict[str, List[ASRSegment]] = {}
        for language in target_languages:
            code = language.strip().lower()
            if not code:
                continue
            path = translated_dir / f"{code}.json"
            if not path.exists():
                issues.append(QualityIssue("error", "missing_translation", f"Missing translation JSON: {path}", code))
                target_summary[code] = {"segments": 0, "missing": True}
                continue
            translated_segments = self._load_segments(path)
            translations[code] = translated_segments
            language_issues, summary = self._assess_translation_segments(
                source_segments,
                translated_segments,
                code,
            )
            issues.extend(language_issues)
            target_summary[code] = summary

            if rendered_video_dir:
                rendered_path = Path(rendered_video_dir) / f"{code}.mp4"
                if not rendered_path.exists():
                    issues.append(
                        QualityIssue(
                            "warning",
                            "missing_render",
                            f"Rendered video is missing for language {code}",
                            code,
                        )
                    )
                else:
                    visual_audit = self._inspect_rendered_subtitles(
                        rendered_path,
                        translated_segments,
                    )
                    target_summary[code]["rendered_visual"] = visual_audit
                    if visual_audit.get("status") != "available":
                        issues.append(QualityIssue(
                            "warning",
                            "subtitle_visual_integration",
                            f"Rendered subtitle visibility could not be verified for language {code}: "
                            f"{visual_audit.get('error') or visual_audit.get('status') or 'unknown'}",
                            code,
                        ))
                    for message in visual_audit.get("issues", []):
                        issues.append(QualityIssue(
                            "warning",
                            "subtitle_visual_integration",
                            message,
                            code,
                        ))

        llm_review = self._run_llm_review(source_segments, translations, story_context, issues)
        issues.extend(self._issues_from_llm_review(llm_review))
        score = self._score(issues)
        status = "passed" if score >= 0.78 and not self._needs_review(issues) else "needs_review"
        report = QualityReport(
            status=status,
            score=score,
            source_summary=self._source_summary(source_segments),
            target_summary=target_summary,
            issues=issues,
            llm_review=llm_review,
            notes=[
                "QA combines OCR/ASR transcript evidence, translation timing heuristics, and optional LLM review.",
                "Rendered subtitle visibility is sampled at cue midpoints and nearby non-cue frames; this is a screening signal, not OCR or face tracking.",
            ],
        )
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def inspect_rendered_subtitles(
        self,
        video_path: str | Path,
        segments: List[ASRSegment],
    ) -> Dict[str, Any]:
        """Expose the rendered subtitle visual screen to final composition QA."""
        return self._inspect_rendered_subtitles(Path(video_path), segments)

    def _inspect_rendered_subtitles(
        self,
        video_path: Path,
        segments: List[ASRSegment],
    ) -> Dict[str, Any]:
        """Screen burned-in subtitle visibility at timed cue midpoints.

        The renderer places subtitles in the lower safe area. Comparing edge
        density during a cue with nearby non-cue frames catches missing burns
        and very low-contrast text without pretending to be a full OCR/face
        detector.
        """
        if not segments:
            return {"status": "not_applicable", "issues": []}
        try:
            import cv2
            import numpy as np

            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                raise RuntimeError(f"rendered video cannot be opened: {video_path}")
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if fps <= 0 or frame_count <= 0:
                raise RuntimeError("rendered video has no usable frame timing")

            active_values: list[float] = []
            inactive_values: list[float] = []
            for segment in segments[:80]:
                midpoint = max(0.0, (float(segment.start) + float(segment.end)) / 2.0)
                active = self._subtitle_band_edge_density(capture, midpoint, fps, frame_count, cv2, np)
                before = max(0.0, float(segment.start) - min(0.25, max(0.05, segment.duration / 3.0)))
                after = float(segment.end) + min(0.25, max(0.05, segment.duration / 3.0))
                inactive = [
                    self._subtitle_band_edge_density(capture, before, fps, frame_count, cv2, np),
                    self._subtitle_band_edge_density(capture, after, fps, frame_count, cv2, np),
                ]
                if active is not None:
                    active_values.append(active)
                inactive_values.extend(value for value in inactive if value is not None)
            capture.release()
            if not active_values:
                raise RuntimeError("no subtitle cue frames could be sampled")
            active_mean = float(np.mean(active_values))
            inactive_mean = float(np.mean(inactive_values)) if inactive_values else 0.0
            contrast_gain = active_mean - inactive_mean
            visible_ratio = sum(value > max(0.015, inactive_mean + 0.01) for value in active_values) / len(active_values)
            score = max(0.0, min(1.0, 0.5 * min(1.0, visible_ratio) + 0.5 * min(1.0, max(0.0, contrast_gain) / 0.08)))
            audit = {
                "status": "available",
                "sampled_cues": len(active_values),
                "visible_ratio": round(visible_ratio, 3),
                "active_edge_density": round(active_mean, 4),
                "inactive_edge_density": round(inactive_mean, 4),
                "contrast_gain": round(contrast_gain, 4),
                "score": round(score, 3),
                "issues": [],
            }
            if visible_ratio < 0.5:
                audit["issues"].append("Subtitle cues are not visibly distinct from nearby frames in the lower safe area.")
            elif contrast_gain < 0.01:
                audit["issues"].append("Rendered subtitle contrast against the lower safe area is weak; review font, outline, and background treatment.")
            return audit
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "issues": []}

    @staticmethod
    def _subtitle_band_edge_density(capture, seconds, fps, frame_count, cv2, np) -> float | None:
        position = min(frame_count - 1, max(0, int(round(seconds * fps))))
        capture.set(cv2.CAP_PROP_POS_FRAMES, position)
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        height, width = frame.shape[:2]
        if height < 20 or width < 20:
            return None
        band = frame[int(height * 0.70):int(height * 0.98), :]
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 160)
        return float(np.mean(edges > 0))

    def _assess_source_segments(self, segments: List[ASRSegment]) -> List[QualityIssue]:
        issues: List[QualityIssue] = []
        if not segments:
            return [QualityIssue("error", "source_transcript", "Chinese source transcript has no segments")]

        ocr_like = [segment for segment in segments if "ocr" in segment.source]
        asr_only = [segment for segment in segments if "ocr" not in segment.source]
        fused = [segment for segment in segments if segment.source == "ocr_asr_fused"]
        if len(ocr_like) < max(1, int(len(segments) * 0.35)):
            issues.append(
                QualityIssue(
                    "warning",
                    "source_confidence",
                    "Too few segments came from OCR-visible subtitles; Chinese source may be dominated by ASR mistakes.",
                )
            )
        if asr_only and not ocr_like:
            issues.append(
                QualityIssue(
                    "warning",
                    "visual_audio_alignment",
                    "No OCR segments are present, so subtitles cannot be checked against visible on-screen text.",
                )
            )
        if len(fused) > max(1, int(len(segments) * 0.35)):
            issues.append(
                QualityIssue(
                    "warning",
                    "visual_audio_alignment",
                    "Many segments had OCR/ASR disagreement; Chinese source subtitles should be reviewed before trusting translation.",
                )
            )

        previous: Optional[ASRSegment] = None
        for index, segment in enumerate(segments, start=1):
            if segment.end <= segment.start:
                issues.append(QualityIssue("error", "source_timing", "Source segment has invalid timing", segment_index=index))
            if segment.duration < 0.35:
                issues.append(
                    QualityIssue(
                        "warning",
                        "source_timing",
                        "Source segment is very short and may be hard to align with speech or screen text.",
                        segment_index=index,
                    )
                )
            if segment.confidence is not None and segment.confidence < settings.OCR_MIN_CONFIDENCE:
                issues.append(
                    QualityIssue(
                        "warning",
                        "ocr_confidence",
                        f"OCR confidence is low: {segment.confidence:.2f}",
                        segment_index=index,
                    )
                )
            if previous and segment.start < previous.end - 0.05:
                issues.append(
                    QualityIssue(
                        "warning",
                        "source_timing",
                        "Source subtitle timing overlaps previous segment.",
                        segment_index=index,
                    )
                )
            previous = segment
        return issues

    def _assess_translation_segments(
        self,
        source_segments: List[ASRSegment],
        translated_segments: List[ASRSegment],
        language: str,
    ) -> tuple[List[QualityIssue], Dict[str, Any]]:
        issues: List[QualityIssue] = []
        max_cps = 18.0 if language == "en" else 16.0
        cps_values: List[float] = []
        if len(source_segments) != len(translated_segments):
            issues.append(
                QualityIssue(
                    "error",
                    "segment_count",
                    f"Translation segment count {len(translated_segments)} does not match source {len(source_segments)}.",
                    language,
                )
            )

        for index, (source, translated) in enumerate(zip(source_segments, translated_segments), start=1):
            if abs(source.start - translated.start) > 0.02 or abs(source.end - translated.end) > 0.02:
                issues.append(
                    QualityIssue(
                        "error",
                        "timestamp_mismatch",
                        "Translated subtitle timing changed from source timing.",
                        language,
                        index,
                    )
                )
            if not translated.text.strip():
                issues.append(QualityIssue("error", "empty_translation", "Translated subtitle is empty.", language, index))
                continue
            cps = len(translated.text) / max(translated.duration, 0.1)
            cps_values.append(cps)
            if cps > max_cps:
                issues.append(
                    QualityIssue(
                        "warning",
                        "reading_speed",
                        f"Translated line may be too long for the subtitle duration: {cps:.1f} chars/sec.",
                        language,
                        index,
                    )
                )
        return issues, {
            "segments": len(translated_segments),
            "avg_chars_per_second": round(sum(cps_values) / len(cps_values), 2) if cps_values else 0.0,
            "max_chars_per_second": round(max(cps_values), 2) if cps_values else 0.0,
        }

    def _run_llm_review(
        self,
        source_segments: List[ASRSegment],
        translations: Dict[str, List[ASRSegment]],
        story_context: Dict[str, Any],
        heuristic_issues: List[QualityIssue],
    ) -> Dict[str, Any]:
        if settings.TRANSLATION_BACKEND not in {"deepseek", "local_llm"}:
            return {"status": "skipped", "reason": f"backend {settings.TRANSLATION_BACKEND} does not support LLM QA"}

        prompt = self._build_llm_review_prompt(source_segments, translations, story_context, heuristic_issues)
        try:
            service = SubtitleTranslationService()
            if settings.TRANSLATION_BACKEND == "deepseek":
                response = service._call_deepseek(prompt)
            else:
                from src.services.llm_service import get_llm_service

                response = get_llm_service().generate(
                    prompt,
                    max_tokens=3072,
                    temperature=0.1,
                    top_p=0.8,
                    stop=None,
                )
            payload = service._extract_json(response)
            return payload if isinstance(payload, dict) else {"status": "invalid_response"}
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def _build_llm_review_prompt(
        self,
        source_segments: List[ASRSegment],
        translations: Dict[str, List[ASRSegment]],
        story_context: Dict[str, Any],
        heuristic_issues: List[QualityIssue],
    ) -> str:
        source_payload = [
            {
                "index": index,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "duration": round(segment.duration, 3),
                "source": segment.source,
                "role": self._segment_role(segment.source),
                "confidence": segment.confidence,
                "text": segment.text,
            }
            for index, segment in enumerate(source_segments, start=1)
        ]
        translation_payload = {
            language: [
                {
                    "index": index,
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "duration": round(segment.duration, 3),
                    "source": segment.source,
                    "role": self._segment_role(segment.source),
                    "text": segment.text,
                }
                for index, segment in enumerate(segments, start=1)
            ]
            for language, segments in translations.items()
        }
        return (
            "You are a senior QA reviewer for short-drama localization.\n"
            "Evaluate three things: whether the Chinese source transcript is semantically plausible from OCR/ASR, "
            "whether each English/target translation is natural and faithful to the story, and whether timing is readable.\n"
            "Use OCR-visible segments as stronger evidence than ASR-only segments. "
            "Distinguish main_subtitle from background_audio: main_subtitle should match visible Chinese subtitles, "
            "while background_audio should provide important off-screen narration or speech when no visible subtitle exists. "
            "Review Chinese first: if the Chinese source is likely wrong or out of sync, mark the target translation as needs_review "
            "even when the English is fluent. Flag lines where the Chinese source likely needs correction before translation.\n"
            "Return strict JSON only in this format: "
            '{"status":"passed|needs_review","score":0.0,'
            '"source_language_review":{"status":"...","issues":["..."]},'
            '"target_language_review":{"en":{"status":"...","issues":["..."]}},'
            '"alignment_review":{"status":"...","issues":["..."]},'
            '"recommended_fixes":[{"segment_index":1,"language":"zh|en","issue":"...","suggestion":"..."}]}.\n'
            f"Story context:\n{json.dumps(story_context, ensure_ascii=False)}\n"
            f"Heuristic issues:\n{json.dumps([asdict(issue) for issue in heuristic_issues], ensure_ascii=False)}\n"
            f"Chinese source segments:\n{json.dumps(source_payload, ensure_ascii=False)}\n"
            f"Translated segments:\n{json.dumps(translation_payload, ensure_ascii=False)}"
        )

    def _issues_from_llm_review(self, review: Dict[str, Any]) -> List[QualityIssue]:
        issues: List[QualityIssue] = []
        if review.get("status") == "needs_review":
            issues.append(QualityIssue("warning", "llm_review", "LLM QA marked this job as needs_review."))
        for fix in review.get("recommended_fixes", []) if isinstance(review.get("recommended_fixes"), list) else []:
            if not isinstance(fix, dict):
                continue
            language = str(fix.get("language", "")).strip() or None
            segment = fix.get("segment_index")
            try:
                segment_index = int(segment) if segment is not None else None
            except Exception:
                segment_index = None
            message = str(fix.get("issue", fix.get("suggestion", ""))).strip()
            if message:
                issues.append(QualityIssue("warning", "llm_recommended_fix", message, language, segment_index))
        return issues

    def _source_summary(self, segments: List[ASRSegment]) -> Dict[str, Any]:
        source_counts: Dict[str, int] = {}
        for segment in segments:
            source_counts[segment.source] = source_counts.get(segment.source, 0) + 1
        total_duration = segments[-1].end - segments[0].start if segments else 0.0
        return {
            "segments": len(segments),
            "duration": round(total_duration, 3),
            "source_counts": source_counts,
        }

    def _segment_role(self, source: str) -> str:
        if source == "background_asr":
            return "background_audio"
        if "ocr" in source:
            return "main_subtitle"
        return "audio_dialogue"

    def _score(self, issues: List[QualityIssue]) -> float:
        score = 1.0
        for issue in issues:
            if issue.severity == "error":
                score -= 0.18
            elif issue.severity == "warning":
                score -= 0.05
        return round(max(0.0, min(1.0, score)), 3)

    def _needs_review(self, issues: List[QualityIssue]) -> bool:
        blocking_categories = {
            "visual_audio_alignment",
            "source_confidence",
            "llm_review",
        }
        return any(issue.severity == "error" or issue.category in blocking_categories for issue in issues)

    def _load_story_context(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _load_segments(self, path: Path) -> List[ASRSegment]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("segments", payload if isinstance(payload, list) else [])
        if not isinstance(items, list):
            return []
        segments: List[ASRSegment] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            start = float(item.get("start", item.get("start_time", 0.0)))
            end = float(item.get("end", start + float(item.get("duration", 0.0))))
            source = str(item.get("source", "subtitle"))
            confidence = item.get("confidence")
            segments.append(
                ASRSegment(
                    start=start,
                    end=end,
                    text=text,
                    source=source,
                    confidence=None if confidence is None else float(confidence),
                )
            )
        return segments
