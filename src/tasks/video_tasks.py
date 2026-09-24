"""Video generation Celery tasks."""

import shutil
from math import gcd
from pathlib import Path

from src.config import settings
from src.database.database import get_db
from src.database.models import Scene
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.generation_provider import ImageGenerationRequest, VideoGenerationRequest, get_generation_provider
from src.services.generation_review import GenerationReviewService, ReviewError, attach_video_aesthetic_gate, platform_video_score, write_report
from src.services.repair_queue import attach_repair_queue
from src.services.svd_service import get_svd_service
from src.services.video_director_service import VideoShotPlan, get_video_director_service
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_video_path

logger = get_logger(__name__)


def _configured_video_provider_name(kwargs: dict | None = None) -> str:
    kwargs = kwargs or {}
    return kwargs.get("provider") or settings.GENERATION_PROVIDER


def _uses_configured_video_provider(provider_name: str) -> bool:
    return provider_name != "local_comfyui" or bool(settings.COMFYUI_VIDEO_WORKFLOW_PATH)


def _build_video_generator(scene: Scene, shot_plan: VideoShotPlan, provider_name: str, end_image: str | None):
    if _uses_configured_video_provider(provider_name):
        return _ComfyVideoGenerator(
            scene,
            provider=get_generation_provider(provider_name),
            shot_plan=shot_plan,
        ).with_end_image(end_image)
    return get_svd_service()


def _aspect_ratio_for_size(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "unknown"
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


class _ComfyVideoGenerator:
    def __init__(self, scene: Scene, provider=None, shot_plan: VideoShotPlan | None = None):
        self.scene = scene
        self.provider = provider or get_generation_provider("local_comfyui")
        self.shot_plan = shot_plan

    def generate_video(
        self,
        image_path: str,
        output_path: str,
        num_frames: int,
        fps: int,
        motion_bucket_id: int,
        noise_aug_strength: float,
    ) -> str:
        duration = (
            self.shot_plan.target_duration_seconds
            if self.shot_plan
            else max(1.0, num_frames / max(fps, 1))
        )
        prompt = (
            self.shot_plan.director_prompt
            if self.shot_plan
            else self.scene.image_prompt or self.scene.visual_description
        )
        negative_prompt = (
            self.shot_plan.negative_prompt
            if self.shot_plan
            else settings.GENERATION_QUALITY_NEGATIVE_APPEND
        )
        seed = abs(hash((self.scene.id, output_path, motion_bucket_id, round(noise_aug_strength, 4)))) % (2 ** 31)
        result = self.provider.generate_video(VideoGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            reference_image=image_path,
            end_image=getattr(self, "end_image", None),
            output_path=output_path,
            duration_seconds=duration,
            width=settings.GENERATION_WIDTH,
            height=settings.GENERATION_HEIGHT,
            aspect_ratio=_aspect_ratio_for_size(settings.GENERATION_WIDTH, settings.GENERATION_HEIGHT),
            fps=fps,
            seed=seed,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
        ))
        return result.output_path

    def with_end_image(self, end_image: str | None):
        self.end_image = end_image
        return self


def _candidate_video_path(final_path: str | Path, index: int) -> str:
    path = Path(final_path)
    return str(path.with_name(f"{path.stem}.candidate_{index:02d}{path.suffix}"))


def _video_variant_params(base_motion: int, base_noise: float, index: int) -> tuple[int, float]:
    motion_offsets = [0, -12, 12, -24, 24, -36, 36, -48]
    noise_offsets = [0.0, 0.01, -0.005, 0.02, -0.01, 0.03, -0.015, 0.04]
    offset_index = (index - 1) % len(motion_offsets)
    motion = max(1, min(255, base_motion + motion_offsets[offset_index]))
    noise = max(0.0, min(1.0, base_noise + noise_offsets[offset_index]))
    return motion, noise


def _refined_video_base_params(motion: int, noise: float) -> tuple[int, float]:
    return max(1, int(motion * 0.72)), max(0.0, round(noise * 0.6, 4))


