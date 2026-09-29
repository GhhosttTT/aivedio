"""Convert generation review failures into targeted repair actions."""

from __future__ import annotations

from typing import Any


ACTION_RULES = [
    (
        (
            "story_room_quality", "story room quality", "short-drama rhythm", "story rhythm",
            "early_hook", "ending_hook", "escalation_cadence", "dialogue_or_reaction_drive",
            "emotional_progression", "market_brief", "reversal", "weak hook", "weak story",
            "too_many_actions_or_beats",
        ),
        "rewrite_short_drama_story_rhythm",
        "Rewrite the script with a visible early hook, recurring escalation, reversal, ending hook, dialogue/reaction drive, emotional progression, and atomic visual beats.",
        "script",
    ),
    (
        (
            "style drift", "visual style drift", "random color grade", "inconsistent color grade",
            "color grade drift", "inconsistent lighting", "lighting mismatch", "wardrobe drift",
            "set dressing drift", "scene style mismatch", "different project look", "look continuity",
            "episode style", "project style bible", "visual bible",
        ),
        "refine_project_style_consistency",
        "Regenerate the keyframe with locked project visual bible, color grade, lighting continuity, wardrobe continuity, and set dressing consistency.",
        "image",
    ),
    (
        (
            "final composition finishing", "final_composition_finishing", "exposure_uniformity",
            "skin_tone_uniformity", "color_grade_uniformity", "sharpness_uniformity",
            "subtitle_visual_integration", "overall_finish_polish", "finishing pass",
            "mixed generated clips", "exposure jumps", "skin tone jumps", "subtitle integration",
        ),
        "refine_final_composition_finish",
        "Rerun final composition finishing with unified exposure, skin tone, color grade, sharpness, subtitle integration, and publishable polish.",
        "video",
    ),
    (
        (
            "dialogue audio", "dialogue_audio", "dialogue_audio_quality", "dialogue_audio_quality_gate",
            "tts_emotion_match", "speech_pacing", "speech timing", "audio duration",
            "audio_duration", "audio missing", "missing audio", "flat tts", "monotone tts",
            "voice delivery", "dialogue delivery", "subtitle timing", "subtitle_sync",
        ),
        "refine_dialogue_audio_delivery",
        "Regenerate dialogue audio with short-drama emotion, pacing, and subtitle timing constraints.",
        "audio",
    ),
    (
        (
            "same-face casting", "same-face characters", "same face characters", "same-face cast",
            "no_same_face_casting", "copied facial geometry", "copied face geometry",
            "merged visual identity", "merged facial geometry", "role_readability",
            "character_distinctiveness", "character distinctiveness",
            "face_geometry_separation", "hair_separation", "wardrobe_separation",
        ),
        "regenerate_keyframe_with_role_separation",
        "Regenerate the keyframe with stricter multi-character role separation, identity contrast, face geometry, hair, and wardrobe constraints.",
        "image",
    ),
    (
        (
            "changed face", "changed hair", "changed wardrobe", "identity drift",
            "wrong camera angle versus character sheet", "wrong wardrobe", "face drift",
            "same-face", "same face", "face_geometry",
        ),
        "regenerate_keyframe_with_identity_lock",
        "Regenerate the keyframe with locked character-sheet identity, wardrobe, hair, and view-angle constraints.",
        "image",
    ),
    (
        ("turnaround", "front view", "side view", "back view", "profile view", "three-quarter", "expression", "body proportion", "wardrobe silhouette", "hair silhouette"),
        "regenerate_turnaround_album",
        "Generate and freeze a production character turnaround album before regenerating this character.",
        "character",
    ),
    (
        ("identity", "facial", "face drift", "same-face", "same face", "changed face"),
        "regenerate_character_identity",
        "Refresh character identity bible, production turnaround album, and reference image before regenerating this shot.",
        "character",
    ),
    (
        (
            "plastic skin", "skin_texture", "skin texture", "ai generated gloss", "ai gloss",
            "wax museum face", "waxy face", "airbrushed skin", "over-smoothed face",
            "over-beautified", "face rendering", "unnatural pores", "fake skin",
        ),
        "refine_face_aesthetic_detail",
        "Regenerate the keyframe with stricter natural face texture, pore detail, and premium short-drama beauty constraints.",
        "image",
    ),
    (
        (
            "spatial", "position", "left/right", "screen direction", "screen_direction_continuity",
            "character_position_continuity", "camera axis", "blocking", "stage map", "relative position",
            "prop_continuity", "cut_smoothness", "scene_order_coherence", "jarring cut", "jump cut",
        ),
        "refreeze_spatial_plan",
        "Review and freeze the spatial plan before regenerating the affected shots.",
        "spatial",
    ),
    (
        ("workflow profile", "workflow", "controlnet", "openpose", "depth", "face repair", "upscale", "missing capability"),
        "fix_workflow_profile",
        "Fix and approve the ComfyUI production workflow profile before rerunning generation.",
        "workflow",
    ),
    (
        ("hand", "finger", "prop", "disappear", "letter", "phone", "cup", "object"),
        "regenerate_keyframe_with_prop_constraints",
        "Regenerate the keyframe with stricter hand and prop continuity constraints.",
        "image",
    ),
    (
        (
            "crop", "composition", "lighting", "light jumps", "muddy", "blur", "sharpness", "exposure",
            "aesthetic", "platform score", "production value", "cheap filter", "plastic skin", "commercial",
            "skin_texture", "lighting_quality", "lighting_consistency", "color_grade", "color_grade_consistency",
            "phone_readability", "background_separation", "production_polish", "ai generated gloss", "ai gloss",
            "wax museum face", "over-beautified", "low-budget set", "low budget set", "messy wardrobe",
        ),
        "refine_prompt_composition",
        "Tighten composition, lighting, crop, and visual clarity before regenerating candidates.",
        "image",
    ),
    (
        ("random text", "logo", "watermark", "repair scar", "inpaint scar", "artifact", "dirty background"),
        "refine_prompt_composition",
        "Regenerate with stronger negative prompts and cleaner background/retouch constraints.",
        "image",
    ),
    (
        (
            "flicker", "flickers", "temporal", "motion", "motion_smoothness", "stutter", "camera jump",
            "warped body", "melting", "first frame", "last frame", "background_stability",
            "artifact_absence", "repair scar flickers",
        ),
        "lower_motion_and_regenerate_video",
        "Lower motion strength/noise and regenerate the video clip from the accepted keyframe.",
        "video",
    ),
    (
        (
            "video performance", "video_performance", "emotion_readability", "gaze_intent",
            "dialogue_reaction", "body_language", "action_intent", "flat acting",
            "unreadable emotion", "dead eyes", "no reaction", "acting", "performance",
        ),
        "regenerate_video_with_performance_direction",
        "Regenerate the clip with stronger shot-plan acting direction, readable emotion, intentional gaze, dialogue reaction, and body language.",
        "video",
    ),
    (
        ("unreadable action", "too complex", "multi-action", "needs_split", "split"),
        "split_scene",
        "Split this scene into simpler atomic shots before running production generation.",
        "script",
    ),
    (
        ("review unavailable", "no local vlm", "technical_only", "review failed"),
        "start_local_reviewer",
        "Start llama.cpp VLM review and rerun candidate selection before accepting output.",
        "review",
    ),
]


