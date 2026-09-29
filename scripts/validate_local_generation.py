"""Run with python -m scripts.validate_local_generation; never substitutes draft media."""

import argparse
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from src.config import settings
from src.services.generation_provider import _extract_workflow_image_metadata
from src.services.comfyui_service import ComfyUIService
from src.services.image_quality_service import ImageQualitySelector
from src.services.video_engine_preflight import (
    VIDEO_WORKFLOW_PLACEHOLDERS,
    likely_video_outputs as _likely_video_outputs,
    preflight_production_video_engine,
    preflight_video_workflow,
    scan_placeholders as _scan_placeholders,
)
from src.services.generation_review import GenerationReviewService, platform_video_score, write_report
from src.services.shot_prompt_service import ShotPromptService
from src.services.repair_queue import attach_repair_queue, build_repair_queue
from src.services.repair_plan import build_repair_execution_plan
from src.services.quality_loop import build_quality_loop_plan
from src.tasks.image_tasks import _apply_image_repair_action, _quality_parameters, _repair_parameter_profile
from scripts.compare_video_baseline import compare as compare_video_baseline

REQUIRED_SAMPLE_COVERAGE = {
    "establishing": "empty or environment establishing shot",
    "single_character_identity": "single-character identity and wardrobe lock shot",
    "reaction_closeup": "close-up reaction with readable expression and face detail",
    "distinct_role_reverse_shot": "second-role or reverse-shot identity distinctiveness shot",
    "prop_story_evidence": "story-critical prop readability shot",
    "stylized_generated_source": "stylized or fully generated source-look shot",
}

REQUIRED_MANUAL_CASE_DIMENSIONS = {
    "identity_match": "character identity, wardrobe, and face match the intended role",
    "phone_readability": "face, prop, and action read clearly on a vertical phone screen",
    "platform_aesthetic": "lighting, skin texture, color, and composition meet premium short-drama expectations",
    "visual_integrity": "hands, props, anatomy, text, and artifacts are clean enough for production",
    "story_match": "image matches the written scene intent without distracting additions",
}

REQUIRED_MANUAL_CLIP_DIMENSIONS = {
    "identity_stability": "character identity and wardrobe stay stable across the full clip",
    "temporal_motion": "motion is smooth enough with no major flicker, warping, or frozen-frame feel",
    "acting_performance": "emotion, gaze, dialogue reaction, and body language are readable",
    "commercial_aesthetic": "overall look is polished enough against the Seed Dance contact sheet",
    "composition_continuity": "frame, crop, camera direction, and scene continuity hold through the clip",
}

MANUAL_CASE_DIMENSION_REPAIR_HINTS = {
    "identity_match": "identity drift face drift changed wardrobe wrong view angle",
    "phone_readability": "phone_readability crop composition face prop action clarity",
    "platform_aesthetic": "platform score commercial aesthetic lighting skin_texture production value",
    "visual_integrity": "visual_integrity artifact hand finger prop anatomy random text",
    "story_match": "story_match composition prompt alignment visual scene intent",
}

MANUAL_CLIP_DIMENSION_REPAIR_HINTS = {
    "identity_stability": "identity drift face drift changed wardrobe temporal stability",
    "temporal_motion": "temporal motion flicker camera jump warped body melting",
    "acting_performance": "video performance acting no reaction dialogue_reaction body_language gaze_intent",
    "commercial_aesthetic": "video aesthetic commercial_aesthetic platform score production value lighting color_grade",
    "composition_continuity": "temporal camera jump composition continuity crop screen direction",
}


def _review_models_endpoint() -> str:
    endpoint = settings.LOCAL_REVIEW_BASE_URL.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    return endpoint + "/models"


def _installed_review_models() -> list[str]:
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.get(_review_models_endpoint())
        response.raise_for_status()
        payload = response.json()
    models = payload.get("data", [])
    names = []
    for item in models:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if name:
                names.append(str(name))
    return names


def preflight(base_url=None):
    report = {"python": platform.python_version(), "checks": {}, "status": "blocked"}
    checks = report["checks"]
    checks["ffmpeg"] = shutil.which("ffmpeg")
    checks["ffprobe"] = shutil.which("ffprobe")
    checks["text_model"] = Path(settings.LLM_MODEL_PATH).is_file()
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=15, check=True)
        checks["local_gpu"] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        checks["local_gpu"] = None
        report["gpu_error"] = str(exc)
    try:
        service = ComfyUIService(base_url=base_url, timeout=15)
        try:
            graph = service._build_workflow("empty office, wide shot", "blurry",
                                            settings.GENERATION_WIDTH, settings.GENERATION_HEIGHT,
                                            settings.GENERATION_STEPS, settings.GENERATION_CFG, 31001)
            service.preflight(graph)
            checks["comfyui"] = True
            report["workflow"] = service.workflow_manager.get_current_workflow().workflow.name
            stats = service.client.get(service.base_url + "/system_stats")
            stats.raise_for_status()
            report["comfyui_devices"] = stats.json().get("devices", [])
        finally:
            service.client.close()
    except Exception as exc:
        checks["comfyui"] = False
        report["comfyui_error"] = str(exc)
    try:
        names = _installed_review_models()
        checks["review_model"] = settings.LOCAL_REVIEW_MODEL in names
        report["review_models_endpoint"] = _review_models_endpoint()
        report["installed_review_models"] = names
    except Exception as exc:
        checks["review_model"] = False
        report["review_error"] = str(exc)
    if all(checks.get(key) for key in ("ffmpeg", "ffprobe", "text_model", "comfyui", "review_model")):
        report["status"] = "ready_for_live_test"
    return report


def render_images(
    cases,
    output: Path,
    base_url=None,
    reference=None,
    quality_mode: str = "ultra",
    optimization_mode: str = "quality",
    repair_action: str | None = None,
    scene_number: int | None = None,
):
    steps, cfg_scale = _quality_parameters(
        0,
        0,
        settings.GENERATION_STEPS,
        settings.GENERATION_CFG,
        repair_action=repair_action,
    )
    report = {
        "status": "error",
        "quality_accepted": False,
        "render_profile": {
            "quality_mode": quality_mode,
            "optimization_mode": optimization_mode,
            "width": settings.GENERATION_WIDTH,
            "height": settings.GENERATION_HEIGHT,
            "base_steps": steps,
            "base_cfg": cfg_scale,
            "uses_reference": bool(reference),
            "prompt_optimization": True,
            "parameter_optimization": quality_mode in {"high_quality", "ultra"},
            "repair_action": repair_action,
            "repair_parameter_profile": _repair_parameter_profile(repair_action),
            "target_scene_number": scene_number,
        },
        "cases": [],
        "skipped_cases": [],
    }
    service = ComfyUIService(base_url=base_url, timeout=900)
    try:
        for case in cases:
            if not str(case["id"]).replace("_", "").isalnum():
                raise ValueError("Case ID must be alphanumeric")
            case_scene = case.get("scene") if isinstance(case.get("scene"), dict) else {}
            case_scene_number = case_scene.get("scene_number")
            if scene_number is not None and case_scene_number != scene_number:
                report["skipped_cases"].append({
                    "id": case["id"],
                    "scene_number": case_scene_number,
                    "reason": "scene_number_filter",
                })
                continue
            compiled = ShotPromptService().compile(case["prompt"])
            prompt, negative_prompt = _apply_image_repair_action(
                compiled.prompt,
                compiled.negative_prompt,
                repair_action,
            )
            path = output / (case["id"] + ".png")
            case_reference = case.get("reference_image") or case.get("reference") or reference
            started = time.monotonic()
            image = service.generate_image(
                prompt=prompt, negative_prompt=negative_prompt,
                output_path=str(path), seed=case["seed"], reference_image=case_reference,
                use_ipadapter=bool(case_reference), width=settings.GENERATION_WIDTH,
                height=settings.GENERATION_HEIGHT, steps=steps,
                cfg_scale=cfg_scale,
                quality_mode=quality_mode,
                optimization_mode=optimization_mode,
                enable_prompt_optimization=True,
                enable_parameter_optimization=quality_mode in {"high_quality", "ultra"},
            )
            report["cases"].append({
                "id": case["id"],
                "image": image,
                "seed": case["seed"],
                "source_prompt": case["prompt"],
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "scene": case.get("scene", {}),
                "validation_categories": case.get("validation_categories", []),
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "actual_workflow": _extract_workflow_image_metadata(image),
                "request": {
                    "width": settings.GENERATION_WIDTH,
                    "height": settings.GENERATION_HEIGHT,
                    "steps": steps,
                    "cfg_scale": cfg_scale,
                    "quality_mode": quality_mode,
                    "optimization_mode": optimization_mode,
                    "reference_image": case_reference,
                    "use_ipadapter": bool(case_reference),
                    "enable_prompt_optimization": True,
                    "enable_parameter_optimization": quality_mode in {"high_quality", "ultra"},
                    "repair_action": repair_action,
                    "repair_parameter_profile": _repair_parameter_profile(repair_action),
                },
            })
            write_report(output / "render.json", report)
        if not report["cases"]:
            raise ValueError(f"No validation cases matched scene_number={scene_number}")
        report["status"] = "rendered_pending_human_review"
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        service.client.close()
    write_report(output / "render.json", report)
    return report


