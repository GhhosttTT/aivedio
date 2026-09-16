"""Video generation Celery tasks."""

import shutil
from pathlib import Path

from src.config import settings
from src.database.database import get_db
from src.database.models import Scene
from src.services.draft_media_service import draft_fallback_enabled, get_draft_media_service
from src.services.generation_review import GenerationReviewService, ReviewError, write_report
from src.services.svd_service import get_svd_service
from src.tasks.celery_app import celery_app
from src.utils.logger import get_logger
from src.utils.storage import get_scene_video_path

logger = get_logger(__name__)


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


def _scene_review_payload(scene: Scene) -> dict:
    return {
        "scene_number": scene.scene_number,
        "description": scene.visual_description,
        "dialogue": scene.dialogue,
        "image_prompt": scene.image_prompt,
        "expected_image": scene.image_path,
    }


def _reference_for_scene(scene: Scene, project_id: int, db) -> str | None:
    from src.tasks.image_tasks import _get_reference_image, _visual_character
    character = _visual_character(scene, project_id, db)
    if not character:
        return None
    return _get_reference_image(character, project_id) or scene.image_path


def _select_best_video_candidate(candidates: list[dict], final_path: str, report_path: Path) -> tuple[str, dict]:
    ranked = sorted(candidates, key=lambda item: item.get("average", 0), reverse=True)
    best = ranked[0]
    report = {
        "kind": "video_candidate_selection",
        "status": "passed" if best.get("status") == "passed" and best.get("average", 0) >= settings.GENERATION_VIDEO_MIN_SCORE else "needs_review",
        "selected_path": best["path"],
        "selected_average": best.get("average", 0),
        "min_average": settings.GENERATION_VIDEO_MIN_SCORE,
        "candidates": ranked,
    }
    if report["status"] != "passed" and settings.GENERATION_REQUIRE_VIDEO_REVIEW:
        write_report(report_path, report)
        raise ReviewError(
            f"Video candidates failed quality gate: average={best.get('average', 0)}, "
            f"required={settings.GENERATION_VIDEO_MIN_SCORE}, report={report_path}"
        )
    Path(final_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best["path"], final_path)
    report["promoted_path"] = final_path
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
) -> tuple[str, dict]:
    candidate_count = max(1, min(settings.GENERATION_VIDEO_CANDIDATES, 6))
    refinement_passes = max(0, min(settings.GENERATION_VIDEO_REFINEMENT_PASSES, 3))
    reviewer = GenerationReviewService()
    reference = _reference_for_scene(scene, project_id, db)
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
                    **_scene_review_payload(scene),
                    "candidate_index": index,
                    "refinement_pass": generated_candidate["pass"],
                    "motion_bucket_id": generated_candidate["motion_bucket_id"],
                    "noise_aug_strength": generated_candidate["noise_aug_strength"],
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
            }
            if review.get("error"):
                candidate["error"] = review["error"]
            candidates.append(candidate)
            pass_candidates.append(candidate)
        if any(
            candidate.get("status") == "passed"
            and candidate.get("average", 0) >= settings.GENERATION_VIDEO_MIN_SCORE
            for candidate in candidates
        ):
            break
        if all(candidate.get("status") == "error" for candidate in pass_candidates):
            break
        current_motion, current_noise = _refined_video_base_params(current_motion, current_noise)
    if all(candidate.get("status") == "error" for candidate in candidates):
        if settings.GENERATION_REQUIRE_VIDEO_REVIEW:
            raise ReviewError("All video candidate reviews failed")
        shutil.copyfile(candidates[0]["path"], output_path)
        report = {
            "kind": "video_candidate_selection",
            "status": "review_unavailable",
            "selected_path": candidates[0]["path"],
            "promoted_path": output_path,
            "candidates": candidates,
        }
        write_report(Path(output_path).with_suffix(".quality.json"), report)
        return output_path, report
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
            from src.services.comfyui_service import get_comfyui_service
            get_comfyui_service().free_memory()
            svd_service = get_svd_service()
            result_path, quality_report = _generate_quality_video_candidates(
                svd_service,
                scene,
                project_id,
                video_path,
                db,
                num_frames=kwargs.get("num_frames", settings.SVD_NUM_FRAMES),
                fps=kwargs.get("fps", settings.SVD_FPS),
                motion_bucket_id=kwargs.get("motion_bucket_id", 127),
                noise_aug_strength=kwargs.get("noise_aug_strength", 0.02),
            )
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
