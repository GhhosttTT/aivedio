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
from src.services.shot_prompt_service import ShotPromptService, CompiledShot
from src.services.generation_review import write_report
from src.services.image_quality_service import ImageQualitySelector, candidate_output_path
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.generation_provider import ImageGenerationRequest, get_generation_provider
from src.services.image_postprocess import ImagePostprocessor
from src.services.shot_complexity_service import ShotComplexityService
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_image_path

logger = get_logger(__name__)


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


def _visible_character_payload(scene: Scene, project_id: int, db) -> list[dict[str, str]]:
    payload = []
    for character in _visual_characters(scene, project_id, db):
        payload.append({
            "name": character.name,
            "appearance": character.appearance or "",
        })
    return payload


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
    if len(anchors) == 1:
        return anchors[0].split(" identity: ", 1)[1]
    return "Keep every visible character distinct. " + " | ".join(anchors)


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
    complexity = _complexity_report(scene, project_id, db)
    if settings.GENERATION_BLOCK_COMPLEX_SHOTS and complexity["status"] == "needs_split":
        raise ValueError("Shot is too complex for one stable generation: " + "; ".join(complexity["reasons"]))
    layout_parts = [composition, complexity["prompt_constraint"]]
    appearance_with_layout = f"{appearance}. {' '.join(layout_parts)}" if appearance else " ".join(layout_parts)
    prompt_with_layout = f"{prompt}\n" + "\n".join(layout_parts)
    artifact = Path(get_scene_image_path(project_id, scene.id)).with_suffix(".prompt.json")
    source_hash = compiler.source_hash(prompt_with_layout, appearance_with_layout)
    if artifact.is_file():
        cached = json.loads(artifact.read_text(encoding="utf-8"))
        if cached.get("source_hash") == source_hash and cached.get("version") == 1:
            compiler.validate_cached_prompt(cached["prompt"])
            return CompiledShot(**cached), character
    compiled = compiler.compile(prompt_with_layout, appearance_with_layout)
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


def _get_reference_image(character: Optional[Character], project_id: int) -> Optional[str]:
    if not character:
        return None
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


def _quality_parameters(index: int, refinement_pass: int, base_steps: int, base_cfg: float) -> tuple[int, float]:
    """
    鏍规嵁閰嶇疆鍐冲畾鏄惁鍙樺寲鍙傛暟

    濡傛灉GENERATION_STEP_VARIATION鍜孏ENERATION_CFG_VARIATION閮戒负0,鍒欐墍鏈夊€欓€夊浘浣跨敤鐩稿悓鍙傛暟
    """
    step_variation = settings.GENERATION_STEP_VARIATION
    cfg_variation = settings.GENERATION_CFG_VARIATION

    if step_variation == 0 and cfg_variation == 0:
        # 鍥哄畾鍙傛暟妯″紡锛氭墍鏈夊€欓€夊浘浣跨敤鐩稿悓鐨剆teps鍜宑fg
        return base_steps, base_cfg

    # 鍔ㄦ€佸弬鏁版ā寮忥細鍘熸湁閫昏緫
    step_boost = min(index, 2) * step_variation + refinement_pass * (step_variation * 1.5)
    cfg_shift = (index % 3 - 1) * cfg_variation
    return min(base_steps + int(step_boost), 48), round(max(4.5, min(base_cfg + cfg_shift, 8.0)), 2)


def _append_terms(text: str | None, addition: str | None) -> str:
    parts = [part.strip() for part in (text or "").split(",") if part.strip()]
    existing = {part.lower() for part in parts}
    for raw in (addition or "").split(","):
        term = raw.strip()
        if term and term.lower() not in existing:
            parts.append(term)
            existing.add(term.lower())
    return ", ".join(parts)


IMAGE_REPAIR_PROMPTS = {
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


def _generate_quality_candidates(provider, request: ImageGenerationRequest, scene_payload: dict, reference_image: str | None) -> tuple[str, dict]:
    candidate_count = max(1, min(settings.GENERATION_IMAGE_CANDIDATES, 8))
    refinement_passes = max(0, min(settings.GENERATION_IMAGE_REFINEMENT_PASSES, 3))
    selector = ImageQualitySelector()
    reports = []
    best_report = None

    for pass_index in range(refinement_passes + 1):
        pass_reports = []
        feedback = _review_feedback(reports) if pass_index else ""
        prompt = _append_terms(request.prompt, settings.GENERATION_QUALITY_PROMPT_APPEND)
        negative_prompt = _append_terms(request.negative_prompt, settings.GENERATION_QUALITY_NEGATIVE_APPEND)
        if feedback:
            prompt = f"{prompt}. Correct previous candidate problems: {feedback}."
            negative_prompt = _append_terms(negative_prompt, feedback)
        for index in range(candidate_count):
            candidate_index = pass_index * candidate_count + index + 1
            output_path = candidate_output_path(request.output_path, candidate_index)
            steps, cfg = _quality_parameters(index, pass_index, request.steps, request.cfg_scale)
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
            report["request"] = {
                "seed": candidate_request.seed,
                "steps": candidate_request.steps,
                "cfg_scale": candidate_request.cfg_scale,
                "width": candidate_request.width,
                "height": candidate_request.height,
                "refinement_pass": pass_index,
                "feedback": feedback,
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
    postprocess_report = ImagePostprocessor().process(
        request.output_path,
        prompt=request.prompt,
        negative_prompt=request.negative_prompt or "",
        reference_image=reference_image,
        report_path=Path(request.output_path).with_suffix(".postprocess.json"),
    )
    selection["postprocess"] = postprocess_report
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
        reference_image = _get_reference_image(character, project_id)
        enhanced_prompt = compiled.prompt
        repair_action = kwargs.get("repair_action")
        enhanced_prompt, negative_prompt = _apply_image_repair_action(
            enhanced_prompt,
            compiled.negative_prompt,
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
                "visible_characters": _visible_character_payload(scene, project_id, db),
                "repair_action": repair_action,
            }
            final_image_path, quality_report = _generate_quality_candidates(provider, request, scene_payload, reference_image)
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
