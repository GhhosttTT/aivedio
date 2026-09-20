"""Preflight checks for production-grade short-drama video generation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.config import settings
from src.services.comfyui_service import ComfyUIService


VIDEO_WORKFLOW_PLACEHOLDERS = {
    "prompt", "positive_prompt", "negative_prompt", "reference_image", "image",
    "start_image", "first_frame", "end_image", "last_frame",
    "width", "height", "duration_seconds", "fps", "seed", "output_prefix",
    "motion_bucket_id", "noise_aug_strength",
}


def scan_placeholders(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(scan_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            found.update(scan_placeholders(item))
    elif isinstance(value, str):
        for name in VIDEO_WORKFLOW_PLACEHOLDERS:
            if "{" + name + "}" in value:
                found.add(name)
    return found


def likely_video_outputs(workflow: dict) -> list[dict]:
    output_keywords = ("video", "vhs", "webm", "gif", "animated")
    matches = []
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", ""))
        if any(keyword in class_type.lower() for keyword in output_keywords):
            matches.append({"node_id": node_id, "class_type": class_type})
    return matches


def preflight_video_workflow(base_url: str | None = None, workflow_path: str | None = None) -> dict:
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
        placeholders = sorted(scan_placeholders(workflow))
        outputs = likely_video_outputs(workflow)
        report["placeholders"] = placeholders
        report["recognized_placeholders"] = sorted(VIDEO_WORKFLOW_PLACEHOLDERS)
        report["likely_output_nodes"] = outputs
        checks["has_reference_placeholder"] = bool({"reference_image", "image"} & set(placeholders))
        checks["has_end_frame_placeholder"] = bool({"end_image", "last_frame"} & set(placeholders))
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
                "duration_seconds": settings.GENERATION_VIDEO_TARGET_SECONDS,
                "fps": settings.GENERATION_VIDEO_MODEL_FPS,
                "seed": 31001,
                "output_prefix": "validation_video",
                "motion_bucket_id": 127,
                "noise_aug_strength": 0.02,
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


def preflight_production_video_engine(base_url: str | None = None, workflow_path: str | None = None) -> dict:
    workflow_report = preflight_video_workflow(base_url, workflow_path)
    provider_report = preflight_video_provider()
    report = {
        "status": "production_not_ready",
        "engine": "director_pipeline",
        "workflow": workflow_report,
        "provider": provider_report,
        "requirements": [
            "A configured ComfyUI image-to-video workflow or production HTTP video provider",
            "Reference image placeholder for each scene keyframe",
            "Prompt placeholders for the director motion contract",
            "A real video output node",
            "ComfyUI preflight passing against installed nodes and models, or API endpoint/key configured",
        ],
        "action_items": [],
    }
    if workflow_report.get("status") == "ready_for_live_test" or provider_report.get("status") == "configured":
        report["status"] = "ready_for_production_video_test"
        report["action_items"].append("Run one full project with video review enabled and compare against the Seed Dance baseline.")
    elif workflow_report.get("status") == "skipped":
        report["action_items"].append("Configure COMFYUI_VIDEO_WORKFLOW_PATH with a stronger local video workflow such as Wan/AnimateDiff/FramePack.")
    elif workflow_report.get("error"):
        report["action_items"].append(workflow_report["error"])
    else:
        report["action_items"].append("Fix the blocked video workflow checks before using production generation.")
    return report


def preflight_video_provider() -> dict:
    provider = settings.GENERATION_PROVIDER
    if provider == "hybrid":
        provider = settings.GENERATION_PRIMARY_PROVIDER
    prefix_by_provider = {
        "jimeng_api": "JIMENG",
        "kling_api": "KLING",
        "hailuo_api": "HAILUO",
        "http_video_api": "HTTP_VIDEO",
    }
    prefix = prefix_by_provider.get(provider)
    report = {"provider": provider, "status": "skipped", "checks": {}}
    if not prefix:
        report["message"] = "GENERATION_PROVIDER is local; production readiness depends on ComfyUI video workflow"
        return report
    endpoint = os.getenv(f"{prefix}_ENDPOINT", "")
    api_key = os.getenv(f"{prefix}_API_KEY", "")
    report["checks"] = {
        "endpoint_configured": bool(endpoint),
        "api_key_configured": bool(api_key),
        "status_endpoint_configured": bool(os.getenv(f"{prefix}_STATUS_ENDPOINT", "")),
    }
    report["status"] = "configured" if endpoint and api_key else "blocked"
    if report["status"] == "blocked":
        report["message"] = f"Set {prefix}_ENDPOINT and {prefix}_API_KEY"
    return report
