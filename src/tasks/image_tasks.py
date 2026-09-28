"""Image generation Celery tasks."""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from src.database.database import get_db
from src.database.models import Character, Project, ProjectStatus, Scene, Task as TaskModel
from src.config import settings
from src.services.character_identity_service import CharacterIdentityService, load_identity_spec
from src.services.character_turnaround_album import CharacterTurnaroundAlbumService
from src.services.shot_prompt_service import ShotPromptService, CompiledShot
from src.services.generation_review import ReviewError, write_report
from src.services.image_quality_service import ImageQualitySelector, candidate_output_path
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.generation_provider import ImageGenerationRequest, get_generation_provider
from src.services.generation_quality_policy import image_quality_budget
from src.services.image_postprocess import ImagePostprocessor
from src.services.repair_queue import build_repair_queue
from src.services.visual_style_assets import VisualStyleAssetService
from src.services.shot_complexity_service import ShotComplexityService
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_image_path

logger = get_logger(__name__)


def _turnaround_view_for_scene(scene: Scene | None, prompt: str = "") -> str:
    text = " ".join(filter(None, [
        prompt,
        getattr(scene, "image_prompt", "") if scene else "",
        getattr(scene, "visual_description", "") if scene else "",
        getattr(scene, "dialogue", "") if scene else "",
    ])).lower()
    if any(term in text for term in ("intense expression", "crying close-up", "angry close-up", "崩溃特写", "哭泣特写", "愤怒特写")):
        return "expression_intense"
    if any(term in text for term in ("neutral expression", "calm close-up", "passport-like", "定妆特写", "平静特写")):
        return "expression_neutral"
    if any(term in text for term in ("full body", "head-to-toe", "wide full shot", "全身", "从头到脚")):
        return "full_body"
    if any(term in text for term in ("back view", "rear view", "from behind", "turns away", "背影", "背面", "背对")):
        return "back"
    if any(term in text for term in ("side view", "side profile", "profile", "90 degree", "侧脸", "侧面", "侧身")):
        return "side"
    if any(term in text for term in ("three-quarter left", "left three quarter", "left 45", "左45", "左侧45")):
        return "three_quarter_left"
    if any(term in text for term in ("three-quarter right", "right three quarter", "right 45", "右45", "右侧45")):
        return "three_quarter_right"
    if any(term in text for term in ("three-quarter", "three quarter", "45 degree", "45度", "斜侧")):
        return "three_quarter_left"
    return "front"


def _turnaround_control_for_character(character: Character, project_id: int, view: str) -> dict | None:
    try:
        validation = CharacterTurnaroundAlbumService().validate_album(character)
    except Exception as exc:
        logger.warning("读取角色生产级立体画册失败: {}", exc)
        return None
    if validation.get("status") != "valid":
        return None
    manifest = validation.get("manifest") if isinstance(validation.get("manifest"), dict) else {}
    views = manifest.get("views") if isinstance(manifest.get("views"), dict) else {}
    item = views.get(view)
    if not isinstance(item, dict) or not item.get("path"):
        return None
    return {
        "view": view,
        "path": item.get("path"),
        "sha256": item.get("sha256"),
        "control_prompt": item.get("control_prompt", ""),
        "expected_features": item.get("expected_features", {}),
        "identity_spec_hash": manifest.get("identity_spec_hash"),
        "project_id": project_id,
    }


def _prompt_safe_name(name: str, fallback: str = "the character") -> str:
    if re.search(r"[\u3400-\u9fff]", name or ""):
        return fallback
    return name


def _visible_character_names(scene: Scene, project_id: int, db) -> list[str]:
    # Speaker and visible actor may differ, especially in narration and reaction shots.
    project = db.query(Project).filter(Project.id == project_id).first()
    plan = json.loads(project.script) if project and project.script else {}
    item = next((s for s in plan.get("scenes", []) if s.get("scene_number") == scene.scene_number), {})
    visible = item.get("characters")
    if visible is None:
        visible = [scene.character_name] if scene.character_name and scene.character_name in scene.visual_description else []
    if isinstance(visible, str):
        visible = [visible]
    return [name for name in visible if isinstance(name, str) and name.strip()]


def _visual_characters(scene: Scene, project_id: int, db) -> list[Character]:
    names = _visible_character_names(scene, project_id, db)
    if not names:
        return []
    characters = db.query(Character).filter(
        Character.project_id == project_id,
        Character.name.in_(names),
    ).all()
    by_name = {character.name: character for character in characters}
    return [by_name[name] for name in names if name in by_name]


def _visual_character(scene: Scene, project_id: int, db) -> Optional[Character]:
    characters = _visual_characters(scene, project_id, db)
    if len(characters) != 1:
        return None
    return characters[0]


def _visible_character_payload(scene: Scene, project_id: int, db) -> list[dict]:
    payload = []
    view = _turnaround_view_for_scene(scene)
    for character in _visual_characters(scene, project_id, db):
        identity_spec = load_identity_spec(character.visual_description)
        item = {
            "name": character.name,
            "appearance": character.appearance or "",
        }
        if identity_spec:
            item["identity_spec"] = identity_spec
        turnaround = _turnaround_control_for_character(character, project_id, view)
        if turnaround:
            item["turnaround_reference"] = turnaround
        payload.append({
            **item,
        })
    return payload