def review_images(output: Path, reference=None):
    render_report = _read_json(output / "render.json")
    report = {"status": "error", "cases": [], "repair_queue": []}
    if not isinstance(render_report, dict) or render_report.get("status") != "rendered_pending_human_review":
        report["error"] = "render.json is missing or render-images has not completed"
        write_report(output / "image_review.json", report)
        return report
    selector = ImageQualitySelector()
    for index, case in enumerate(render_report.get("cases", []), start=1):
        image = Path(str(case.get("image") or ""))
        if not image.is_absolute():
            image = output / image
        scene = case.get("scene") if isinstance(case.get("scene"), dict) else {}
        payload = {
            "scene_number": int(scene.get("scene_number") or index),
            "visual_description": scene.get("visual_description") or case.get("prompt") or case.get("id") or "",
            "visible_characters": scene.get("visible_characters", []),
            "reference_requirements": scene.get("reference_requirements", []),
        }
        for key in ("turnaround_view", "turnaround_expected_features", "turnaround_control_prompt"):
            if key in scene:
                payload[key] = scene[key]
        case_reference = reference or (case.get("request") or {}).get("reference_image")
        try:
            case_report = selector.review_candidate(
                index,
                image,
                payload,
                str(case.get("prompt") or ""),
                case_reference,
            )
        except Exception as exc:
            case_report = {
                "index": index,
                "status": "error",
                "path": str(image),
                "error": str(exc),
            }
        case_report["id"] = case.get("id")
        case_report["image"] = str(image)
        case_report["scene"] = {
            "scene_number": payload["scene_number"],
            "visual_description": payload["visual_description"],
        }
        report["cases"].append(case_report)
    report["status"] = "passed" if _image_review_cases_passed(report) else "needs_review"
    if report["status"] != "passed":
        queue_report = {
            "status": report["status"],
            "candidates": report["cases"],
        }
        attach_repair_queue(queue_report, "image")
        report["repair_queue"] = queue_report.get("repair_queue", [])
    write_report(output / "image_review.json", report)
    return report


def _read_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _issue_text(case: dict) -> str:
    tags = case.get("issue_tags") or case.get("issues") or []
    if isinstance(tags, str):
        tags = [tags]
    return " ".join(str(item).lower() for item in tags + [case.get("note", ""), case.get("reason", "")])


def _manual_blocking_issues(manual_cases: list[dict], manual_clip: dict) -> list[dict]:
    blocking_tokens = (
        "identity drift", "face drift", "same-face", "same face", "not same person",
        "flicker", "warp", "warping", "temporal break", "broken motion",
        "broken hand", "bad anatomy", "artifact", "random text", "watermark",
        "身份漂移", "脸漂移", "不像", "同脸", "闪烁", "变形", "动作断", "坏手", "水印", "随机文字",
    )
    findings = []
    review_items = list(manual_cases)
    if manual_clip:
        review_items.append({"id": "clip", **manual_clip})
    for item in review_items:
        tags = []
        for key in ("blocking_issues", "issue_tags", "issues"):
            value = item.get(key)
            if isinstance(value, str):
                tags.append(value)
            elif isinstance(value, list):
                tags.extend(str(tag) for tag in value)
        text = " ".join(tags).lower()
        matched = sorted({token for token in blocking_tokens if token in text})
        if matched:
            findings.append({
                "id": str(item.get("id") or "clip"),
                "blocking_issues": matched,
            })
    return findings


def _manual_scene_number(item: dict) -> int | None:
    value = item.get("scene_number")
    if value is None:
        value = item.get("scene")
    if isinstance(value, dict):
        value = value.get("scene_number")
    try:
        scene_number = int(value)
    except (TypeError, ValueError):
        return None
    return scene_number if scene_number > 0 else None


def _manual_issue_reasons(item: dict) -> list[str]:
    reasons = []
    for key in ("blocking_issues", "issue_tags", "issues"):
        value = item.get(key)
        if isinstance(value, str):
            reasons.append(value)
        elif isinstance(value, list):
            reasons.extend(str(tag) for tag in value)
    if item.get("decision") == "reject":
        reasons.append(str(item.get("note") or item.get("reason") or "manual review rejected this output"))
    score = item.get("score")
    if isinstance(score, (int, float)) and score < 4:
        reasons.append(str(item.get("note") or item.get("reason") or f"manual score {score} below 4"))
    return [reason for reason in reasons if reason and reason.strip()]


def _manual_dimension_issue_reasons(
    item: dict,
    required: dict[str, str],
    repair_hints: dict[str, str],
    item_kind: str,
) -> list[str]:
    scores = _dimension_scores(item)
    reasons = []
    for dimension, description in required.items():
        hint = repair_hints.get(dimension, dimension)
        if dimension not in scores:
            continue
        score = scores[dimension]
        if score < 4:
            reasons.append(
                f"manual {item_kind} dimension {dimension} score {score:g} below 4: {description}; repair focus {hint}"
            )
    return reasons


def _render_scene_by_case_id(render_report: dict | None) -> dict[str, dict]:
    if not isinstance(render_report, dict):
        return {}
    cases = render_report.get("cases", []) if isinstance(render_report.get("cases"), list) else []
    result = {}
    for case in cases:
        if isinstance(case, dict) and case.get("id") is not None and isinstance(case.get("scene"), dict):
            result[str(case["id"])] = case["scene"]
    return result


def _manual_repair_queue(manual_review: dict | None, render_report: dict | None = None) -> list[dict]:
    if not isinstance(manual_review, dict):
        return []
    queue: list[dict] = []
    render_scene_by_id = _render_scene_by_case_id(render_report)
    cases = manual_review.get("cases", []) if isinstance(manual_review.get("cases"), list) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        reasons = _manual_issue_reasons(case)
        reasons.extend(_manual_dimension_issue_reasons(
            case,
            REQUIRED_MANUAL_CASE_DIMENSIONS,
            MANUAL_CASE_DIMENSION_REPAIR_HINTS,
            "case",
        ))
        if not reasons:
            continue
        if not isinstance(case.get("scene"), dict) and case.get("id") is not None:
            case = {**case, "scene": render_scene_by_id.get(str(case["id"]), {})}
        scene_number = _manual_scene_number(case)
        report = {
            "status": "needs_review",
            "candidates": [{
                "index": case.get("id"),
                "scene": {"scene_number": scene_number} if scene_number else {},
                "review": {
                    "issues": [
                        {
                            "severity": "major",
                            "reason": reason,
                            **({"scene_number": scene_number} if scene_number else {}),
                        }
                        for reason in reasons
                    ],
                },
            }],
        }
        queue.extend(build_repair_queue(report, "image"))
    clip = _manual_clip_review(manual_review)
    clip_reasons = []
    if clip:
        clip_reasons = _manual_issue_reasons({"id": "clip", **clip})
        clip_reasons.extend(_manual_dimension_issue_reasons(
            clip,
            REQUIRED_MANUAL_CLIP_DIMENSIONS,
            MANUAL_CLIP_DIMENSION_REPAIR_HINTS,
            "clip",
        ))
    if clip_reasons:
        report = {
            "status": "needs_review",
            "batches": [{
                "status": "needs_review",
                "review": {
                    "issues": [
                        {"severity": "major", "reason": reason}
                        for reason in clip_reasons
                    ],
                },
            }],
        }
        queue.extend(build_repair_queue(report, "video"))
    return queue


def _review_low_dimensions(video_review_report: dict | None) -> list[str]:
    low = []
    if not isinstance(video_review_report, dict):
        return low
    for batch in video_review_report.get("batches", []):
        review = batch.get("review", {})
        for key, value in review.items():
            if isinstance(value, dict) and value.get("score", 5) < 4:
                low.append(key)
    return sorted(set(low))


def _video_review_gate_scores(video_review_report: dict | None) -> dict[str, float]:
    if not isinstance(video_review_report, dict):
        return {}
    scores: dict[str, list[float]] = {
        "facial_identity": [],
        "identity_consistency": [],
        "temporal_consistency": [],
    }
    for batch in video_review_report.get("batches", []):
        review = batch.get("review", {})
        for key in scores:
            value = review.get(key)
            if isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
                scores[key].append(float(value["score"]))
    return {key: min(values) for key, values in scores.items() if values}


