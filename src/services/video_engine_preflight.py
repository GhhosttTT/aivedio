"""Preflight checks for production-grade short-drama video generation."""

from __future__ import annotations

import json
import ipaddress
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from src.config import settings
from src.services.comfyui_service import ComfyUIService
from src.services.generation_provider import (
    _seedance_model,
    _seedance_model_is_10,
    _seedance_model_is_25,
    _seedance_model_supports_first_last_frame,
    _seedance_model_supports_multimodal_references,
    _seedance_model_supports_reference_audio,
    _seedance_duration_bounds,
    _seedance_supported_resolutions,
)


VIDEO_WORKFLOW_PLACEHOLDERS = {
    "prompt", "positive_prompt", "negative_prompt", "reference_image", "image",
    "start_image", "first_frame", "end_image", "last_frame",
    "width", "height", "duration_seconds", "fps", "seed", "output_prefix",
    "motion_bucket_id", "noise_aug_strength",
    "quality_mode", "quality_profile", "repair_action", "quality_pipeline",
    "quality_pipeline_json", "quality_pipeline_stages", "quality_pipeline_prompt",
    "quality_pipeline_negative",
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
    output_keywords = ("vhs", "webm", "gif", "animated")
    output_markers = ("save", "combine", "output", "export", "preview")
    matches = []
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", ""))
        lower_class = class_type.lower()
        if any(keyword in lower_class for keyword in output_keywords) or (
            "video" in lower_class and any(marker in lower_class for marker in output_markers)
        ):
            matches.append({"node_id": node_id, "class_type": class_type})
    return matches


def preflight_video_workflow(base_url: str | None = None, workflow_path: str | None = None) -> dict:
    path = workflow_path or settings.COMFYUI_VIDEO_WORKFLOW_PATH
    report = {"status": "blocked", "workflow_path": path, "checks": {}, "action_items": []}
    checks = report["checks"]
    if not path:
        checks["configured"] = False
        report["status"] = "skipped"
        report["message"] = "COMFYUI_VIDEO_WORKFLOW_PATH is empty; video generation will use SVD"
        report["action_items"].append("Set COMFYUI_VIDEO_WORKFLOW_PATH to a production ComfyUI video API workflow.")
        return report
    checks["configured"] = True
    workflow_file = Path(path)
    if not workflow_file.is_absolute():
        workflow_file = Path.cwd() / workflow_file
    checks["workflow_file"] = workflow_file.is_file()
    report["resolved_workflow_path"] = str(workflow_file)
    if not workflow_file.is_file():
        report["error"] = f"workflow file does not exist: {workflow_file}"
        report["action_items"].append(report["error"])
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
        checks["has_quality_profile_placeholder"] = bool({"quality_mode", "quality_profile"} & set(placeholders))
        checks["has_repair_action_placeholder"] = "repair_action" in set(placeholders)
        checks["has_quality_pipeline_placeholder"] = bool({
            "quality_pipeline", "quality_pipeline_json", "quality_pipeline_stages",
            "quality_pipeline_prompt", "quality_pipeline_negative",
        } & set(placeholders))
        checks["has_likely_video_output"] = bool(outputs)
        contract_required = (
            "workflow_file", "has_reference_placeholder", "has_prompt_placeholder",
            "has_quality_profile_placeholder", "has_repair_action_placeholder",
            "has_quality_pipeline_placeholder", "has_likely_video_output",
        )
        if not all(checks.get(key) for key in contract_required):
            checks["comfyui_preflight"] = False
            report["status"] = "blocked"
            report["action_items"].extend(_video_workflow_action_items(checks))
            return report
        service = ComfyUIService(base_url=base_url, timeout=15)
        try:
            quality_pipeline = {
                "stages": ["platform_reference_gap_repair", "commercial_lighting_pass"],
                "prompt_directive": "premium short-drama video quality validation",
                "negative_directive": "cheap filter, low-budget lighting, unstable face",
            }
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
                "quality_mode": "seed_dance_reference",
                "quality_profile": "seed_dance_reference",
                "repair_action": "refine_video_commercial_aesthetic",
                "quality_pipeline": quality_pipeline,
                "quality_pipeline_json": json.dumps(quality_pipeline, ensure_ascii=False),
                "quality_pipeline_stages": ", ".join(quality_pipeline["stages"]),
                "quality_pipeline_prompt": quality_pipeline["prompt_directive"],
                "quality_pipeline_negative": quality_pipeline["negative_directive"],
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
        report["action_items"].append(str(exc))
        return report
    required = ("workflow_file", "comfyui_preflight")
    report["status"] = "ready_for_live_test" if all(checks.get(key) for key in required) else "blocked"
    if report["status"] == "blocked":
        report["action_items"].extend(_video_workflow_action_items(checks))
    return report


def _video_workflow_action_items(checks: dict) -> list[str]:
    items = []
    if not checks.get("has_reference_placeholder"):
        items.append("Add {reference_image} or {image} to the workflow input image node.")
    if not checks.get("has_prompt_placeholder"):
        items.append("Add {prompt} or {positive_prompt} to the positive prompt node.")
    if not checks.get("has_quality_profile_placeholder"):
        items.append("Add {quality_mode} or {quality_profile} so the workflow can switch production quality profiles.")
    if not checks.get("has_repair_action_placeholder"):
        items.append("Add {repair_action} so repair passes can select stronger generation branches.")
    if not checks.get("has_quality_pipeline_placeholder"):
        items.append(
            "Add {quality_pipeline_json}, {quality_pipeline_stages}, {quality_pipeline_prompt}, "
            "or {quality_pipeline_negative} so commercial quality stages reach the workflow."
        )
    if not checks.get("has_likely_video_output"):
        items.append("Add a video output node such as VHS_VideoCombine, WebM/GIF export, or another video save node.")
    if not checks.get("comfyui_preflight"):
        items.append("Fix ComfyUI node/model preflight errors before running production video generation.")
    return items


def preflight_production_video_engine(
    base_url: str | None = None,
    workflow_path: str | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    request_mode_override: str | None = None,
    resolution_override: str | None = None,
    output_format_override: str | None = None,
    duration_override: float | None = None,
) -> dict:
    workflow_report = preflight_video_workflow(base_url, workflow_path)
    if any(
        value is not None and value != ""
        for value in (
            provider_override,
            model_override,
            request_mode_override,
            resolution_override,
            output_format_override,
        )
    ) or duration_override is not None:
        provider_kwargs = {"provider_override": provider_override}
        if model_override:
            provider_kwargs["model_override"] = model_override
        if request_mode_override:
            provider_kwargs["request_mode_override"] = request_mode_override
        if resolution_override:
            provider_kwargs["resolution_override"] = resolution_override
        if output_format_override:
            provider_kwargs["output_format_override"] = output_format_override
        if duration_override is not None:
            provider_kwargs["duration_override"] = duration_override
        provider_report = preflight_video_provider(**provider_kwargs)
    else:
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
            "Quality profile, repair action, and quality-pipeline placeholders for commercial repair passes",
            "A real video output node",
            "ComfyUI preflight passing against installed nodes and models, or API endpoint/key configured",
        ],
        "action_items": [],
    }
    provider_warnings = provider_report.get("warnings") or []
    if provider_warnings:
        report["warnings"] = list(provider_warnings)
    provider_blocked = provider_report.get("status") == "blocked"
    workflow_ready = workflow_report.get("status") == "ready_for_live_test"
    provider_ready = provider_report.get("status") == "configured"
    if workflow_ready or provider_ready:
        report["status"] = "ready_for_production_video_test"
        report["action_items"].append("Run one full project with video review enabled and compare against the Seed Dance baseline.")
        report["action_items"].extend(provider_warnings)
    elif provider_blocked and workflow_report.get("status") == "skipped":
        report["action_items"].extend(
            provider_report.get("action_items")
            or [provider_report.get("message") or "Fix the configured video provider before production."]
        )
    elif workflow_report.get("status") == "skipped":
        report["action_items"].append("Configure COMFYUI_VIDEO_WORKFLOW_PATH with a stronger local video workflow such as Wan/AnimateDiff/FramePack.")
    elif workflow_report.get("error"):
        report["action_items"].append(workflow_report["error"])
    else:
        report["action_items"].extend(
            workflow_report.get("action_items") or ["Fix the blocked video workflow checks before using production generation."]
        )
    return report