def _character_sheet_generation_contract(visible_characters: list[dict]) -> dict:
    """Build generator-facing constraints from frozen character-sheet assets."""
    prompts = []
    references = []
    identity_specs = [
        item.get("identity_spec")
        for item in visible_characters
        if isinstance(item.get("identity_spec"), dict)
    ]
    contrast_matrix = CharacterIdentityService().identity_contrast_matrix(identity_specs) if len(identity_specs) >= 2 else {}
    contrast_prompt = CharacterIdentityService().identity_contrast_prompt(identity_specs) if len(identity_specs) >= 2 else ""
    for item in visible_characters:
        turnaround = item.get("turnaround_reference") if isinstance(item.get("turnaround_reference"), dict) else None
        if not turnaround:
            continue
        expected = turnaround.get("expected_features") if isinstance(turnaround.get("expected_features"), dict) else {}
        feature_terms = [
            f"{key}: {value}"
            for key, value in expected.items()
            if str(value or "").strip()
        ][:7]
        prompt = turnaround.get("control_prompt") or ""
        view = turnaround.get("view") or "front"
        name = _prompt_safe_name(item.get("name", ""), "the character")
        contract = (
            f"{name} character-sheet reference view={view}; {prompt}; "
            f"must match reviewed features: {'; '.join(feature_terms)}"
        ).strip(" ;")
        prompts.append(contract)
        references.append({
            "name": item.get("name"),
            "view": view,
            "path": turnaround.get("path"),
            "sha256": turnaround.get("sha256"),
            "expected_features": expected,
        })
    if contrast_prompt:
        prompts.append(contrast_prompt)
    if not prompts:
        return {"prompt": "", "negative": "", "references": [], "identity_contrast_matrix": contrast_matrix}
    return {
        "prompt": "Character sheet contract: " + " | ".join(prompts),
        "negative": (
            "changed face, changed hair, changed wardrobe, identity drift, same-face cast, "
            "same facial geometry across different roles, copied hairstyle across roles, "
            "wrong camera angle versus character sheet"
        ),
        "references": references,
        "identity_contrast_matrix": contrast_matrix,
    }


def _appearance_anchor(characters: list[Character], db, compiler) -> str | None:
    if not characters:
        return None
    anchors = []
    for character in characters:
        appearance = character.appearance
        if appearance and (re.search(r"[\u3400-\u9fff]", appearance) or len(appearance.split()) > 25):
            from src.services.script_generator import ScriptGenerator
            if compiler.llm_service is None:
                from src.services.llm_service import get_llm_service
                compiler.llm_service = get_llm_service()
            appearance = ScriptGenerator(db, compiler.llm_service)._generate_character_appearance(character.name, appearance)
            character.appearance = appearance
            db.commit()
        if appearance:
            safe_name = _prompt_safe_name(character.name, "character")
            anchors.append(f"{safe_name} identity: {appearance}")
    if not anchors:
        return None
    specs = [
        spec for character in characters
        if (spec := load_identity_spec(character.visual_description))
    ]
    contrast = CharacterIdentityService().identity_contrast_prompt(specs)
    if len(anchors) == 1:
        return anchors[0].split(" identity: ", 1)[1]
    return "Keep every visible character distinct. " + " | ".join(anchors) + (f" {contrast}" if contrast else "")


def _composition_constraint(scene: Scene, project_id: int, db) -> str:
    names = _visible_character_names(scene, project_id, db)
    if not names:
        return "Composition constraint: clean establishing shot, clear subject area, no random people."
    if len(names) == 1:
        safe_name = _prompt_safe_name(names[0])
        return (
            f"Composition constraint: {safe_name} is the only visible person, clear silhouette, "
            "face unobstructed, hands visible when relevant, no extra people."
        )
    if len(names) == 2:
        safe_names = [_prompt_safe_name(names[0], "character A"), _prompt_safe_name(names[1], "character B")]
        return (
            f"Composition constraint: two-shot layout, {safe_names[0]} on frame left and {safe_names[1]} on frame right, "
            "separate faces, separate wardrobes, no merged bodies, both faces readable."
        )
    positions = ["frame left", "center", "frame right", "background left", "background right"]
    layout = ", ".join(
        f"{_prompt_safe_name(name, f'character {index + 1}')} at {positions[index % len(positions)]}"
        for index, name in enumerate(names[:5])
    )
    return (
        f"Composition constraint: group layout with {layout}; keep each person separated, "
        "no duplicated faces, no merged limbs, no random extra people."
    )


def _complexity_report(scene: Scene, project_id: int, db) -> dict:
    names = _visible_character_names(scene, project_id, db)
    return ShotComplexityService().diagnose(
        scene.visual_description or "",
        names,
        scene.dialogue or "",
    ).to_dict()