def _video_review_platform_score(video_review_report: dict | None) -> float | None:
    if not isinstance(video_review_report, dict):
        return None
    scores = []
    for batch in video_review_report.get("batches", []):
        if isinstance(batch.get("platform_score"), (int, float)):
            scores.append(float(batch["platform_score"]))
            continue
        review = batch.get("review", {})
        score = platform_video_score(review) if isinstance(review, dict) else None
        if score is not None:
            scores.append(score)
    return round(min(scores), 2) if scores else None


def _video_aesthetic_gates_passed(video_review_report: dict | None) -> bool:
    if not isinstance(video_review_report, dict):
        return False
    batches = video_review_report.get("batches", [])
    if not batches:
        return False
    for batch in batches:
        gate = batch.get("video_aesthetic_gate") if isinstance(batch, dict) else None
        if not isinstance(gate, dict) or gate.get("status") != "passed":
            return False
    return True


def _video_character_distinctiveness_gates_passed(video_review_report: dict | None) -> bool:
    if not isinstance(video_review_report, dict):
        return True
    gates = [
        batch.get("character_distinctiveness_gate")
        for batch in video_review_report.get("batches", [])
        if isinstance(batch, dict) and isinstance(batch.get("character_distinctiveness_gate"), dict)
    ]
    return all(gate.get("status") == "passed" for gate in gates)


def _video_performance_gates_passed(video_review_report: dict | None) -> bool:
    if not isinstance(video_review_report, dict):
        return False
    batches = video_review_report.get("batches", [])
    if not batches:
        return False
    for batch in batches:
        gate = batch.get("video_performance_gate") if isinstance(batch, dict) else None
        if not isinstance(gate, dict) or gate.get("status") != "passed":
            return False
    return True


def _quality_reports(output: Path) -> dict[str, dict]:
    reports = {}
    for path in sorted(output.rglob("*.quality.json")):
        try:
            payload = _read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            reports[str(path.relative_to(output))] = payload
    return reports


def _composition_review_reports(output: Path) -> dict[str, dict]:
    reports = {}
    for path in sorted(output.rglob("*.composition_review.json")):
        try:
            payload = _read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            reports[str(path.relative_to(output))] = payload
    return reports


def _final_video_reviews(quality_reports: dict[str, dict]) -> list[dict]:
    reviews = []
    for source, report in quality_reports.items():
        review = report.get("final_video_review")
        if isinstance(review, dict):
            reviews.append({"source_report": source, **review})
    return reviews


def _composition_reviews(composition_reports: dict[str, dict]) -> list[dict]:
    reviews = []
    for source, report in composition_reports.items():
        reviews.append({"source_report": source, **report})
    return reviews


def _final_video_reviews_passed(final_reviews: list[dict]) -> bool:
    if not final_reviews:
        return True
    for review in final_reviews:
        if review.get("status") != "passed":
            return False
        if float(review.get("average") or 0) < settings.GENERATION_VIDEO_MIN_SCORE:
            return False
        gate_scores = review.get("gate_scores") if isinstance(review.get("gate_scores"), dict) else {}
        if gate_scores:
            if float(gate_scores.get("facial_identity") or 0) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
                return False
            if float(gate_scores.get("identity_consistency") or 0) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
                return False
            if float(gate_scores.get("temporal_consistency") or 0) < settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE:
                return False
        platform_score = review.get("platform_score")
        if isinstance(platform_score, (int, float)) and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
            return False
        aesthetic_gate = review.get("video_aesthetic_gate")
        if not isinstance(aesthetic_gate, dict) or aesthetic_gate.get("status") != "passed":
            return False
        distinctiveness_gate = review.get("character_distinctiveness_gate")
        if isinstance(distinctiveness_gate, dict) and distinctiveness_gate.get("status") != "passed":
            return False
        performance_gate = review.get("video_performance_gate")
        if not isinstance(performance_gate, dict) or performance_gate.get("status") != "passed":
            return False
    return True


def _composition_reviews_passed(composition_reviews: list[dict]) -> bool:
    if not composition_reviews:
        return True
    for review in composition_reviews:
        if review.get("status") != "passed":
            return False
        if float(review.get("average") or 0) < settings.GENERATION_VIDEO_MIN_SCORE:
            return False
        batches = review.get("batches") if isinstance(review.get("batches"), list) else []
        if not batches:
            return False
        for batch in batches:
            if not isinstance(batch, dict) or batch.get("status") != "passed":
                return False
            batch_review = batch.get("review") if isinstance(batch.get("review"), dict) else {}
            for key in ("facial_identity", "identity_consistency"):
                value = batch_review.get(key)
                if isinstance(value, dict) and float(value.get("score") or 0) < settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE:
                    return False
            temporal = batch_review.get("temporal_consistency")
            if isinstance(temporal, dict) and float(temporal.get("score") or 0) < settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE:
                return False
            platform_score = batch.get("platform_score")
            if isinstance(platform_score, (int, float)) and platform_score < settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE:
                return False
            if not _video_aesthetic_gates_passed({"batches": [batch]}):
                return False
            if not _video_character_distinctiveness_gates_passed({"batches": [batch]}):
                return False
            if not _video_performance_gates_passed({"batches": [batch]}):
                return False
    return True


def _image_review_cases_passed(image_review_report: dict | None) -> bool:
    if not isinstance(image_review_report, dict):
        return False
    cases = image_review_report.get("cases", [])
    if not cases:
        return False
    for case in cases:
        if not isinstance(case, dict) or case.get("status") != "passed":
            return False
        review = case.get("review") if isinstance(case.get("review"), dict) else {}
        for key in ("facial_identity", "identity_consistency"):
            value = review.get(key)
            if isinstance(value, dict) and float(value.get("score", 0)) < settings.GENERATION_IMAGE_IDENTITY_MIN_SCORE:
                return False
        platform_score = case.get("platform_score")
        if not isinstance(platform_score, (int, float)) or platform_score < settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE:
            return False
        aesthetic_gate = case.get("platform_aesthetic_gate")
        if not isinstance(aesthetic_gate, dict) or aesthetic_gate.get("status") != "passed":
            return False
        turnaround_gate = case.get("turnaround_gate")
        if isinstance(turnaround_gate, dict) and turnaround_gate.get("status") != "passed":
            return False
    return True


def _case_ids(cases: list[dict]) -> set[str]:
    return {
        str(case.get("id"))
        for case in cases
        if isinstance(case, dict) and case.get("id") is not None
    }


def _render_workflow_parameters_passed(render_report: dict | None) -> bool:
    if not isinstance(render_report, dict):
        return False
    cases = render_report.get("cases", [])
    if not cases:
        return False
    profile = render_report.get("render_profile") if isinstance(render_report.get("render_profile"), dict) else {}
    min_steps = 40 if profile.get("quality_mode") in {"high_quality", "ultra"} else settings.GENERATION_STEPS
    for case in cases:
        workflow = case.get("actual_workflow") if isinstance(case, dict) else {}
        if not isinstance(workflow, dict):
            return False
        steps = workflow.get("steps")
        if not isinstance(steps, (int, float)) or steps < min_steps:
            return False
    return True


def _sample_case_categories(case: dict) -> set[str]:
    categories = case.get("validation_categories") if isinstance(case.get("validation_categories"), list) else []
    detected = {str(item) for item in categories if str(item).strip()}
    case_id = str(case.get("id") or "").lower()
    prompt = str(case.get("prompt") or case.get("source_prompt") or "").lower()
    scene = case.get("scene") if isinstance(case.get("scene"), dict) else {}
    description = str(scene.get("visual_description") or "").lower()
    requirements = " ".join(str(item).lower() for item in scene.get("reference_requirements", []) or [])
    visible_characters = scene.get("visible_characters", []) if isinstance(scene.get("visible_characters"), list) else []
    text = " ".join([case_id, prompt, description, requirements])

    if case_id == "establishing" or "empty office" in text or "establishing" in text:
        detected.add("establishing")
    if len(visible_characters) == 1 and any(term in text for term in ("single", "only visible", "only person", "readable face", "identity")):
        detected.add("single_character_identity")
    if case_id == "reaction" or "reaction" in text or "shocked" in text or "close-up" in text or "close up" in text:
        detected.add("reaction_closeup")
    if case_id in {"reverse_shot", "opponent", "second_role"} or any(term in text for term in ("reverse shot", "opposing role", "distinct from", "must not share")):
        detected.add("distinct_role_reverse_shot")
    if case_id == "prop" or any(term in text for term in ("prop", "red envelope", "key", "phone", "letter", "evidence")):
        detected.add("prop_story_evidence")
    if case_id == "stylized" or any(term in text for term in ("animation style", "stylized", "anime", "cartoon", "generated source")):
        detected.add("stylized_generated_source")
    return detected


