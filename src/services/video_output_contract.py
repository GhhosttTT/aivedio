"""Validate that generated video output honors the requested media contract."""

from __future__ import annotations

import math
import hashlib
import json
from pathlib import Path

from src.config import settings


RESOLUTION_SHORT_EDGE = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}


class VideoRequestPlanError(ValueError):
    """Raised when a sequence plan cannot be safely submitted to a provider."""


def validate_sequence_request_plan(
    shot_plan: dict | None,
    *,
    sequence_level: bool,
    expected_duration_seconds: float | None = None,
) -> None:
    """Fail closed on malformed sequence plans before a provider request is sent."""
    if not sequence_level:
        return
    if not isinstance(shot_plan, dict):
        raise VideoRequestPlanError("Sequence-level generation requires a shot plan")
    shots = shot_plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise VideoRequestPlanError("Sequence-level generation requires at least one shot")

    scene_numbers: set[int] = set()
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise VideoRequestPlanError(f"Sequence shot {index} must be an object")
        scene_number = shot.get("scene_number")
        if isinstance(scene_number, bool) or not isinstance(scene_number, int) or scene_number <= 0:
            raise VideoRequestPlanError(f"Sequence shot {index} needs a positive integer scene_number")
        if scene_number in scene_numbers:
            raise VideoRequestPlanError(f"Sequence plan contains duplicate scene_number={scene_number}")
        scene_numbers.add(scene_number)
        if shot.get("duration_seconds") is not None:
            duration = _positive_number(shot.get("duration_seconds"))
            if not duration:
                raise VideoRequestPlanError(f"Sequence shot {scene_number} needs a positive duration_seconds")

    timeline = shot_plan.get("sequence_timeline")
    if timeline is None:
        return
    if not isinstance(timeline, list) or len(timeline) != len(shots):
        raise VideoRequestPlanError("sequence_timeline must contain exactly one entry per sequence shot")
    previous_end = 0.0
    for index, item in enumerate(timeline, start=1):
        if not isinstance(item, dict):
            raise VideoRequestPlanError(f"Sequence timeline entry {index} must be an object")
        if item.get("scene_number") != shots[index - 1].get("scene_number"):
            raise VideoRequestPlanError(f"Sequence timeline entry {index} does not match its shot scene_number")
        start = _finite_number(item.get("start_seconds"))
        end = _finite_number(item.get("end_seconds"))
        if start < 0 or end <= start:
            raise VideoRequestPlanError(f"Sequence timeline entry {index} has invalid start/end seconds")
        if start < previous_end:
            raise VideoRequestPlanError("Sequence timeline overlaps or moves backwards")
        previous_end = end
    if expected_duration_seconds is not None:
        expected = _positive_number(expected_duration_seconds)
        if expected and abs(previous_end - expected) > 0.01:
            raise VideoRequestPlanError(
                f"Sequence timeline ends at {previous_end:.3f}s but request duration is {expected:.3f}s"
            )