def _project_complexity_report(scenes: list[Scene], project_id: int, db) -> dict:
    items = []
    for scene in scenes:
        report = _complexity_report(scene, project_id, db)
        items.append({
            "scene_id": scene.id,
            "scene_number": scene.scene_number,
            "status": report["status"],
            "score": report["score"],
            "visible_characters": report["visible_characters"],
            "reasons": report["reasons"],
            "recommendations": report["recommendations"],
        })
    needs_split = [item for item in items if item["status"] == "needs_split"]
    warn = [item for item in items if item["status"] == "warn"]
    return {
        "kind": "shot_complexity",
        "status": "needs_split" if needs_split else ("warn" if warn else "passed"),
        "summary": {
            "total": len(items),
            "needs_split": len(needs_split),
            "warn": len(warn),
        },
        "scenes": items,
    }


def _prepare_prompt(scene: Scene, project_id: int, prompt: str, db, compiler=None):
    compiler = compiler or ShotPromptService()
    characters = _visual_characters(scene, project_id, db)
    appearance = _appearance_anchor(characters, db, compiler)
    character = characters[0] if len(characters) == 1 else None
    composition = _composition_constraint(scene, project_id, db)
    style_service = VisualStyleAssetService()
    visual_style = style_service.generation_prompt_for_project(project_id)
    style_negative = style_service.generation_negative_for_project(project_id)
    complexity = _complexity_report(scene, project_id, db)
    if settings.GENERATION_BLOCK_COMPLEX_SHOTS and complexity["status"] == "needs_split":
        raise ValueError("Shot is too complex for one stable generation: " + "; ".join(complexity["reasons"]))
    layout_parts = [part for part in (composition, visual_style, complexity["prompt_constraint"]) if part]
    if appearance:
        if len(characters) > 1:
            appearance_parts = [part for part in (composition, appearance, visual_style, complexity["prompt_constraint"]) if part]
        else:
            appearance_parts = [part for part in (appearance, composition, visual_style, complexity["prompt_constraint"]) if part]
        appearance_with_layout = ". ".join(appearance_parts)
    else:
        appearance_with_layout = " ".join(layout_parts)
    prompt_with_layout = f"{prompt}\n" + "\n".join(layout_parts)
    artifact = Path(get_scene_image_path(project_id, scene.id)).with_suffix(".prompt.json")
    source_hash = compiler.source_hash(f"{prompt_with_layout}\n{style_negative}", appearance_with_layout)
    if artifact.is_file():
        cached = json.loads(artifact.read_text(encoding="utf-8"))
        if cached.get("source_hash") == source_hash and cached.get("version") == 1:
            compiler.validate_cached_prompt(cached["prompt"])
            return CompiledShot(**cached), character
    compiled = compiler.compile(prompt_with_layout, appearance_with_layout)
    compiled = CompiledShot(
        compiled.prompt,
        compiled.negative_prompt,
        source_hash,
        compiled.word_count,
        compiled.version,
    )
    if style_negative:
        compiled = CompiledShot(
            compiled.prompt,
            _append_terms(compiled.negative_prompt, style_negative),
            compiled.source_hash,
            compiled.word_count,
            compiled.version,
        )
    write_report(artifact, compiled.to_dict())
    return compiled, character


@celery_app.task(bind=True, name="prepare_generation")
def prepare_generation_task(self, project_id: int, task_id: int, compile_images: bool = True):
    db = next(get_db())
    try:
        scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
        if not scenes:
            raise ValueError("Project has no scenes")
        compiler = ShotPromptService()
        from src.services.generation_review import GenerationReviewService, TextReviewer, fingerprint, require_passed
        from src.tasks.review_tasks import current_story
        from src.utils.storage import storage_manager
        project = db.query(Project).filter(Project.id == project_id).first()
        story = current_story(project, scenes)
        review_path = storage_manager.get_project_path(project_id) / "reviews" / "production_story.json"
        complexity = _project_complexity_report(scenes, project_id, db)
        write_report(storage_manager.get_project_path(project_id) / "reviews" / "shot_complexity.json", complexity)
        if settings.GENERATION_BLOCK_COMPLEX_SHOTS and complexity["status"] == "needs_split":
            raise ValueError("Project contains shots that need splitting: " + str([
                item["scene_number"] for item in complexity["scenes"] if item["status"] == "needs_split"
            ]))
        if len(scenes) == 1:
            reviewed = {
                "kind": "story",
                "mode": "single_shot_smoke_test",
                "input_hash": fingerprint(story),
                "status": "passed",
                "average": 4.0,
                "review": {
                    "filmability": {
                        "score": 4,
                        "evidence": "Single-shot production skips cross-scene story review and relies on shot complexity checks.",
                    },
                    "reviewed_scenes": [scenes[0].scene_number],
                    "issues": [],
                },
            }
            write_report(review_path, reviewed)
        else:
            reviewed = json.loads(review_path.read_text(encoding="utf-8")) if review_path.is_file() else {}
        if len(scenes) > 1 and (reviewed.get("input_hash") != fingerprint(story) or reviewed.get("status") != "passed"):
            from src.services.llm_service import get_llm_service
            compiler.llm_service = get_llm_service()
            reviewed = GenerationReviewService(TextReviewer(compiler.llm_service)).review_story(story, review_path)
            if reviewed.get("status") != "passed":
                from src.services.script_generator import ScriptGenerator

                parsed_script = {
                    "script": json.loads(project.script).get("script", "") if project.script else "",
                    "characters": [
                        {"name": character.name, "description": character.description}
                        for character in project.characters
                    ],
                    "scenes": [
                        {
                            "scene_number": scene.scene_number,
                            "description": scene.visual_description,
                            "dialogue": scene.dialogue,
                            "speaker": scene.character_name,
                        }
                        for scene in scenes
                    ],
                }
                script_generator = ScriptGenerator(db, compiler.llm_service)
                repaired_script, reviewed = script_generator.repair_script_for_review(
                    project=project,
                    parsed_script=parsed_script,
                    failed_review=reviewed,
                    review_path=review_path,
                    max_attempts=3,
                )
                require_passed(reviewed)
                script_generator._save_script_to_db(project, repaired_script)
                project.script = json.dumps(repaired_script, ensure_ascii=False)
                project.status = ProjectStatus.SCRIPT_GENERATED
                db.commit()
                scenes = db.query(Scene).filter(Scene.project_id == project_id).order_by(Scene.scene_number).all()
                complexity = _project_complexity_report(scenes, project_id, db)
                write_report(storage_manager.get_project_path(project_id) / "reviews" / "shot_complexity.json", complexity)
                if settings.GENERATION_BLOCK_COMPLEX_SHOTS and complexity["status"] == "needs_split":
                    raise ValueError("Project contains shots that need splitting after repair: " + str([
                        item["scene_number"] for item in complexity["scenes"] if item["status"] == "needs_split"
                    ]))
        require_passed(reviewed)
        if compile_images:
            for scene in scenes:
                _prepare_prompt(scene, project_id, scene.image_prompt or scene.visual_description, db, compiler)
        return {"prepared": len(scenes), "complexity": complexity}
    finally:
        from src.services.llm_service import cleanup_llm_service
        cleanup_llm_service()
        db.close()