def preflight_video_provider(
    provider_override: str | None = None,
    model_override: str | None = None,
    request_mode_override: str | None = None,
    resolution_override: str | None = None,
    output_format_override: str | None = None,
    duration_override: float | None = None,
) -> dict:
    def runtime_value(name: str, default=""):
        value = os.getenv(name)
        if value is not None:
            return value
        return getattr(settings, name, default)

    def runtime_bool(name: str, default: bool = False) -> bool:
        return str(runtime_value(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}

    provider = str(provider_override or os.getenv("GENERATION_PROVIDER") or settings.GENERATION_PROVIDER).strip().lower()
    if provider == "hybrid":
        provider = os.getenv("GENERATION_PRIMARY_PROVIDER") or settings.GENERATION_PRIMARY_PROVIDER
    prefix_by_provider = {
        "jimeng_api": "JIMENG",
        "kling_api": "KLING",
        "hailuo_api": "HAILUO",
        "http_video_api": "HTTP_VIDEO",
        "seedance_api": "SEEDANCE",
    }
    prefix = prefix_by_provider.get(provider)
    report = {"provider": provider, "status": "skipped", "checks": {}}
    if not prefix:
        report["message"] = "GENERATION_PROVIDER is local; production readiness depends on ComfyUI video workflow"
        return report
    endpoint = os.getenv(f"{prefix}_ENDPOINT") or str(getattr(settings, f"{prefix}_ENDPOINT", "") or "")
    api_key = os.getenv(f"{prefix}_API_KEY") or str(getattr(settings, f"{prefix}_API_KEY", "") or "")
    status_endpoint = os.getenv(f"{prefix}_STATUS_ENDPOINT") or str(getattr(settings, f"{prefix}_STATUS_ENDPOINT", "") or "")
    result_endpoint = os.getenv(f"{prefix}_RESULT_ENDPOINT") or str(getattr(settings, f"{prefix}_RESULT_ENDPOINT", "") or "")
    endpoint_host = (urlparse(endpoint).hostname or "").lower() if endpoint else ""
    endpoint_path = urlparse(endpoint).path if endpoint else ""
    looks_like_ark_endpoint = (
        endpoint_host in {"ark.cn-beijing.volcengine.com", "ark.cn-beijing.volces.com"}
        or endpoint_host.endswith(".volcengine.com")
        or endpoint_host.endswith(".volces.com")
    )
    if provider == "seedance_api":
        configured_api_format = str(runtime_value("SEEDANCE_API_FORMAT", "legacy")).strip().lower() or "legacy"
        api_format = configured_api_format
        if (
            ("SEEDANCE_API_FORMAT" not in os.environ or not str(os.environ.get("SEEDANCE_API_FORMAT", "")).strip())
            and configured_api_format.strip().lower() == "legacy"
            and looks_like_ark_endpoint
        ):
            api_format = "ark_v3"
        model = str(model_override or runtime_value("SEEDANCE_MODEL", "") or "").strip()
        if not model:
            model = _seedance_model()
        resolution = str(resolution_override or runtime_value("SEEDANCE_RESOLUTION", "1080p"))
        output_format = str(output_format_override or runtime_value("SEEDANCE_OUTPUT_FORMAT", "mp4"))
        request_mode = str(request_mode_override or runtime_value("SEEDANCE_REQUEST_MODE", "reference_to_video"))
        report["configuration"] = {
            "api_format": api_format,
            "model": model,
            "request_mode": request_mode,
            "resolution": resolution,
            "output_format": output_format,
            "duration_seconds": duration_override,
        }
        report["capabilities"] = {
            "multimodal_references": True,
            "native_audio": runtime_bool("SEEDANCE_NATIVE_AUDIO", True),
            "multi_shot": runtime_bool("SEEDANCE_MULTI_SHOT", True),
            "continuity_last_frame": runtime_bool("SEEDANCE_RETURN_LAST_FRAME", True),
            "first_last_frame": True,
            "edit_and_extend": True,
        }
    ark_native = (
        provider == "seedance_api"
        and report.get("configuration", {}).get("api_format", "").strip().lower()
        in {"ark", "ark_v3", "volcengine", "volcengine_v3"}
    )
    if ark_native and endpoint and not status_endpoint:
        status_endpoint = endpoint.rstrip("/") + "/{job_id}"
    report["checks"] = {
        "endpoint_configured": bool(endpoint),
        "api_key_configured": bool(api_key),
        "status_endpoint_configured": bool(status_endpoint),
        "result_endpoint_configured": bool(result_endpoint),
        "result_endpoint_required": not ark_native,
        "native_ark_format": ark_native,
        "ark_endpoint_detected": looks_like_ark_endpoint,
    }
    checks = report["checks"]
    configuration_ok = True
    if provider == "seedance_api":
        callback_url = str(runtime_value("SEEDANCE_CALLBACK_URL", "") or "").strip()
        callback_secret = str(runtime_value("SEEDANCE_CALLBACK_SECRET", "") or "").strip()
        checks["callback_url_configured"] = bool(callback_url)
        checks["callback_secret_configured"] = bool(callback_secret)
        if callback_url and not callback_secret:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "SEEDANCE_CALLBACK_URL requires SEEDANCE_CALLBACK_SECRET; configure both or disable callbacks."
            )
        api_format = report["configuration"]["api_format"].strip().lower()
        resolution = report["configuration"]["resolution"].strip().lower()
        output_format = report["configuration"]["output_format"].strip().lower()
        valid_formats = {"legacy", "generic", "compatible", "ark", "ark_v3", "volcengine", "volcengine_v3"}
        model_name = report["configuration"]["model"].strip().lower()
        model_is_10 = _seedance_model_is_10(model_name)
        model_is_25 = _seedance_model_is_25(model_name)
        valid_resolutions = (
            _seedance_supported_resolutions(model_name)
            if ark_native
            else {"480p", "720p", "1080p", "4k"}
        )
        checks["api_format_valid"] = api_format in valid_formats
        checks["resolution_valid"] = resolution in valid_resolutions
        checks["output_format_valid"] = output_format in {"mp4", "mov"}
        if ark_native and output_format == "mov" and not model_is_25:
            checks["output_format_valid"] = False
        checks["request_mode_valid"] = request_mode.strip().lower() in {
            "reference", "reference_to_video", "auto", "multi_shot", "seedance_2_5", "2.5", "edit", "extend",
        }
        configuration_ok = configuration_ok and all(
            checks[key] for key in (
                "api_format_valid", "resolution_valid", "output_format_valid", "request_mode_valid",
            )
        )
        if not checks["request_mode_valid"]:
            report.setdefault("action_items", []).append(
                "SEEDANCE_REQUEST_MODE must be reference, reference_to_video, auto, multi_shot, seedance_2_5, 2.5, edit, or extend."
            )
        if duration_override is not None:
            try:
                requested_duration = float(duration_override)
            except (TypeError, ValueError):
                requested_duration = 0
            minimum_duration, maximum_duration = _seedance_duration_bounds(model_name, request_mode)
            duration_valid = minimum_duration <= requested_duration <= maximum_duration
            if model_is_25 and request_mode.strip().lower() in {"edit", "extend"}:
                duration_valid = False
            checks["duration_valid"] = duration_valid
            if not duration_valid:
                configuration_ok = False
                if model_is_25 and request_mode.strip().lower() in {"edit", "extend"}:
                    report.setdefault("action_items", []).append(
                        "Native Seedance 2.5 edit/extend tasks require automatic duration (-1); clear the per-run duration."
                    )
                else:
                    report.setdefault("action_items", []).append(
                        f"Native Seedance model {model_name} duration must be between {minimum_duration} and {maximum_duration} seconds; configured {requested_duration:g}."
                    )
        if ark_native and request_mode.strip().lower() in {"multi_shot", "seedance_2_5", "2.5"}:
            try:
                configured_sequence_duration = float(runtime_value("SEEDANCE_MULTI_SHOT_DURATION_SECONDS", "30"))
            except (TypeError, ValueError):
                configured_sequence_duration = 0
            minimum_duration, maximum_duration = _seedance_duration_bounds(model_name, request_mode)
            checks["multi_shot_duration_valid"] = minimum_duration <= configured_sequence_duration <= maximum_duration
            if not checks["multi_shot_duration_valid"]:
                configuration_ok = False
                report.setdefault("action_items", []).append(
                    f"Native Seedance model {model_name} multi-shot duration must be between "
                    f"{minimum_duration} and {maximum_duration} seconds; configured {configured_sequence_duration:g}."
                )
        if (
            ark_native
            and model_is_10
            and request_mode.strip().lower() in {"edit", "extend"}
        ):
            configuration_ok = False
            report.setdefault("action_items", []).append(
                f"Native Seedance model {model_name} does not support {request_mode.strip().lower()} tasks; use Seedance 2.0 or 2.5."
            )
        if ark_native and request_mode.strip().lower() == "auto" and not model_is_25:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                f"Native Seedance model {model_name} does not support omni_reference_task_type=auto; use Seedance 2.5."
            )
        if not checks["resolution_valid"]:
            report.setdefault("action_items", []).append(
                f"{report['configuration']['model']} does not support {resolution}; use one of "
                f"{', '.join(sorted(valid_resolutions))}."
            )
        if ark_native and output_format == "mov" and not model_is_25:
            report.setdefault("action_items", []).append(
                "Native Ark MOV output requires Seedance 2.5; use MP4 for Seedance 2.0/1.0."
            )
        if looks_like_ark_endpoint and not ark_native:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "The configured endpoint is a Volcano Ark endpoint but the effective format is legacy; configure a compatible gateway or set SEEDANCE_API_FORMAT=ark_v3 explicitly."
            )
        elif ark_native and endpoint and not looks_like_ark_endpoint:
            report.setdefault("warnings", []).append(
                "SEEDANCE_API_FORMAT=ark_v3 is enabled but the endpoint host is not Volcano Ark; verify the gateway contract."
            )
        if looks_like_ark_endpoint and ark_native and endpoint_path and "/api/v3/contents/generations/tasks" not in endpoint_path:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "Native Ark endpoint should use /api/v3/contents/generations/tasks."
            )
        checks["model_configured"] = bool(report["configuration"]["model"].strip())
        checks["model_is_25"] = model_is_25
        if ark_native:
            report["capabilities"]["multimodal_references"] = _seedance_model_supports_multimodal_references(model_name)
            report["capabilities"]["first_last_frame"] = _seedance_model_supports_first_last_frame(model_name)
            report["capabilities"]["edit_and_extend"] = not model_is_10
            minimum_duration, maximum_duration = _seedance_duration_bounds(model_name, request_mode)
            report["capabilities"].update({
                "supported_resolutions": sorted(valid_resolutions),
                "duration_min_seconds": minimum_duration,
                "duration_max_seconds": maximum_duration,
                "supports_draft": model_is_25,
                "supports_auto_mode": model_is_25,
                "supports_edit": not model_is_10,
                "supports_extend": not model_is_10,
                "supports_mov": model_is_25,
            })
        report["capabilities"]["reference_item_limit"] = (
            50 if model_is_25 and ark_native else (15 if ark_native else None)
        )
        report["capabilities"]["reference_category_limits"] = (
            {"images": 30, "videos": 10, "audios": 10}
            if model_is_25 and ark_native
            else (
                {"images": 2 if _seedance_model_supports_first_last_frame(model_name) else 1, "videos": 0, "audios": 0}
                if model_is_10 and ark_native
                else {"images": 9, "videos": 3, "audios": 3}
            )
        )
        if model_is_10 and ark_native:
            report["capabilities"]["reference_item_limit"] = 2 if _seedance_model_supports_first_last_frame(model_name) else 1
        # Ark's reference-audio support is model-specific: 2.0 accepts it
        # alongside image/video references, 2.5 accepts it directly, while
        # 1.0 does not advertise the capability.
        report["capabilities"]["reference_audio_supported"] = bool(
            ark_native and _seedance_model_supports_reference_audio(model_name)
        )
        checks["production_resolution"] = resolution in {"1080p", "4k"}
        if not checks["model_configured"]:
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "Set SEEDANCE_MODEL to a real provider model id before submitting generation tasks."
            )
        if not checks["production_resolution"]:
            report.setdefault("warnings", []).append(
                f"Seedance production output is configured as {resolution}; use 1080p or 4k for final delivery."
            )
        if not model_is_25:
            report.setdefault("warnings", []).append(
                "The configured Seedance model is not identified as 2.5; 2.5 multimodal limits and Draft promotion are unavailable."
            )
        if not report["capabilities"]["native_audio"]:
            report.setdefault("warnings", []).append(
                "Native audio is disabled; dialogue will use the separate audio pipeline and cannot use Ark audio generation."
            )
        output_validation_enabled = runtime_bool("SEEDANCE_VALIDATE_OUTPUT", True)
        checks["output_validation_enabled"] = output_validation_enabled
        checks["ffprobe_available"] = bool(shutil.which("ffprobe"))
        report["capabilities"]["output_artifact_validation"] = bool(
            output_validation_enabled and checks["ffprobe_available"]
        )
        if output_validation_enabled and not checks["ffprobe_available"]:
            report.setdefault("warnings", []).append(
                "SEEDANCE_VALIDATE_OUTPUT is enabled but ffprobe is unavailable; returned Ark artifacts cannot be validated immediately."
            )
            configuration_ok = False
            report.setdefault("action_items", []).append(
                "Install ffprobe or set SEEDANCE_VALIDATE_OUTPUT=false explicitly before using native Ark in production."
            )
        if not report["capabilities"]["continuity_last_frame"]:
            report.setdefault("warnings", []).append(
                "return_last_frame is disabled; cross-shot continuity will fall back to local video-frame extraction."
            )
        if ark_native:
            media_template = str(runtime_value("SEEDANCE_MEDIA_URL_TEMPLATE", "") or "")
            mode = str(report["configuration"]["request_mode"]).strip().lower()
            requires_video_transport = mode in {"edit", "extend"}
            media_template_valid = False
            if media_template:
                try:
                    sample_url = media_template.format(filename="preflight.mp4", path="preflight/preflight.mp4")
                    parsed = urlparse(sample_url)
                    hostname = parsed.hostname or ""
                    private_host = hostname.lower() in {"localhost", "localhost.localdomain"}
                    try:
                        address = ipaddress.ip_address(hostname)
                        private_host = private_host or any(
                            (
                                address.is_private,
                                address.is_loopback,
                                address.is_link_local,
                                address.is_reserved,
                            )
                        )
                    except ValueError:
                        pass
                    media_template_valid = (
                        ("{filename}" in media_template or "{path}" in media_template)
                        and parsed.scheme == "https"
                        and bool(parsed.netloc)
                        and not private_host
                    )
                except (KeyError, ValueError):
                    media_template_valid = False
            checks["local_video_reference_transport_configured"] = media_template_valid
            report["capabilities"]["local_video_audio_references"] = media_template_valid
            if not media_template_valid:
                message = (
                    "Native Ark image references and small local audio files can use Base64; local video and "
                    "oversized audio references require a valid HTTP(S) SEEDANCE_MEDIA_URL_TEMPLATE with "
                    "{filename}/{path}, or pre-ingested public asset IDs."
                )
                report.setdefault("warnings", []).append(message)
                if requires_video_transport:
                    configuration_ok = False
                    report.setdefault("action_items", []).append(message)
    report["status"] = "configured" if endpoint and api_key and configuration_ok else "blocked"
    if report["status"] == "blocked":
        if not endpoint or not api_key:
            report["message"] = f"Set {prefix}_ENDPOINT and {prefix}_API_KEY"
        else:
            report["message"] = "Fix Seedance API format, resolution, or output format settings"
    return report