def build_repair_queue(report: dict[str, Any], media_type: str) -> list[dict[str, Any]]:
    """Return deduplicated repair actions for a quality report."""

    actions: list[dict[str, Any]] = []
    for candidate in report.get("candidates", []) or []:
        actions.extend(_actions_for_candidate(candidate, media_type))
    for batch in report.get("batches", []) or []:
        if not isinstance(batch, dict):
            continue
        candidate = dict(batch)
        if isinstance(report.get("scene"), dict) and not isinstance(candidate.get("scene"), dict):
            candidate["scene"] = report["scene"]
        if report.get("stage") and not candidate.get("stage"):
            candidate["stage"] = report["stage"]
        actions.extend(_actions_for_candidate(candidate, media_type))
    for candidate in _top_level_gate_candidates(report):
        actions.extend(_actions_for_candidate(candidate, media_type))
    if report.get("error"):
        action = _classify_evidence(str(report["error"]), media_type, report)
        if action:
            actions.append(action)
    if report.get("status") in {"needs_review", "review_unavailable"} and not actions:
        actions.append({
            "priority": "high",
            "stage": media_type,
            "action": "manual_review",
            "reason": "Quality report needs review but did not expose a specific repair reason.",
            "scene_number": _first_scene_number(report),
        })
    return _dedupe(actions)