def _apply_video_repair_action(
    motion_bucket_id: int,
    noise_aug_strength: float,
    repair_action: str | None,
) -> tuple[int, float]:
    if repair_action != "lower_motion_and_regenerate_video":
        return motion_bucket_id, noise_aug_strength
    return (
        max(1, min(255, int(motion_bucket_id * 0.58))),
        max(0.0, min(1.0, round(noise_aug_strength * 0.45, 4))),
    )


def _scene_review_payload(scene: Scene, project_id: int | None = None, db=None) -> dict:
    visible_characters = []
    if project_id is not None and db is not None:
        from src.tasks.image_tasks import _visible_character_payload
        visible_characters = _visible_character_payload(scene, project_id, db)
    return {
        "scene_number": scene.scene_number,
        "description": scene.visual_description,
        "dialogue": scene.dialogue,
        "image_prompt": scene.image_prompt,
        "expected_image": scene.image_path,
        "visible_characters": visible_characters,
    }


def _visible_characters_for_scene(scene: Scene, project_id: int, db) -> list[dict]:
    from src.tasks.image_tasks import _visible_character_payload
    return _visible_character_payload(scene, project_id, db)


def _scene_end_frame_path(project_id: int, scene_id: int) -> str:
    from src.utils.storage import storage_manager
    path = storage_manager.get_image_path(project_id, scene_id, f"scene_{scene_id}_end.png")
    return str(path)


def _generate_end_frame(scene: Scene, project_id: int, shot_plan: VideoShotPlan, provider=None) -> str:
    provider = provider or get_generation_provider("local_comfyui")
    output_path = _scene_end_frame_path(project_id, scene.id)
    request = ImageGenerationRequest(
        prompt=shot_plan.end_frame_prompt,
        negative_prompt=shot_plan.negative_prompt,
        output_path=output_path,
        width=settings.GENERATION_WIDTH,
        height=settings.GENERATION_HEIGHT,
        steps=settings.GENERATION_STEPS,
        cfg_scale=settings.GENERATION_CFG,
        seed=abs(hash((scene.id, "end_frame", shot_plan.shot_role))) % (2 ** 31),
        reference_image=scene.image_path,
        use_ipadapter=bool(scene.image_path and settings.COMFYUI_REFERENCE_WORKFLOW_PATH),
        quality_mode=settings.GENERATION_QUALITY_PROFILE,
    )
    result = provider.generate_image(request)
    return result.output_path


def _reference_for_scene(scene: Scene, project_id: int, db) -> str | None:
    from src.tasks.image_tasks import _get_reference_image, _visual_character
    character = _visual_character(scene, project_id, db)
    if not character:
        return None
    return _get_reference_image(character, project_id) or scene.image_path


def _review_score_from_batch(batch: dict, key: str) -> float | None:
    value = (batch.get("review") or {}).get(key)
    if isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
        return float(value["score"])
    return None


def _video_gate_scores(review_report: dict) -> dict[str, float]:
    batches = review_report.get("batches") or []
    scores: dict[str, list[float]] = {
        "facial_identity": [],
        "identity_consistency": [],
        "temporal_consistency": [],
    }
    for batch in batches:
        for key in scores:
            score = _review_score_from_batch(batch, key)
            if score is not None:
                scores[key].append(score)
    return {key: min(values) for key, values in scores.items() if values}


def _video_platform_score(review_report: dict) -> float | None:
    scores = []
    for batch in review_report.get("batches") or []:
        attach_video_aesthetic_gate(batch)
        if isinstance(batch.get("platform_score"), (int, float)):
            scores.append(float(batch["platform_score"]))
            continue
        review = batch.get("review") if isinstance(batch.get("review"), dict) else {}
        score = platform_video_score(review)
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return round(min(scores), 2)