def _sample_coverage(render_report: dict | None) -> dict:
    cases = render_report.get("cases", []) if isinstance(render_report, dict) else []
    covered: set[str] = set()
    by_case: dict[str, list[str]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        categories = _sample_case_categories(case)
        case_id = str(case.get("id") or "")
        if case_id:
            by_case[case_id] = sorted(categories)
        covered.update(categories)
    missing = [key for key in REQUIRED_SAMPLE_COVERAGE if key not in covered]
    return {
        "required": REQUIRED_SAMPLE_COVERAGE,
        "covered": sorted(covered),
        "missing": missing,
        "by_case": by_case,
        "passed": not missing,
    }


def _baseline_contact_sheet_present(baseline_report: dict | None, output: Path) -> bool:
    if not isinstance(baseline_report, dict):
        return False
    path_value = baseline_report.get("contact_sheet_path")
    if not path_value:
        return False
    path = Path(str(path_value))
    if not path.is_absolute():
        path = output / path
    return path.is_file()


def _manual_clip_review(manual_review: dict | None) -> dict:
    if not isinstance(manual_review, dict):
        return {}
    clip = manual_review.get("clip") or manual_review.get("video")
    return clip if isinstance(clip, dict) else {}


def _dimension_scores(item: dict) -> dict[str, float]:
    raw = item.get("dimension_scores") or item.get("scores")
    if not isinstance(raw, dict):
        return {}
    scores: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, (int, float)):
            scores[str(key)] = float(value)
        elif isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
            scores[str(key)] = float(value["score"])
    return scores


def _manual_dimension_review(
    items: list[dict],
    required: dict[str, str],
    *,
    id_key: str = "id",
) -> dict:
    missing: list[dict] = []
    low: list[dict] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get(id_key) or item.get("id") or index)
        scores = _dimension_scores(item)
        for key in required:
            if key not in scores:
                missing.append({"id": item_id, "dimension": key})
                continue
            if scores[key] < 4:
                low.append({"id": item_id, "dimension": key, "score": scores[key]})
    return {
        "required": required,
        "missing": missing,
        "low": low,
        "passed": bool(items) and not missing and not low,
    }