def _get_reference_image(character: Optional[Character], project_id: int, scene: Scene | None = None) -> Optional[str]:
    if not character:
        return None
    turnaround = _turnaround_control_for_character(character, project_id, _turnaround_view_for_scene(scene))
    if turnaround and turnaround.get("path"):
        return str(turnaround["path"])
    try:
        from src.services.character_service import get_character_manager

        references = get_character_manager().get_character_references(character.id, project_id)
        return references[0] if references else None
    except Exception as exc:
        logger.warning("璇诲彇瑙掕壊鍙傝€冨浘澶辫触: {}", exc)
        return None


def _save_first_reference(character: Optional[Character], project_id: int, scene: Scene, image_path: str) -> None:
    if not character:
        return
    try:
        from src.services.character_service import get_character_manager

        get_character_manager().save_character_reference(
            character_id=character.id,
            project_id=project_id,
            image_path=image_path,
            description=f"Generated from scene {scene.scene_number}",
        )
    except Exception as exc:
        logger.warning("淇濆瓨瑙掕壊鍙傝€冨浘澶辫触: {}", exc)


def _update_progress(db, project_id: int, task_id: int) -> tuple[float, int, int]:
    task_model = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if task_model is None:
        task_model = (
            db.query(TaskModel)
            .filter(TaskModel.project_id == project_id)
            .order_by(TaskModel.created_at.desc())
            .first()
        )
    completed_images = db.query(Scene).filter(
        Scene.project_id == project_id,
        Scene.image_path.isnot(None),
    ).count()
    total_scenes = db.query(Scene).filter(Scene.project_id == project_id).count()
    progress_percentage = (completed_images / total_scenes) * 25.0 if total_scenes else 0.0

    if task_model:
        progress_percentage = task_model.progress

    return progress_percentage, completed_images, total_scenes


def _broadcast_progress(project_id: int, task_id: int, scene: Scene, progress: float, completed: int, total: int) -> None:
    try:
        from src.api.websocket import manager

        asyncio.run(
            manager.broadcast(
                project_id,
                {
                    "type": "progress",
                    "task_id": str(task_id),
                    "project_id": project_id,
                    "scene_id": scene.id,
                    "task_type": "image",
                    "status": "completed",
                    "progress": progress / 100.0,
                    "current_step": f"Scene {scene.scene_number} image completed ({completed}/{total})",
                    "message": f"Image generated ({completed}/{total})",
                },
            )
        )
    except Exception as exc:
        logger.warning("WebSocket 鎺ㄩ€佸け璐? {}", exc)


def _candidate_seed(base_seed: int, index: int, refinement_pass: int = 0) -> int:
    material = f"{base_seed}:{index}:{refinement_pass}".encode()
    return int(hashlib.sha256(material).hexdigest()[:8], 16)


IMAGE_REPAIR_PARAMETER_PROFILES = {
    "regenerate_keyframe_with_identity_lock": {
        "steps_boost": 10,
        "cfg_delta": -0.2,
        "reason": "character_identity_lock_repair",
    },
    "refine_prompt_composition": {
        "steps_boost": 8,
        "cfg_delta": -0.3,
        "reason": "composition_aesthetic_repair",
    },
    "regenerate_keyframe_with_prop_constraints": {
        "steps_boost": 6,
        "cfg_delta": 0.2,
        "reason": "prop_hand_repair",
    },
}