def _video_aesthetic_gate_summary(review_report: dict) -> dict | None:
    gates = [
        batch.get("video_aesthetic_gate")
        for batch in review_report.get("batches") or []
        if isinstance(batch.get("video_aesthetic_gate"), dict)
    ]
    if not gates:
        return None
    failed = [gate for gate in gates if gate.get("status") != "passed"]
    selected = failed[0] if failed else min(gates, key=lambda item: item.get("average", 5))
    return {
        "status": "needs_review" if failed else "passed",
        "min_score": selected.get("min_score"),
        "average": selected.get("average"),
        "low": selected.get("low", {}),
        "missing": selected.get("missing", []),
    }


def _video_gate_passes(candidate: dict) -> tuple[bool, dict[str, float]]:
    scores = candidate.get("gate_scores") or {}
    if not scores:
        return True, {}
    identity_min = settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE
    temporal_min = settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE
    identity_ok = all(
        scores.get(key, identity_min) >= identity_min
        for key in ("facial_identity", "identity_consistency")
    )
    temporal_ok = scores.get("temporal_consistency", temporal_min) >= temporal_min
    return identity_ok and temporal_ok, scores


def _select_best_video_candidate(candidates: list[dict], final_path: str, report_path: Path) -> tuple[str, dict]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            1 if _video_gate_passes(item)[0] else 0,
            item.get("platform_score", item.get("average", 0)),
            item.get("average", 0),
        ),
        reverse=True,
    )
    best = ranked[0]
    gate_ok, gate_scores = _video_gate_passes(best)
    platform_score = best.get("platform_score")
    report = {
        "kind": "video_candidate_selection",
        "status": "passed" if (
            best.get("status") == "passed"
            and best.get("average", 0) >= settings.GENERATION_VIDEO_MIN_SCORE
            and (platform_score is None or platform_score >= settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE)
            and gate_ok
        ) else "needs_review",
        "selected_path": best["path"],
        "selected_average": best.get("average", 0),
        "selected_platform_score": platform_score,
        "min_average": settings.GENERATION_VIDEO_MIN_SCORE,
        "min_identity_score": settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE,
        "min_temporal_score": settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE,
        "min_platform_score": settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE,
        "selected_gate_scores": gate_scores,
        "candidates": ranked,
    }
    if not gate_ok:
        report["error"] = f"Selected video gate scores are below threshold: {gate_scores}"
    elif platform_score is not None and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
        report["error"] = (
            f"Best video platform score {platform_score} is below "
            f"{settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE}"
        )
    elif best.get("average", 0) < settings.GENERATION_VIDEO_MIN_SCORE:
        report["error"] = (
            f"Best video score {best.get('average', 0)} is below "
            f"{settings.GENERATION_VIDEO_MIN_SCORE}"
        )
    if report["status"] != "passed" and settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        attach_repair_queue(report, "video")
        write_report(report_path, report)
        raise ReviewError(
            f"Video candidates failed quality gate: average={best.get('average', 0)}, "
            f"required={settings.GENERATION_VIDEO_MIN_SCORE}, gates={gate_scores}, "
            f"reason={report.get('error')}, report={report_path}"
        )
    Path(final_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best["path"], final_path)
    report["promoted_path"] = final_path
    if report["status"] != "passed":
        attach_repair_queue(report, "video")
    write_report(report_path, report)
    return final_path, report