def _calibration_recommendations(manual_cases: list[dict], video_review_report: dict | None) -> list[dict]:
    recommendations = []
    low_dimensions = _review_low_dimensions(video_review_report)
    if "identity_consistency" in low_dimensions or "facial_identity" in low_dimensions or any(
        token in _issue_text(case) for case in manual_cases for token in ("identity", "face", "character", "same person", "身份", "脸", "不像")
    ):
        recommendations.append({
            "area": "identity",
            "priority": "high",
            "change": "Regenerate or manually select stronger character references; enable stricter reference workflow/IPAdapter weight; reject candidates with face or wardrobe drift.",
        })
    if "temporal_consistency" in low_dimensions or any(
        token in _issue_text(case) for case in manual_cases for token in ("flicker", "drift", "motion", "warp", "temporal", "闪烁", "漂移", "变形", "动作断")
    ):
        recommendations.append({
            "area": "video_motion",
            "priority": "high",
            "change": "Lower motion strength/noise, increase GENERATION_VIDEO_REFINEMENT_PASSES, and prefer the configured ComfyUI video workflow over SVD for this shot type.",
        })
    if "composition" in low_dimensions or any(
        token in _issue_text(case) for case in manual_cases for token in ("composition", "crop", "framing", "构图", "裁切", "遮挡")
    ):
        recommendations.append({
            "area": "composition",
            "priority": "medium",
            "change": "Tighten scene framing text, split crowded shots, and add pose/depth/control guidance in the ComfyUI workflow before raising candidate count.",
        })
    if "visual_integrity" in low_dimensions or any(
        token in _issue_text(case) for case in manual_cases for token in ("hand", "anatomy", "artifact", "broken", "手", "肢体", "瑕疵")
    ):
        recommendations.append({
            "area": "visual_integrity",
            "priority": "medium",
            "change": "Raise image candidates/refinement passes, strengthen negative prompts for hands/anatomy/artifacts, and keep the best image before video generation.",
        })
    if any(case.get("score", 5) < 3 for case in manual_cases):
        recommendations.append({
            "area": "shot_design",
            "priority": "high",
            "change": "Rewrite sub-3 manual-score scenes as simpler shots: one subject, one action, one camera move, and one lighting setup.",
        })
    seen = set()
    unique = []
    for item in recommendations:
        key = item["area"]
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def summarize_validation(output: Path):
    preflight_report = _read_json(output / "preflight.json")
    video_workflow_report = _read_json(output / "video_workflow_preflight.json")
    render_report = _read_json(output / "render.json")
    image_review_report = _read_json(output / "image_review.json")
    video_review_report = _read_json(output / "video_review.json")
    quality_reports = _quality_reports(output)
    final_video_reviews = _final_video_reviews(quality_reports)
    composition_reports = _composition_review_reports(output)
    composition_reviews = _composition_reviews(composition_reports)
    baseline_comparison_report = _read_json(output / "seed_dance_baseline_comparison.json")
    manual_review = _read_json(output / "manual_review.json")
    report = {
        "status": "needs_action",
        "generated_at": round(time.time()),
        "inputs": {
            "preflight": str(output / "preflight.json"),
            "video_workflow_preflight": str(output / "video_workflow_preflight.json"),
            "render": str(output / "render.json"),
            "image_review": str(output / "image_review.json"),
            "video_review": str(output / "video_review.json"),
            "quality_reports": sorted(quality_reports),
            "composition_review_reports": sorted(composition_reports),
            "seed_dance_baseline_comparison": str(output / "seed_dance_baseline_comparison.json"),
            "manual_review": str(output / "manual_review.json"),
        },
        "checks": {},
        "action_items": [],
        "calibration_recommendations": [],
    }
    checks = report["checks"]
    checks["environment_ready"] = bool(preflight_report and preflight_report.get("status") == "ready_for_live_test")
    checks["video_workflow_ready"] = bool(
        video_workflow_report
        and video_workflow_report.get("status") in {"ready_for_live_test", "skipped"}
    )
    checks["images_rendered"] = bool(render_report and render_report.get("status") == "rendered_pending_human_review")
    rendered_cases = render_report.get("cases", []) if isinstance(render_report, dict) else []
    rendered_case_ids = _case_ids(rendered_cases)
    render_profile = render_report.get("render_profile", {}) if isinstance(render_report, dict) else {}
    checks["render_profile"] = render_profile
    checks["render_profile_passed"] = bool(
        render_profile
        and render_profile.get("quality_mode") in {"high_quality", "ultra"}
        and render_profile.get("optimization_mode") in {"quality", "realism"}
        and render_profile.get("prompt_optimization") is True
        and render_profile.get("parameter_optimization") is True
    )
    checks["render_workflow_parameters_passed"] = _render_workflow_parameters_passed(render_report)
    checks["sample_coverage"] = _sample_coverage(render_report)
    checks["sample_coverage_passed"] = checks["sample_coverage"]["passed"]
    image_review_cases = image_review_report.get("cases", []) if isinstance(image_review_report, dict) else []
    image_review_case_ids = _case_ids(image_review_cases)
    missing_image_review_case_ids = sorted(rendered_case_ids - image_review_case_ids)
    checks["image_review_present"] = bool(image_review_report)
    checks["image_review_covers_rendered_cases"] = bool(rendered_case_ids) and not missing_image_review_case_ids
    checks["image_review_missing_case_ids"] = missing_image_review_case_ids
    checks["image_review_passed"] = (
        _image_review_cases_passed(image_review_report)
        and checks["image_review_covers_rendered_cases"]
    )
    video_gate_scores = _video_review_gate_scores(video_review_report)
    checks["video_gate_scores"] = video_gate_scores
    checks["video_identity_gate_passed"] = bool(
        video_gate_scores
        and video_gate_scores.get("facial_identity", 0) >= settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE
        and video_gate_scores.get("identity_consistency", 0) >= settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE
    )
    checks["video_temporal_gate_passed"] = bool(
        video_gate_scores
        and video_gate_scores.get("temporal_consistency", 0) >= settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE
    )
    video_platform_score = _video_review_platform_score(video_review_report)
    checks["video_platform_score"] = video_platform_score
    checks["video_platform_gate_passed"] = bool(
        video_platform_score is not None
        and video_platform_score >= settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE
    )
    checks["video_aesthetic_gate_passed"] = _video_aesthetic_gates_passed(video_review_report)
    checks["video_character_distinctiveness_gate_passed"] = _video_character_distinctiveness_gates_passed(video_review_report)
    checks["video_performance_gate_passed"] = _video_performance_gates_passed(video_review_report)
    checks["final_normalized_video_review_count"] = len(final_video_reviews)
    checks["final_normalized_video_review_passed"] = _final_video_reviews_passed(final_video_reviews)
    checks["composition_review_count"] = len(composition_reviews)
    checks["composition_review_passed"] = _composition_reviews_passed(composition_reviews)
    checks["video_review_passed"] = bool(
        video_review_report
        and video_review_report.get("status") == "passed"
        and checks["video_identity_gate_passed"]
        and checks["video_temporal_gate_passed"]
        and checks["video_platform_gate_passed"]
        and checks["video_aesthetic_gate_passed"]
        and checks["video_character_distinctiveness_gate_passed"]
        and checks["video_performance_gate_passed"]
        and checks["final_normalized_video_review_passed"]
        and checks["composition_review_passed"]
    )
    checks["baseline_comparison_present"] = bool(baseline_comparison_report)
    checks["baseline_contact_sheet_present"] = _baseline_contact_sheet_present(baseline_comparison_report, output)
    checks["baseline_comparison_passed"] = bool(
        baseline_comparison_report
        and baseline_comparison_report.get("status") == "passed"
        and checks["baseline_contact_sheet_present"]
    )
    manual_cases = manual_review.get("cases", []) if isinstance(manual_review, dict) else []
    manual_clip = _manual_clip_review(manual_review)
    manual_case_ids = _case_ids(manual_cases)
    missing_manual_case_ids = sorted(rendered_case_ids - manual_case_ids)
    case_dimension_review = _manual_dimension_review(manual_cases, REQUIRED_MANUAL_CASE_DIMENSIONS)
    clip_dimension_review = _manual_dimension_review([manual_clip] if manual_clip else [], REQUIRED_MANUAL_CLIP_DIMENSIONS)
    checks["manual_review_present"] = bool(manual_cases)
    checks["manual_review_covers_rendered_cases"] = bool(rendered_case_ids) and not missing_manual_case_ids
    checks["manual_review_missing_case_ids"] = missing_manual_case_ids
    checks["manual_case_dimension_review"] = case_dimension_review
    checks["manual_case_dimension_review_passed"] = case_dimension_review["passed"]
    checks["manual_clip_review_present"] = bool(manual_clip)
    checks["manual_clip_score"] = manual_clip.get("score") if manual_clip else None
    checks["manual_clip_dimension_review"] = clip_dimension_review
    checks["manual_clip_dimension_review_passed"] = clip_dimension_review["passed"]
    checks["manual_clip_review_passed"] = bool(
        manual_clip
        and manual_clip.get("decision") == "accept"
        and isinstance(manual_clip.get("score"), (int, float))
        and manual_clip.get("score") >= 4
        and manual_clip.get("watched_full_clip") is True
        and manual_clip.get("watched_seed_dance_contact_sheet") is True
        and checks["manual_clip_dimension_review_passed"]
    )
    manual_blocking_issues = _manual_blocking_issues(manual_cases, manual_clip)
    checks["manual_blocking_issues"] = manual_blocking_issues
    checks["manual_blocking_issues_passed"] = not manual_blocking_issues
    if manual_cases:
        scores = [case.get("score", 0) for case in manual_cases]
        checks["manual_average_score"] = round(sum(scores) / len(scores), 2)
        checks["manual_min_score"] = min(scores)
        failed_manual = [case for case in manual_cases if case.get("score", 0) < 4 or case.get("decision") == "reject"]
        checks["manual_review_passed"] = (
            not failed_manual
            and checks["manual_review_covers_rendered_cases"]
            and checks["manual_case_dimension_review_passed"]
            and checks["manual_clip_review_passed"]
            and checks["manual_blocking_issues_passed"]
        )
        report["manual_failures"] = failed_manual
    else:
        checks["manual_average_score"] = None
        checks["manual_min_score"] = None
        checks["manual_review_passed"] = False

    if not checks["environment_ready"]:
        report["action_items"].append("Run preflight and fix ffmpeg/ffprobe/model/ComfyUI/llama.cpp readiness before judging quality.")
    if not checks["video_workflow_ready"]:
        report["action_items"].append("Run preflight-video-workflow and fix workflow placeholders, nodes, models, or output nodes.")
    if not checks["images_rendered"]:
        report["action_items"].append("Run render-images on the fixed validation cases and inspect generated keyframes.")
    elif not checks["render_profile_passed"]:
        report["action_items"].append("Rerun render-images with --quality-mode ultra --optimization-mode quality before accepting sample quality.")
    elif not checks["render_workflow_parameters_passed"]:
        report["action_items"].append("Rerun render-images and verify every case records actual ComfyUI workflow steps for the production quality profile.")
    if checks["images_rendered"] and not checks["sample_coverage_passed"]:
        missing_labels = [
            REQUIRED_SAMPLE_COVERAGE[key]
            for key in checks["sample_coverage"]["missing"]
        ]
        report["action_items"].append(
            "Expand validation cases before accepting sample quality; missing coverage: "
            + "; ".join(missing_labels)
        )
    if not checks["image_review_present"]:
        report["action_items"].append("Run review-images so local llama.cpp VLM checks every rendered keyframe before accepting sample quality.")
    elif not checks["image_review_covers_rendered_cases"]:
        report["action_items"].append(
            "Run review-images or add image_review.json entries for every rendered validation case: "
            + ", ".join(missing_image_review_case_ids)
        )
    elif not checks["image_review_passed"]:
        report["action_items"].append("Improve rendered keyframes until image VLM review passes platform aesthetic, identity, and turnaround gates.")
    if not checks["video_review_passed"]:
        report["action_items"].append(
            "Run review-video on a generated clip and pass identity/temporal/platform/aesthetic/character-distinctiveness/performance gates; "
            "fix identity drift, same-face characters, flicker, temporal breaks, low commercial appeal, flat acting, missing video gates, or VLM setup."
        )
    if not checks["final_normalized_video_review_passed"]:
        report["action_items"].append(
            "Fix final normalized video review failures from production .quality.json reports before accepting sample quality."
        )
    if not checks["composition_review_passed"]:
        report["action_items"].append(
            "Fix final composed episode review failures from .composition_review.json before accepting sample quality."
        )
    if not checks["baseline_comparison_present"]:
        report["action_items"].append("Run compare-baseline against a Seed Dance reference clip before claiming replacement quality.")
    elif not isinstance(baseline_comparison_report, dict) or baseline_comparison_report.get("status") != "passed":
        report["action_items"].append("Improve video engine/settings until Seed Dance baseline comparison passes measurable gates.")
    elif not checks["baseline_contact_sheet_present"]:
        report["action_items"].append("Rerun compare-baseline with an output path so seed_dance_contact_sheet.png is generated for visual evidence.")
    if not checks["manual_review_present"]:
        report["action_items"].append("Create manual_review.json with 0-5 human scores for each rendered case and clip.")
    elif not checks["manual_review_covers_rendered_cases"]:
        report["action_items"].append(
            "Add manual_review.json scores for every rendered validation case: "
            + ", ".join(missing_manual_case_ids)
        )
    elif not checks["manual_case_dimension_review_passed"]:
        report["action_items"].append(
            "Add or improve manual_review.json case dimension_scores for identity_match, phone_readability, "
            "platform_aesthetic, visual_integrity, and story_match; every rendered case needs scores >= 4."
        )
    elif report.get("manual_failures"):
        report["action_items"].append("Improve prompts/workflow/model settings for manual cases below 4 before scaling up.")
    if checks["manual_review_present"] and not checks["manual_clip_review_present"]:
        report["action_items"].append("Add manual_review.json clip review after watching the full generated clip and Seed Dance contact sheet.")
    elif checks["manual_clip_review_present"] and not checks["manual_clip_dimension_review_passed"]:
        report["action_items"].append(
            "Add or improve manual_review.json clip dimension_scores for identity_stability, temporal_motion, "
            "acting_performance, commercial_aesthetic, and composition_continuity; every clip dimension needs score >= 4."
        )
    elif checks["manual_clip_review_present"] and not checks["manual_clip_review_passed"]:
        report["action_items"].append("Improve the generated clip until human clip review score is at least 4 and decision is accept.")
    if not checks["manual_blocking_issues_passed"]:
        report["action_items"].append("Resolve manual blocking issues before accepting production quality: " + json.dumps(manual_blocking_issues, ensure_ascii=False))
    report["calibration_recommendations"] = _calibration_recommendations(manual_cases, video_review_report)
    repair_queue = _collect_repair_queue(
        render_report,
        image_review_report,
        video_review_report,
        *quality_reports.values(),
        *composition_reports.values(),
        baseline_comparison_report,
        manual_review,
        {"repair_queue": _manual_repair_queue(manual_review, render_report)},
    )
    report["repair_queue"] = repair_queue
    checks["repair_queue_empty"] = not repair_queue
    if repair_queue:
        report["action_items"].append("Resolve all repair_queue actions before accepting the sample as production-quality.")

    if all(checks[key] for key in (
        "environment_ready", "video_workflow_ready", "images_rendered",
        "render_profile_passed", "render_workflow_parameters_passed",
        "sample_coverage_passed",
        "image_review_passed", "video_review_passed", "baseline_comparison_passed", "manual_review_passed",
        "repair_queue_empty",
    )):
        report["status"] = "ready_for_seed_dance_candidate"
    elif (
        checks["images_rendered"]
        or checks["video_review_passed"]
        or checks["baseline_comparison_present"]
        or checks["manual_review_present"]
    ):
        report["status"] = "partial_needs_review"
    return report


