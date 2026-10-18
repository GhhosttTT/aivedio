"""Validate that generated video output honors the requested media contract."""

from __future__ import annotations

import math
from pathlib import Path

from src.config import settings


RESOLUTION_SHORT_EDGE = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}


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
