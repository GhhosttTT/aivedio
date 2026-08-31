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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "render-images", "review-video"], nargs="?", default="preflight")
    parser.add_argument("--base-url", help="ComfyUI address on the GPU machine")
    parser.add_argument("--cases", default="examples/local_generation_cases.json")
    parser.add_argument("--output", type=Path, default=Path("storage/validation"))
    parser.add_argument("--video")
    parser.add_argument("--reference", help="An explicitly selected character reference image")
    parser.add_argument("--description", help="Expected scene content for frame review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "preflight":
        report = preflight(args.base_url)
        write_report(args.output / "preflight.json", report)
    elif args.mode == "render-images":
        report = render_images(json.loads(Path(args.cases).read_text(encoding="utf-8")), args.output, args.base_url, args.reference)
    else:
        if not args.video or not args.description:
            parser.error("review-video needs --video and --description")
        report = GenerationReviewService().review_video(
            args.video, {"scene_number": 1, "description": args.description},
            args.output / "video_review.json", args.reference,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"ready_for_live_test", "rendered_pending_human_review", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
