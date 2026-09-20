"""Project-level visual style contracts for consistent short-drama output."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.database.models import Project, Scene
from src.utils.storage import storage_manager


class VisualStyleAssetService:
    VERSION = 1

    def freeze_project_style(
        self,
        project: Project,
        scenes: Iterable[Scene],
        *,
        style_prompt: str | None = None,
        negative_prompt: str | None = None,
        notes: str = "",
    ) -> dict:
        current = self.build_current_manifest(project, scenes)
        manifest = {
            **current,
            "status": "frozen",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "style_prompt": style_prompt.strip() if style_prompt and style_prompt.strip() else current["style_prompt"],
            "negative_prompt": negative_prompt.strip() if negative_prompt and negative_prompt.strip() else current["negative_prompt"],
            "notes": notes,
        }
        path = self._path(project.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def validate_project_style(self, project: Project, scenes: Iterable[Scene]) -> dict:
        path = self._path(project.id)
        current = self.build_current_manifest(project, scenes)
        if not path.is_file():
            return {"status": "missing", "path": str(path), "current": current}
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "invalid", "path": str(path), "error": str(exc), "current": current}
        stale = []
        for key in ("source_hash", "scene_style_hash"):
            if manifest.get(key) != current.get(key):
                stale.append(key)
        if not str(manifest.get("style_prompt") or "").strip():
            stale.append("style_prompt")
        if not str(manifest.get("negative_prompt") or "").strip():
            stale.append("negative_prompt")
        return {
            "status": "valid" if manifest.get("status") == "frozen" and not stale else "stale",
            "path": str(path),
            "stale": sorted(set(stale)),
            "manifest": manifest,
            "current": current,
        }

    def style_prompt_for_project(self, project_id: int) -> str:
        manifest = self._read_manifest(project_id)
        return str(manifest.get("style_prompt") or "").strip()

    def negative_prompt_for_project(self, project_id: int) -> str:
        manifest = self._read_manifest(project_id)
        return str(manifest.get("negative_prompt") or "").strip()

    def build_current_manifest(self, project: Project, scenes: Iterable[Scene]) -> dict:
        scene_items = [
            {
                "scene_number": scene.scene_number,
                "visual_description": scene.visual_description or "",
                "location": getattr(scene, "location", "") or "",
                "time_period": getattr(scene, "time_period", "") or "",
            }
            for scene in sorted(list(scenes), key=lambda item: item.scene_number)
        ]
        source = {
            "project_id": project.id,
            "theme": project.theme or "",
            "outline": project.outline or "",
            "scene_count": len(scene_items),
        }
        style_source = {
            **source,
            "locations": sorted({item["location"] for item in scene_items if item["location"]}),
            "time_periods": sorted({item["time_period"] for item in scene_items if item["time_period"]}),
            "scene_descriptions": [item["visual_description"] for item in scene_items],
        }
        return {
            "version": self.VERSION,
            "project_id": project.id,
            "source_hash": self._hash(source),
            "scene_style_hash": self._hash(style_source),
            "style_prompt": self._default_style_prompt(project, scene_items),
            "negative_prompt": self._default_negative_prompt(),
            "scene_count": len(scene_items),
        }

    def _default_style_prompt(self, project: Project, scenes: list[dict]) -> str:
        theme = (project.theme or project.description or "modern urban short-drama").strip()
        locations = [item["location"] for item in scenes if item.get("location")]
        location_hint = ", ".join(sorted(set(locations))[:3]) or "consistent modern short-drama locations"
        return (
            f"Project visual style bible: {theme}; vertical mobile short-drama look; "
            f"consistent color grade across all scenes; clean natural skin texture; "
            f"commercial but believable lighting; restrained cinematic contrast; "
            f"phone-screen readable faces and emotions; coherent wardrobe colors; "
            f"locations stay visually consistent: {location_hint}."
        )

    @staticmethod
    def _default_negative_prompt() -> str:
        return (
            "style drift between shots, random color grade, inconsistent lighting, cheap filter look, "
            "over-smoothed plastic skin, over-saturated colors, muddy shadows, blown highlights, "
            "random text, logo, watermark, inconsistent set decoration"
        )

    def _read_manifest(self, project_id: int) -> dict:
        path = self._path(project_id)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("status") == "frozen" else {}

    def _path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "style" / "visual_style_asset_pack.json"

    @staticmethod
    def _hash(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
