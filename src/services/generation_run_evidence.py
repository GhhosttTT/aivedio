"""Runtime evidence for local image/video generation validation runs."""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from typing import Any


def collect_gpu_evidence() -> dict[str, Any]:
    """Collect a safe, best-effort snapshot without making GPU availability a gate."""
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
        devices = []
        for line in result.stdout.splitlines():
            values = [item.strip() for item in line.split(",")]
            if len(values) != 5:
                continue
            name, total, used, free, utilization = values
            devices.append({
                "name": name,
                "memory_total_mb": _number(total),
                "memory_used_mb": _number(used),
                "memory_free_mb": _number(free),
                "utilization_percent": _number(utilization),
            })
        return {"status": "available" if devices else "unavailable", "devices": devices}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "devices": [], "reason": str(exc)}


def build_generation_run_evidence(
    render_report: dict[str, Any] | None,
    preflight_report: dict[str, Any] | None = None,
    *,
    gpu_evidence: dict[str, Any] | None = None,
    generated_at: int | None = None,
) -> dict[str, Any]:
    """Normalize runtime facts so reports remain comparable across validation runs."""
    render_report = render_report if isinstance(render_report, dict) else {}
    cases = [case for case in render_report.get("cases", []) if isinstance(case, dict)]
    candidate_count = 0
    accepted_count = 0
    for case in cases:
        search = case.get("search") if isinstance(case.get("search"), dict) else {}
        candidates = search.get("candidates") if isinstance(search.get("candidates"), list) else []
        candidate_count += len(candidates) or 1
        accepted_count += 1 if case.get("image") else 0
    elapsed = [float(case["elapsed_seconds"]) for case in cases if _is_number(case.get("elapsed_seconds"))]
    return {
        "schema_version": 2,
        "generated_at": generated_at if generated_at is not None else round(time.time()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "executable": sys.executable,
        },
        "runtime": {
            "status": render_report.get("status", "not_started"),
            "elapsed_seconds_sum": round(sum(elapsed), 2),
            "elapsed_seconds_max": round(max(elapsed), 2) if elapsed else 0.0,
            "case_count": len(cases),
            "candidate_count": candidate_count,
            "accepted_count": accepted_count,
            "acceptance_rate": round(accepted_count / len(cases), 4) if cases else 0.0,
        },
        "render_profile": render_report.get("render_profile", {}),
        "gpu": gpu_evidence if isinstance(gpu_evidence, dict) else collect_gpu_evidence(),
        "preflight": {
            "status": preflight_report.get("status") if isinstance(preflight_report, dict) else "missing",
            "local_gpu": (preflight_report.get("checks") or {}).get("local_gpu")
            if isinstance(preflight_report, dict) else None,
        },
    }


def build_video_generation_evidence(
    quality_report: dict[str, Any] | None,
    *,
    generated_at: int | None = None,
) -> dict[str, Any]:
    """Summarize provider attempts and promotion decisions for one video shot."""
    quality_report = quality_report if isinstance(quality_report, dict) else {}
    candidates = [item for item in quality_report.get("candidates", []) if isinstance(item, dict)]
    elapsed = [
        float(item["elapsed_seconds"])
        for item in candidates
        if _is_number(item.get("elapsed_seconds"))
    ]
    providers = sorted({
        str((item.get("provider_metadata") or {}).get("provider_name"))
        for item in candidates
        if isinstance(item.get("provider_metadata"), dict)
        and (item.get("provider_metadata") or {}).get("provider_name")
    })
    task_ids = sorted({
        str((item.get("provider_metadata") or {}).get("provider_task_id"))
        for item in candidates
        if isinstance(item.get("provider_metadata"), dict)
        and (item.get("provider_metadata") or {}).get("provider_task_id")
    })
    contract_hashes = sorted({
        str((item.get("provider_metadata") or {}).get("request_contract_hash"))
        for item in candidates
        if isinstance(item.get("provider_metadata"), dict)
        and (item.get("provider_metadata") or {}).get("request_contract_hash")
    })
    spatial_contract_hashes = sorted({
        str(
            ((item.get("provider_metadata") or {}).get("request_contract") or {})
            .get("spatial_asset_pack", {})
            .get("scene_contract_hash")
        )
        for item in candidates
        if isinstance(item.get("provider_metadata"), dict)
        and isinstance((item.get("provider_metadata") or {}).get("request_contract"), dict)
        and ((item.get("provider_metadata") or {}).get("request_contract") or {})
        .get("spatial_asset_pack", {}).get("scene_contract_hash")
    })
    spatial_project_signatures = sorted({
        str(
            ((item.get("provider_metadata") or {}).get("request_contract") or {})
            .get("spatial_asset_pack", {})
            .get("project_signature")
        )
        for item in candidates
        if isinstance(item.get("provider_metadata"), dict)
        and isinstance((item.get("provider_metadata") or {}).get("request_contract"), dict)
        and ((item.get("provider_metadata") or {}).get("request_contract") or {})
        .get("spatial_asset_pack", {}).get("project_signature")
    })
    generated = [item for item in candidates if item.get("status") != "error" and item.get("path")]
    passed = [item for item in candidates if item.get("status") == "passed"]
    return {
        "schema_version": 2,
        "kind": "video_generation_run",
        "generated_at": generated_at if generated_at is not None else round(time.time()),
        "status": quality_report.get("status", "unknown"),
        "selected_path": quality_report.get("selected_path"),
        "promoted_path": quality_report.get("promoted_path"),
        "attempts": {
            "candidate_count": len(candidates),
            "generated_count": len(generated),
            "passed_count": len(passed),
            "error_count": sum(1 for item in candidates if item.get("status") == "error"),
            "elapsed_seconds_sum": round(sum(elapsed), 2),
            "elapsed_seconds_max": round(max(elapsed), 2) if elapsed else 0.0,
            "pass_rate": round(len(passed) / len(generated), 4) if generated else 0.0,
        },
        "providers": providers,
        "provider_task_ids": task_ids,
        "request_contract_hashes": contract_hashes,
        "spatial_scene_contract_hashes": spatial_contract_hashes,
        "spatial_project_signatures": spatial_project_signatures,
        "quality_budget": quality_report.get("quality_budget", {}),
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: str) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number