def attach_repair_queue(report: dict[str, Any], media_type: str) -> dict[str, Any]:
    report["repair_queue"] = build_repair_queue(report, media_type)
    return report


def _top_level_gate_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for gate_name in ("episode_style_consistency_gate", "dialogue_audio_quality_gate"):
        gate = report.get(gate_name)
        if not isinstance(gate, dict):
            continue
        low = gate.get("low") if isinstance(gate.get("low"), dict) else {}
        for key, payload in low.items():
            scene_number = payload.get("scene_number") if isinstance(payload, dict) else None
            candidates.append({
                "index": key,
                "scene": {"scene_number": scene_number} if isinstance(scene_number, int) else {},
                gate_name: {
                    "status": "needs_review",
                    "low": {key: payload},
                    "missing": [],
                },
            })
    story_gate = report.get("story_room_quality_gate")
    if isinstance(story_gate, dict):
        missing = story_gate.get("missing") if isinstance(story_gate.get("missing"), list) else []
        if missing:
            candidates.append({
                "index": "story_room_quality",
                "scene": {},
                "story_room_quality_gate": {
                    "status": "needs_review",
                    "low": {},
                    "missing": missing,
                },
            })
        low = story_gate.get("low") if isinstance(story_gate.get("low"), dict) else {}
        for key, payload in low.items():
            scene_number = payload.get("scene_number") if isinstance(payload, dict) else None
            candidates.append({
                "index": key,
                "scene": {"scene_number": scene_number} if isinstance(scene_number, int) else {},
                "story_room_quality_gate": {
                    "status": "needs_review",
                    "low": {key: payload},
                    "missing": [],
                },
            })
    return candidates


def _actions_for_candidate(candidate: dict[str, Any], media_type: str) -> list[dict[str, Any]]:
    actions = []
    evidence_items = _candidate_evidence(candidate)
    for evidence in evidence_items:
        action = _classify_evidence(str(evidence), media_type, candidate)
        if action:
            actions.append(action)
    return actions


def _candidate_evidence(candidate: dict[str, Any]) -> list[str]:
    evidence = []
    if candidate.get("error"):
        evidence.append(str(candidate["error"]))
    if candidate.get("status"):
        evidence.append(str(candidate["status"]))
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    for issue in review.get("issues", []) or []:
        if isinstance(issue, dict):
            evidence.append(str(issue.get("reason") or ""))
    for key, value in review.items():
        if isinstance(value, dict) and value.get("score", 5) <= 3:
            evidence.append(str(value.get("evidence") or key))
            evidence.append(str(key))
        elif isinstance(value, dict):
            evidence.extend(_nested_score_evidence(value))
    for gate_name in (
        "platform_aesthetic_gate",
        "video_aesthetic_gate",
        "episode_style_consistency_gate",
        "episode_continuity_gate",
        "turnaround_gate",
        "character_distinctiveness_gate",
        "video_performance_gate",
        "final_composition_finishing_gate",
        "dialogue_audio_quality_gate",
        "story_room_quality_gate",
    ):
        gate = candidate.get(gate_name) if isinstance(candidate.get(gate_name), dict) else {}
        evidence.extend(_gate_evidence(gate, gate_name))
    evidence.extend(_technical_metric_evidence(candidate))
    return [item for item in evidence if item]


def _technical_metric_evidence(candidate: dict[str, Any]) -> list[str]:
    evidence = []
    image_metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    image_score = image_metrics.get("technical_score")
    if image_metrics and isinstance(image_score, (int, float)) and image_score < 3:
        evidence.append("low technical image score: exposure sharpness composition")
        if image_metrics.get("sharpness", 99) < 4:
            evidence.append("low image sharpness and blurry keyframe")
        mean_luma = image_metrics.get("mean_luma")
        if isinstance(mean_luma, (int, float)) and (mean_luma < 65 or mean_luma > 205):
            evidence.append("bad image exposure and lighting balance")
        if image_metrics.get("colorfulness", 99) < 6:
            evidence.append("dull color grade and weak production polish")

    video_metrics = candidate.get("technical_metrics") if isinstance(candidate.get("technical_metrics"), dict) else {}
    video_score = video_metrics.get("technical_score")
    if video_metrics and isinstance(video_score, (int, float)) and video_score < 3:
        if video_metrics.get("motion_energy", 99) < 2:
            evidence.append("video motion too static or frozen")
        if video_metrics.get("sharpness", 99) < 8:
            evidence.append("video sharpness collapsed and blurry frames")
        brightness = video_metrics.get("brightness")
        if isinstance(brightness, (int, float)) and (brightness < 65 or brightness > 205):
            evidence.append("video exposure is outside usable range")
        if video_metrics.get("brightness_variance", 0) > 500:
            evidence.append("video brightness flicker and unstable exposure")
        evidence.append("low technical video score: motion sharpness exposure stability")
    return evidence


