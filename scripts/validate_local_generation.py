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
from src.services.repair_queue import attach_repair_queue
from scripts.compare_video_baseline import compare as compare_video_baseline


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
):
    report = {
        "status": "error",
        "quality_accepted": False,
        "render_profile": {
            "quality_mode": quality_mode,
            "optimization_mode": optimization_mode,
            "width": settings.GENERATION_WIDTH,
            "height": settings.GENERATION_HEIGHT,
            "base_steps": settings.GENERATION_STEPS,
            "base_cfg": settings.GENERATION_CFG,
            "uses_reference": bool(reference),
            "prompt_optimization": True,
            "parameter_optimization": quality_mode in {"high_quality", "ultra"},
        },
        "cases": [],
    }
    service = ComfyUIService(base_url=base_url, timeout=900)
    try:
        for case in cases:
            if not str(case["id"]).replace("_", "").isalnum():
                raise ValueError("Case ID must be alphanumeric")
            compiled = ShotPromptService().compile(case["prompt"])
            path = output / (case["id"] + ".png")
            case_reference = case.get("reference_image") or case.get("reference") or reference
            started = time.monotonic()
            image = service.generate_image(
                prompt=compiled.prompt, negative_prompt=compiled.negative_prompt,
                output_path=str(path), seed=case["seed"], reference_image=case_reference,
                use_ipadapter=bool(case_reference), width=settings.GENERATION_WIDTH,
                height=settings.GENERATION_HEIGHT, steps=settings.GENERATION_STEPS,
                cfg_scale=settings.GENERATION_CFG,
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
                "prompt": compiled.prompt,
                "scene": case.get("scene", {}),
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "actual_workflow": _extract_workflow_image_metadata(image),
                "request": {
                    "width": settings.GENERATION_WIDTH,
                    "height": settings.GENERATION_HEIGHT,
                    "steps": settings.GENERATION_STEPS,
                    "cfg_scale": settings.GENERATION_CFG,
                    "quality_mode": quality_mode,
                    "optimization_mode": optimization_mode,
                    "reference_image": case_reference,
                    "use_ipadapter": bool(case_reference),
                    "enable_prompt_optimization": True,
                    "enable_parameter_optimization": quality_mode in {"high_quality", "ultra"},
                },
            })
            write_report(output / "render.json", report)
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
    checks["video_review_passed"] = bool(
        video_review_report
        and video_review_report.get("status") == "passed"
        and checks["video_identity_gate_passed"]
        and checks["video_temporal_gate_passed"]
        and checks["video_platform_gate_passed"]
    )
    checks["baseline_comparison_present"] = bool(baseline_comparison_report)
    checks["baseline_comparison_passed"] = bool(
        baseline_comparison_report and baseline_comparison_report.get("status") == "passed"
    )
    manual_cases = manual_review.get("cases", []) if isinstance(manual_review, dict) else []
    manual_case_ids = _case_ids(manual_cases)
    missing_manual_case_ids = sorted(rendered_case_ids - manual_case_ids)
    checks["manual_review_present"] = bool(manual_cases)
    checks["manual_review_covers_rendered_cases"] = bool(rendered_case_ids) and not missing_manual_case_ids
    checks["manual_review_missing_case_ids"] = missing_manual_case_ids
    if manual_cases:
        scores = [case.get("score", 0) for case in manual_cases]
        checks["manual_average_score"] = round(sum(scores) / len(scores), 2)
        checks["manual_min_score"] = min(scores)
        failed_manual = [case for case in manual_cases if case.get("score", 0) < 4 or case.get("decision") == "reject"]
        checks["manual_review_passed"] = not failed_manual and checks["manual_review_covers_rendered_cases"]
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
            "Run review-video on a generated clip and pass identity/temporal/platform gates; "
            "fix identity drift, same-face characters, flicker, temporal breaks, low commercial appeal, or VLM setup."
        )
    if not checks["baseline_comparison_present"]:
        report["action_items"].append("Run compare-baseline against a Seed Dance reference clip before claiming replacement quality.")
    elif not checks["baseline_comparison_passed"]:
        report["action_items"].append("Improve video engine/settings until Seed Dance baseline comparison passes measurable gates.")
    if not checks["manual_review_present"]:
        report["action_items"].append("Create manual_review.json with 0-5 human scores for each rendered case and clip.")
    elif not checks["manual_review_covers_rendered_cases"]:
        report["action_items"].append(
            "Add manual_review.json scores for every rendered validation case: "
            + ", ".join(missing_manual_case_ids)
        )
    elif not checks["manual_review_passed"]:
        report["action_items"].append("Improve prompts/workflow/model settings for manual cases below 4 before scaling up.")
    report["calibration_recommendations"] = _calibration_recommendations(manual_cases, video_review_report)

    if all(checks[key] for key in (
        "environment_ready", "video_workflow_ready", "images_rendered",
        "render_profile_passed", "render_workflow_parameters_passed",
        "image_review_passed", "video_review_passed", "baseline_comparison_passed", "manual_review_passed",
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
    }


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
    manual_by_id = {str(case.get("id")): case for case in manual_cases if case.get("id") is not None}
    rendered_case_ids = [str(case.get("id")) for case in rendered_cases if case.get("id") is not None]
    return {
        "required_case_ids": rendered_case_ids,
        "reviewed_case_ids": sorted(manual_by_id.keys()),
        "missing_case_ids": checks.get("manual_review_missing_case_ids", []),
        "average_score": checks.get("manual_average_score"),
        "min_score": checks.get("manual_min_score"),
        "failures": summary.get("manual_failures", []),
        "cases": [
            {
                "id": case_id,
                "image": next((case.get("image") for case in rendered_cases if str(case.get("id")) == case_id), None),
                "manual_score": manual_by_id.get(case_id, {}).get("score"),
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
        "image_review_passed",
        "image_review_covers_rendered_cases",
        "video_review_passed",
        "video_identity_gate_passed",
        "video_temporal_gate_passed",
        "video_platform_gate_passed",
        "baseline_comparison_passed",
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
        "## Human Checklist",
        "",
    ])
    for item in package["human_review_checklist"]:
        lines.append(f"- [ ] {item}")
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
    baseline_report = _read_json(output / "seed_dance_baseline_comparison.json")
    manual_review = _read_json(output / "manual_review.json")
    repair_queue = _collect_repair_queue(render_report, image_review_report, video_review_report, baseline_report, manual_review, summary)
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
        "video_review": {
            "status": video_review_report.get("status") if isinstance(video_review_report, dict) else None,
            "gate_scores": summary.get("checks", {}).get("video_gate_scores", {}),
            "batches": video_review_report.get("batches", []) if isinstance(video_review_report, dict) else [],
        },
        "seed_dance_baseline": baseline_report if isinstance(baseline_report, dict) else None,
        "calibration_recommendations": summary.get("calibration_recommendations", []),
        "repair_queue": repair_queue,
        "human_review_checklist": [
            "Confirm every rendered case image matches the intended character, wardrobe, scene, and camera angle.",
            "Reject same-face characters, face drift, broken hands, unreadable expressions, bad crops, and random text/watermarks.",
            "Watch the generated clip at normal speed and half speed for flicker, warping, identity drift, and broken motion.",
            "Compare against the Seed Dance reference clip for composition, lighting, facial consistency, motion stability, and overall appeal.",
            "Update manual_review.json with scores for every rendered case; do not score only the best-looking outputs.",
        ],
    }
    package["blocking_action_items"] = _acceptance_action_items(summary, manual_section, repair_queue)
    write_report(output / "validation_summary.json", summary)
    write_report(output / "acceptance_package.json", package)
    (output / "acceptance_package.md").write_text(_build_acceptance_markdown(package), encoding="utf-8")
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "preflight-video-workflow", "preflight-production-video", "render-images", "review-images", "review-video", "compare-baseline", "summarize", "acceptance-package"], nargs="?", default="preflight")
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
        report = compare_video_baseline(Path(args.candidate), Path(args.baseline))
        write_report(args.output / "seed_dance_baseline_comparison.json", report)
    elif args.mode == "summarize":
        report = summarize_validation(args.output)
        write_report(args.output / "validation_summary.json", report)
    else:
        report = build_acceptance_package(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {
        "ready_for_live_test", "rendered_pending_human_review", "passed",
        "ready_for_seed_dance_candidate",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