def _generate_quality_video_candidates(
    svd_service,
    scene: Scene,
    project_id: int,
    output_path: str,
    db,
    *,
    num_frames: int,
    fps: int,
    motion_bucket_id: int,
    noise_aug_strength: float,
    shot_plan: VideoShotPlan | None = None,
    repair_action: str | None = None,
) -> tuple[str, dict]:
    candidate_count = max(1, min(settings.GENERATION_VIDEO_CANDIDATES, 6))
    refinement_passes = max(0, min(settings.GENERATION_VIDEO_REFINEMENT_PASSES, 3))
    reviewer = GenerationReviewService()
    reference = _reference_for_scene(scene, project_id, db)
    scene_payload = _scene_review_payload(scene, project_id, db)
    candidate_scene = {
        "scene_number": scene.scene_number,
        "description": scene.visual_description,
        "dialogue": scene.dialogue,
        "repair_action": repair_action,
    }
    shot_plan_payload = shot_plan.as_dict() if shot_plan else None
    candidates = []
    from src.services.svd_service import cleanup_svd_service
    current_motion = motion_bucket_id
    current_noise = noise_aug_strength
    for pass_index in range(refinement_passes + 1):
        generated = []
        try:
            for offset in range(1, candidate_count + 1):
                index = pass_index * candidate_count + offset
                candidate_path = _candidate_video_path(output_path, index)
                motion, noise = _video_variant_params(current_motion, current_noise, offset)
                generated_path = svd_service.generate_video(
                    image_path=scene.image_path,
                    output_path=candidate_path,
                    num_frames=num_frames,
                    fps=fps,
                    motion_bucket_id=motion,
                    noise_aug_strength=noise,
                )
                generated.append({
                    "index": index,
                    "pass": pass_index,
                    "path": generated_path,
                    "motion_bucket_id": motion,
                    "noise_aug_strength": noise,
                    "scene": candidate_scene,
                    "request": {
                        "image_path": scene.image_path,
                        "num_frames": num_frames,
                        "fps": fps,
                        "motion_bucket_id": motion,
                        "noise_aug_strength": noise,
                        "reference_image": reference,
                        "repair_action": repair_action,
                    },
                    "shot_plan": shot_plan_payload,
                    "repair_action": repair_action,
                })
        finally:
            cleanup_svd_service()

        pass_candidates = []
        for generated_candidate in generated:
            index = generated_candidate["index"]
            generated_path = generated_candidate["path"]
            review_path = Path(generated_path).with_suffix(".review.json")
            review = reviewer.review_video(
                generated_path,
                {
                    **scene_payload,
                    "shot_plan": shot_plan_payload,
                    "candidate_index": index,
                    "refinement_pass": generated_candidate["pass"],
                    "motion_bucket_id": generated_candidate["motion_bucket_id"],
                    "noise_aug_strength": generated_candidate["noise_aug_strength"],
                    "repair_action": repair_action,
                },
                review_path,
                reference,
            )
            candidate = {
                "index": index,
                "pass": generated_candidate["pass"],
                "path": generated_path,
                "status": review.get("status"),
                "average": review.get("average", 0),
                "review_path": str(review_path),
                "motion_bucket_id": generated_candidate["motion_bucket_id"],
                "noise_aug_strength": generated_candidate["noise_aug_strength"],
                "scene": generated_candidate["scene"],
                "request": generated_candidate["request"],
            }
            gate_scores = _video_gate_scores(review)
            if gate_scores:
                candidate["gate_scores"] = gate_scores
            platform_score = _video_platform_score(review)
            if platform_score is not None:
                candidate["platform_score"] = platform_score
            aesthetic_gate = _video_aesthetic_gate_summary(review)
            if aesthetic_gate:
                candidate["video_aesthetic_gate"] = aesthetic_gate
            if repair_action:
                candidate["repair_action"] = repair_action
            if shot_plan_payload:
                candidate["shot_plan"] = shot_plan_payload
            if review.get("error"):
                candidate["error"] = review["error"]
            candidates.append(candidate)
            pass_candidates.append(candidate)
        if any(
            candidate.get("status") == "passed"
            and candidate.get("average", 0) >= settings.GENERATION_VIDEO_MIN_SCORE
            and _video_gate_passes(candidate)[0]
            for candidate in candidates
        ):
            break
        if all(candidate.get("status") == "error" for candidate in pass_candidates):
            break
        current_motion, current_noise = _refined_video_base_params(current_motion, current_noise)
    if all(candidate.get("status") == "error" for candidate in candidates):
        report = {
            "kind": "video_candidate_selection",
            "status": "review_unavailable",
            "selected_path": candidates[0]["path"],
            "candidates": candidates,
        }
        attach_repair_queue(report, "video")
        write_report(Path(output_path).with_suffix(".quality.json"), report)
        raise ReviewError("All video candidate reviews failed")
    return _select_best_video_candidate(candidates, output_path, Path(output_path).with_suffix(".quality.json"))