def _path_exists(path: Path) -> bool:
    return path.is_file()


def _collect_validation_evidence(output: Path) -> dict:
    quality_reports = sorted(str(path.relative_to(output)) for path in output.rglob("*.quality.json"))
    composition_reviews = sorted(str(path.relative_to(output)) for path in output.rglob("*.composition_review.json"))
    known = {
        "preflight": output / "preflight.json",
        "video_workflow_preflight": output / "video_workflow_preflight.json",
        "production_video_engine_preflight": output / "production_video_engine_preflight.json",
        "render": output / "render.json",
        "image_review": output / "image_review.json",
        "video_review": output / "video_review.json",
        "seed_dance_baseline_comparison": output / "seed_dance_baseline_comparison.json",
        "manual_review": output / "manual_review.json",
        "validation_summary": output / "validation_summary.json",
    }
    return {
        name: {"path": str(path), "present": _path_exists(path)}
        for name, path in known.items()
    } | {
        "quality_reports": {
            "count": len(quality_reports),
            "paths": quality_reports,
            "present": bool(quality_reports),
        },
        "composition_reviews": {
            "count": len(composition_reviews),
            "paths": composition_reviews,
            "present": bool(composition_reviews),
        }
    }


def _blank_scores(required: dict[str, str]) -> dict[str, None]:
    return {key: None for key in required}


