"""Audit whether an episode's generated clips share one provider context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GenerationContextAuditReport:
    status: str
    checked_scene_count: int
    context_count: int
    contexts: list[dict[str, Any]]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "generation_context_audit",
            "status": self.status,
            "checked_scene_count": self.checked_scene_count,
            "context_count": self.context_count,
            "contexts": self.contexts,
            "issues": self.issues,
            "issue_count": len(self.issues),
            "repair_queue": self._repair_queue(),
        }

    def _repair_queue(self) -> list[dict[str, Any]]:
        if not self.issues:
            return []
        return [{
            "priority": "high",
            "stage": "workflow",
            "action": "fix_video_output_contract",
            "execution": "setup_required",
            "scene_number": None,
            "reason": "; ".join(issue["code"] for issue in self.issues[:3]),
            "recommendation": "Regenerate the affected clips with one locked Provider model, output contract, and spatial project signature.",
        }]


class GenerationContextAuditService:
    """Fail closed when generated clips silently use incompatible contexts."""

    FIELDS = (
        "provider_name", "provider_model", "request_mode", "resolution",
        "output_format", "aspect_ratio", "spatial_project_signature",
    )

    def audit(self, scenes: list, reports: dict[str, Any]) -> GenerationContextAuditReport:
        contexts = []
        missing_context_scenes: list[int] = []
        for scene in sorted(scenes or [], key=lambda item: item.scene_number):
            has_video = bool(getattr(scene, "video_path", None))
            metadata = self._scene_metadata(scene)
            if not metadata:
                metadata = self._metadata_from_reports(scene.scene_number, reports)
            if not metadata and not has_video:
                continue
            context = self._context(scene.scene_number, metadata)
            if context:
                contexts.append(context)
            elif has_video:
                missing_context_scenes.append(scene.scene_number)
        if not contexts:
            return GenerationContextAuditReport("not_applicable", 0, 0, [], [])
        signatures = {self._signature(context) for context in contexts}
        issues: list[dict[str, Any]] = []
        if missing_context_scenes:
            issues.append({
                "severity": "high",
                "code": "missing_provider_context_evidence",
                "scene_numbers": missing_context_scenes,
                "evidence": (
                    "provider generation context is missing or incomplete for scene(s) "
                    + ", ".join(str(number) for number in missing_context_scenes)
                ),
                "recommendation": "Persist provider metadata and the request contract for every generated clip before delivery.",
            })
        if len(signatures) > 1:
            issues.append({
                "severity": "high",
                "code": "provider_context_drift",
                "scene_numbers": [item["scene_number"] for item in contexts],
                "evidence": f"{len(signatures)} incompatible generation contexts found across {len(contexts)} rendered scenes",
                "recommendation": "Lock model, task mode, output contract, and spatial project signature before retrying.",
            })
        identity_signatures = {
            str(context.get("character_identity_signature") or "").strip().lower()
            for context in contexts
            if str(context.get("character_identity_signature") or "").strip()
        }
        if len(identity_signatures) > 1:
            issues.append({
                "severity": "high",
                "code": "character_identity_context_drift",
                "scene_numbers": [
                    item["scene_number"] for item in contexts
                    if item.get("character_identity_signature")
                ],
                "evidence": (
                    f"{len(identity_signatures)} character identity reference signatures found across "
                    f"{len(contexts)} rendered scenes"
                ),
                "recommendation": "Regenerate affected shots with one frozen character-sheet asset pack.",
            })
        missing = [item["scene_number"] for item in contexts if not item.get("request_contract_hash")]
        if missing:
            issues.append({
                "severity": "warning",
                "code": "missing_request_contract_hash",
                "scene_numbers": missing,
                "evidence": f"scene(s) {', '.join(map(str, missing))} have Provider metadata without a request contract hash",
                "recommendation": "Persist the exact request contract before accepting a remote generation result.",
            })
        status = "needs_review" if any(item["severity"] == "high" for item in issues) else ("warn" if issues else "passed")
        return GenerationContextAuditReport(
            status,
            len(contexts) + len(missing_context_scenes),
            len(signatures),
            contexts,
            issues,
        )

    def _scene_metadata(self, scene) -> dict[str, Any] | None:
        video_path = getattr(scene, "video_path", None)
        if not video_path:
            return None
        path = Path(str(video_path)).with_suffix(".provider.json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _metadata_from_reports(self, scene_number: int, reports: dict[str, Any]) -> dict[str, Any] | None:
        for report in reports.values():
            if not isinstance(report, dict):
                continue
            for candidate in self._walk(report):
                if self._scene_number(candidate) != scene_number:
                    continue
                metadata = candidate.get("provider_metadata") or candidate.get("selected_provider_metadata")
                if isinstance(metadata, dict):
                    return metadata
        return None

    def _walk(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk(child)

    def _scene_number(self, candidate: dict[str, Any]) -> int | None:
        value = candidate.get("scene_number")
        if value is None and isinstance(candidate.get("scene"), dict):
            value = candidate["scene"].get("scene_number")
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    def _context(self, scene_number: int, metadata: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(metadata, dict):
            return None
        contract = metadata.get("request_contract") if isinstance(metadata.get("request_contract"), dict) else {}
        spatial = contract.get("spatial_asset_pack") if isinstance(contract.get("spatial_asset_pack"), dict) else {}
        values = {
            "scene_number": scene_number,
            "provider_name": metadata.get("provider_name") or metadata.get("provider"),
            "provider_model": metadata.get("provider_model") or metadata.get("requested_model") or contract.get("model"),
            "request_mode": metadata.get("request_mode") or contract.get("request_mode"),
            "resolution": metadata.get("requested_resolution") or contract.get("resolution"),
            "output_format": metadata.get("requested_output_format") or contract.get("output_format"),
            "aspect_ratio": metadata.get("requested_aspect_ratio") or contract.get("aspect_ratio"),
            "spatial_project_signature": spatial.get("project_signature"),
            "character_identity_signature": (
                metadata.get("character_identity_signature")
                or contract.get("character_identity_signature")
            ),
            "request_contract_hash": metadata.get("request_contract_hash") or contract.get("contract_hash"),
        }
        if not any(values.get(key) for key in self.FIELDS):
            return None
        return values

    def _signature(self, context: dict[str, Any]) -> tuple:
        return tuple(str(context.get(field) or "").strip().lower() for field in self.FIELDS)