def _repair_parameter_profile(repair_action: str | None) -> dict:
    profile = IMAGE_REPAIR_PARAMETER_PROFILES.get(repair_action or "")
    return dict(profile) if profile else {}


def _quality_parameters(
    index: int,
    refinement_pass: int,
    base_steps: int,
    base_cfg: float,
    repair_action: str | None = None,
) -> tuple[int, float]:
    """
    鏍规嵁閰嶇疆鍐冲畾鏄惁鍙樺寲鍙傛暟

    濡傛灉GENERATION_STEP_VARIATION鍜孏ENERATION_CFG_VARIATION閮戒负0,鍒欐墍鏈夊€欓€夊浘浣跨敤鐩稿悓鍙傛暟
    """
    step_variation = settings.GENERATION_STEP_VARIATION
    cfg_variation = settings.GENERATION_CFG_VARIATION

    repair_profile = _repair_parameter_profile(repair_action)

    if step_variation == 0 and cfg_variation == 0:
        # 鍥哄畾鍙傛暟妯″紡锛氭墍鏈夊€欓€夊浘浣跨敤鐩稿悓鐨剆teps鍜宑fg
        steps = base_steps
        cfg = base_cfg
    else:
        # 鍔ㄦ€佸弬鏁版ā寮忥細鍘熸湁閫昏緫
        step_boost = min(index, 2) * step_variation + refinement_pass * (step_variation * 1.5)
        cfg_shift = (index % 3 - 1) * cfg_variation
        steps = base_steps + int(step_boost)
        cfg = base_cfg + cfg_shift

    steps += int(repair_profile.get("steps_boost", 0))
    cfg += float(repair_profile.get("cfg_delta", 0.0))
    return min(steps, 56), round(max(4.5, min(cfg, 8.0)), 2)


def _append_terms(text: str | None, addition: str | None) -> str:
    parts = [part.strip() for part in (text or "").split(",") if part.strip()]
    existing = {part.lower() for part in parts}
    for raw in (addition or "").split(","):
        term = raw.strip()
        if term and term.lower() not in existing:
            parts.append(term)
            existing.add(term.lower())
    return ", ".join(parts)


def _append_sentence_once(text: str | None, addition: str | None) -> str:
    base = str(text or "").strip()
    addition = str(addition or "").strip()
    if not addition:
        return base
    if addition.lower() in base.lower():
        return base
    if not base:
        return addition
    return base.rstrip(" .") + ". " + addition.strip(" .") + "."


IMAGE_REPAIR_PROMPTS = {
    "regenerate_keyframe_with_identity_lock": (
        "repair pass: lock the approved character-sheet identity, preserve exact face geometry, hair shape, "
        "wardrobe color and silhouette, selected reference view angle, no same-face casting, no random outfit changes"
    ),
    "refine_prompt_composition": (
        "repair pass: improve short-drama framing, balanced composition, clean crop, readable face, "
        "cinematic lighting, clear foreground-background separation, polished commercial still"
    ),
    "regenerate_keyframe_with_prop_constraints": (
        "repair pass: preserve important props, readable hands, natural fingers, clear hand-object contact, "
        "stable prop color and position, no disappearing objects"
    ),
}

IMAGE_REPAIR_NEGATIVES = {
    "regenerate_keyframe_with_identity_lock": (
        "changed face, changed hair, changed wardrobe, wrong view angle, same-face cast, identity drift, "
        "face swap, random costume, inconsistent body proportion"
    ),
    "refine_prompt_composition": (
        "bad crop, cropped face, awkward framing, flat lighting, muddy lighting, cluttered composition, "
        "unclear subject, low production value"
    ),
    "regenerate_keyframe_with_prop_constraints": (
        "broken fingers, fused fingers, missing fingers, deformed hands, disappearing prop, changed prop, "
        "floating object, unclear hand-object contact"
    ),
}


def _apply_image_repair_action(
    prompt: str,
    negative_prompt: str,
    repair_action: str | None,
) -> tuple[str, str]:
    """Translate a targeted repair action into generator-facing constraints."""
    if not repair_action:
        return prompt, negative_prompt
    return (
        _append_terms(prompt, IMAGE_REPAIR_PROMPTS.get(repair_action)),
        _append_terms(negative_prompt, IMAGE_REPAIR_NEGATIVES.get(repair_action)),
    )


def _review_feedback(reports: list[dict]) -> str:
    feedback = []
    for report in sorted(reports, key=lambda item: item.get("average", 0))[:3]:
        review = report.get("review") or {}
        for issue in review.get("issues", [])[:3]:
            reason = issue.get("reason") if isinstance(issue, dict) else None
            if reason:
                feedback.append(reason)
        for key, value in review.items():
            if isinstance(value, dict) and value.get("score", 5) <= 2:
                feedback.append(value.get("evidence", key))
            elif isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, dict) and nested_value.get("score", 5) <= 2:
                        feedback.append(nested_value.get("evidence", nested_key))
        for gate_name in ("platform_aesthetic_gate", "turnaround_gate"):
            gate = report.get(gate_name) if isinstance(report.get(gate_name), dict) else {}
            low = gate.get("low") if isinstance(gate.get("low"), dict) else {}
            for key, value in low.items():
                evidence = value.get("evidence", key) if isinstance(value, dict) else key
                feedback.append(f"{key}: {evidence}")
        if report.get("status") == "technical_only" and report.get("metrics", {}).get("technical_score", 5) < 3:
            feedback.append("improve exposure, sharpness, color separation and visual clarity")
    compact = []
    seen = set()
    for item in feedback:
        item = str(item).strip().replace("\n", " ")
        if item and item.lower() not in seen:
            compact.append(item[:140])
            seen.add(item.lower())
        if len(compact) >= 6:
            break
    return "; ".join(compact)


