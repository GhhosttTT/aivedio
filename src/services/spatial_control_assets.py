"""Project-level spatial continuity asset packs for short-drama generation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.database.models import Character, Project, Scene
from src.services.video_director_service import get_video_director_service
from src.utils.storage import storage_manager


class SpatialControlAssetService:
    """Freeze per-shot camera, blocking, and control-reference contracts."""

    def freeze_project_pack(
        self,
        project: Project,
        scenes: list[Scene],
        characters: list[Character],
        notes: str = "",
    ) -> dict:
        manifest = self.build_current_manifest(project, scenes, characters)
        manifest["status"] = "frozen"
        manifest["created_at"] = datetime.now(timezone.utc).isoformat()
        manifest["notes"] = notes
        path = self._pack_path(project.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def validate_project_pack(
        self,
        project: Project,
        scenes: list[Scene],
        characters: list[Character],
    ) -> dict:
        current = self.build_current_manifest(project, scenes, characters)
        stored = self.get_project_pack(project.id)
        if not stored:
            return {"status": "missing", "missing": ["spatial_asset_pack"], "current": current}
        if stored.get("status") != "frozen":
            return {"status": "invalid", "missing": ["frozen_status"], "manifest": stored, "current": current}
        stale = []
        if stored.get("project_signature") != current.get("project_signature"):
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
                field for field in ("source_hash", "spatial_plan_hash", "control_references_hash")
                if stored_item.get(field) != current_item.get(field)
            ]
            if changed:
                scene_stale.append({"scene_number": number, "changed": changed})
        if scene_stale:
            stale.append("scene_contracts")
        return {
            "status": "valid" if not stale else "stale",
            "stale": stale,
            "scene_stale": scene_stale,
            "manifest": stored,
            "current": current,
        }

    def get_project_pack(self, project_id: int) -> dict | None:
        path = self._pack_path(project_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "invalid", "path": str(path)}

    def build_current_manifest(
        self,
        project: Project,
        scenes: list[Scene],
        characters: list[Character],
    ) -> dict:
        script_scenes = self._script_scene_map(project)
        character_by_name = {character.name: character for character in characters}
        director = get_video_director_service()
        scene_items = []
        for scene in sorted(scenes, key=lambda item: item.scene_number):
            visible_names = self._visible_character_names(scene, script_scenes.get(scene.scene_number, {}))
            visible_payload = [
                {"name": name, "appearance": character_by_name[name].appearance or ""}
                for name in visible_names
                if name in character_by_name
            ]
            shot_plan = director.plan_scene(scene, project.id, visible_payload)
            spatial_plan = shot_plan.spatial_plan or {}
            control_references = spatial_plan.get("control_references") or {}
            source_payload = {
                "scene_number": scene.scene_number,
                "visual_description": scene.visual_description or "",
                "dialogue": scene.dialogue or "",
                "visible_characters": visible_names,
            }
            scene_items.append({
                "scene_number": scene.scene_number,
                "source_hash": self._hash(source_payload),
                "spatial_plan_hash": self._hash(spatial_plan),
                "control_references_hash": self._hash(control_references),
                "visible_characters": visible_names,
                "spatial_plan": spatial_plan,
                "control_references": control_references,
            })
        project_signature = self._hash({
            "project_id": project.id,
            "scene_numbers": [item["scene_number"] for item in scene_items],
            "source_hashes": [item["source_hash"] for item in scene_items],
            "spatial_plan_hashes": [item["spatial_plan_hash"] for item in scene_items],
        })
        return {
            "version": 1,
            "status": "draft",
            "project_id": project.id,
            "project_signature": project_signature,
            "required_control_types": ["pose", "depth", "camera"],
            "scenes": scene_items,
        }

    def _pack_path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "spatial" / "spatial_asset_pack.json"

    def _script_scene_map(self, project: Project) -> dict[int, dict]:
        if not project.script:
            return {}
        try:
            payload = json.loads(project.script)
        except (TypeError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        result = {}
        for item in payload.get("scenes", []):
            if isinstance(item, dict) and isinstance(item.get("scene_number"), int):
                result[item["scene_number"]] = item
        return result

    def _visible_character_names(self, scene: Scene, script_scene: dict) -> list[str]:
        visible = script_scene.get("characters")
        if visible is None:
            visible = [scene.character_name] if scene.character_name and scene.character_name in (scene.visual_description or "") else []
        if isinstance(visible, str):
            visible = [visible]
        if not isinstance(visible, list):
            return []
        names = []
        for name in visible:
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
        return names

    def _hash(self, payload) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
