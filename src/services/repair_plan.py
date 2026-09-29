"""Actionable rerun plans for unresolved generation repair items."""

from pathlib import Path
from typing import Any


def build_repair_execution_plan(output: str | Path, repair_queue: list[dict[str, Any]]) -> dict[str, Any]:
    """Build actionable rerun guidance from unresolved repair actions."""
    output_path = Path(output)
    plan: dict[str, Any] = {
        "auto": [],
        "setup_required": [],
        "manual": [],
        "rerun_validation_commands": [],
    }
    command_set = set()
    for item in repair_queue:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        execution = item.get("execution") or "manual"
        entry = {
            "action": action,
            "stage": item.get("stage"),
            "scene_number": item.get("scene_number"),
            "reason": item.get("reason"),
            "recommendation": item.get("recommendation"),
        }
        if action == "regenerate_keyframe_with_identity_lock":
            entry["rerun_strategy"] = (
                "Regenerate affected keyframes with locked character-sheet identity and view-angle constraints."
            )
            entry["parameter_hints"] = {
                "repair_action": "regenerate_keyframe_with_identity_lock",
                "lock_character_sheet": True,
                "increase_image_candidates": True,
                "quality_mode": "ultra",
                "optimization_mode": "quality",
            }
            commands = [
                _render_images_command(output_path, action, item.get("scene_number")),
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refine_prompt_composition":
            entry["rerun_strategy"] = (
                "Rerun keyframe generation with composition repair constraints, then run review-images again."
            )
            entry["parameter_hints"] = {
                "repair_action": "refine_prompt_composition",
                "quality_mode": "ultra",
                "optimization_mode": "quality",
                "increase_image_candidates": True,
            }
            commands = [
                _render_images_command(output_path, action, item.get("scene_number")),
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refine_face_aesthetic_detail":
            entry["rerun_strategy"] = (
                "Rerun keyframe generation with stricter face texture, natural pores, catchlights, and premium beauty-lighting constraints."
            )
            entry["parameter_hints"] = {
                "repair_action": "refine_face_aesthetic_detail",
                "quality_mode": "ultra",
                "optimization_mode": "quality",
                "increase_image_candidates": True,
                "natural_face_texture_required": True,
            }
            commands = [
                _render_images_command(output_path, action, item.get("scene_number")),
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "regenerate_keyframe_with_prop_constraints":
            entry["rerun_strategy"] = (
                "Regenerate affected keyframes with hand and prop constraints before video generation."
            )
            entry["parameter_hints"] = {
                "repair_action": "regenerate_keyframe_with_prop_constraints",
                "lock_props": True,
                "increase_image_candidates": True,
            }
            commands = [
                _render_images_command(output_path, action, item.get("scene_number")),
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "lower_motion_and_regenerate_video":
            entry["rerun_strategy"] = (
                "Regenerate the affected clip with lower motion/noise, then rerun VLM video review and baseline comparison."
            )
            entry["parameter_hints"] = {
                "repair_action": "lower_motion_and_regenerate_video",
                "lower_motion_bucket_id": True,
                "lower_noise_aug_strength": True,
                "increase_video_refinement_passes": True,
            }
            commands = [
                f"python -m scripts.validate_local_generation review-video --output {output_path} --video <regenerated_clip.mp4> --description \"<scene description>\"",
                f"python -m scripts.validate_local_generation compare-baseline --output {output_path} --candidate <regenerated_clip.mp4> --baseline <seed_dance_reference.mp4>",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "increase_motion_and_regenerate_video":
            entry["rerun_strategy"] = (
                "Regenerate the affected clip with a higher motion floor, then rerun VLM video review and baseline comparison."
            )
            entry["parameter_hints"] = {
                "repair_action": "increase_motion_and_regenerate_video",
                "raise_motion_bucket_id": True,
                "raise_noise_aug_strength_slightly": True,
                "increase_video_candidates": True,
            }
            commands = [
                f"python -m scripts.validate_local_generation review-video --output {output_path} --video <regenerated_clip.mp4> --description \"<scene description>\"",
                f"python -m scripts.validate_local_generation compare-baseline --output {output_path} --candidate <regenerated_clip.mp4> --baseline <seed_dance_reference.mp4>",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "regenerate_video_with_performance_direction":
            entry["rerun_strategy"] = (
                "Regenerate the affected clip with stronger shot-plan acting direction, then rerun VLM video review and baseline comparison."
            )
            entry["parameter_hints"] = {
                "repair_action": "regenerate_video_with_performance_direction",
                "strengthen_shot_plan_performance": True,
                "raise_motion_bucket_id_slightly": True,
                "raise_noise_aug_strength_slightly": True,
                "increase_video_candidates": True,
                "preserve_identity": True,
            }
            commands = [
                f"python -m scripts.validate_local_generation review-video --output {output_path} --video <regenerated_clip.mp4> --description \"<scene description>\"",
                f"python -m scripts.validate_local_generation compare-baseline --output {output_path} --candidate <regenerated_clip.mp4> --baseline <seed_dance_reference.mp4>",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        else:
            entry["rerun_strategy"] = item.get("recommendation") or "Resolve this repair action and rerun summarize."
            commands = [f"python -m scripts.validate_local_generation summarize --output {output_path}"]

        bucket = execution if execution in plan else "manual"
        plan[bucket].append(entry)
        for command in commands:
            if command not in command_set:
                plan["rerun_validation_commands"].append(command)
                command_set.add(command)
    return plan


def _render_images_command(output_path: Path, repair_action: str, scene_number: Any = None) -> str:
    command = (
        "python -m scripts.validate_local_generation render-images "
        f"--output {output_path} --quality-mode ultra --optimization-mode quality "
        f"--repair-action {repair_action}"
    )
    try:
        scene_number_int = int(scene_number)
    except (TypeError, ValueError):
        return command
    if scene_number_int > 0:
        command += f" --scene-number {scene_number_int}"
    return command