def _feedback_repair_directive(feedback: str) -> tuple[str, str]:
    """Translate low-score evidence into generator-facing repair constraints."""
    text = (feedback or "").lower()
    prompt_terms = []
    negative_terms = []
    rules = [
        (
            ("skin_texture", "plastic skin", "waxy", "airbrushed", "ai generated gloss", "ai gloss", "wax museum face", "over-beautified"),
            "natural skin texture with visible pores, soft but realistic facial highlights",
            "plastic skin, waxy face, over-smoothed face, airbrushed skin, AI generated gloss, wax museum face, over-beautified influencer skin",
        ),
        (
            ("lighting_quality", "lighting_consistency", "muddy light", "muddy lighting", "flat lighting"),
            "controlled soft key light, clean catchlights, separated face and background",
            "muddy lighting, flat lighting, crushed shadows, blown highlights",
        ),
        (
            ("color_grade", "color_grade_consistency", "oversaturated", "cheap filter"),
            "tasteful commercial color grade with natural contrast and stable skin tones",
            "oversaturated filter, cheap filter look, unnatural color cast",
        ),
        (
            ("phone_readability", "tiny unreadable", "unreadable face", "face readable"),
            "phone-readable face, clear eyes and expression, medium close framing",
            "tiny face, unreadable expression, face hidden in frame",
        ),
        (
            ("background_separation", "flat background", "messy background"),
            "clear foreground-background separation, tidy production-designed background",
            "flat background, cluttered background, dirty background",
        ),
        (
            ("production_polish", "low production value", "looks cheap", "low-budget set", "low budget set", "messy wardrobe"),
            "premium short-drama production polish, styled but believable wardrobe, clean practical set dressing",
            "low production value, cheap costume, messy wardrobe, messy set dressing, low-budget set dressing",
        ),
        (
            ("repair_artifacts_absent", "repair scar", "upscale artifact", "artifact"),
            "clean retouched render without visible repair marks or upscale artifacts",
            "repair scar, inpaint scar, noisy upscale artifacts, distorted face repair",
        ),
    ]
    for keywords, prompt, negative in rules:
        if any(keyword in text for keyword in keywords):
            prompt_terms.append(prompt)
            negative_terms.append(negative)
    return "; ".join(dict.fromkeys(prompt_terms)), ", ".join(dict.fromkeys(negative_terms))


def _repair_action_from_reports(reports: list[dict]) -> str | None:
    """Infer the next automatic repair action from failed candidate reviews."""
    if not reports:
        return None
    queue = build_repair_queue(
        {"status": "needs_review", "candidates": sorted(reports, key=lambda item: item.get("average", 0))[:4]},
        "image",
    )
    for item in queue:
        if item.get("execution") == "auto" and item.get("action"):
            return str(item["action"])
    return None