def audit_video_output_contract(
    contract: dict | None,
    provider_metadata: dict | None,
    metrics: dict | None,
    output_path: str | Path,
) -> dict:
    """Return an evidence report without guessing when contract data is absent."""
    contract = contract if isinstance(contract, dict) else {}
    provider_metadata = provider_metadata if isinstance(provider_metadata, dict) else {}
    metrics = metrics if isinstance(metrics, dict) else {}
    if not contract:
        return {"status": "not_applicable", "issues": [], "checked": []}

    issues: list[dict] = []
    checked: list[str] = []
    contract_version = contract.get("provider_request_version")
    if isinstance(contract_version, int) and contract_version >= 2:
        checked.append("request_contract_integrity")
        required_fingerprint_fields = (
            "prompt_fingerprint",
            "negative_prompt_fingerprint",
            "shot_plan_fingerprint",
        )
        if any(field not in contract for field in required_fingerprint_fields):
            issues.append(_issue(
                "request_contract_fingerprints_missing",
                "Version 2 request contract is missing one or more control fingerprints.",
            ))
        if contract_version >= 3:
            required_control_fields = (
                "width",
                "height",
                "fps",
                "seed",
                "motion_bucket_id",
                "noise_aug_strength",
                "quality_mode",
                "repair_action",
                "quality_pipeline_fingerprint",
            )
            if any(field not in contract for field in required_control_fields):
                issues.append(_issue(
                    "request_contract_controls_missing",
                    "Version 3 request contract is missing one or more generation controls.",
                ))
        supplied_hash = str(contract.get("contract_hash") or "")
        canonical_contract = dict(contract)
        canonical_contract.pop("contract_hash", None)
        encoded = json.dumps(
            canonical_contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_hash = hashlib.sha256(encoded).hexdigest()
        if supplied_hash != expected_hash:
            issues.append(_issue(
                "request_contract_hash_mismatch",
                "Request contract hash does not match its recorded controls.",
            ))
    if metrics.get("status") != "available":
        issues.append(_issue("metrics_unavailable", "Output media metrics are unavailable."))
    else:
        resolution = str(contract.get("resolution") or "").lower()
        minimum_edge = RESOLUTION_SHORT_EDGE.get(resolution)
        short_edge = min(int(metrics.get("width") or 0), int(metrics.get("height") or 0))
        if minimum_edge:
            checked.append("resolution")
            if short_edge < minimum_edge:
                issues.append(_issue("resolution_drift", f"Requested {resolution} but output short edge is {short_edge}px."))
        expected_format = str(contract.get("output_format") or "").lower()
        actual_suffix = Path(output_path).suffix.lower().lstrip(".")
        if expected_format and actual_suffix:
            checked.append("output_format")
            if expected_format != actual_suffix:
                issues.append(_issue("output_format_drift", f"Requested {expected_format} but output path is .{actual_suffix}."))
        requested_duration = _positive_number(contract.get("duration_seconds"))
        actual_duration = _positive_number(metrics.get("duration_seconds"))
        if requested_duration and actual_duration:
            checked.append("duration")
            tolerance = max(
                settings.GENERATION_VIDEO_DURATION_SYNC_TOLERANCE_SECONDS,
                requested_duration * 0.08,
            )
            if abs(actual_duration - requested_duration) > tolerance:
                issues.append(_issue("duration_drift", f"Requested {requested_duration:.3f}s but output is {actual_duration:.3f}s."))
        audio_requested = bool(contract.get("generate_audio") or contract.get("reference_audio_count"))
        if audio_requested:
            checked.append("audio")
            if metrics.get("audio_present") is not True:
                issues.append(_issue("audio_missing", "Audio was requested but the output has no audio stream."))

    requested_model = str(contract.get("model") or "").strip()
    actual_model = str(provider_metadata.get("provider_model") or provider_metadata.get("requested_model") or "").strip()
    if requested_model and actual_model:
        checked.append("model")
        if requested_model != actual_model:
            issues.append(_issue("model_drift", f"Requested model {requested_model} but provider reported {actual_model}."))
    if contract.get("sequence_level_multi_shot") and contract.get("spatial_asset_pack"):
        checked.append("sequence_spatial_contracts")
        sequence_contracts = contract.get("sequence_shot_contracts")
        valid_contracts = [
            item for item in sequence_contracts or []
            if isinstance(item, dict)
            and item.get("scene_number") is not None
            and str(item.get("scene_contract_hash") or "").strip()
        ]
        if not isinstance(sequence_contracts, list) or not valid_contracts:
            issues.append(_issue(
                "sequence_spatial_contracts_missing",
                "Sequence-level generation has a frozen spatial asset pack but no per-shot spatial contracts.",
            ))
        elif len({item["scene_number"] for item in valid_contracts}) != len(valid_contracts):
            issues.append(_issue(
                "sequence_spatial_contracts_duplicate",
                "Sequence-level generation contains duplicate per-shot spatial contracts.",
            ))
    return {
        "status": "needs_review" if issues else "passed",
        "contract_hash": contract.get("contract_hash"),
        "checked": checked,
        "issues": issues,
    }


def _issue(code: str, message: str) -> dict:
    return {"code": code, "severity": "high", "message": message}


def _positive_number(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def _finite_number(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return -1.0
    return number if math.isfinite(number) else -1.0
