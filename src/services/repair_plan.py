"""Actionable rerun plans for unresolved generation repair items."""

from pathlib import Path
from typing import Any

from src.services.generation_quality_policy import image_quality_pipeline, video_quality_pipeline


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
            _attach_image_pipeline_hint(entry, action)
            commands = [
                _render_images_command(output_path, action, item.get("scene_number")),
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "regenerate_keyframe_with_role_separation":
            entry["rerun_strategy"] = (
                "Regenerate affected keyframes with stricter multi-character role separation and identity contrast constraints."
            )
            entry["parameter_hints"] = {
                "repair_action": "regenerate_keyframe_with_role_separation",
                "lock_character_sheet": True,
                "use_identity_contrast_matrix": True,
                "require_role_separation": True,
                "increase_image_candidates": True,
                "quality_mode": "ultra",
                "optimization_mode": "quality",
            }
            _attach_image_pipeline_hint(entry, action, {"id": "two_shot"})
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
            _attach_image_pipeline_hint(entry, action)
            commands = [
                _render_images_command(output_path, action, item.get("scene_number")),
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refine_project_style_consistency":
            entry["rerun_strategy"] = (
                "Rerun keyframe generation with locked project visual bible, color grade, lighting continuity, wardrobe continuity, and set dressing constraints."
            )
            entry["parameter_hints"] = {
                "repair_action": "refine_project_style_consistency",
                "lock_project_style_bible": True,
                "lock_color_grade": True,
                "lock_lighting_continuity": True,
                "lock_wardrobe_palette": True,
                "increase_image_candidates": True,
                "quality_mode": "ultra",
                "optimization_mode": "quality",
            }
            _attach_image_pipeline_hint(entry, action, {"id": "establishing"})
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
            _attach_image_pipeline_hint(entry, action, {"id": "close_up"})
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
                "quality_mode": "ultra",
                "optimization_mode": "quality",
                "anatomy_integrity_required": True,
                "repair_artifacts_absent_required": True,
            }
            _attach_image_pipeline_hint(entry, action, {"id": "prop_interaction"})
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
            _attach_video_pipeline_hint(entry, action, {"shot_role": "dialogue_reaction"})
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
            _attach_video_pipeline_hint(entry, action, {"shot_role": "action"})
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
            _attach_video_pipeline_hint(entry, action, {"shot_role": "dialogue_reaction"})
            commands = [
                f"python -m scripts.validate_local_generation review-video --output {output_path} --video <regenerated_clip.mp4> --description \"<scene description>\"",
                f"python -m scripts.validate_local_generation compare-baseline --output {output_path} --candidate <regenerated_clip.mp4> --baseline <seed_dance_reference.mp4>",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refine_video_commercial_aesthetic":
            entry["rerun_strategy"] = (
                "Regenerate the affected clip with stricter platform-reference, commercial short-drama lighting, color grade, phone-frame composition, and production polish constraints."
            )
            entry["parameter_hints"] = {
                "repair_action": "refine_video_commercial_aesthetic",
                "stabilize_motion_for_aesthetic_polish": True,
                "lower_noise_aug_strength_slightly": True,
                "increase_video_candidates": True,
                "preserve_identity": True,
                "commercial_aesthetic_required": True,
                "platform_reference_required": True,
                "seed_dance_gap_required": True,
                "scroll_stop_appeal_required": True,
                "premium_casting_required": True,
                "production_design_required": True,
            }
            _attach_video_pipeline_hint(entry, action, {"shot_role": "emotion_reaction"})
            commands = [
                f"python -m scripts.validate_local_generation review-video --output {output_path} --video <regenerated_clip.mp4> --description \"<scene description>\"",
                f"python -m scripts.validate_local_generation compare-baseline --output {output_path} --candidate <regenerated_clip.mp4> --baseline <seed_dance_reference.mp4>",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refine_final_composition_finish":
            entry["rerun_strategy"] = (
                "Rerun final episode composition or the affected clip with unified exposure, skin tone, color grade, sharpness, subtitle integration, and finishing polish."
            )
            entry["parameter_hints"] = {
                "repair_action": "refine_final_composition_finish",
                "unify_exposure": True,
                "unify_skin_tone": True,
                "unify_color_grade": True,
                "stabilize_sharpness": True,
                "check_subtitle_safe_area": True,
                "increase_video_candidates": True,
            }
            _attach_video_pipeline_hint(entry, action, {"shot_role": "establishing"})
            commands = [
                f"python -m scripts.validate_local_generation review-video --output {output_path} --video <final_or_refinished_episode.mp4> --description \"final composed short-drama episode\"",
                f"python -m scripts.validate_local_generation compare-baseline --output {output_path} --candidate <final_or_refinished_episode.mp4> --baseline <seed_dance_reference.mp4>",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refine_dialogue_audio_delivery":
            entry["rerun_strategy"] = (
                "Regenerate affected dialogue audio with stronger short-drama emotion, pacing, and subtitle timing, then rerun composition review."
            )
            entry["parameter_hints"] = {
                "repair_action": "refine_dialogue_audio_delivery",
                "force_short_drama_emotion": True,
                "retime_subtitles_after_audio": True,
                "check_dialogue_duration": True,
                "avoid_flat_tts_delivery": True,
            }
            commands = [
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "rewrite_short_drama_story_rhythm":
            entry["rerun_strategy"] = (
                "Rewrite the shooting script before GPU generation: visible early hook, recurring escalation, mid/final reversal, ending hook, dialogue/reaction drive, emotional progression, and atomic visual beats."
            )
            entry["parameter_hints"] = {
                "repair_action": "rewrite_short_drama_story_rhythm",
                "requires_script_rewrite": True,
                "early_hook_required": True,
                "escalation_every_3_to_4_scenes": True,
                "reversal_required": True,
                "ending_hook_required": True,
                "split_overloaded_atomic_shots": True,
            }
            commands = [
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "fix_video_output_contract":
            entry["rerun_strategy"] = (
                "Fix the provider/model output contract before regenerating: verify resolution, format, duration, native audio, and selected model are supported and actually applied."
            )
            entry["parameter_hints"] = {
                "requires_provider_reconfiguration": True,
                "verify_requested_model": True,
                "verify_output_resolution": True,
                "verify_output_format": True,
                "verify_duration": True,
                "verify_native_audio": True,
            }
            commands = [
                "python -m scripts.validate_seedance_gateway --dry-run --api-format ark_v3",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "regenerate_turnaround_album":
            entry["rerun_strategy"] = (
                "Regenerate the character turnaround album, select one approved front/side/back view, "
                "freeze the album, then invalidate affected keyframes."
            )
            entry["parameter_hints"] = {
                "repair_action": action,
                "required_views": ["front", "side", "back"],
                "freeze_approved_album": True,
                "invalidate_stale_keyframes": True,
            }
            entry["required_inputs"] = ["project_id", "character_id", "approved_view_images"]
            commands = [
                "POST /api/projects/<project_id>/characters/<character_id>/generate-turnaround-album",
                "POST /api/projects/<project_id>/characters/<character_id>/freeze-turnaround-album",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "regenerate_character_identity":
            entry["rerun_strategy"] = (
                "Refresh the character identity specification and references, freeze the asset pack, "
                "then regenerate only scenes that expose the stale identity."
            )
            entry["parameter_hints"] = {
                "repair_action": action,
                "refresh_identity_bible": True,
                "freeze_asset_pack_before_render": True,
                "invalidate_stale_references": True,
            }
            entry["required_inputs"] = ["project_id", "character_id", "identity_specification"]
            commands = [
                "POST /api/projects/<project_id>/characters/<character_id>/identity-plan",
                "POST /api/projects/<project_id>/characters/<character_id>/freeze-asset-pack",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "refreeze_spatial_plan":
            entry["rerun_strategy"] = (
                "Review stage map, screen direction, character positions, prop continuity, and camera axis; "
                "freeze a new spatial plan before regenerating affected shots."
            )
            entry["parameter_hints"] = {
                "repair_action": action,
                "require_stage_map": True,
                "require_camera_axis": True,
                "require_character_positions": True,
                "require_prop_positions": True,
                "invalidate_affected_shots": True,
            }
            entry["required_inputs"] = ["project_id", "scene_numbers", "spatial_plan_review"]
            commands = [
                "POST /api/projects/<project_id>/spatial-plan/freeze",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "fix_workflow_profile":
            entry["rerun_strategy"] = (
                "Repair and freeze the ComfyUI production workflow profile, verify hashes and required "
                "capabilities, then rerun the affected generation stage."
            )
            entry["parameter_hints"] = {
                "repair_action": action,
                "verify_workflow_hash": True,
                "require_identity_capability": True,
                "require_spatial_control_capability": True,
                "require_face_repair_capability": True,
                "require_upscale_capability": True,
                "freeze_before_generation": True,
            }
            entry["required_inputs"] = ["workflow_path", "workflow_capabilities", "workflow_sha256"]
            commands = [
                "POST /api/projects/workflow-profile/freeze",
                "python -m scripts.validate_local_generation preflight-production-video",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "start_local_reviewer":
            entry["rerun_strategy"] = (
                "Start the local VLM reviewer, verify its health endpoint, and rerun candidate review "
                "before accepting any generated media."
            )
            entry["parameter_hints"] = {
                "repair_action": action,
                "require_health_check": True,
                "require_candidate_review": True,
                "require_human_review_for_unavailable_cases": True,
            }
            entry["required_inputs"] = ["reviewer_base_url", "reviewer_model"]
            commands = [
                "python -m scripts.start_llm_service --help",
                f"python -m scripts.validate_local_generation review-images --output {output_path}",
                f"python -m scripts.validate_local_generation summarize --output {output_path}",
            ]
        elif action == "split_scene":
            entry["rerun_strategy"] = (
                "Split the overloaded scene into atomic shots with one visible action and one camera intent, "
                "then regenerate script, subtitles, audio, and video for the affected range."
            )
            entry["parameter_hints"] = {
                "repair_action": action,
                "one_visible_action_per_shot": True,
                "one_camera_intent_per_shot": True,
                "rebuild_downstream_assets": True,
                "rerun_story_room_gate": True,
            }
            entry["required_inputs"] = ["project_id", "scene_number", "split_plan"]
            commands = [
                "POST /api/projects/<project_id>/generate-script",
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


def _attach_image_pipeline_hint(
    entry: dict[str, Any],
    repair_action: str,
    shot_profile: dict[str, Any] | None = None,
) -> None:
    pipeline = image_quality_pipeline(shot_profile, repair_action)
    entry["quality_pipeline"] = pipeline.as_dict()
    entry.setdefault("parameter_hints", {})["required_quality_pipeline_stages"] = pipeline.stages
    entry["parameter_hints"]["required_workflow_capabilities"] = pipeline.required_capabilities


def _attach_video_pipeline_hint(
    entry: dict[str, Any],
    repair_action: str,
    shot_plan: dict[str, Any] | None = None,
) -> None:
    pipeline = video_quality_pipeline(shot_plan, repair_action)
    entry["quality_pipeline"] = pipeline.as_dict()
    entry.setdefault("parameter_hints", {})["required_quality_pipeline_stages"] = pipeline.stages
    entry["parameter_hints"]["required_workflow_capabilities"] = pipeline.required_capabilities