def _generate_quality_candidates(
    provider,
    request: ImageGenerationRequest,
    scene_payload: dict,
    reference_image: str | None,
    repair_action: str | None = None,
) -> tuple[str, dict]:
    budget = image_quality_budget(repair_action)
    candidate_count = budget.candidate_count
    refinement_passes = max(0, min(budget.refinement_passes, 4))
    selector = ImageQualitySelector()
    reports = []
    best_report = None

    for pass_index in range(refinement_passes + 1):
        pass_reports = []
        feedback = _review_feedback(reports) if pass_index else ""
        base_prompt = request.prompt
        platform_contract = scene_payload.get("platform_aesthetic_contract")
        platform_prompt = ""
        platform_negative = ""
        if isinstance(platform_contract, dict):
            platform_prompt = str(platform_contract.get("prompt") or "")
            platform_negative = str(platform_contract.get("negative_prompt") or "")
        base_prompt = _append_sentence_once(base_prompt, platform_prompt)
        sheet_contract = str(scene_payload.get("character_sheet_contract") or "").strip()
        base_prompt = _append_sentence_once(base_prompt, sheet_contract)
        prompt = _append_terms(base_prompt, settings.GENERATION_QUALITY_PROMPT_APPEND)
        negative_prompt = _append_terms(request.negative_prompt, platform_negative)
        negative_prompt = _append_terms(negative_prompt, settings.GENERATION_QUALITY_NEGATIVE_APPEND)
        if feedback:
            prompt = f"{prompt}. Correct previous candidate problems: {feedback}."
            negative_prompt = _append_terms(negative_prompt, feedback)
            feedback_prompt, feedback_negative = _feedback_repair_directive(feedback)
            if feedback_prompt:
                prompt = f"{prompt}. Repair directive: {feedback_prompt}."
            if feedback_negative:
                negative_prompt = _append_terms(negative_prompt, feedback_negative)
        current_repair_action = repair_action or (_repair_action_from_reports(reports) if pass_index else None)
        prompt, negative_prompt = _apply_image_repair_action(prompt, negative_prompt, current_repair_action)
        for index in range(candidate_count):
            candidate_index = pass_index * candidate_count + index + 1
            output_path = candidate_output_path(request.output_path, candidate_index)
            repair_profile = _repair_parameter_profile(current_repair_action)
            steps, cfg = _quality_parameters(index, pass_index, request.steps, request.cfg_scale, current_repair_action)
            candidate_request = ImageGenerationRequest(
                prompt=prompt,
                negative_prompt=negative_prompt,
                output_path=output_path,
                width=request.width,
                height=request.height,
                steps=steps,
                cfg_scale=cfg,
                seed=_candidate_seed(request.seed, index, pass_index),
                reference_image=request.reference_image,
                use_ipadapter=request.use_ipadapter,
                scene_type=request.scene_type,
                quality_mode="ultra",
                optimization_mode=request.optimization_mode,
            )
            result = provider.generate_image(candidate_request)
            report = selector.review_candidate(
                candidate_index,
                result.output_path,
                scene_payload,
                candidate_request.prompt,
                reference_image,
            )
            report["provider"] = result.provider
            report["provider_metadata"] = result.metadata
            report["scene"] = {
                "scene_number": scene_payload.get("scene_number"),
                "visual_description": scene_payload.get("visual_description") or scene_payload.get("description"),
                "repair_action": scene_payload.get("repair_action"),
                "visible_characters": scene_payload.get("visible_characters", []),
                "platform_aesthetic_contract": scene_payload.get("platform_aesthetic_contract", {}),
            }
            report["request"] = {
                "seed": candidate_request.seed,
                "steps": candidate_request.steps,
                "cfg_scale": candidate_request.cfg_scale,
                "width": candidate_request.width,
                "height": candidate_request.height,
                "reference_image": candidate_request.reference_image,
                "use_ipadapter": candidate_request.use_ipadapter,
                "character_sheet_references": scene_payload.get("character_sheet_references", []),
                "identity_contrast_matrix": scene_payload.get("identity_contrast_matrix", {}),
                "platform_aesthetic_contract": scene_payload.get("platform_aesthetic_contract", {}),
                "refinement_pass": pass_index,
                "feedback": feedback,
                "repair_action": current_repair_action,
                "repair_parameter_profile": repair_profile,
                "quality_budget": budget.as_dict(),
            }
            report["path"] = result.output_path
            pass_reports.append(report)
            reports.append(report)
        best_report = max(pass_reports if best_report is None else reports, key=lambda item: item.get("average", 0))
        if best_report.get("average", 0) >= settings.GENERATION_IMAGE_MIN_SCORE and best_report.get("status") != "technical_only":
            break

    selection = selector.select_best(
        reports,
        request.output_path,
        Path(request.output_path).with_suffix(".quality.json"),
    )
    selection["quality_budget"] = budget.as_dict()
    postprocess_report = ImagePostprocessor().process(
        request.output_path,
        prompt=request.prompt,
        negative_prompt=request.negative_prompt or "",
        reference_image=reference_image,
        report_path=Path(request.output_path).with_suffix(".postprocess.json"),
    )
    selection["postprocess"] = postprocess_report
    if postprocess_report.get("status") == "passed":
        postprocess_review = selector.review_candidate(
            0,
            request.output_path,
            scene_payload,
            request.prompt,
            reference_image,
        )
        postprocess_review["stage"] = "postprocess_review"
        selection["postprocess_review"] = postprocess_review
        postprocess_gate = postprocess_review.get("platform_aesthetic_gate")
        if settings.GENERATION_REQUIRE_IMAGE_REVIEW and (
            postprocess_review.get("status") != "passed"
            or (
                isinstance(postprocess_gate, dict)
                and postprocess_gate.get("status") != "passed"
            )
        ):
            selection["status"] = "needs_review"
            selection["error"] = "Postprocessed image failed final local VLM review"
            selection["repair_queue"] = build_repair_queue(
                {"status": "needs_review", "candidates": [postprocess_review]},
                "image",
            )
            write_report(Path(request.output_path).with_suffix(".quality.json"), selection)
            raise ReviewError(selection["error"])
    write_report(Path(request.output_path).with_suffix(".quality.json"), selection)
    return request.output_path, selection


