"""Quality gates shared by orchestration and direct composition calls."""

import json
import os
from pathlib import Path

from src.database.database import get_db
from src.database.models import Project, Scene, Task, TaskStatus
from src.services.generation_review import (
    GenerationReviewService, ReviewError, file_hash, fingerprint, require_passed, write_report,
)
from src.tasks.celery_app import celery_app
from src.services.task_recovery import load_production_video_options
from src.utils.storage import storage_manager


def current_story(project, scenes):
    original = json.loads(project.script) if project.script else {}
    return {"script": original.get("script", project.outline or project.theme or ""),
            "characters": [{"name": c.name, "description": c.description} for c in project.characters],
            "scenes": [{"scene_number": s.scene_number, "description": s.visual_description,
                        "dialogue": s.dialogue, "speaker": s.character_name} for s in scenes]}


def generation_signature(project, scenes):
    return fingerprint({"story": current_story(project, scenes), "assets": [
        {"scene": s.scene_number, "video": file_hash(Path(s.video_path)),
         "image": file_hash(Path(s.image_path)) if s.image_path else None,
         "audio": _optional_asset_hash(getattr(s, "audio_path", None)),
         "subtitle": _optional_asset_hash(getattr(s, "subtitle_path", None)),
         "audio_duration": getattr(s, "audio_duration", None) if isinstance(getattr(s, "audio_duration", None), (int, float)) else None}
        for s in scenes
    ], "character_assets": _character_asset_evidence(project)})


def _character_asset_evidence(project) -> list[dict]:
    """Include frozen character assets in the review invalidation signature."""
    characters = getattr(project, "characters", []) or []
    if not isinstance(characters, (list, tuple)) or not characters:
        return []
    try:
        from src.services.character_service import get_character_manager

        manager = get_character_manager()
    except (OSError, RuntimeError, TypeError):
        manager = None
    evidence = []
    for character in characters:
        item = {
            "character_id": getattr(character, "id", None),
            "name": getattr(character, "name", ""),
            "appearance": getattr(character, "appearance", None),
            "asset_pack": None,
            "reference_hashes": {},
        }
        if manager is not None:
            try:
                pack = manager.get_character_asset_pack(character.id, project.id)
                if isinstance(pack, dict):
                    item["asset_pack"] = {
                        "status": pack.get("status"),
                        "identity_spec_hash": pack.get("identity_spec_hash"),
                        "reference_paths": sorted(pack.get("reference_paths") or []),
                        "reference_hashes": dict(sorted((pack.get("reference_hashes") or {}).items())),
                    }
                references = manager.get_character_references(character.id, project.id)
                item["reference_hashes"] = {
                    str(path): _optional_asset_hash(path) for path in sorted(references or [])
                }
            except (OSError, TypeError, ValueError):
                item["asset_pack"] = {"status": "unavailable"}
        evidence.append(item)
    return evidence


def _production_control_asset_evidence(project) -> dict:
    """Return stable fingerprints for the frozen visual and spatial contracts."""
    project_id = getattr(project, "id", None)
    evidence = {}
    try:
        from src.services.visual_style_assets import VisualStyleAssetService

        style_pack = VisualStyleAssetService().get_project_pack(project_id)
    except (OSError, RuntimeError, TypeError, ValueError):
        style_pack = {"status": "unavailable"}
    if isinstance(style_pack, dict):
        evidence["visual_style"] = {
            "status": style_pack.get("status", "missing"),
            "version": style_pack.get("version"),
            "source_hash": style_pack.get("source_hash"),
            "scene_style_hash": style_pack.get("scene_style_hash"),
            "style_prompt": style_pack.get("style_prompt"),
            "negative_prompt": style_pack.get("negative_prompt"),
        }
    else:
        evidence["visual_style"] = {"status": "missing"}

    try:
        from src.services.spatial_control_assets import SpatialControlAssetService

        spatial_pack = SpatialControlAssetService().get_project_pack(project_id)
    except (OSError, RuntimeError, TypeError, ValueError):
        spatial_pack = {"status": "unavailable"}
    if isinstance(spatial_pack, dict):
        evidence["spatial_control"] = {
            "status": spatial_pack.get("status", "missing"),
            "version": spatial_pack.get("version"),
            "planner_contract_version": spatial_pack.get("planner_contract_version"),
            "required_control_types": list(spatial_pack.get("required_control_types") or []),
            "project_signature": spatial_pack.get("project_signature"),
            "scenes": [
                {
                    "scene_number": item.get("scene_number"),
                    "source_hash": item.get("source_hash"),
                    "spatial_plan_hash": item.get("spatial_plan_hash"),
                    "control_references_hash": item.get("control_references_hash"),
                    "turnaround_controls_hash": item.get("turnaround_controls_hash"),
                }
                for item in spatial_pack.get("scenes", [])
                if isinstance(item, dict)
            ],
        }
    else:
        evidence["spatial_control"] = {"status": "missing"}
    return evidence


