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
from src.services.generation_review import GenerationReviewService, write_report
from src.services.shot_prompt_service import ShotPromptService


VIDEO_WORKFLOW_PLACEHOLDERS = {
    "prompt", "positive_prompt", "negative_prompt", "reference_image", "image",
    "width", "height", "duration_seconds", "fps", "seed", "output_prefix",
}


def _scan_placeholders(value):
    found = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(_scan_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_scan_placeholders(item))
    elif isinstance(value, str):
        for name in VIDEO_WORKFLOW_PLACEHOLDERS:
            if "{" + name + "}" in value:
                found.add(name)
    return found


def _likely_video_outputs(workflow):
    output_keywords = ("video", "vhs", "webm", "gif", "animated")
    matches = []
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", ""))
        lowered = class_type.lower()
        if any(keyword in lowered for keyword in output_keywords):
            matches.append({"node_id": node_id, "class_type": class_type})
    return matches


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
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.get(settings.LOCAL_REVIEW_BASE_URL.rstrip("/") + "/api/tags")
            response.raise_for_status()
            names = [m["name"] for m in response.json()["models"]]
            checks["review_model"] = settings.LOCAL_REVIEW_MODEL in names
            report["installed_review_models"] = names
    except Exception as exc:
        checks["review_model"] = False
        report["review_error"] = str(exc)
    if all(checks.get(key) for key in ("ffmpeg", "ffprobe", "text_model", "comfyui", "review_model")):
        report["status"] = "ready_for_live_test"
    return report


def preflight_video_workflow(base_url=None, workflow_path=None):
    path = workflow_path or settings.COMFYUI_VIDEO_WORKFLOW_PATH
    report = {"status": "blocked", "workflow_path": path, "checks": {}}
    checks = report["checks"]
    if not path:
        checks["configured"] = False
        report["status"] = "skipped"
        report["message"] = "COMFYUI_VIDEO_WORKFLOW_PATH is empty; video generation will use SVD"
        return report
    checks["configured"] = True
    workflow_file = Path(path)
    if not workflow_file.is_absolute():
        workflow_file = Path.cwd() / workflow_file
    checks["workflow_file"] = workflow_file.is_file()
    report["resolved_workflow_path"] = str(workflow_file)
    if not workflow_file.is_file():
        report["error"] = f"workflow file does not exist: {workflow_file}"
        return report
    try:
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            raise ValueError("workflow JSON root must be an object")
        placeholders = sorted(_scan_placeholders(workflow))
        outputs = _likely_video_outputs(workflow)
        report["placeholders"] = placeholders
        report["recognized_placeholders"] = sorted(VIDEO_WORKFLOW_PLACEHOLDERS)
        report["likely_output_nodes"] = outputs
        checks["has_reference_placeholder"] = bool({"reference_image", "image"} & set(placeholders))
        checks["has_prompt_placeholder"] = bool({"prompt", "positive_prompt"} & set(placeholders))
        checks["has_likely_video_output"] = bool(outputs)
        service = ComfyUIService(base_url=base_url, timeout=15)
        try:
            resolved = service._replace_workflow_placeholders(workflow, {
                "prompt": "validation cinematic short-drama shot",
                "positive_prompt": "validation cinematic short-drama shot",
                "negative_prompt": "flicker, warped face, bad motion",
                "reference_image": "validation_reference.png",
                "image": "validation_reference.png",
                "width": settings.GENERATION_WIDTH,
                "height": settings.GENERATION_HEIGHT,
                "duration_seconds": 2.0,
                "fps": settings.SVD_FPS,
                "seed": 31001,
                "output_prefix": "validation_video",
            })
            service.preflight(resolved)
            checks["comfyui_preflight"] = True
            stats = service.client.get(service.base_url + "/system_stats")
            stats.raise_for_status()
            report["comfyui_devices"] = stats.json().get("devices", [])
        finally:
            service.client.close()
    except Exception as exc:
        checks["comfyui_preflight"] = False
        report["error"] = str(exc)
        return report
    required = ("workflow_file", "has_reference_placeholder", "has_prompt_placeholder", "has_likely_video_output", "comfyui_preflight")
    report["status"] = "ready_for_live_test" if all(checks.get(key) for key in required) else "blocked"
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


