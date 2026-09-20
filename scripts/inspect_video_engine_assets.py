"""Inspect local assets needed for a production-grade video engine."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMFY_ROOTS = [
    ROOT / "ComfyUI" / "ComfyUI",
    ROOT / "ComfyUI",
]
VIDEO_NODE_KEYWORDS = (
    "wan", "animatediff", "framepack", "hunyuan", "ltx", "mochi", "cosmos", "video", "vhs"
)
VIDEO_MODEL_KEYWORDS = (
    "wan", "animatediff", "motion", "framepack", "hunyuan", "ltx", "mochi", "cosmos", "i2v", "video"
)


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def inspect_assets() -> dict:
    comfy_root = _first_existing(COMFY_ROOTS)
    report = {
        "status": "blocked",
        "comfy_root": str(comfy_root) if comfy_root else None,
        "custom_nodes": [],
        "video_models": [],
        "missing": [],
        "recommended_next_steps": [],
    }
    if not comfy_root:
        report["missing"].append("ComfyUI root")
        report["recommended_next_steps"].append("Install or point scripts/start_comfyui_windows.ps1 to a complete ComfyUI checkout.")
        return report

    custom_nodes = comfy_root / "custom_nodes"
    if custom_nodes.is_dir():
        for path in custom_nodes.iterdir():
            if path.is_dir() and any(key in path.name.lower() for key in VIDEO_NODE_KEYWORDS):
                report["custom_nodes"].append(str(path))
    else:
        report["missing"].append("ComfyUI custom_nodes directory")

    models = comfy_root / "models"
    if models.is_dir():
        for path in models.rglob("*"):
            if path.is_file() and any(key in path.name.lower() for key in VIDEO_MODEL_KEYWORDS):
                report["video_models"].append({"path": str(path), "bytes": path.stat().st_size})
    else:
        report["missing"].append("ComfyUI models directory")

    if not report["custom_nodes"]:
        report["missing"].append("prompt-aware video custom node, such as Wan/AnimateDiff/FramePack/LTXV")
    if not report["video_models"]:
        report["missing"].append("local video model weights for the selected node")

    if not report["missing"]:
        report["status"] = "assets_detected"
        report["recommended_next_steps"].append("Export a ComfyUI API workflow with prompt/reference placeholders and set COMFYUI_VIDEO_WORKFLOW_PATH.")
    else:
        report["recommended_next_steps"].extend([
            "Install one production video backend first: Wan image-to-video, AnimateDiff, FramePack, LTXV, or HunyuanVideo.",
            "Export an API workflow that contains {prompt}, {negative_prompt}, {reference_image}, {seed}, {fps}, and {output_prefix}.",
            "Run: python -m scripts.validate_local_generation preflight-production-video",
        ])
    return report


def main() -> int:
    report = inspect_assets()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "assets_detected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