def _optional_asset_hash(path):
    return file_hash(Path(path)) if isinstance(path, (str, Path)) and path else None


def validate_generation_review_coverage(report: dict, scenes) -> dict:
    """Verify that a passed generation review covers every project scene once."""
    expected = [int(scene.scene_number) for scene in scenes]
    entries = report.get("scenes") if isinstance(report, dict) else None
    if not isinstance(entries, list):
        return {
            "passed": False, "expected": expected, "reviewed": [],
            "missing": expected, "duplicate": [], "unexpected": [],
            "not_passed": [], "reason": "per-scene review entries are missing",
        }
    numbers = [
        int(item.get("scene_number"))
        for item in entries
        if isinstance(item, dict) and str(item.get("scene_number", "")).strip().isdigit()
    ]
    expected_set = set(expected)
    number_set = set(numbers)
    duplicate = sorted({number for number in numbers if numbers.count(number) > 1})
    missing = sorted(expected_set - number_set)
    unexpected = sorted(number_set - expected_set)
    not_passed = sorted(
        int(item.get("scene_number"))
        for item in entries
        if isinstance(item, dict)
        and str(item.get("scene_number", "")).strip().isdigit()
        and int(item.get("scene_number")) in expected_set
        and item.get("status") != "passed"
    )
    passed = not missing and not duplicate and not unexpected and not not_passed and len(numbers) == len(expected)
    return {
        "passed": passed, "expected": expected, "reviewed": numbers,
        "missing": missing, "duplicate": duplicate, "unexpected": unexpected,
        "not_passed": not_passed, "reason": "ok" if passed else "per-scene review coverage is incomplete",
    }


def validate_story_review_coverage(report: dict, scenes) -> dict:
    """Verify that the nested story review covers every scene exactly once."""
    expected = [int(scene.scene_number) for scene in scenes]
    review = report.get("review") if isinstance(report, dict) else None
    reviewed = review.get("reviewed_scenes") if isinstance(review, dict) else None
    if not isinstance(reviewed, list):
        return {
            "passed": False, "expected": expected, "reviewed": [],
            "missing": expected, "duplicate": [], "unexpected": [],
            "reason": "reviewed_scenes is missing",
        }
    numbers = [int(value) for value in reviewed if str(value).strip().isdigit()]
    expected_set = set(expected)
    number_set = set(numbers)
    duplicate = sorted({number for number in numbers if numbers.count(number) > 1})
    missing = sorted(expected_set - number_set)
    unexpected = sorted(number_set - expected_set)
    passed = not missing and not duplicate and not unexpected and len(numbers) == len(expected)
    return {
        "passed": passed, "expected": expected, "reviewed": numbers,
        "missing": missing, "duplicate": duplicate, "unexpected": unexpected,
        "reason": "ok" if passed else "story review coverage is incomplete",
    }


def validate_generation_review_evidence(report: dict, scenes) -> dict:
    """Verify that each reviewed scene points to a live, matching evidence file."""
    if isinstance(report, dict) and report.get("mode") == "single_shot_smoke_test":
        return {
            "passed": False,
            "missing": [],
            "invalid": [],
            "reason": "draft smoke tests are not production review evidence",
        }
    expected = {int(scene.scene_number): scene for scene in scenes}
    missing: list[int] = []
    invalid: list[int] = []
    for item in (report.get("scenes", []) if isinstance(report, dict) else []):
        if not isinstance(item, dict) or not str(item.get("scene_number", "")).strip().isdigit():
            continue
        number = int(item["scene_number"])
        evidence_path = Path(str(item.get("report") or ""))
        if not evidence_path.is_file():
            missing.append(number)
            continue
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            invalid.append(number)
            continue
        scene = expected.get(number)
        expected_hash = (
            file_hash(Path(scene.video_path))
            if scene and scene.video_path and Path(scene.video_path).is_file()
            else None
        )
        if (
            not isinstance(evidence, dict)
            or evidence.get("status") != "passed"
            or not expected_hash
            or evidence.get("video_sha256") != expected_hash
        ):
            invalid.append(number)
    passed = not missing and not invalid
    return {
        "passed": passed,
        "missing": sorted(set(missing)),
        "invalid": sorted(set(invalid)),
        "reason": "ok" if passed else "scene review evidence is missing or stale",
    }


