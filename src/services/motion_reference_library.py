"""Deterministic selection of approved motion-driving clips for local video models."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MotionReferenceLibraryError(ValueError):
    """Raised when a configured motion library is invalid."""


@dataclass(frozen=True)
class MotionReferenceSelection:
    asset_id: str
    path: str
    sha256: str
    matched_tags: tuple[str, ...]
    selection_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "path": self.path,
            "sha256": self.sha256,
            "matched_tags": list(self.matched_tags),
            "selection_reasons": list(self.selection_reasons),
        }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _string_list(value: object, *, label: str, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        suffix = " non-empty" if required else ""
        raise MotionReferenceLibraryError(f"Motion reference {label} must be a{suffix} list")
    normalized = []
    for item in value:
        text = str(item or "").strip().casefold()
        if not text:
            raise MotionReferenceLibraryError(f"Motion reference {label} cannot contain empty values")
        if text not in normalized:
            normalized.append(text)
    return normalized


def load_motion_reference_library(path: str | Path) -> list[dict[str, Any]]:
    manifest_path = Path(path)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise MotionReferenceLibraryError(f"Motion reference library does not exist: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MotionReferenceLibraryError(f"Invalid motion reference library: {exc}") from exc
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list) or not assets:
        raise MotionReferenceLibraryError("Motion reference library must contain a non-empty assets list")

    normalized = []
    seen_ids: set[str] = set()
    for index, item in enumerate(assets, start=1):
        if not isinstance(item, dict):
            raise MotionReferenceLibraryError(f"Motion reference asset #{index} must be an object")
        asset_id = str(item.get("id") or "").strip()
        if not asset_id or asset_id in seen_ids:
            raise MotionReferenceLibraryError(f"Motion reference asset #{index} needs a unique non-empty id")
        seen_ids.add(asset_id)
        asset_path = Path(str(item.get("path") or "").strip())
        if not asset_path.is_absolute():
            asset_path = manifest_path.parent / asset_path
        asset_path = asset_path.resolve()
        if not asset_path.is_file():
            raise MotionReferenceLibraryError(
                f"Motion reference asset {asset_id} does not exist: {asset_path}"
            )
        tags = _string_list(item.get("tags"), label=f"{asset_id} tags", required=True)
        roles = _string_list(item.get("shot_roles"), label=f"{asset_id} shot_roles")
        intensities = _string_list(
            item.get("action_intensities"), label=f"{asset_id} action_intensities",
        )
        minimum = int(item.get("min_characters", 1))
        maximum = int(item.get("max_characters", minimum))
        if minimum < 0 or maximum < minimum:
            raise MotionReferenceLibraryError(
                f"Motion reference asset {asset_id} has invalid character bounds"
            )
        normalized.append({
            "id": asset_id,
            "path": str(asset_path),
            "sha256": _file_sha256(asset_path),
            "tags": tags,
            "shot_roles": roles,
            "action_intensities": intensities,
            "min_characters": minimum,
            "max_characters": maximum,
            "priority": int(item.get("priority", 0)),
        })
    return normalized


def _searchable_motion_text(shot_plan: dict[str, Any]) -> str:
    values = [
        shot_plan.get("director_prompt"),
        shot_plan.get("performance_direction"),
        shot_plan.get("edit_intent"),
    ]
    spec = shot_plan.get("shot_spec")
    if isinstance(spec, dict):
        values.extend((spec.get("purpose"), spec.get("emotion"), spec.get("camera_movement")))
        for state in spec.get("character_states") or []:
            if isinstance(state, dict):
                values.extend((state.get("action"), state.get("start_state"), state.get("end_state")))
    return re.sub(r"\s+", " ", " ".join(str(value or "") for value in values)).casefold().strip()


def select_motion_reference(
    assets: list[dict[str, Any]],
    *,
    shot_plan: dict[str, Any],
) -> MotionReferenceSelection | None:
    role = str(shot_plan.get("shot_role") or "").strip().casefold()
    intensity = str(shot_plan.get("action_intensity") or "").strip().casefold()
    try:
        visible_count = max(0, int(shot_plan.get("visible_character_count") or 0))
    except (TypeError, ValueError):
        visible_count = 0
    searchable = _searchable_motion_text(shot_plan)
    ranked = []
    for asset in assets:
        roles = asset.get("shot_roles") or []
        intensities = asset.get("action_intensities") or []
        if roles and role not in roles:
            continue
        if intensities and intensity not in intensities:
            continue
        if not int(asset.get("min_characters", 0)) <= visible_count <= int(asset.get("max_characters", 99)):
            continue
        matched_tags = tuple(tag for tag in asset.get("tags") or [] if tag in searchable)
        if not matched_tags:
            continue
        reasons = [f"tag:{tag}" for tag in matched_tags]
        if roles:
            reasons.append(f"shot_role:{role}")
        if intensities:
            reasons.append(f"action_intensity:{intensity}")
        score = (
            len(matched_tags),
            int(bool(roles)),
            int(bool(intensities)),
            int(asset.get("priority", 0)),
        )
        ranked.append((score, str(asset.get("id") or ""), asset, tuple(reasons)))
    if not ranked:
        return None
    ranked.sort(key=lambda item: tuple(-value for value in item[0]) + (item[1],))
    _, _, selected, reasons = ranked[0]
    return MotionReferenceSelection(
        asset_id=str(selected["id"]),
        path=str(selected["path"]),
        sha256=str(selected["sha256"]),
        matched_tags=tuple(reason.removeprefix("tag:") for reason in reasons if reason.startswith("tag:")),
        selection_reasons=reasons,
    )


def resolve_motion_reference(
    manifest_path: str | Path | None,
    *,
    shot_plan: dict[str, Any],
) -> MotionReferenceSelection | None:
    if not str(manifest_path or "").strip():
        return None
    return select_motion_reference(
        load_motion_reference_library(str(manifest_path)),
        shot_plan=shot_plan,
    )
