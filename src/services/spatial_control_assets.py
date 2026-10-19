"""Project-level spatial continuity asset packs for short-drama generation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.database.models import Character, Project, Scene
from src.services.character_turnaround_album import CharacterTurnaroundAlbumService, PRODUCTION_TURNAROUND_VIEWS
from src.services.video_director_service import get_video_director_service
from src.utils.atomic_json import write_json_atomic
from src.utils.storage import storage_manager


class SpatialControlAssetService:
    """Freeze per-shot camera, blocking, and control-reference contracts."""

    PLANNER_CONTRACT_VERSION = "spatial-director-v2"
    REQUIRED_CONTROL_TYPES = ("pose", "depth", "camera", "character_turnaround")

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
        write_json_atomic(path, manifest)
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
            return {"status": "missing", "missing": ["spatial_asset_pack"], "control_gaps": [], "current": current}
        if stored.get("status") != "frozen":
            return {"status": "invalid", "missing": ["frozen_status"], "control_gaps": [], "manifest": stored, "current": current}
        stale = []
        if stored.get("planner_contract_version") != self.PLANNER_CONTRACT_VERSION:
            stale.append("planner_contract_version")
        if tuple(stored.get("required_control_types") or []) != self.REQUIRED_CONTROL_TYPES:
            stale.append("required_control_types")
        if stored.get("project_signature") != current.get("project_signature"):
            stale.append("project_signature")
        stored_scenes = {item.get("scene_number"): item for item in stored.get("scenes", []) if isinstance(item, dict)}
        current_scenes = {item.get("scene_number"): item for item in current.get("scenes", []) if isinstance(item, dict)}
        if sorted(stored_scenes) != sorted(current_scenes):
            stale.append("scene_set")
        scene_stale = []
        control_gaps = []
        for number, current_item in current_scenes.items():
            stored_item = stored_scenes.get(number)
            if not stored_item:
                continue
            changed = [
                field for field in (
                    "source_hash",
                    "spatial_plan_hash",
                    "control_references_hash",
                    "turnaround_controls_hash",
                )
                if stored_item.get(field) != current_item.get(field)
            ]
            if changed:
                scene_stale.append({"scene_number": number, "changed": changed})
            control_references = stored_item.get("control_references")
            if not isinstance(control_references, dict):
                control_references = {}
            missing_controls = [
                f"{control_type}_reference_prompt"
                for control_type in ("pose", "depth", "camera")
                if not str(control_references.get(f"{control_type}_reference_prompt") or "").strip()
            ]
            if missing_controls:
                control_gaps.append({"scene_number": number, "missing": missing_controls})
                scene_stale.append({"scene_number": number, "changed": ["missing_control_references"]})
                stale.append("scene_contracts")
            turnaround_controls = stored_item.get("character_turnaround_controls")
            if not isinstance(turnaround_controls, dict):
                turnaround_controls = {}
            for character_name in current_item.get("visible_characters") or []:
                character_control = turnaround_controls.get(character_name)
                missing_turnaround = []
                if not isinstance(character_control, dict):
                    missing_turnaround = ["turnaround_album"]
                else:
                    if character_control.get("status") != "valid":
                        missing_turnaround.extend(character_control.get("missing") or [])
                        missing_turnaround.extend(character_control.get("stale") or [])
                        if not missing_turnaround:
                            missing_turnaround.append(str(character_control.get("status") or "invalid"))
                    else:
                        views = character_control.get("views") if isinstance(character_control.get("views"), dict) else {}
                        for view in PRODUCTION_TURNAROUND_VIEWS:
                            item = views.get(view)
                            if not isinstance(item, dict) or not str(item.get("path") or "").strip():
                                missing_turnaround.append(f"view:{view}")
                            elif not str(item.get("control_prompt") or "").strip():
                                missing_turnaround.append(f"control_prompt:{view}")
                missing_turnaround = list(dict.fromkeys(str(item) for item in missing_turnaround))
                if missing_turnaround:
                    control_gaps.append({
                        "scene_number": number,
                        "control_type": "character_turnaround",
                        "character": character_name,
                        "missing": missing_turnaround,
                    })
                    scene_stale.append({"scene_number": number, "changed": ["missing_character_turnaround_controls"]})
                    stale.append("scene_contracts")
        if scene_stale:
            stale.append("scene_contracts")
        return {
            "status": "valid" if not stale else "stale",
            "stale": stale,
            "scene_stale": scene_stale,
            "control_gaps": control_gaps,
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

    def get_scene_contract(self, project_id: int, scene_number: int) -> dict | None:
        """Return the frozen, provider-facing contract for one scene.

        Generation must use the exact scene contract that was approved by the
        spatial freeze step.  Returning only a compact envelope keeps provider
        metadata auditable without requiring the task to rebuild the project
        manifest on every retry.
        """
        pack = self.get_project_pack(project_id)
        if not isinstance(pack, dict) or pack.get("status") != "frozen":
            return None
        scene = next(
            (
                item for item in pack.get("scenes", [])
                if isinstance(item, dict) and item.get("scene_number") == scene_number
            ),
            None,
        )
        if not scene:
            return None
        contract_payload = {
            "scene_number": scene_number,
            "spatial_plan": scene.get("spatial_plan") or {},
            "control_references": scene.get("control_references") or {},
            "character_turnaround_controls": scene.get("character_turnaround_controls") or {},
            "source_hash": scene.get("source_hash"),
            "spatial_plan_hash": scene.get("spatial_plan_hash"),
            "control_references_hash": scene.get("control_references_hash"),
            "turnaround_controls_hash": scene.get("turnaround_controls_hash"),
        }
        return {
            "planner_contract_version": pack.get("planner_contract_version"),
            "required_control_types": list(pack.get("required_control_types") or []),
            "project_signature": pack.get("project_signature"),
            "scene_contract_hash": self._hash(contract_payload),
            **contract_payload,
        }

    def build_current_manifest(
        self,
        project: Project,
        scenes: list[Scene],
        characters: list[Character],
    ) -> dict:
        script_scenes = self._script_scene_map(project)
        character_by_name = {character.name: character for character in characters}
        turnaround_service = CharacterTurnaroundAlbumService()
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
            turnaround_controls = self._scene_turnaround_controls(
                visible_names,
                character_by_name,
                turnaround_service,
            )
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
                "turnaround_controls_hash": self._hash(turnaround_controls),
                "visible_characters": visible_names,
                "spatial_plan": spatial_plan,
                "control_references": control_references,
                "character_turnaround_controls": turnaround_controls,
            })
        project_signature = self._hash({
            "project_id": project.id,
            "planner_contract_version": self.PLANNER_CONTRACT_VERSION,
            "required_control_types": self.REQUIRED_CONTROL_TYPES,
            "scene_numbers": [item["scene_number"] for item in scene_items],
            "source_hashes": [item["source_hash"] for item in scene_items],
            "spatial_plan_hashes": [item["spatial_plan_hash"] for item in scene_items],
            "turnaround_hashes": [item["turnaround_controls_hash"] for item in scene_items],
        })
        return {
            "version": 2,
            "planner_contract_version": self.PLANNER_CONTRACT_VERSION,
            "status": "draft",
            "project_id": project.id,
            "project_signature": project_signature,
            "required_control_types": list(self.REQUIRED_CONTROL_TYPES),
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

    def _scene_turnaround_controls(
        self,
        visible_names: list[str],
        character_by_name: dict[str, Character],
        turnaround_service: CharacterTurnaroundAlbumService,
    ) -> dict:
        controls = {}
        for name in visible_names:
            character = character_by_name.get(name)
            if not character:
                continue
            validation = turnaround_service.validate_album(character)
            manifest = validation.get("manifest") if isinstance(validation.get("manifest"), dict) else {}
            views = manifest.get("views") if isinstance(manifest.get("views"), dict) else {}
            controls[name] = {
                "status": validation.get("status"),
                "identity_spec_hash": manifest.get("identity_spec_hash"),
                "missing": validation.get("missing", []),
                "stale": validation.get("stale", []),
                "views": {
                    view: {
                        "path": (views.get(view) or {}).get("path"),
                        "sha256": (views.get(view) or {}).get("sha256"),
                        "control_prompt": (views.get(view) or {}).get("control_prompt"),
                    }
                    for view in PRODUCTION_TURNAROUND_VIEWS
                    if isinstance(views.get(view), dict)
                },
            }
        return controls

    def _hash(self, payload) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