def require_generation_review(project, scenes):
    require_story_review(project, scenes)
    path = storage_manager.get_project_path(project.id) / "reviews" / "generation.json"
    if not path.is_file():
        raise ReviewError("Missing sampled-frame review; run review_generation before composing")
    report = json.loads(path.read_text(encoding="utf-8"))
    require_passed(report)
    coverage = validate_generation_review_coverage(report, scenes)
    if not coverage["passed"]:
        raise ReviewError(
            "Generation review does not cover every scene: "
            f"missing={coverage['missing']}, duplicate={coverage['duplicate']}, "
            f"unexpected={coverage['unexpected']}, not_passed={coverage['not_passed']}"
        )
    if report.get("input_hash") != generation_signature(project, scenes):
        raise ReviewError("Story or media changed after review; rerun sampled-frame review")
    evidence = validate_generation_review_evidence(report, scenes)
    if not evidence["passed"]:
        raise ReviewError(
            "Generation review evidence is missing or stale: "
            f"missing={evidence['missing']}, invalid={evidence['invalid']}"
        )
    return report


def require_story_review(project, scenes):
    path = storage_manager.get_project_path(project.id) / "reviews" / "production_story.json"
    if not path.is_file():
        raise ReviewError("Missing production story review")
    review = json.loads(path.read_text(encoding="utf-8"))
    require_passed(review)
    coverage = validate_story_review_coverage(review, scenes)
    if not coverage["passed"]:
        raise ReviewError(
            "Story review does not cover every scene: "
            f"missing={coverage['missing']}, duplicate={coverage['duplicate']}, "
            f"unexpected={coverage['unexpected']}"
        )
    if review.get("input_hash") != fingerprint(current_story(project, scenes)):
        raise ReviewError("Story changed after review")


@celery_app.task(bind=True, name="review_generation")
def review_generation_task(self, project_id: int, task_id: int):
    db = next(get_db())
    root = storage_manager.get_project_path(project_id) / "reviews"
    report = {"status": "error", "scenes": []}
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
        if not project or not scenes or any(not s.video_path for s in scenes):
            raise ReviewError("All scene videos are required for review")
        require_story_review(project, scenes)
        # These are process-local resources; the single GPU worker owns them.
        from src.services.llm_service import cleanup_llm_service
        from src.services.svd_service import cleanup_svd_service
        cleanup_llm_service()
        cleanup_svd_service()
        report["input_hash"] = generation_signature(project, scenes)
        production_options = load_production_video_options(project_id, task_id) or {}
        explicit_draft_run = bool(production_options.get("draft"))
        if len(scenes) == 1 and explicit_draft_run and os.getenv("ENABLE_DRAFT_MEDIA_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}:
            raise ReviewError("Draft smoke tests cannot enter production review")
        reviewer = GenerationReviewService()
        references = {}
        from src.tasks.image_tasks import _visual_character, _get_reference_image
        from src.tasks.video_tasks import _scene_review_payload
        for scene in scenes:
            if scene.image_path:
                metadata = Path(scene.image_path).with_suffix(".generation.json")
                if metadata.is_file() and json.loads(metadata.read_text(encoding="utf-8")).get("status") == "draft":
                    raise ReviewError("Draft media cannot pass production review")
            character = _visual_character(scene, project_id, db)
            reference = None
            if character:
                reference = _get_reference_image(character, project_id, scene) or references.setdefault(character.id, scene.image_path)
            payload = _scene_review_payload(scene, project_id, db)
            payload["identity"] = character.appearance if character else None
            result = reviewer.review_video(scene.video_path, payload, root / f"scene_{scene.id}.json", reference)
            report["scenes"].append({"scene_id": scene.id, "scene_number": scene.scene_number,
                                     "status": result["status"], "average": result.get("average"),
                                     "report": str(root / f"scene_{scene.id}.json")})
        report["status"] = "passed" if all(s["status"] == "passed" for s in report["scenes"]) else "needs_review"
        write_report(root / "generation.json", report)
        require_passed(report)
        return report
    except Exception as exc:
        report["error"] = str(exc)
        write_report(root / "generation.json", report)
        task = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = f"Quality review requires attention: {root / 'generation.json'}: {exc}"
            db.commit()
        raise
    finally:
        db.close()