def _nested_score_evidence(section: dict[str, Any]) -> list[str]:
    evidence = []
    for key, value in section.items():
        if isinstance(value, dict) and value.get("score", 5) <= 3:
            evidence.append(str(value.get("evidence") or key))
            evidence.append(str(key))
    return evidence


def _gate_evidence(gate: dict[str, Any], gate_name: str) -> list[str]:
    evidence = []
    for bucket in ("low", "missing"):
        values = gate.get(bucket)
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, dict):
                    evidence.append(str(value.get("evidence") or key))
                evidence.append(str(key))
        elif isinstance(values, list):
            evidence.extend(str(item) for item in values)
    if evidence:
        evidence.append(gate_name)
    return evidence


def _classify_evidence(evidence: str, media_type: str, candidate: dict[str, Any]) -> dict[str, Any] | None:
    text = evidence.lower()
    if text.startswith("low technical image score") or text.startswith("low image sharpness") or text.startswith("bad image exposure") or text.startswith("dull color grade"):
        return {
            "priority": _priority(text),
            "stage": "image",
            "action": "refine_prompt_composition",
            "execution": _execution_mode("refine_prompt_composition"),
            "reason": evidence[:240],
            "recommendation": "Regenerate with stronger lighting, exposure, sharpness, color grade, and clean composition constraints.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if text.startswith("video motion too static"):
        return {
            "priority": _priority(text),
            "stage": "video",
            "action": "increase_motion_and_regenerate_video",
            "execution": _execution_mode("increase_motion_and_regenerate_video"),
            "reason": evidence[:240],
            "recommendation": "Regenerate the clip with a higher motion floor so it does not read as a frozen still.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if text.startswith("low technical video score") or text.startswith("video sharpness collapsed") or text.startswith("video exposure") or text.startswith("video brightness flicker"):
        return {
            "priority": _priority(text),
            "stage": "video",
            "action": "lower_motion_and_regenerate_video",
            "execution": _execution_mode("lower_motion_and_regenerate_video"),
            "reason": evidence[:240],
            "recommendation": "Regenerate the clip with lower motion/noise and keep only candidates with readable motion, sharp frames, and stable exposure.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if media_type == "video" and any(
        term in text
        for term in (
            "video performance", "video_performance", "emotion_readability", "gaze_intent",
            "dialogue_reaction", "body_language", "action_intent", "flat acting",
            "unreadable emotion", "dead eyes", "no reaction", "acting", "performance",
        )
    ):
        return {
            "priority": _priority(text),
            "stage": "video",
            "action": "regenerate_video_with_performance_direction",
            "execution": _execution_mode("regenerate_video_with_performance_direction"),
            "reason": evidence[:240],
            "recommendation": "Regenerate the clip with stronger shot-plan acting direction, readable emotion, intentional gaze, dialogue reaction, and body language.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if media_type == "video" and any(
        term in text
        for term in (
            "final composition finishing", "final_composition_finishing", "exposure_uniformity",
            "skin_tone_uniformity", "color_grade_uniformity", "sharpness_uniformity",
            "subtitle_visual_integration", "overall_finish_polish", "finishing pass",
            "mixed generated clips", "exposure jumps", "skin tone jumps",
        )
    ):
        return {
            "priority": _priority(text),
            "stage": "video",
            "action": "refine_final_composition_finish",
            "execution": _execution_mode("refine_final_composition_finish"),
            "reason": evidence[:240],
            "recommendation": "Rerun final composition finishing with unified exposure, skin tone, color grade, sharpness, subtitle integration, and publishable polish.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if media_type == "video" and any(
        term in text
        for term in (
            "video aesthetic", "video_aesthetic", "commercial_aesthetic", "commercial aesthetic",
            "platform score", "production value", "production polish", "commercial polish",
            "color_grade", "lighting_quality", "lighting consistency", "phone-frame polish",
        )
    ):
        return {
            "priority": _priority(text),
            "stage": "video",
            "action": "refine_video_commercial_aesthetic",
            "execution": _execution_mode("refine_video_commercial_aesthetic"),
            "reason": evidence[:240],
            "recommendation": "Regenerate the clip with stricter commercial short-drama lighting, color grade, phone-frame composition, and production polish constraints.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if any(term in text for term in ("after face repair", "face repair scar", "distorted face repair")):
        return {
            "priority": _priority(text),
            "stage": "workflow",
            "action": "fix_workflow_profile",
            "execution": _execution_mode("fix_workflow_profile"),
            "reason": evidence[:240],
            "recommendation": "Fix the local face/detail/upscale workflow or postprocess command before rerunning generation.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    if media_type == "video" and any(
        term in text
        for term in ("changed face", "changed hair", "changed wardrobe", "identity drift", "face drift")
    ):
        return {
            "priority": _priority(text),
            "stage": "video",
            "action": "lower_motion_and_regenerate_video",
            "execution": _execution_mode("lower_motion_and_regenerate_video"),
            "reason": evidence[:240],
            "recommendation": "Lower motion/noise and regenerate the clip to reduce identity drift across frames.",
            "candidate_index": candidate.get("index"),
            "scene_number": _scene_number(candidate),
        }
    for keywords, action, message, stage in ACTION_RULES:
        if any(keyword in text for keyword in keywords):
            return {
                "priority": _priority(text),
                "stage": stage if media_type == "video" or stage != "video" else media_type,
                "action": action,
                "execution": _execution_mode(action),
                "reason": evidence[:240],
                "recommendation": message,
                "candidate_index": candidate.get("index"),
                "scene_number": _scene_number(candidate),
            }
    return None


def _execution_mode(action: str) -> str:
    if action in {
        "regenerate_keyframe_with_identity_lock",
        "regenerate_keyframe_with_role_separation",
        "regenerate_keyframe_with_prop_constraints",
        "refine_prompt_composition",
        "refine_face_aesthetic_detail",
        "refine_project_style_consistency",
        "lower_motion_and_regenerate_video",
        "increase_motion_and_regenerate_video",
        "regenerate_video_with_performance_direction",
        "refine_video_commercial_aesthetic",
        "refine_final_composition_finish",
        "refine_dialogue_audio_delivery",
    }:
        return "auto"
    if action in {
        "regenerate_turnaround_album",
        "regenerate_character_identity",
        "refreeze_spatial_plan",
        "fix_workflow_profile",
        "start_local_reviewer",
        "rewrite_short_drama_story_rhythm",
    }:
        return "setup_required"
    return "manual"


def _priority(text: str) -> str:
    if any(term in text for term in ("critical", "major", "failed", "below", "unavailable")):
        return "high"
    if any(term in text for term in ("warning", "minor")):
        return "medium"
    return "high"


def _scene_number(candidate: dict[str, Any]) -> int | None:
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    issues = review.get("issues", []) if isinstance(review, dict) else []
    for issue in issues:
        if isinstance(issue, dict) and isinstance(issue.get("scene_number"), int):
            return issue["scene_number"]
    scene = candidate.get("scene") if isinstance(candidate.get("scene"), dict) else {}
    return scene.get("scene_number") if isinstance(scene.get("scene_number"), int) else None


def _first_scene_number(report: dict[str, Any]) -> int | None:
    for candidate in report.get("candidates", []) or []:
        if isinstance(candidate, dict):
            scene_number = _scene_number(candidate)
            if isinstance(scene_number, int):
                return scene_number
    for batch in report.get("batches", []) or []:
        if isinstance(batch, dict):
            candidate = dict(batch)
            if isinstance(report.get("scene"), dict) and not isinstance(candidate.get("scene"), dict):
                candidate["scene"] = report["scene"]
            scene_number = _scene_number(candidate)
            if isinstance(scene_number, int):
                return scene_number
    return None


def _dedupe(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for action in actions:
        key = (action.get("action"), action.get("stage"), action.get("scene_number"))
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result[:8]