@celery_app.task(bind=True, name="generate_image")
def generate_image_task(
    self,
    scene_id: int,
    prompt: str,
    project_id: int,
    task_id: int,
    character_name: str = None,
    **kwargs,
):
    """Generate an image for one scene."""
    logger.info("寮€濮嬬敓鎴愬浘鍍? scene_id={}, character={}", scene_id, character_name)
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "image_generation"})

    db = next(get_db())
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene or scene.project_id != project_id:
            raise ValueError(f"鍒嗛暅涓嶅瓨鍦? {scene_id}")

        try:
            try:
                compiled, character = _prepare_prompt(scene, project_id, prompt, db)
            except Exception as exc:
                if not draft_fallback_enabled():
                    raise
                logger.warning("鎻愮ず璇嶇紪璇戝け璐ワ紝浣跨敤鑽夌鎻愮ず璇? scene_id={}, error={}", scene_id, exc)
                fallback_prompt = _append_terms(prompt, _composition_constraint(scene, project_id, db))
                compiled = CompiledShot(
                    fallback_prompt,
                    ShotPromptService.NEGATIVE_PROMPT,
                    hashlib.sha256(fallback_prompt.encode()).hexdigest(),
                    len(fallback_prompt.split()),
                )
                character = _visual_character(scene, project_id, db)
        finally:
            from src.services.llm_service import cleanup_llm_service
            cleanup_llm_service()
        reference_image = _get_reference_image(character, project_id, scene)
        visible_characters = _visible_character_payload(scene, project_id, db)
        character_sheet_contract = _character_sheet_generation_contract(visible_characters)
        platform_aesthetic_contract = VisualStyleAssetService().platform_aesthetic_contract(project_id)
        enhanced_prompt = compiled.prompt
        if character_sheet_contract["prompt"]:
            enhanced_prompt = f"{enhanced_prompt}. {character_sheet_contract['prompt']}."
        repair_action = kwargs.get("repair_action")
        enhanced_prompt, negative_prompt = _apply_image_repair_action(
            enhanced_prompt,
            _append_terms(compiled.negative_prompt, character_sheet_contract["negative"]),
            repair_action,
        )

        image_path = get_scene_image_path(project_id, scene_id)
        provider = get_generation_provider(kwargs.get("provider"))
        seed = kwargs.get("seed", int(hashlib.sha256(f"{project_id}:{scene_id}".encode()).hexdigest()[:8], 16))
        request = ImageGenerationRequest(
            prompt=enhanced_prompt, negative_prompt=negative_prompt,
            output_path=image_path, seed=seed,
            width=kwargs.get("width", settings.GENERATION_WIDTH),
            height=kwargs.get("height", settings.GENERATION_HEIGHT),
            steps=kwargs.get("steps", settings.GENERATION_STEPS),
            cfg_scale=kwargs.get("cfg_scale", settings.GENERATION_CFG),
            reference_image=reference_image, use_ipadapter=reference_image is not None,
        )

        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "generation_provider"})
        try:
            scene_payload = {
                "scene_number": scene.scene_number,
                "visual_description": scene.visual_description,
                "composition_constraint": _composition_constraint(scene, project_id, db),
                "complexity": _complexity_report(scene, project_id, db),
                "dialogue": scene.dialogue,
                "character_name": scene.character_name,
                "visible_characters": visible_characters,
                "character_sheet_contract": character_sheet_contract["prompt"],
                "character_sheet_references": character_sheet_contract["references"],
                "identity_contrast_matrix": character_sheet_contract["identity_contrast_matrix"],
                "platform_aesthetic_contract": platform_aesthetic_contract,
                "repair_action": repair_action,
            }
            final_image_path, quality_report = _generate_quality_candidates(
                provider,
                request,
                scene_payload,
                reference_image,
                repair_action=repair_action,
            )
            provider_name = getattr(getattr(provider, "name", None), "value", str(getattr(provider, "name", "unknown")))
            result = type(
                "SelectedImageResult",
                (),
                {"output_path": final_image_path, "provider": provider_name, "metadata": {"quality": quality_report}},
            )()
        except Exception as exc:
            if not draft_fallback_enabled():
                raise
            logger.warning("鐪熷疄鍥剧墖鐢熸垚澶辫触锛屼娇鐢ㄨ崏绋垮厹搴曞浘: scene_id={}, error={}", scene_id, exc)
            draft_path = get_draft_media_service().generate_image(
                prompt=enhanced_prompt,
                output_path=image_path,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 576),
                scene_number=scene.scene_number,
            )
            result = type(
                "DraftImageResult",
                (),
                {"output_path": draft_path, "provider": "draft_fallback"},
            )()

        from dataclasses import asdict
        write_report(Path(image_path).with_suffix(".generation.json"), {
            "provider": result.provider, "request": asdict(request),
            "status": "draft" if result.provider == "draft_fallback" else "generated",
            "complexity": _complexity_report(scene, project_id, db),
            "repair_action": repair_action,
            "quality": getattr(result, "metadata", {}).get("quality") if hasattr(result, "metadata") else None,
        })
        scene.image_path = result.output_path
        db.commit()

        # Generated frames become references only after explicit human selection.

        progress, completed, total = _update_progress(db, project_id, task_id)
        _broadcast_progress(project_id, task_id, scene, progress, completed, total)

        logger.info("鍥惧儚鐢熸垚鎴愬姛: scene_id={}, path={}", scene_id, result.output_path)
        return {
            "scene_id": scene_id,
            "image_path": result.output_path,
            "provider": result.provider,
            "status": "completed",
        }
    except Exception as exc:
        logger.error("鍥惧儚鐢熸垚澶辫触: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="batch_generate_images")
def batch_generate_images_task(self, scene_ids: list, **kwargs):
    """Placeholder for future batch image generation."""
    total = len(scene_ids)
    for i, _scene_id in enumerate(scene_ids):
        self.update_state(state="PROGRESS", meta={"current": i + 1, "total": total})
    return {"total": total, "completed": 0, "results": []}
