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
from src.services.comfyui_service import ComfyUIService
from src.services.video_engine_preflight import (
    VIDEO_WORKFLOW_PLACEHOLDERS,
    likely_video_outputs as _likely_video_outputs,
    preflight_production_video_engine,
    preflight_video_workflow,
    scan_placeholders as _scan_placeholders,
)
from src.services.generation_review import GenerationReviewService, write_report
from src.services.shot_prompt_service import ShotPromptService
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


def render_images(cases, output: Path, base_url=None, reference=None):
    report = {"status": "error", "quality_accepted": False, "cases": []}
    service = ComfyUIService(base_url=base_url, timeout=900)
    try:
        for case in cases:
            if not str(case["id"]).replace("_", "").isalnum():
                raise ValueError("Case ID must be alphanumeric")
            compiled = ShotPromptService().compile(case["prompt"])
            path = output / (case["id"] + ".png")
            started = time.monotonic()
            image = service.generate_image(
                prompt=compiled.prompt, negative_prompt=compiled.negative_prompt,
                output_path=str(path), seed=case["seed"], reference_image=reference,
                use_ipadapter=bool(reference), width=settings.GENERATION_WIDTH,
                height=settings.GENERATION_HEIGHT, steps=settings.GENERATION_STEPS,
                cfg_scale=settings.GENERATION_CFG,
            )
            report["cases"].append({"id": case["id"], "image": image, "seed": case["seed"],
                                    "prompt": compiled.prompt, "elapsed_seconds": round(time.monotonic() - started, 2)})
            write_report(output / "render.json", report)
        report["status"] = "rendered_pending_human_review"
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        service.client.close()
    write_report(output / "render.json", report)
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
    checks["video_review_passed"] = bool(
        video_review_report
        and video_review_report.get("status") == "passed"
        and checks["video_identity_gate_passed"]
        and checks["video_temporal_gate_passed"]
    )
    checks["baseline_comparison_present"] = bool(baseline_comparison_report)
    checks["baseline_comparison_passed"] = bool(
        baseline_comparison_report and baseline_comparison_report.get("status") == "passed"
    )
    manual_cases = manual_review.get("cases", []) if isinstance(manual_review, dict) else []
    rendered_cases = render_report.get("cases", []) if isinstance(render_report, dict) else []
    rendered_case_ids = {
        str(case.get("id"))
        for case in rendered_cases
        if case.get("id") is not None
    }
    manual_case_ids = {
        str(case.get("id"))
        for case in manual_cases
        if case.get("id") is not None
    }
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
    if not checks["video_review_passed"]:
        report["action_items"].append(
            "Run review-video on a generated clip and pass identity/temporal gates; "
            "fix identity drift, same-face characters, flicker, temporal breaks, or VLM setup."
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
        "video_review_passed", "baseline_comparison_passed", "manual_review_passed",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "preflight-video-workflow", "preflight-production-video", "render-images", "review-video", "compare-baseline", "summarize"], nargs="?", default="preflight")
    parser.add_argument("--base-url", help="ComfyUI address on the GPU machine")
    parser.add_argument("--cases", default="examples/local_generation_cases.json")
    parser.add_argument("--output", type=Path, default=Path("storage/validation"))
    parser.add_argument("--video")
    parser.add_argument("--candidate", help="Generated video to compare against a Seed Dance baseline")
    parser.add_argument("--baseline", help="Seed Dance reference video for measurable comparison")
    parser.add_argument("--video-workflow", help="ComfyUI image-to-video API workflow JSON")
    parser.add_argument("--reference", help="An explicitly selected character reference image")
    parser.add_argument("--description", help="Expected scene content for frame review")
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
        report = render_images(json.loads(Path(args.cases).read_text(encoding="utf-8")), args.output, args.base_url, args.reference)
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
    else:
        report = summarize_validation(args.output)
        write_report(args.output / "validation_summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {
        "ready_for_live_test", "rendered_pending_human_review", "passed",
        "ready_for_seed_dance_candidate",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
