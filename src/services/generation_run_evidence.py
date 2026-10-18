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
        "schema_version": 1,
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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: str) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number