@celery_app.task(bind=True, name="generate_video")
def generate_video_task(
    self,
    scene_id: int,
    project_id: int,
    task_id: int,
    **kwargs,
):
    """Generate a video clip for one scene."""
    logger.info("Start video generation: scene_id={}", scene_id)
    self.update_state(state="PROGRESS", meta={"current": 0, "total": 100, "step": "video_generation"})

    db = next(get_db())
    try:
        scene = db.query(Scene).filter(Scene.id == scene_id).first()
        if not scene:
            raise ValueError(f"Scene not found: {scene_id}")
        if not scene.image_path:
            raise ValueError(f"Scene image is missing: {scene_id}")

        video_path = get_scene_video_path(project_id, scene_id)
        self.update_state(state="PROGRESS", meta={"current": 50, "total": 100, "step": "svd_generation"})

        try:
            try:
                from src.services.comfyui_service import get_comfyui_service
                get_comfyui_service().free_memory()
            except Exception as exc:
                logger.warning("Could not ask ComfyUI to free memory before video generation; continuing: {}", exc)
            visible_characters = _visible_characters_for_scene(scene, project_id, db)
            shot_plan = get_video_director_service().plan_scene(scene, project_id, visible_characters)
            num_frames = max(kwargs.get("num_frames", settings.SVD_NUM_FRAMES), shot_plan.num_frames)
            fps = kwargs.get("fps", shot_plan.fps)
            motion_bucket_id = kwargs.get("motion_bucket_id", shot_plan.motion_bucket_id)
            noise_aug_strength = kwargs.get("noise_aug_strength", shot_plan.noise_aug_strength)
            repair_action = kwargs.get("repair_action")
            motion_bucket_id, noise_aug_strength = _apply_video_repair_action(
                motion_bucket_id,
                noise_aug_strength,
                repair_action,
            )
            provider_name = _configured_video_provider_name(kwargs)
            end_image = None
            if settings.GENERATION_VIDEO_END_FRAME_ENABLED and _uses_configured_video_provider(provider_name):
                end_image = _generate_end_frame(scene, project_id, shot_plan)
            video_generator = _build_video_generator(scene, shot_plan, provider_name, end_image)
            result_path, quality_report = _generate_quality_video_candidates(
                video_generator,
                scene,
                project_id,
                video_path,
                db,
                num_frames=num_frames,
                fps=fps,
                motion_bucket_id=motion_bucket_id,
                noise_aug_strength=noise_aug_strength,
                shot_plan=shot_plan,
                repair_action=repair_action,
            )
            normalized_path = str(Path(video_path).with_name(f"{Path(video_path).stem}.normalized.mp4"))
            normalized = get_video_director_service().normalize_clip(
                result_path,
                normalized_path,
                shot_plan.target_duration_seconds,
            )
            if normalized != result_path:
                shutil.copyfile(normalized, video_path)
                result_path = video_path
            logger.info("Video candidate selection completed: scene_id={}, report={}", scene_id, quality_report)
        except Exception as exc:
            if not draft_fallback_enabled():
                raise
            duration = get_draft_media_service().estimate_dialogue_duration(scene.dialogue or "")
            logger.warning(
                "Real video generation failed; using draft still-video fallback: scene_id={}, duration={}, error={}",
                scene_id,
                duration,
                exc,
            )
            result_path = get_draft_media_service().generate_video_from_image(
                image_path=scene.image_path,
                output_path=video_path,
                duration=duration,
                fps=kwargs.get("fps", 24),
            )

        scene.video_path = result_path
        db.commit()

        logger.info("Video generation completed: scene_id={}, path={}", scene_id, result_path)
        return {"scene_id": scene_id, "video_path": result_path, "status": "completed"}
    except Exception as exc:
        logger.error("Video generation failed: scene_id={}, error={}", scene_id, exc)
        raise
    finally:
        db.close()
