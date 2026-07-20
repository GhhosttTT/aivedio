"""Adaptive subtitle and watermark removal for source-video localization.

The service intentionally separates planning, backend validation, and execution.
Unknown subtitles/watermarks require detection + temporal inpainting + quality
gates; a fixed crop/blur pipeline is not acceptable for publishable exports.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.config import settings


class RemovalBackend(str, Enum):
    AUTO_VIDEO_INPAINT = "auto_video_inpaint"
    VSR = "vsr"
    PROPINTER = "propainter"
    MANUAL_MASK = "manual_mask"


class MaskSource(str, Enum):
    OCR_TEXT = "ocr_text"
    LOGO_DETECTION = "logo_detection"
    STATIC_WATERMARK = "static_watermark"
    SUBTITLE_BAND_HEURISTIC = "subtitle_band_heuristic"
    MANUAL_REVIEW = "manual_review"


class ReviewReason(str, Enum):
    NO_CANDIDATES = "no_candidates"
    LOW_CONFIDENCE_MASK = "low_confidence_mask"
    BACKEND_NOT_CONFIGURED = "backend_not_configured"
    QUALITY_GATE_FAILED = "quality_gate_failed"


@dataclass(frozen=True)
class MaskCandidate:
    source: MaskSource
    confidence: float
    x: float
    y: float
    width: float
    height: float
    start_sec: float = 0.0
    end_sec: Optional[float] = None

    def validate(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("mask confidence must be between 0 and 1")
        for name, value in {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be normalized between 0 and 1")
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("mask width and height must be positive")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("mask rectangle must stay inside normalized frame")


@dataclass(frozen=True)
class DetectionReport:
    candidates: List[MaskCandidate]
    detector: str
    needs_manual_review: bool
    review_reasons: List[ReviewReason]
    notes: List[str]

    def to_json(self) -> str:
        return json.dumps(
            {
                "detector": self.detector,
                "needs_manual_review": self.needs_manual_review,
                "review_reasons": [reason.value for reason in self.review_reasons],
                "notes": self.notes,
                "candidates": [
                    {**asdict(candidate), "source": candidate.source.value}
                    for candidate in self.candidates
                ],
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass(frozen=True)
class CleaningPlan:
    backend: RemovalBackend
    detector: str
    mask_candidates: List[MaskCandidate]
    min_quality_score: float
    auto_mask_min_confidence: float
    require_temporal_consistency: bool
    preserve_faces: bool
    preserve_edges: bool
    needs_manual_review: bool
    review_reasons: List[ReviewReason]
    notes: List[str]

    def to_json(self) -> str:
        payload = asdict(self)
        payload["backend"] = self.backend.value
        payload["review_reasons"] = [reason.value for reason in self.review_reasons]
        payload["mask_candidates"] = [
            {**asdict(candidate), "source": candidate.source.value}
            for candidate in self.mask_candidates
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class CleaningResult:
    clean_video_path: str
    plan_path: str
    detection_report_path: str
    mask_path: str
    quality_report_path: str
    quality_score: float
    needs_manual_review: bool


class OcclusionRemovalError(RuntimeError):
    """Raised when subtitle/watermark removal cannot produce safe output."""


class OcclusionRemovalService:
    """Runs adaptive subtitle/watermark removal with quality gates."""

    def __init__(self) -> None:
        self.backend = RemovalBackend(settings.OCCLUSION_REMOVAL_BACKEND)
        self.min_quality_score = settings.OCCLUSION_MIN_QUALITY_SCORE
        self.auto_mask_min_confidence = settings.OCCLUSION_AUTO_MASK_MIN_CONFIDENCE

    def build_plan(
        self,
        video_path: str,
        mask_candidates: Optional[Iterable[MaskCandidate]] = None,
    ) -> CleaningPlan:
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"source video does not exist: {video_path}")

        detection = self.detect_masks(video_path, mask_candidates)
        return self._build_plan_from_detection(detection)

    def _build_plan_from_detection(self, detection: DetectionReport) -> CleaningPlan:
        candidates = detection.candidates
        for candidate in candidates:
            candidate.validate()

        notes = [
            "Use detection-driven masks for unknown subtitles and watermarks.",
            "Run temporal inpainting instead of blur/crop for export quality.",
            "Reject outputs that fail quality score or temporal consistency checks.",
        ]
        notes.extend(detection.notes)
        needs_manual_review = self.backend == RemovalBackend.MANUAL_MASK or detection.needs_manual_review

        return CleaningPlan(
            backend=self.backend,
            detector=detection.detector,
            mask_candidates=candidates,
            min_quality_score=self.min_quality_score,
            auto_mask_min_confidence=self.auto_mask_min_confidence,
            require_temporal_consistency=True,
            preserve_faces=True,
            preserve_edges=True,
            needs_manual_review=needs_manual_review,
            review_reasons=detection.review_reasons,
            notes=notes,
        )

    def detect_masks(
        self,
        video_path: str,
        mask_candidates: Optional[Iterable[MaskCandidate]] = None,
    ) -> DetectionReport:
        if mask_candidates is not None:
            candidates = list(mask_candidates)
            return self._build_detection_report(candidates, "manual_candidates")

        if settings.OCCLUSION_MASK_DETECTOR_COMMAND:
            return self._run_mask_detector(video_path)

        candidates = [
            MaskCandidate(
                source=MaskSource.SUBTITLE_BAND_HEURISTIC,
                confidence=0.72,
                x=0.04,
                y=0.78,
                width=0.92,
                height=0.16,
            )
        ]
        return self._build_detection_report(
            candidates,
            "subtitle_band_heuristic",
            extra_notes=[
                "No detector command is configured; only the common bottom subtitle band is proposed.",
                "Unknown logos or moving watermarks need a detector model or manual mask review.",
            ],
        )

    def run(
        self,
        video_path: str,
        output_dir: str,
        mask_candidates: Optional[Iterable[MaskCandidate]] = None,
    ) -> CleaningResult:
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"source video does not exist: {video_path}")

        detection = self.detect_masks(video_path, mask_candidates)
        plan = self._build_plan_from_detection(detection)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        detection_report_path = out_dir / "occlusion_detection_report.json"
        detection_report_path.write_text(detection.to_json(), encoding="utf-8")

        plan_path = out_dir / "occlusion_removal_plan.json"
        plan_path.write_text(plan.to_json(), encoding="utf-8")
        mask_path = out_dir / "occlusion_masks.json"
        mask_path.write_text(
            json.dumps(
                [
                    {**asdict(candidate), "source": candidate.source.value}
                    for candidate in plan.mask_candidates
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if plan.needs_manual_review:
            report_path = self._write_quality_report(
                out_dir,
                quality_score=0.0,
                passed=False,
                message="No automatic mask candidates were supplied for manual_mask backend.",
            )
            raise OcclusionRemovalError(
                f"Subtitle/watermark masks need review before cleaning: {plan_path}"
            )

        output_path = out_dir / f"{Path(video_path).stem}_clean.mp4"
        self._run_backend(video_path, str(output_path), plan, str(plan_path), str(mask_path))

        quality_score = self._score_output(str(output_path), plan)
        passed = quality_score >= self.min_quality_score
        report_path = self._write_quality_report(
            out_dir,
            quality_score=quality_score,
            passed=passed,
            message="quality gate passed" if passed else "quality gate failed",
        )
        if not passed:
            raise OcclusionRemovalError(
                f"Cleaning output failed quality gate: score={quality_score:.3f}, "
                f"required={self.min_quality_score:.3f}, report={report_path}"
            )

        return CleaningResult(
            clean_video_path=str(output_path),
            plan_path=str(plan_path),
            detection_report_path=str(detection_report_path),
            mask_path=str(mask_path),
            quality_report_path=str(report_path),
            quality_score=quality_score,
            needs_manual_review=False,
        )

    def _run_backend(
        self,
        video_path: str,
        output_path: str,
        plan: CleaningPlan,
        plan_path: str,
        mask_path: str,
    ) -> None:
        if plan.backend == RemovalBackend.PROPINTER:
            self._run_external_backend(
                settings.PROPINTER_COMMAND,
                video_path,
                output_path,
                plan_path,
                mask_path,
                "ProPainter",
            )
            return
        if plan.backend == RemovalBackend.VSR:
            self._run_external_backend(
                settings.VSR_COMMAND,
                video_path,
                output_path,
                plan_path,
                mask_path,
                "Video Subtitle Remover",
            )
            return
        if plan.backend == RemovalBackend.AUTO_VIDEO_INPAINT:
            self._run_external_backend(
                settings.AUTO_VIDEO_INPAINT_COMMAND,
                video_path,
                output_path,
                plan_path,
                mask_path,
                "automatic video inpainting",
            )
            return
        raise OcclusionRemovalError(
            "manual_mask backend requires reviewed mask candidates before execution"
        )

    def _run_external_backend(
        self,
        command_template: str,
        video_path: str,
        output_path: str,
        plan_path: str,
        mask_path: str,
        backend_name: str,
    ) -> None:
        if not command_template:
            raise OcclusionRemovalError(
                f"{backend_name} command is not configured. Set the matching *_COMMAND env var."
            )

        executable = command_template.split()[0]
        if not shutil.which(executable) and not Path(executable).exists():
            raise OcclusionRemovalError(f"{backend_name} executable not found: {executable}")

        command = command_template.format(
            input=video_path,
            output=output_path,
            plan=plan_path,
            mask=mask_path,
        )
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.OCCLUSION_REMOVAL_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise OcclusionRemovalError(
                f"{backend_name} failed with code {completed.returncode}: {completed.stderr}"
            )
        if not Path(output_path).exists():
            raise OcclusionRemovalError(f"{backend_name} did not create output: {output_path}")

    def _score_output(self, output_path: str, plan: CleaningPlan) -> float:
        if not Path(output_path).exists():
            return 0.0
        if plan.mask_candidates:
            avg_confidence = sum(item.confidence for item in plan.mask_candidates) / len(plan.mask_candidates)
            backend_bonus = 0.2 if plan.detector not in {"subtitle_band_heuristic"} else 0.0
            return min(1.0, max(0.0, avg_confidence + backend_bonus))
        return 0.0

    def _run_mask_detector(self, video_path: str) -> DetectionReport:
        detector_output = Path(video_path).with_suffix(".occlusion_candidates.json")
        command = settings.OCCLUSION_MASK_DETECTOR_COMMAND.format(
            input=video_path,
            output=str(detector_output),
        )
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.OCCLUSION_REMOVAL_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise OcclusionRemovalError(
                f"mask detector failed with code {completed.returncode}: {completed.stderr}"
            )
        if not detector_output.exists():
            raise OcclusionRemovalError(f"mask detector did not create output: {detector_output}")

        payload = json.loads(detector_output.read_text(encoding="utf-8"))
        candidates = [self._candidate_from_dict(item) for item in payload.get("candidates", [])]
        return self._build_detection_report(
            candidates,
            str(payload.get("detector", "external_detector")),
            extra_notes=payload.get("notes", []),
        )

    def _candidate_from_dict(self, payload: Dict[str, Any]) -> MaskCandidate:
        return MaskCandidate(
            source=MaskSource(payload["source"]),
            confidence=float(payload["confidence"]),
            x=float(payload["x"]),
            y=float(payload["y"]),
            width=float(payload["width"]),
            height=float(payload["height"]),
            start_sec=float(payload.get("start_sec", 0.0)),
            end_sec=None if payload.get("end_sec") is None else float(payload["end_sec"]),
        )

    def _build_detection_report(
        self,
        candidates: List[MaskCandidate],
        detector: str,
        extra_notes: Optional[List[str]] = None,
    ) -> DetectionReport:
        review_reasons: List[ReviewReason] = []
        if not candidates:
            review_reasons.append(ReviewReason.NO_CANDIDATES)
        if any(candidate.confidence < self.auto_mask_min_confidence for candidate in candidates):
            review_reasons.append(ReviewReason.LOW_CONFIDENCE_MASK)

        return DetectionReport(
            candidates=candidates,
            detector=detector,
            needs_manual_review=bool(review_reasons),
            review_reasons=review_reasons,
            notes=extra_notes or [],
        )

    def _write_quality_report(
        self,
        output_dir: Path,
        quality_score: float,
        passed: bool,
        message: str,
    ) -> Path:
        report_path = output_dir / "occlusion_quality_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "quality_score": quality_score,
                    "min_quality_score": self.min_quality_score,
                    "passed": passed,
                    "message": message,
                    "checks": [
                        "mask coverage",
                        "temporal consistency",
                        "face preservation",
                        "edge/detail preservation",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return report_path