def summarize_validation(output: Path):
    preflight_report = _read_json(output / "preflight.json")
    video_workflow_report = _read_json(output / "video_workflow_preflight.json")
    render_report = _read_json(output / "render.json")
    video_review_report = _read_json(output / "video_review.json")
    manual_review = _read_json(output / "manual_review.json")
    report = {
        "status": "needs_action",
        "generated_at": round(time.time()),
        "inputs": {
            "preflight": str(output / "preflight.json"),
            "video_workflow_preflight": str(output / "video_workflow_preflight.json"),
            "render": str(output / "render.json"),
            "video_review": str(output / "video_review.json"),
            "manual_review": str(output / "manual_review.json"),
        },
        "checks": {},
        "action_items": [],
    }
    checks = report["checks"]
    checks["environment_ready"] = bool(preflight_report and preflight_report.get("status") == "ready_for_live_test")
    checks["video_workflow_ready"] = bool(
        video_workflow_report
        and video_workflow_report.get("status") in {"ready_for_live_test", "skipped"}
    )
    checks["images_rendered"] = bool(render_report and render_report.get("status") == "rendered_pending_human_review")
    checks["video_review_passed"] = bool(video_review_report and video_review_report.get("status") == "passed")
    manual_cases = manual_review.get("cases", []) if isinstance(manual_review, dict) else []
    checks["manual_review_present"] = bool(manual_cases)
    if manual_cases:
        scores = [case.get("score", 0) for case in manual_cases]
        checks["manual_average_score"] = round(sum(scores) / len(scores), 2)
        checks["manual_min_score"] = min(scores)
        failed_manual = [case for case in manual_cases if case.get("score", 0) < 4 or case.get("decision") == "reject"]
        checks["manual_review_passed"] = not failed_manual
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
        report["action_items"].append("Run review-video on a generated clip; fix identity drift, flicker, temporal breaks, or VLM setup.")
    if not checks["manual_review_present"]:
        report["action_items"].append("Create manual_review.json with 0-5 human scores for each rendered case and clip.")
    elif not checks["manual_review_passed"]:
        report["action_items"].append("Improve prompts/workflow/model settings for manual cases below 4 before scaling up.")

    if all(checks[key] for key in (
        "environment_ready", "video_workflow_ready", "images_rendered",
        "video_review_passed", "manual_review_passed",
    )):
        report["status"] = "ready_for_calibrated_generation"
    elif checks["images_rendered"] or checks["video_review_passed"] or checks["manual_review_present"]:
        report["status"] = "partial_needs_review"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "preflight-video-workflow", "render-images", "review-video", "summarize"], nargs="?", default="preflight")
    parser.add_argument("--base-url", help="ComfyUI address on the GPU machine")
    parser.add_argument("--cases", default="examples/local_generation_cases.json")
    parser.add_argument("--output", type=Path, default=Path("storage/validation"))
    parser.add_argument("--video")
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
    elif args.mode == "render-images":
        report = render_images(json.loads(Path(args.cases).read_text(encoding="utf-8")), args.output, args.base_url, args.reference)
    elif args.mode == "review-video":
        if not args.video or not args.description:
            parser.error("review-video needs --video and --description")
        report = GenerationReviewService().review_video(
            args.video, {"scene_number": 1, "description": args.description},
            args.output / "video_review.json", args.reference,
        )
    else:
        report = summarize_validation(args.output)
        write_report(args.output / "validation_summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {
        "ready_for_live_test", "rendered_pending_human_review", "passed",
        "ready_for_calibrated_generation",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
