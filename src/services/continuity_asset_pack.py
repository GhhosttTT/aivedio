"""Frozen project-level contracts for cross-shot continuity assets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.database.models import Project, Scene
from src.models.shot_specification import ShotSpecification
from src.utils.atomic_json import write_json_atomic
from src.utils.storage import storage_manager


class ContinuityAssetPackService:
    """Freeze auditable prop, wardrobe, injury, environment, and blocking state.

    The source of truth remains the editable per-shot specification. The frozen
    pack makes the approved snapshot explicit for generation and detects drift
    before an expensive batch renders from an outdated state contract.
    """

    VERSION = 1

    def freeze_project_pack(self, project: Project, scenes: list[Scene], notes: str = "") -> dict:
        manifest = self.build_current_manifest(project, scenes)
        manifest.update({
            "status": "frozen",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        })
        write_json_atomic(self._path(project.id), manifest)
        return manifest

    def validate_project_pack(self, project: Project, scenes: list[Scene]) -> dict:
        current = self.build_current_manifest(project, scenes)
        stored = self.get_project_pack(project.id)
        if not stored:
            return {"status": "missing", "current": current}
        if stored.get("status") != "frozen":
            return {"status": "invalid", "manifest": stored, "current": current}

        stale = []
        if stored.get("project_signature") != current["project_signature"]:
            stale.append("project_signature")
        stored_scenes = {item.get("scene_number"): item for item in stored.get("scenes", []) if isinstance(item, dict)}
        current_scenes = {item.get("scene_number"): item for item in current.get("scenes", []) if isinstance(item, dict)}
        if sorted(stored_scenes) != sorted(current_scenes):
            stale.append("scene_set")
        scene_stale = []
        for number, current_item in current_scenes.items():
            stored_item = stored_scenes.get(number)
            if not stored_item:
                continue
            changed = [
                field for field in ("source_hash", "continuity_asset_hash")
                if stored_item.get(field) != current_item.get(field)
            ]
            if changed:
                scene_stale.append({"scene_number": number, "changed": changed})
        if scene_stale:
            stale.append("scene_contracts")
        return {
            "status": "valid" if not stale else "stale",
            "stale": sorted(set(stale)),
            "scene_stale": scene_stale,
            "manifest": stored,
            "current": current,
        }

    def get_project_pack(self, project_id: int) -> dict | None:
        path = self._path(project_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "invalid", "path": str(path)}
        return payload if isinstance(payload, dict) else {"status": "invalid", "path": str(path)}

    def get_scene_contract(self, project_id: int, scene_number: int) -> dict | None:
        pack = self.get_project_pack(project_id)
        if not isinstance(pack, dict) or pack.get("status") != "frozen":
            return None
        scene = next((
            item for item in pack.get("scenes", [])
            if isinstance(item, dict) and item.get("scene_number") == scene_number
        ), None)
        if not isinstance(scene, dict):
            return None
        payload = {
            "scene_number": scene_number,
            "assets": scene.get("assets") or [],
            "source_hash": scene.get("source_hash"),
            "continuity_asset_hash": scene.get("continuity_asset_hash"),
        }
        return {
            "version": pack.get("version"),
            "project_signature": pack.get("project_signature"),
            "scene_contract_hash": self._hash(payload),
            **payload,
        }

    def build_current_manifest(self, project: Project, scenes: list[Scene]) -> dict:
        script_scenes = self._script_scene_map(project)
        scene_items = []
        for scene in sorted(scenes, key=lambda item: item.scene_number):
            source_item = script_scenes.get(scene.scene_number, {})
            raw_spec = source_item.get("shot_spec") if isinstance(source_item, dict) else None
            spec = ShotSpecification.model_validate(raw_spec) if isinstance(raw_spec, dict) else ShotSpecification()
            assets = [asset.model_dump() for asset in spec.continuity_assets]
            source = {
                "scene_number": scene.scene_number,
                "visual_description": scene.visual_description or "",
                "dialogue": scene.dialogue or "",
                "assets": assets,
            }
            scene_items.append({
                "scene_number": scene.scene_number,
                "source_hash": self._hash(source),
                "continuity_asset_hash": self._hash(assets),
                "assets": assets,
            })
        project_signature = self._hash({
            "version": self.VERSION,
            "project_id": project.id,
            "scenes": [
                {"scene_number": item["scene_number"], "source_hash": item["source_hash"]}
                for item in scene_items
            ],
        })
        return {
            "version": self.VERSION,
            "status": "draft",
            "project_id": project.id,
            "project_signature": project_signature,
            "asset_ids": sorted({asset["asset_id"] for item in scene_items for asset in item["assets"]}),
            "scenes": scene_items,
        }

    @staticmethod
    def prompt_directive(contract: dict | None, *, phase: str) -> str:
        if not isinstance(contract, dict):
            return ""
        key = "start_state" if phase == "opening" else "end_state"
        parts = []
        for asset in contract.get("assets") or []:
            if not isinstance(asset, dict) or not isinstance(asset.get(key), dict):
                continue
            state = ", ".join(f"{name}={value}" for name, value in asset[key].items())
            if state:
                parts.append(f"{asset.get('asset_id')}: {state}")
        if not parts:
            return ""
        label = "opening" if phase == "opening" else "ending"
        return f"Frozen continuity assets for the {label} frame: " + "; ".join(parts) + "."

    def _path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "continuity" / "continuity_asset_pack.json"

    @staticmethod
    def _script_scene_map(project: Project) -> dict[int, dict]:
        if not project.script:
            return {}
        try:
            payload = json.loads(project.script)
        except (TypeError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            item["scene_number"]: item
            for item in payload.get("scenes", [])
            if isinstance(item, dict) and isinstance(item.get("scene_number"), int)
        }

    @staticmethod
    def _hash(payload: object) -> str:
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
