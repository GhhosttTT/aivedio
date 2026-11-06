"""Apply deterministic short-drama coverage plans to persisted scenes."""

from __future__ import annotations

import json
import re
from typing import Any

from src.database.models import Project, ProjectStatus, Scene
from src.services.shot_complexity_service import ShotComplexityService


class ShotDecompositionError(ValueError):
    pass


class ShotDecompositionService:
    def __init__(self, db):
        self.db = db

    def plan(self, project: Project, scene: Scene) -> dict[str, Any]:
        script = self._script(project)
        script_item = next(
            (
                item for item in script.get("scenes", [])
                if isinstance(item, dict) and item.get("scene_number") == scene.scene_number
            ),
            {},
        )
        visible = script_item.get("characters") if isinstance(script_item, dict) else []
        if isinstance(visible, str):
            visible = [visible]
        if not isinstance(visible, list):
            visible = []
        visible = list(dict.fromkeys(
            str(name).strip() for name in visible if str(name).strip()
        ))
        if scene.character_name and scene.character_name not in visible:
            visible.insert(0, scene.character_name)
        report = ShotComplexityService().diagnose(
            scene.visual_description or "",
            visible,
            scene.dialogue or "",
        ).to_dict()
        suggestions = report.get("suggested_atomic_shots") or []
        if not suggestions:
            raise ShotDecompositionError(
                f"Scene {scene.scene_number} does not require deterministic decomposition"
            )
        return {
            "project_id": project.id,
            "source_scene_number": scene.scene_number,
            "source_status": report["status"],
            "source_score": report["score"],
            "source_reasons": report["reasons"],
            "atomic_shots": suggestions,
            "scene_count_delta": len(suggestions) - 1,
        }

    def apply(self, project: Project, scene: Scene) -> dict[str, Any]:
        if project.status == ProjectStatus.IN_PRODUCTION:
            raise ShotDecompositionError("Project is in production and cannot be decomposed")
        plan = self.plan(project, scene)
        atomic_shots = plan["atomic_shots"]
        delta = plan["scene_count_delta"]
        source_number = int(scene.scene_number)
        script = self._script(project)
        script_items = script.get("scenes")
        if not isinstance(script_items, list):
            raise ShotDecompositionError("Project script scenes must be a list")

        later_scenes = (
            self.db.query(Scene)
            .filter(Scene.project_id == project.id, Scene.scene_number > source_number)
            .order_by(Scene.scene_number.desc())
            .all()
        )
        for later in later_scenes:
            later.scene_number += delta
            self._clear_media(later)

        rebuilt_script = []
        source_script_item = None
        for item in script_items:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            number = item.get("scene_number")
            if number == source_number:
                source_script_item = item
                continue
            if isinstance(number, int) and number > source_number:
                item["scene_number"] = number + delta
            rebuilt_script.append(item)

        inherited_metadata = {
            key: value for key, value in (source_script_item or {}).items()
            if key not in {
                "scene_number", "description", "dialogue", "speaker", "characters",
                "shot_spec", "decomposition",
            }
        }
        created_scenes = []
        for offset, shot in enumerate(atomic_shots):
            number = source_number + offset
            visible = list(shot.get("visible_characters") or [])
            dialogue = self._dialogue_without_speaker_prefix(
                str(shot.get("dialogue") or ""), visible
            ) or None
            speaker = visible[0] if dialogue and len(visible) == 1 else None
            description = str(shot.get("visual_description") or "").strip()
            if not description:
                raise ShotDecompositionError("Atomic shot visual description cannot be empty")
            if offset == 0:
                target = scene
            else:
                target = Scene(project_id=project.id, scene_number=number, visual_description=description)
                self.db.add(target)
            target.scene_number = number
            target.visual_description = description
            target.dialogue = dialogue
            target.character_name = speaker
            self._clear_media(target)
            created_scenes.append(target)

            continuity_note = str(shot.get("continuity_note") or "").strip()
            item = {
                **inherited_metadata,
                "scene_number": number,
                "description": description,
                "dialogue": dialogue,
                "speaker": speaker,
                "characters": visible,
                "decomposition": {
                    "source_scene_number": source_number,
                    "order": shot.get("order"),
                    "shot_role": shot.get("shot_role"),
                    "primary_action": shot.get("primary_action"),
                    "camera": shot.get("camera"),
                    "camera_axis": shot.get("camera_axis"),
                    "screen_positions": dict(shot.get("screen_positions") or {}),
                    "eyeline_directions": dict(shot.get("eyeline_directions") or {}),
                    "required_engine_capabilities": list(
                        shot.get("required_engine_capabilities") or []
                    ),
                },
                "shot_spec": {
                    "purpose": str(shot.get("primary_action") or ""),
                    "shot_role": shot.get("shot_role"),
                    "required_engine_capabilities": list(
                        shot.get("required_engine_capabilities") or []
                    ),
                    "camera_movement": str(shot.get("camera") or ""),
                    "action_intensity": "low",
                    "performance_intensity": 3,
                    "continuity_constraints": [
                        item for item in (
                            continuity_note,
                            str(shot.get("camera_axis") or "").strip(),
                            "; ".join(
                                f"{name} stays {position}"
                                for name, position in (shot.get("screen_positions") or {}).items()
                            ),
                            "; ".join(
                                f"{name} keeps eyeline toward {direction}"
                                for name, direction in (shot.get("eyeline_directions") or {}).items()
                            ),
                        ) if item
                    ],
                    "character_states": [],
                    "continuity_assets": [],
                },
            }
            rebuilt_script.append(item)

        rebuilt_script.sort(key=lambda item: int(item.get("scene_number") or 0))
        script["scenes"] = rebuilt_script
        project.script = json.dumps(script, ensure_ascii=False)
        project.final_video_path = None
        project.status = ProjectStatus.SCRIPT_GENERATED
        self.db.commit()
        self.db.refresh(project)
        plan["applied"] = True
        plan["created_scene_numbers"] = [item.scene_number for item in created_scenes]
        plan["invalidated_scene_numbers"] = [
            item.scene_number for item in created_scenes + later_scenes
        ]
        plan["source_script_item_preserved"] = bool(source_script_item)
        return plan

    @staticmethod
    def _script(project: Project) -> dict:
        if not project.script:
            raise ShotDecompositionError("Project script is missing")
        try:
            script = json.loads(project.script)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ShotDecompositionError("Project script is invalid JSON") from exc
        if not isinstance(script, dict) or not isinstance(script.get("scenes"), list):
            raise ShotDecompositionError("Project script scenes must be a list")
        return script

    @staticmethod
    def _clear_media(scene: Scene) -> None:
        scene.image_prompt = None
        scene.image_path = None
        scene.video_path = None
        scene.audio_path = None
        scene.audio_duration = None
        scene.subtitle_path = None

    @staticmethod
    def _dialogue_without_speaker_prefix(dialogue: str, visible: list[str]) -> str:
        text = str(dialogue or "").strip()
        if len(visible) != 1:
            return text
        return re.sub(
            rf"^\s*{re.escape(visible[0])}\s*[：:]\s*",
            "",
            text,
            flags=re.I,
        ).strip()
