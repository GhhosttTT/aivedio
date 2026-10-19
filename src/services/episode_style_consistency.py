"""Cross-shot visual style consistency evidence for generated episodes.

The local VLM reviews individual frames well, but a short drama can still feel
incoherent when exposure, colour, sharpness, or framing drifts between shots.
This audit is deliberately deterministic and conservative: it does not claim
to judge acting or taste, it only creates evidence for large technical style
drifts that should be fixed before final composition.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from src.config import settings


@dataclass(frozen=True)
class EpisodeStyleConsistencyReport:
    status: str
    scene_count: int
    sampled_count: int
    issues: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "episode_style_consistency",
            "status": self.status,
            "scene_count": self.scene_count,
            "sampled_count": self.sampled_count,
            "issue_count": len(self.issues),
            "issues": self.issues,
            "scenes": self.scenes,
            "thresholds": self.thresholds,
            "repair_queue": self._repair_queue(),
        }

    def _repair_queue(self) -> list[dict[str, Any]]:
        if not self.issues:
            return []
        scene_numbers = sorted({
            int(issue["scene_number"])
            for issue in self.issues
            if isinstance(issue.get("scene_number"), int)
        })
        return [{
            "priority": "high" if self.status == "needs_review" else "medium",
            "stage": "image",
            "action": "refine_project_style_consistency",
            "execution": "auto",
            "scene_number": scene_numbers[0] if len(scene_numbers) == 1 else None,
            "reason": "Episode visual style drifts across rendered keyframes: "
                      + "; ".join(issue["code"] for issue in self.issues[:3]),
            "recommendation": "Reapply the frozen style contract and regenerate the outlier keyframes before video composition.",
        }]


class EpisodeStyleConsistencyService:
    """Audit rendered keyframes against the episode's robust visual median."""

    THRESHOLDS = {
        "brightness_warning": 24.0,
        "brightness_blocker": 45.0,
        "saturation_warning": 0.14,
        "saturation_blocker": 0.24,
        "contrast_warning": 28.0,
        "contrast_blocker": 52.0,
        "sharpness_ratio_warning": 2.2,
        "sharpness_ratio_blocker": 3.5,
        "aspect_ratio_warning": 0.08,
        "aspect_ratio_blocker": 0.16,
    }

    @staticmethod
    def _configured_thresholds() -> dict[str, float]:
        return {
            "brightness_warning": float(settings.GENERATION_EPISODE_STYLE_BRIGHTNESS_WARNING),
            "brightness_blocker": float(settings.GENERATION_EPISODE_STYLE_BRIGHTNESS_BLOCKER),
            "saturation_warning": float(settings.GENERATION_EPISODE_STYLE_SATURATION_WARNING),
            "saturation_blocker": float(settings.GENERATION_EPISODE_STYLE_SATURATION_BLOCKER),
            "contrast_warning": float(settings.GENERATION_EPISODE_STYLE_CONTRAST_WARNING),
            "contrast_blocker": float(settings.GENERATION_EPISODE_STYLE_CONTRAST_BLOCKER),
            "sharpness_ratio_warning": float(settings.GENERATION_EPISODE_STYLE_SHARPNESS_RATIO_WARNING),
            "sharpness_ratio_blocker": float(settings.GENERATION_EPISODE_STYLE_SHARPNESS_RATIO_BLOCKER),
            "aspect_ratio_warning": float(settings.GENERATION_EPISODE_STYLE_ASPECT_RATIO_WARNING),
            "aspect_ratio_blocker": float(settings.GENERATION_EPISODE_STYLE_ASPECT_RATIO_BLOCKER),
        }

    def audit(self, project, scenes: list) -> EpisodeStyleConsistencyReport:
        ordered = sorted(scenes or [], key=lambda scene: scene.scene_number)
        thresholds = self._configured_thresholds()
        sampled: list[dict[str, Any]] = []
        missing_scene_numbers: list[int] = []
        for scene in ordered:
            path_value = getattr(scene, "image_path", None)
            if not path_value:
                missing_scene_numbers.append(scene.scene_number)
                continue
            metrics = self._image_metrics(Path(path_value))
            if metrics is None:
                missing_scene_numbers.append(scene.scene_number)
                continue
            sampled.append({"scene_number": scene.scene_number, **metrics})
        if not sampled:
            return EpisodeStyleConsistencyReport(
                "not_applicable", len(ordered), len(sampled), [], sampled, thresholds
            )

        issues: list[dict[str, Any]] = []
        for scene_number in missing_scene_numbers:
            issues.append({
                "severity": "high",
                "code": "missing_keyframe_evidence",
                "scene_number": scene_number,
                "evidence": "keyframe is missing or unreadable; episode style cannot be verified for every scene",
                "recommendation": "Generate or repair the missing keyframe before evaluating episode style consistency.",
            })
        if len(sampled) < 2:
            status = "needs_review" if issues else "not_applicable"
            return EpisodeStyleConsistencyReport(
                status, len(ordered), len(sampled), issues, sampled, thresholds
            )

        medians = {
            key: statistics.median(item[key] for item in sampled)
            for key in ("brightness", "saturation", "contrast", "sharpness", "aspect_ratio")
        }
        for item in sampled:
            scene_number = item["scene_number"]
            brightness_delta = abs(item["brightness"] - medians["brightness"])
            saturation_delta = abs(item["saturation"] - medians["saturation"])
            contrast_delta = abs(item["contrast"] - medians["contrast"])
            sharpness_ratio = max(item["sharpness"], 1.0) / max(medians["sharpness"], 1.0)
            inverse_sharpness_ratio = max(medians["sharpness"], 1.0) / max(item["sharpness"], 1.0)
            sharpness_drift = max(sharpness_ratio, inverse_sharpness_ratio)
            aspect_delta = abs(item["aspect_ratio"] - medians["aspect_ratio"])
            checks = (
                ("exposure_drift", brightness_delta, "brightness", thresholds["brightness_warning"], thresholds["brightness_blocker"]),
                ("saturation_drift", saturation_delta, "saturation", thresholds["saturation_warning"], thresholds["saturation_blocker"]),
                ("contrast_drift", contrast_delta, "contrast", thresholds["contrast_warning"], thresholds["contrast_blocker"]),
                ("sharpness_drift", sharpness_drift, "sharpness_ratio", thresholds["sharpness_ratio_warning"], thresholds["sharpness_ratio_blocker"]),
                ("framing_drift", aspect_delta, "aspect_ratio", thresholds["aspect_ratio_warning"], thresholds["aspect_ratio_blocker"]),
            )
            for code, value, metric, warning_limit, blocker_limit in checks:
                if value < warning_limit:
                    continue
                severity = "high" if value >= blocker_limit else "warning"
                issues.append({
                    "severity": severity,
                    "code": code,
                    "scene_number": scene_number,
                    "metric": metric,
                    "value": round(value, 4),
                    "episode_median": round(medians[metric], 4) if metric != "sharpness_ratio" else 1.0,
                    "evidence": f"scene {scene_number} differs from episode median on {metric}: {value:.3f}",
                    "recommendation": "Regenerate this keyframe with the frozen episode style contract and matching frame geometry.",
                })
            item["deviations"] = {
                "brightness": round(brightness_delta, 3),
                "saturation": round(saturation_delta, 3),
                "contrast": round(contrast_delta, 3),
                "sharpness_ratio": round(sharpness_drift, 3),
                "aspect_ratio": round(aspect_delta, 3),
            }
        status = "needs_review" if any(item["severity"] == "high" for item in issues) else ("warn" if issues else "passed")
        return EpisodeStyleConsistencyReport(status, len(ordered), len(sampled), issues, sampled, thresholds)

    def _image_metrics(self, path: Path) -> dict[str, Any] | None:
        try:
            with Image.open(path) as image:
                image = image.convert("RGB")
                image.thumbnail((256, 256), Image.Resampling.LANCZOS)
                gray = image.convert("L")
                hsv = image.convert("HSV")
                brightness = float(ImageStat.Stat(gray).mean[0])
                contrast = float(ImageStat.Stat(gray).stddev[0])
                saturation = float(ImageStat.Stat(hsv).mean[1]) / 255.0
                edge = gray.filter(ImageFilter.FIND_EDGES)
                sharpness = float(ImageStat.Stat(edge).mean[0])
                width, height = image.size
                if width <= 0 or height <= 0:
                    return None
                return {
                    "path": str(path),
                    "width": int(width),
                    "height": int(height),
                    "aspect_ratio": round(width / height, 5),
                    "brightness": round(brightness, 3),
                    "saturation": round(saturation, 5),
                    "contrast": round(contrast, 3),
                    "sharpness": round(sharpness, 3),
                }
        except (OSError, ValueError, TypeError):
            return None
