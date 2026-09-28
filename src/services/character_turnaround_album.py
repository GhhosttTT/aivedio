"""Character turnaround albums for multi-angle short-drama identity control."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.database.models import Character
from src.services.character_identity_service import load_identity_spec
from src.services.turnaround_quality import turnaround_expected_features
from src.utils.storage import storage_manager


REQUIRED_TURNAROUND_VIEWS = ("front", "side", "back")
PRODUCTION_TURNAROUND_VIEWS = (
    "front",
    "three_quarter_left",
    "three_quarter_right",
    "side",
    "back",
    "full_body",
    "expression_neutral",
    "expression_intense",
)


class CharacterTurnaroundAlbumService:
    """Freeze production character references before final video generation."""

    def freeze_album(
        self,
        character: Character,
        view_paths: dict[str, str],
        notes: str = "",
    ) -> dict:
        identity_spec = load_identity_spec(character.visual_description)
        if not identity_spec:
            raise ValueError("character identity bible is required before freezing turnaround album")
        required_views = PRODUCTION_TURNAROUND_VIEWS
        missing_views = [view for view in required_views if not view_paths.get(view)]
        if missing_views:
            raise ValueError("missing turnaround views: " + ", ".join(missing_views))
        normalized = {}
        for view in required_views:
            path = Path(view_paths[view])
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.is_file():
                raise ValueError(f"turnaround view file does not exist: {view}={path}")
            normalized[view] = str(path)
        manifest = {
            "version": 2,
            "status": "frozen",
            "character_id": character.id,
            "project_id": character.project_id,
            "character_name": character.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "required_views": list(REQUIRED_TURNAROUND_VIEWS),
            "production_required_views": list(PRODUCTION_TURNAROUND_VIEWS),
            "coverage": {
                "identity_angles": ["front", "three_quarter_left", "three_quarter_right", "side", "back"],
                "body_scale": ["full_body"],
                "expression_refs": ["expression_neutral", "expression_intense"],
            },
            "identity_spec_hash": self._json_hash(identity_spec),
            "identity_anchor": identity_spec.get("identity_anchor", character.appearance or ""),
            "views": {
                view: {
                    "path": path,
                    "sha256": self._file_hash(Path(path)),
                    "control_prompt": self._view_control_prompt(view, identity_spec),
                    "expected_features": turnaround_expected_features(view, identity_spec),
                }
                for view, path in normalized.items()
            },
            "notes": notes,
        }
        path = self._album_path(character.project_id, character.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def validate_album(self, character: Character) -> dict:
        identity_spec = load_identity_spec(character.visual_description)
        if not identity_spec:
            return {"status": "missing", "missing": ["identity_spec"]}
        manifest = self.get_album(character.project_id, character.id)
        if not manifest:
            return {"status": "missing", "missing": ["turnaround_album"]}
        if manifest.get("status") != "frozen":
            return {"status": "invalid", "missing": ["frozen_status"], "manifest": manifest}
        missing = []
        stale = []
        if manifest.get("identity_spec_hash") != self._json_hash(identity_spec):
            stale.append("identity_spec")
        views = manifest.get("views") if isinstance(manifest.get("views"), dict) else {}
        required_views = list(manifest.get("production_required_views") or PRODUCTION_TURNAROUND_VIEWS)
        for view in required_views:
            item = views.get(view)
            if not isinstance(item, dict) or not item.get("path"):
                missing.append(view)
                continue
            path = Path(item["path"])
            if not path.is_file():
                missing.append(view)
            elif item.get("sha256") != self._file_hash(path):
                stale.append(view)
        return {
            "status": "valid" if not missing and not stale else "stale",
            "missing": missing,
            "stale": sorted(set(stale)),
            "manifest": manifest,
        }

    def get_album(self, project_id: int, character_id: int) -> dict | None:
        path = self._album_path(project_id, character_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "invalid", "path": str(path)}

    def _album_path(self, project_id: int, character_id: int) -> Path:
        return storage_manager.base_path / "characters" / str(project_id) / str(character_id) / "turnaround_album.json"

    def _view_control_prompt(self, view: str, identity_spec: dict) -> str:
        anchor = identity_spec.get("identity_anchor", "")
        view_text = {
            "front": "front view, face readable, shoulders square to camera",
            "three_quarter_left": "45 degree left three-quarter view, both eyes readable, nose bridge contour visible",
            "three_quarter_right": "45 degree right three-quarter view, both eyes readable, nose bridge contour visible",
            "side": "strict side profile view, nose silhouette, hair outline, outfit side seam visible",
            "back": "back view, hairstyle back shape, outfit back silhouette, no face visible",
            "full_body": "full-body front model-sheet view, head-to-toe visible, same body scale",
            "expression_neutral": "front close-up neutral expression reference, relaxed face",
            "expression_intense": "front close-up intense short-drama expression reference, identity preserved",
        }[view]
        return f"{view_text}; preserve exact identity and wardrobe anchor: {anchor}"

    def _json_hash(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _file_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