def _build_manual_review_markdown(template: dict) -> str:
    lines = [
        "# Manual Review Template",
        "",
        f"- Generated at: `{template['generated_at']}`",
        f"- Save completed JSON as: `{template['target_path']}`",
        "",
        "## Case Scores",
        "",
        "| Case | Image | identity_match | phone_readability | platform_aesthetic | visual_integrity | story_match | Decision |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in template["cases"]:
        scores = case["dimension_scores"]
        lines.append(
            "| {id} | {image} | {identity_match} | {phone_readability} | {platform_aesthetic} | {visual_integrity} | {story_match} | {decision} |".format(
                id=case.get("id", ""),
                image=case.get("image") or "",
                identity_match=scores.get("identity_match", ""),
                phone_readability=scores.get("phone_readability", ""),
                platform_aesthetic=scores.get("platform_aesthetic", ""),
                visual_integrity=scores.get("visual_integrity", ""),
                story_match=scores.get("story_match", ""),
                decision=case.get("decision", ""),
            )
        )
    clip = template["clip"]
    clip_scores = clip["dimension_scores"]
    lines.extend([
        "",
        "## Clip Scores",
        "",
        f"- Candidate video: `{clip.get('candidate_video') or ''}`",
        f"- Seed Dance contact sheet: `{clip.get('seed_dance_contact_sheet') or ''}`",
        "",
        "| identity_stability | temporal_motion | acting_performance | commercial_aesthetic | composition_continuity | Decision |",
        "| --- | --- | --- | --- | --- | --- |",
        "| {identity_stability} | {temporal_motion} | {acting_performance} | {commercial_aesthetic} | {composition_continuity} | {decision} |".format(
            identity_stability=clip_scores.get("identity_stability", ""),
            temporal_motion=clip_scores.get("temporal_motion", ""),
            acting_performance=clip_scores.get("acting_performance", ""),
            commercial_aesthetic=clip_scores.get("commercial_aesthetic", ""),
            composition_continuity=clip_scores.get("composition_continuity", ""),
            decision=clip.get("decision", ""),
        ),
        "",
        "## Required Dimensions",
        "",
    ])
    for key, description in REQUIRED_MANUAL_CASE_DIMENSIONS.items():
        lines.append(f"- case `{key}`: {description}")
    for key, description in REQUIRED_MANUAL_CLIP_DIMENSIONS.items():
        lines.append(f"- clip `{key}`: {description}")
    return "\n".join(lines) + "\n"


def build_manual_review_template(output: Path) -> dict:
    render_report = _read_json(output / "render.json")
    baseline_report = _read_json(output / "seed_dance_baseline_comparison.json")
    rendered_cases = render_report.get("cases", []) if isinstance(render_report, dict) else []
    cases = []
    for index, case in enumerate(rendered_cases, start=1):
        if not isinstance(case, dict):
            continue
        scene = case.get("scene") if isinstance(case.get("scene"), dict) else {}
        cases.append({
            "id": str(case.get("id") or index),
            "image": case.get("image"),
            "scene_number": scene.get("scene_number") or index,
            "visual_description": scene.get("visual_description") or case.get("prompt") or "",
            "reference_requirements": scene.get("reference_requirements", []),
            "score": None,
            "decision": "pending",
            "dimension_scores": _blank_scores(REQUIRED_MANUAL_CASE_DIMENSIONS),
            "issue_tags": [],
            "blocking_issues": [],
            "note": "",
        })
    contact_sheet = None
    if isinstance(baseline_report, dict):
        contact_sheet = baseline_report.get("contact_sheet_path")
    template = {
        "status": "template",
        "generated_at": round(time.time()),
        "target_path": str(output / "manual_review.json"),
        "instructions": [
            "Fill every case score and dimension_scores field with 0-5 numeric scores.",
            "Use decision=accept only when every required case dimension is >= 4 and no blocking issue remains.",
            "Set clip watched_full_clip and watched_seed_dance_contact_sheet to true only after full visual review.",
            "Use issue_tags or blocking_issues to trigger targeted repair suggestions.",
        ],
        "required_case_dimensions": REQUIRED_MANUAL_CASE_DIMENSIONS,
        "required_clip_dimensions": REQUIRED_MANUAL_CLIP_DIMENSIONS,
        "cases": cases,
        "clip": {
            "score": None,
            "decision": "pending",
            "dimension_scores": _blank_scores(REQUIRED_MANUAL_CLIP_DIMENSIONS),
            "watched_full_clip": False,
            "watched_seed_dance_contact_sheet": False,
            "seed_dance_contact_sheet": contact_sheet,
            "candidate_video": None,
            "issue_tags": [],
            "blocking_issues": [],
            "note": "",
        },
    }
    write_report(output / "manual_review_template.json", template)
    (output / "manual_review_template.md").write_text(_build_manual_review_markdown(template), encoding="utf-8")
    return template


def _collect_repair_queue(*reports) -> list[dict]:
    queue = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        items = report.get("repair_queue")
        if isinstance(items, list):
            queue.extend(item for item in items if isinstance(item, dict))
        for batch in report.get("batches", []):
            if isinstance(batch, dict) and isinstance(batch.get("repair_queue"), list):
                queue.extend(item for item in batch["repair_queue"] if isinstance(item, dict))
    return queue


def _manual_review_section(summary: dict, render_report: dict | None, manual_review: dict | None) -> dict:
    checks = summary.get("checks", {})
    rendered_cases = render_report.get("cases", []) if isinstance(render_report, dict) else []
    manual_cases = manual_review.get("cases", []) if isinstance(manual_review, dict) else []
    manual_clip = _manual_clip_review(manual_review)
    manual_by_id = {str(case.get("id")): case for case in manual_cases if case.get("id") is not None}
    rendered_case_ids = [str(case.get("id")) for case in rendered_cases if case.get("id") is not None]
    return {
        "required_case_ids": rendered_case_ids,
        "reviewed_case_ids": sorted(manual_by_id.keys()),
        "missing_case_ids": checks.get("manual_review_missing_case_ids", []),
        "average_score": checks.get("manual_average_score"),
        "min_score": checks.get("manual_min_score"),
        "failures": summary.get("manual_failures", []),
        "blocking_issues": checks.get("manual_blocking_issues", []),
        "case_dimension_review": checks.get("manual_case_dimension_review", {}),
        "clip_dimension_review": checks.get("manual_clip_dimension_review", {}),
        "clip": {
            "present": bool(manual_clip),
            "score": checks.get("manual_clip_score"),
            "decision": manual_clip.get("decision"),
            "dimension_scores": _dimension_scores(manual_clip),
            "watched_full_clip": manual_clip.get("watched_full_clip"),
            "watched_seed_dance_contact_sheet": manual_clip.get("watched_seed_dance_contact_sheet"),
            "note": manual_clip.get("note"),
            "passed": checks.get("manual_clip_review_passed"),
        },
        "cases": [
            {
                "id": case_id,
                "image": next((case.get("image") for case in rendered_cases if str(case.get("id")) == case_id), None),
                "manual_score": manual_by_id.get(case_id, {}).get("score"),
                "dimension_scores": _dimension_scores(manual_by_id.get(case_id, {})),
                "decision": manual_by_id.get(case_id, {}).get("decision"),
                "note": manual_by_id.get(case_id, {}).get("note"),
            }
            for case_id in rendered_case_ids
        ],
    }


def _acceptance_action_items(summary: dict, manual_section: dict, repair_queue: list[dict]) -> list[str]:
    items = list(summary.get("action_items", []))
    if manual_section["missing_case_ids"]:
        items.append("Finish human review for missing rendered cases before scaling production.")
    if not manual_section.get("clip", {}).get("passed"):
        items.append("Finish full-clip human review against the Seed Dance contact sheet before accepting production quality.")
    setup_required = [item for item in repair_queue if item.get("execution") == "setup_required"]
    if setup_required:
        items.append("Resolve setup-required repair actions before rerunning automatic generation.")
    manual_actions = [item for item in repair_queue if item.get("execution") == "manual"]
    if manual_actions:
        items.append("Confirm manual repair decisions for subjective or ambiguous failures.")
    unique = []
    seen = set()
    for item in items:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def _markdown_bool(value) -> str:
    return "PASS" if value else "FAIL"


def _build_acceptance_markdown(package: dict) -> str:
    checks = package.get("checks", {})
    manual = package.get("manual_review", {})
    lines = [
        "# Local Generation Acceptance Package",
        "",
        f"- Status: `{package['status']}`",
        f"- Required status: `{package['required_status']}`",
        f"- Generated at: `{package['generated_at']}`",
        "",
        "## Gate Summary",
        "",
        "| Gate | Result |",
        "| --- | --- |",
    ]
    for key in (
        "environment_ready",
        "video_workflow_ready",
        "images_rendered",
        "render_profile_passed",
        "render_workflow_parameters_passed",
        "sample_coverage_passed",
        "image_review_passed",
        "image_review_covers_rendered_cases",
        "video_review_passed",
        "video_identity_gate_passed",
        "video_temporal_gate_passed",
        "video_platform_gate_passed",
        "video_aesthetic_gate_passed",
        "video_character_distinctiveness_gate_passed",
        "video_performance_gate_passed",
        "composition_review_passed",
        "baseline_contact_sheet_present",
        "baseline_comparison_passed",
        "manual_clip_review_passed",
        "manual_case_dimension_review_passed",
        "manual_clip_dimension_review_passed",
        "manual_blocking_issues_passed",
        "repair_queue_empty",
        "manual_review_passed",
    ):
        lines.append(f"| {key} | {_markdown_bool(checks.get(key))} |")
    lines.extend([
        "",
        "## Rendered Case Review",
        "",
        "| Case | Image | Manual Score | Decision | Note |",
        "| --- | --- | --- | --- | --- |",
    ])
    for case in manual.get("cases", []):
        lines.append(
            "| {id} | {image} | {score} | {decision} | {note} |".format(
                id=case.get("id", ""),
                image=case.get("image") or "",
                score=case.get("manual_score", ""),
                decision=case.get("decision") or "",
                note=(case.get("note") or "").replace("|", "/"),
            )
        )
    lines.extend([
        "",
        "## Manual Case Dimensions",
        "",
        "| Case | identity_match | phone_readability | platform_aesthetic | visual_integrity | story_match |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for case in manual.get("cases", []):
        scores = case.get("dimension_scores") if isinstance(case.get("dimension_scores"), dict) else {}
        lines.append(
            "| {id} | {identity_match} | {phone_readability} | {platform_aesthetic} | {visual_integrity} | {story_match} |".format(
                id=case.get("id", ""),
                identity_match=scores.get("identity_match", ""),
                phone_readability=scores.get("phone_readability", ""),
                platform_aesthetic=scores.get("platform_aesthetic", ""),
                visual_integrity=scores.get("visual_integrity", ""),
                story_match=scores.get("story_match", ""),
            )
        )
    clip = manual.get("clip", {})
    lines.extend([
        "",
        "## Full Clip Review",
        "",
        "| Score | Decision | Watched Clip | Watched Contact Sheet | Note |",
        "| --- | --- | --- | --- | --- |",
        "| {score} | {decision} | {clip_seen} | {sheet_seen} | {note} |".format(
            score=clip.get("score", ""),
            decision=clip.get("decision") or "",
            clip_seen=_markdown_bool(clip.get("watched_full_clip")),
            sheet_seen=_markdown_bool(clip.get("watched_seed_dance_contact_sheet")),
            note=(clip.get("note") or "").replace("|", "/"),
        ),
        "",
        "## Manual Clip Dimensions",
        "",
        "| identity_stability | temporal_motion | acting_performance | commercial_aesthetic | composition_continuity |",
        "| --- | --- | --- | --- | --- |",
        "| {identity_stability} | {temporal_motion} | {acting_performance} | {commercial_aesthetic} | {composition_continuity} |".format(
            identity_stability=(clip.get("dimension_scores") or {}).get("identity_stability", ""),
            temporal_motion=(clip.get("dimension_scores") or {}).get("temporal_motion", ""),
            acting_performance=(clip.get("dimension_scores") or {}).get("acting_performance", ""),
            commercial_aesthetic=(clip.get("dimension_scores") or {}).get("commercial_aesthetic", ""),
            composition_continuity=(clip.get("dimension_scores") or {}).get("composition_continuity", ""),
        ),
    ])
    lines.extend([
        "",
        "## Human Checklist",
        "",
    ])
    for item in package["human_review_checklist"]:
        lines.append(f"- [ ] {item}")
    repair_plan = package.get("repair_execution_plan", {})
    commands = repair_plan.get("rerun_validation_commands") or []
    if commands:
        lines.extend([
            "",
            "## Repair Rerun Plan",
            "",
        ])
        for command in commands:
            lines.append(f"- `{command}`")
    loop_plan = package.get("quality_loop_plan", {})
    if loop_plan:
        lines.extend([
            "",
            "## Next Quality Loop",
            "",
            f"- Status: `{loop_plan.get('status')}`",
            f"- Next step: {loop_plan.get('next_step')}",
        ])
        selected = loop_plan.get("selected") or []
        if selected:
            lines.append("- Selected automatic repairs:")
            for item in selected:
                lines.append(
                    "  - scene {scene}: `{action}` ({stage})".format(
                        scene=item.get("scene_number", ""),
                        action=item.get("action", ""),
                        stage=item.get("stage", ""),
                    )
                )
        setup_required = loop_plan.get("setup_required") or []
        if setup_required:
            lines.append("- Setup required before rerun:")
            for item in setup_required:
                lines.append(f"  - `{item.get('action', '')}`: {item.get('reason', '')}")
        manual_actions = loop_plan.get("manual_actions") or []
        if manual_actions:
            lines.append("- Manual decisions required:")
            for item in manual_actions:
                lines.append(f"  - `{item.get('action', '')}`: {item.get('reason', '')}")
        selected_plan = package.get("selected_repair_execution_plan", {})
        selected_commands = selected_plan.get("rerun_validation_commands") or []
        if selected_commands:
            lines.append("- Commands for selected repairs:")
            for command in selected_commands:
                lines.append(f"  - `{command}`")
    lines.extend([
        "",
        "## Blocking Action Items",
        "",
    ])
    action_items = package.get("blocking_action_items") or ["No blocking action items."]
    for item in action_items:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_acceptance_package(output: Path) -> dict:
    summary = _read_json(output / "validation_summary.json") or summarize_validation(output)
    render_report = _read_json(output / "render.json")
    image_review_report = _read_json(output / "image_review.json")
    video_review_report = _read_json(output / "video_review.json")
    quality_reports = _quality_reports(output)
    final_video_reviews = _final_video_reviews(quality_reports)
    composition_reports = _composition_review_reports(output)
    composition_reviews = _composition_reviews(composition_reports)
    baseline_report = _read_json(output / "seed_dance_baseline_comparison.json")
    manual_review = _read_json(output / "manual_review.json")
    manual_review_template = build_manual_review_template(output)
    repair_queue = _validation_repair_queue(output, summary)
    summary_for_loop = {**summary, "repair_queue": repair_queue}
    quality_loop_plan = build_quality_loop_plan(summary_for_loop, max_actions=5)
    manual_section = _manual_review_section(summary, render_report, manual_review)
    package = {
        "status": summary.get("status", "needs_action"),
        "required_status": "ready_for_seed_dance_candidate",
        "generated_at": round(time.time()),
        "summary_path": str(output / "validation_summary.json"),
        "evidence_files": _collect_validation_evidence(output),
        "checks": summary.get("checks", {}),
        "rendered_cases": render_report.get("cases", []) if isinstance(render_report, dict) else [],
        "image_review": {
            "status": image_review_report.get("status") if isinstance(image_review_report, dict) else None,
            "cases": image_review_report.get("cases", []) if isinstance(image_review_report, dict) else [],
        },
        "manual_review": manual_section,
        "manual_review_template": {
            "path": str(output / "manual_review_template.json"),
            "markdown_path": str(output / "manual_review_template.md"),
            "case_count": len(manual_review_template["cases"]),
            "required_case_dimensions": manual_review_template["required_case_dimensions"],
            "required_clip_dimensions": manual_review_template["required_clip_dimensions"],
        },
        "video_review": {
            "status": video_review_report.get("status") if isinstance(video_review_report, dict) else None,
            "gate_scores": summary.get("checks", {}).get("video_gate_scores", {}),
            "batches": video_review_report.get("batches", []) if isinstance(video_review_report, dict) else [],
            "final_normalized_reviews": final_video_reviews,
            "composition_reviews": composition_reviews,
        },
        "seed_dance_baseline": baseline_report if isinstance(baseline_report, dict) else None,
        "calibration_recommendations": summary.get("calibration_recommendations", []),
        "repair_queue": repair_queue,
        "repair_execution_plan": build_repair_execution_plan(output, repair_queue),
        "quality_loop_plan": quality_loop_plan,
        "selected_repair_execution_plan": build_repair_execution_plan(output, quality_loop_plan["selected"]),
        "human_review_checklist": [
            "Confirm every rendered case image matches the intended character, wardrobe, scene, and camera angle.",
            "Reject same-face characters, face drift, broken hands, unreadable expressions, bad crops, and random text/watermarks.",
            "Watch the generated clip at normal speed and half speed for flicker, warping, identity drift, and broken motion.",
            "Compare against the Seed Dance reference clip for composition, lighting, facial consistency, motion stability, and overall appeal.",
            "Update manual_review.json with scores for every rendered case and a clip review; do not score only the best-looking outputs.",
        ],
    }
    package["blocking_action_items"] = _acceptance_action_items(summary, manual_section, repair_queue)
    write_report(output / "validation_summary.json", summary)
    write_report(output / "acceptance_package.json", package)
    (output / "acceptance_package.md").write_text(_build_acceptance_markdown(package), encoding="utf-8")
    return package


def _validation_repair_queue(output: Path, summary: dict | None = None) -> list[dict]:
    render_report = _read_json(output / "render.json")
    image_review_report = _read_json(output / "image_review.json")
    video_review_report = _read_json(output / "video_review.json")
    quality_reports = _quality_reports(output)
    composition_reports = _composition_review_reports(output)
    baseline_report = _read_json(output / "seed_dance_baseline_comparison.json")
    manual_review = _read_json(output / "manual_review.json")
    return _collect_repair_queue(
        render_report,
        image_review_report,
        video_review_report,
        *quality_reports.values(),
        *composition_reports.values(),
        baseline_report,
        manual_review,
        {"repair_queue": _manual_repair_queue(manual_review, render_report)},
        summary,
    )


def build_quality_loop_package(output: Path, max_actions: int = 5) -> dict:
    summary = _read_json(output / "validation_summary.json") or summarize_validation(output)
    repair_queue = _validation_repair_queue(output, summary)
    plan = build_quality_loop_plan({**summary, "repair_queue": repair_queue}, max_actions=max_actions)
    package = {
        "status": plan["status"],
        "generated_at": round(time.time()),
        "summary_path": str(output / "validation_summary.json"),
        "repair_queue_total": len(repair_queue),
        "plan": plan,
        "repair_execution_plan": build_repair_execution_plan(output, repair_queue),
        "selected_repair_execution_plan": build_repair_execution_plan(output, plan["selected"]),
    }
    write_report(output / "validation_summary.json", summary)
    write_report(output / "quality_loop_plan.json", package)
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "preflight-video-workflow", "preflight-production-video", "render-images", "review-images", "review-video", "compare-baseline", "summarize", "manual-review-template", "quality-loop", "acceptance-package"], nargs="?", default="preflight")
    parser.add_argument("--base-url", help="ComfyUI address on the GPU machine")
    parser.add_argument("--cases", default="examples/local_generation_cases.json")
    parser.add_argument("--output", type=Path, default=Path("storage/validation"))
    parser.add_argument("--video")
    parser.add_argument("--candidate", help="Generated video to compare against a Seed Dance baseline")
    parser.add_argument("--baseline", help="Seed Dance reference video for measurable comparison")
    parser.add_argument("--video-workflow", help="ComfyUI image-to-video API workflow JSON")
    parser.add_argument("--reference", help="An explicitly selected character reference image")
    parser.add_argument("--description", help="Expected scene content for frame review")
    parser.add_argument("--quality-mode", default="ultra", choices=["fast", "normal", "high_quality", "ultra"], help="Image quality mode for render-images")
    parser.add_argument("--optimization-mode", default="quality", choices=["quality", "realism", "artistic", "balanced"], help="Prompt optimization mode for render-images")
    parser.add_argument("--repair-action", choices=[
        "regenerate_keyframe_with_identity_lock",
        "refine_prompt_composition",
        "refine_face_aesthetic_detail",
        "regenerate_keyframe_with_prop_constraints",
    ], help="Apply targeted image repair constraints during render-images")
    parser.add_argument("--scene-number", type=int, help="Render only one validation scene number")
    parser.add_argument("--max-actions", type=int, default=5, help="Maximum automatic repairs to select for quality-loop")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "preflight":
        report = preflight(args.base_url)
        write_report(args.output / "preflight.json", report)
    elif args.mode == "preflight-video-workflow":
        report = preflight_video_workflow(args.base_url, args.video_workflow)
        write_report(args.output / "video_workflow_preflight.json", report)
    elif args.mode == "preflight-production-video":
        report = preflight_production_video_engine(args.base_url, args.video_workflow)
        write_report(args.output / "production_video_engine_preflight.json", report)
    elif args.mode == "render-images":
        report = render_images(
            json.loads(Path(args.cases).read_text(encoding="utf-8")),
            args.output,
            args.base_url,
            args.reference,
            quality_mode=args.quality_mode,
            optimization_mode=args.optimization_mode,
            repair_action=args.repair_action,
            scene_number=args.scene_number,
        )
    elif args.mode == "review-images":
        report = review_images(args.output, args.reference)
    elif args.mode == "review-video":
        if not args.video or not args.description:
            parser.error("review-video needs --video and --description")
        report = GenerationReviewService().review_video(
            args.video, {"scene_number": 1, "description": args.description},
            args.output / "video_review.json", args.reference,
        )
    elif args.mode == "compare-baseline":
        if not args.candidate or not args.baseline:
            parser.error("compare-baseline needs --candidate and --baseline")
        report = compare_video_baseline(Path(args.candidate), Path(args.baseline), artifact_dir=args.output)
        write_report(args.output / "seed_dance_baseline_comparison.json", report)
    elif args.mode == "summarize":
        report = summarize_validation(args.output)
        write_report(args.output / "validation_summary.json", report)
    elif args.mode == "manual-review-template":
        report = build_manual_review_template(args.output)
    elif args.mode == "quality-loop":
        report = build_quality_loop_package(args.output, max_actions=args.max_actions)
    else:
        report = build_acceptance_package(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {
        "ready_for_live_test", "rendered_pending_human_review", "passed",
        "ready_for_seed_dance_candidate", "can_auto_repair", "setup_required",
        "manual_review_required", "ready", "template",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
