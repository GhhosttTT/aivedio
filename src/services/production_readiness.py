"""Project-level production readiness checks for short-drama generation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.config import settings
from src.database.models import Character, Project, Scene
from src.services.character_service import get_character_manager
from src.services.character_identity_service import CharacterIdentityService, FACIAL_FIELDS, load_identity_spec
from src.services.script_generator import MIN_PRODUCTION_SCENES
from src.services.shot_complexity_service import ShotComplexityService
from src.services.video_engine_preflight import preflight_production_video_engine


@dataclass
class ReadinessIssue:
    code: str
    message: str
    severity: str = "blocker"

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message}


class ProductionReadinessService:
    """Build a single evidence report before expensive generation starts."""

    def __init__(self, db_session: Session):
        self.db = db_session

    def build_report(self, project_id: int, include_engine_preflight: bool = True) -> dict:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {
                "project_id": project_id,
                "status": "blocked",
                "blockers": [
                    ReadinessIssue("project_missing", f"Project does not exist: {project_id}").to_dict()
                ],
                "warnings": [],
                "checks": {},
                "action_items": [f"Create or restore project {project_id} before production."],
            }

        scenes = (
            self.db.query(Scene)
            .filter(Scene.project_id == project_id)
            .order_by(Scene.scene_number)
            .all()
        )
        characters = self.db.query(Character).filter(Character.project_id == project_id).all()
        blockers: list[ReadinessIssue] = []
        warnings: list[ReadinessIssue] = []
        checks = {
            "script": self._script_check(project, scenes, blockers),
            "characters": self._character_check(project, scenes, characters, blockers, warnings),
            "shot_complexity": self._shot_complexity_check(project, scenes, blockers, warnings),
            "reviewer": self._reviewer_check(warnings),
        }
        if include_engine_preflight:
            checks["video_engine"] = self._video_engine_check(blockers)

        action_items = [issue.message for issue in blockers + warnings]
        status = "blocked" if blockers else ("needs_review" if warnings else "ready")
        return {
            "project_id": project_id,
            "status": status,
            "blockers": [issue.to_dict() for issue in blockers],
            "warnings": [issue.to_dict() for issue in warnings],
            "checks": checks,
            "action_items": action_items,
        }

    def _script_check(self, project: Project, scenes: list[Scene], blockers: list[ReadinessIssue]) -> dict:
        scene_count = len(scenes)
        numbers = [scene.scene_number for scene in scenes]
        expected = list(range(1, scene_count + 1))
        if scene_count == 0:
            blockers.append(ReadinessIssue("no_scenes", "Generate a script and storyboard before production."))
        elif scene_count < MIN_PRODUCTION_SCENES and not settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK:
            blockers.append(ReadinessIssue(
                "too_few_atomic_scenes",
                f"Short-drama production needs at least {MIN_PRODUCTION_SCENES} atomic scenes; current project has {scene_count}.",
            ))
        if numbers != expected:
            blockers.append(ReadinessIssue(
                "non_contiguous_scene_numbers",
                "Scene numbers must be contiguous from 1 before production.",
            ))
        return {
            "scene_count": scene_count,
            "minimum_production_scenes": MIN_PRODUCTION_SCENES,
            "scene_numbers": numbers,
            "contiguous_scene_numbers": numbers == expected,
            "draft_fallback_enabled": settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK,
            "has_script_json": bool(project.script),
        }

    def _character_check(
        self,
        project: Project,
        scenes: list[Scene],
        characters: list[Character],
        blockers: list[ReadinessIssue],
        warnings: list[ReadinessIssue],
    ) -> dict:
        by_name = {character.name: character for character in characters}
        script_scenes = self._script_scene_map(project)
        visible_names: list[str] = []
        scene_payload = []
        for scene in scenes:
            names = self._visible_character_names(scene, script_scenes.get(scene.scene_number, {}))
            visible_names.extend(names)
            scene_payload.append({"scene_number": scene.scene_number, "visible_characters": names})
        required_names = sorted(set(visible_names))
        missing_records = [name for name in required_names if name not in by_name]
        if missing_records:
            blockers.append(ReadinessIssue(
                "missing_character_records",
                "Create character records for visible roles: " + ", ".join(missing_records),
            ))

        manager = get_character_manager()
        character_payload = []
        identity_specs = []
        missing_identity_specs = []
        incomplete_identity_specs = []
        missing_references = []
        missing_appearance = []
        for name in required_names:
            character = by_name.get(name)
            if not character:
                continue
            identity_spec = load_identity_spec(character.visual_description)
            missing_fields = self._missing_identity_fields(identity_spec)
            if not identity_spec:
                missing_identity_specs.append(name)
            elif missing_fields:
                incomplete_identity_specs.append({"name": name, "missing_fields": missing_fields})
            else:
                identity_specs.append(identity_spec)
            references = manager.get_character_references(character.id, project.id)
            if not references:
                missing_references.append(name)
            if not (character.appearance or "").strip():
                missing_appearance.append(name)
            character_payload.append({
                "id": character.id,
                "name": character.name,
                "has_appearance": bool((character.appearance or "").strip()),
                "has_identity_spec": bool(identity_spec),
                "missing_identity_fields": missing_fields,
                "reference_count": len(references),
            })
        if missing_identity_specs:
            blockers.append(ReadinessIssue(
                "missing_character_identity_bible",
                "Generate a structured identity bible for visible characters: " + ", ".join(missing_identity_specs),
            ))
        if incomplete_identity_specs:
            details = "; ".join(
                f"{item['name']} missing {', '.join(item['missing_fields'])}"
                for item in incomplete_identity_specs
            )
            blockers.append(ReadinessIssue(
                "incomplete_character_identity_bible",
                "Complete character identity bible fields: " + details,
            ))
        if missing_references:
            blockers.append(ReadinessIssue(
                "missing_character_references",
                "Approve at least one reference image for visible characters: " + ", ".join(missing_references),
            ))
        if missing_appearance:
            warnings.append(ReadinessIssue(
                "missing_character_appearance",
                "Add detailed face/body/outfit anchors for characters: " + ", ".join(missing_appearance),
                severity="warning",
            ))
        distinctiveness = CharacterIdentityService().distinctiveness_report(identity_specs)
        if distinctiveness.get("status") == "needs_revision":
            blockers.append(ReadinessIssue(
                "character_identities_too_similar",
                "Revise character identity bibles; at least one visible character pair is too similar.",
            ))
        return {
            "total_characters": len(characters),
            "visible_character_names": required_names,
            "missing_records": missing_records,
            "missing_identity_specs": missing_identity_specs,
            "incomplete_identity_specs": incomplete_identity_specs,
            "missing_references": missing_references,
            "missing_appearance": missing_appearance,
            "distinctiveness": distinctiveness,
            "characters": character_payload,
            "scenes": scene_payload,
        }

    def _shot_complexity_check(
        self,
        project: Project,
        scenes: list[Scene],
        blockers: list[ReadinessIssue],
        warnings: list[ReadinessIssue],
    ) -> dict:
        script_scenes = self._script_scene_map(project)
        service = ShotComplexityService()
        reports = []
        for scene in scenes:
            visible = self._visible_character_names(scene, script_scenes.get(scene.scene_number, {}))
            report = service.diagnose(scene.visual_description or "", visible, scene.dialogue or "").to_dict()
            reports.append({
                "scene_number": scene.scene_number,
                "status": report["status"],
                "score": report["score"],
                "reasons": report["reasons"],
                "recommendations": report["recommendations"],
            })
        needs_split = [item for item in reports if item["status"] == "needs_split"]
        warn = [item for item in reports if item["status"] == "warn"]
        if needs_split:
            scene_numbers = ", ".join(str(item["scene_number"]) for item in needs_split)
            blockers.append(ReadinessIssue(
                "overloaded_shots",
                f"Split overloaded scenes before production: {scene_numbers}.",
            ))
        elif warn:
            scene_numbers = ", ".join(str(item["scene_number"]) for item in warn)
            warnings.append(ReadinessIssue(
                "complex_shot_warnings",
                f"Review complex scenes before final generation: {scene_numbers}.",
                severity="warning",
            ))
        return {
            "status": "needs_split" if needs_split else ("warn" if warn else "passed"),
            "summary": {"total": len(reports), "needs_split": len(needs_split), "warn": len(warn)},
            "scenes": reports,
        }

    def _video_engine_check(self, blockers: list[ReadinessIssue]) -> dict:
        report = preflight_production_video_engine()
        if report.get("status") != "ready_for_production_video_test":
            detail = "; ".join(report.get("action_items") or ["Configure a production video engine."])
            blockers.append(ReadinessIssue("video_engine_not_ready", detail))
        return report

    def _reviewer_check(self, warnings: list[ReadinessIssue]) -> dict:
        backend = settings.LOCAL_REVIEW_BACKEND.lower().strip()
        configured = backend == "llama_cpp" and bool(settings.LOCAL_REVIEW_BASE_URL and settings.LOCAL_REVIEW_MODEL)
        if backend != "llama_cpp":
            warnings.append(ReadinessIssue(
                "review_backend_not_llama_cpp",
                "Use LOCAL_REVIEW_BACKEND=llama_cpp for the local review path requested for this platform.",
                severity="warning",
            ))
        if not configured:
            warnings.append(ReadinessIssue(
                "reviewer_not_configured",
                "Configure LOCAL_REVIEW_BASE_URL and LOCAL_REVIEW_MODEL for local VLM review.",
                severity="warning",
            ))
        if not settings.GENERATION_REQUIRE_IMAGE_REVIEW:
            warnings.append(ReadinessIssue(
                "image_review_not_required",
                "Enable GENERATION_REQUIRE_IMAGE_REVIEW=true before claiming production visual quality.",
                severity="warning",
            ))
        if not settings.GENERATION_REQUIRE_VIDEO_REVIEW:
            warnings.append(ReadinessIssue(
                "video_review_not_required",
                "Enable GENERATION_REQUIRE_VIDEO_REVIEW=true before claiming production video quality.",
                severity="warning",
            ))
        return {
            "backend": settings.LOCAL_REVIEW_BACKEND,
            "base_url": settings.LOCAL_REVIEW_BASE_URL,
            "model": settings.LOCAL_REVIEW_MODEL,
            "configured": configured,
            "image_review_required": settings.GENERATION_REQUIRE_IMAGE_REVIEW,
            "video_review_required": settings.GENERATION_REQUIRE_VIDEO_REVIEW,
        }

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

    def _missing_identity_fields(self, identity_spec: dict | None) -> list[str]:
        required = FACIAL_FIELDS + ["wardrobe", "identity_anchor", "negative_identity"]
        if not identity_spec:
            return required
        return [field for field in required if not str(identity_spec.get(field) or "").strip()]
