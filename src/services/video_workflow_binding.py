"""Bind model-facing controls into an exported ComfyUI API workflow.

Official ComfyUI workflows contain concrete node ids and ordinary input values.
They do not understand application-specific JSON placeholders. A sidecar binding
manifest lets the application update real node inputs without modifying the
upstream workflow graph or pretending that audit metadata controls sampling.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


class VideoWorkflowBindingError(ValueError):
    pass


def resolve_video_binding_path(
    workflow_path: str | Path,
    configured_path: str | None = None,
) -> Path | None:
    if configured_path and str(configured_path).strip():
        path = Path(str(configured_path).strip())
        return path if path.is_absolute() else Path.cwd() / path
    workflow = Path(workflow_path)
    candidates = (
        workflow.with_suffix(".bindings.json"),
        workflow.with_name(f"{workflow.stem}.binding.json"),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def load_video_workflow_bindings(
    workflow_path: str | Path,
    configured_path: str | None = None,
) -> dict:
    path = resolve_video_binding_path(workflow_path, configured_path)
    if path is None:
        return {
            "status": "missing",
            "path": "",
            "bindings": {},
            "derived_controls": [],
            "sha256": "",
        }
    if not path.is_file():
        raise VideoWorkflowBindingError(f"Video workflow binding file does not exist: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise VideoWorkflowBindingError(f"Invalid video workflow binding file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise VideoWorkflowBindingError("Video workflow binding root must be an object")
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise VideoWorkflowBindingError("Video workflow binding must define a non-empty bindings object")
    derived = payload.get("derived_controls") or []
    if not isinstance(derived, list) or any(not isinstance(item, str) or not item.strip() for item in derived):
        raise VideoWorkflowBindingError("derived_controls must be a list of control names")
    return {
        **payload,
        "status": "configured",
        "path": str(path),
        "bindings": bindings,
        "derived_controls": sorted({item.strip() for item in derived}),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _targets(value: Any) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    raise VideoWorkflowBindingError("Each video control binding must be an object or list of objects")


def validate_video_workflow_bindings(workflow: dict, manifest: dict) -> dict:
    errors: list[str] = []
    controls: list[str] = []
    for control, raw_targets in (manifest.get("bindings") or {}).items():
        if not isinstance(control, str) or not control.strip():
            errors.append("Binding control names must be non-empty strings")
            continue
        controls.append(control)
        try:
            targets = _targets(raw_targets)
        except VideoWorkflowBindingError as exc:
            errors.append(f"{control}: {exc}")
            continue
        if not targets:
            errors.append(f"{control}: at least one target is required")
        for target in targets:
            node_id = str(target.get("node_id", "")).strip()
            input_name = str(target.get("input", "")).strip()
            if not node_id or not input_name:
                errors.append(f"{control}: every target needs node_id and input")
                continue
            node = workflow.get(node_id)
            if not isinstance(node, dict):
                errors.append(f"{control}: node {node_id} does not exist")
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or input_name not in inputs:
                errors.append(f"{control}: node {node_id} has no input named {input_name}")
    return {
        "status": "valid" if not errors else "invalid",
        "controls": sorted(set(controls)),
        "derived_controls": list(manifest.get("derived_controls") or []),
        "errors": errors,
        "path": manifest.get("path", ""),
        "sha256": manifest.get("sha256", ""),
    }


def binding_has_control(manifest: dict, names: str | set[str]) -> bool:
    expected = {names} if isinstance(names, str) else set(names)
    available = set((manifest.get("bindings") or {}).keys())
    available.update(manifest.get("derived_controls") or [])
    return bool(expected & available)


def apply_video_workflow_bindings(workflow: dict, manifest: dict, values: dict[str, Any]) -> dict:
    result = copy.deepcopy(workflow)
    validation = validate_video_workflow_bindings(result, manifest)
    if validation["status"] != "valid":
        raise VideoWorkflowBindingError("; ".join(validation["errors"]))
    for control, raw_targets in (manifest.get("bindings") or {}).items():
        if control not in values:
            continue
        for target in _targets(raw_targets):
            node_id = str(target["node_id"])
            input_name = str(target["input"])
            result[node_id]["inputs"][input_name] = copy.deepcopy(values[control])
    return result


def discover_video_workflow_bindings(workflow: dict) -> dict:
    """Build a conservative draft binding manifest from an API-format graph.

    Ambiguous prompt and image nodes are deliberately left unresolved. Sampling
    controls may bind to multiple active stages, which is required by Wan 2.2
    high-noise/low-noise workflows.
    """
    bindings: dict[str, Any] = {}
    evidence: dict[str, list[dict]] = {}

    def title(node: dict) -> str:
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
        return str(meta.get("title") or node.get("title") or "").strip().lower()

    def candidates(predicate, input_names: tuple[str, ...]) -> list[dict]:
        found = []
        for node_id, node in workflow.items():
            if not isinstance(node, dict) or not predicate(node):
                continue
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            input_name = next((name for name in input_names if name in inputs), None)
            if input_name:
                found.append({
                    "node_id": str(node_id),
                    "input": input_name,
                    "class_type": str(node.get("class_type") or ""),
                    "title": title(node),
                })
        return found

    text_nodes = candidates(
        lambda node: "textencode" in str(node.get("class_type") or "").lower(),
        ("text",),
    )
    positive = [item for item in text_nodes if any(word in item["title"] for word in ("positive", "正向"))]
    negative = [item for item in text_nodes if any(word in item["title"] for word in ("negative", "负向", "反向"))]
    if len(positive) == 1:
        bindings["positive_prompt"] = {key: positive[0][key] for key in ("node_id", "input")}
    if len(negative) == 1:
        bindings["negative_prompt"] = {key: negative[0][key] for key in ("node_id", "input")}
    evidence["positive_prompt"] = positive or text_nodes
    evidence["negative_prompt"] = negative or text_nodes

    image_nodes = candidates(
        lambda node: str(node.get("class_type") or "").lower() == "loadimage",
        ("image",),
    )
    opening = [
        item for item in image_nodes
        if any(word in item["title"] for word in ("start", "first", "opening", "input image", "首帧", "起始"))
    ]
    ending = [
        item for item in image_nodes
        if any(word in item["title"] for word in ("end", "last", "closing", "尾帧", "结束"))
    ]
    if len(image_nodes) == 1 and not opening:
        opening = image_nodes
    if len(opening) == 1:
        bindings["reference_image"] = {key: opening[0][key] for key in ("node_id", "input")}
    if len(ending) == 1:
        bindings["end_image"] = {key: ending[0][key] for key in ("node_id", "input")}
    evidence["reference_image"] = opening or image_nodes
    evidence["end_image"] = ending or image_nodes

    video_nodes = candidates(
        lambda node: any(
            marker in str(node.get("class_type") or "").lower()
            for marker in ("loadvideo", "load_video")
        ),
        ("video", "filename", "file"),
    )
    audio_nodes = candidates(
        lambda node: any(
            marker in str(node.get("class_type") or "").lower()
            for marker in ("loadaudio", "load_audio")
        ),
        ("audio", "filename", "file"),
    )
    if len(video_nodes) == 1:
        bindings["driving_video"] = {
            key: video_nodes[0][key] for key in ("node_id", "input")
        }
    if len(audio_nodes) == 1:
        bindings["performance_audio"] = {
            key: audio_nodes[0][key] for key in ("node_id", "input")
        }
    evidence["driving_video"] = video_nodes
    evidence["performance_audio"] = audio_nodes

    keyframe_nodes = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        node_title = title(node)
        image_input = next(
            (name for name in ("keyframe_images", "conditioning_images", "images") if name in inputs),
            None,
        )
        index_input = next(
            (name for name in ("keyframe_indices", "conditioning_indices", "indices") if name in inputs),
            None,
        )
        if image_input and index_input and any(
            word in node_title for word in ("keyframe", "conditioning", "关键帧")
        ):
            keyframe_nodes.append({
                "node_id": str(node_id),
                "image_input": image_input,
                "index_input": index_input,
                "strength_input": next(
                    (name for name in ("keyframe_strengths", "conditioning_strengths", "strengths") if name in inputs),
                    None,
                ),
                "class_type": str(node.get("class_type") or ""),
                "title": node_title,
            })
    if len(keyframe_nodes) == 1:
        item = keyframe_nodes[0]
        bindings["keyframe_images"] = {
            "node_id": item["node_id"], "input": item["image_input"],
        }
        bindings["keyframe_indices"] = {
            "node_id": item["node_id"], "input": item["index_input"],
        }
        if item["strength_input"]:
            bindings["keyframe_strengths"] = {
                "node_id": item["node_id"], "input": item["strength_input"],
            }
    evidence["keyframe_images"] = keyframe_nodes
    evidence["keyframe_indices"] = keyframe_nodes

    latent_predicate = lambda node: any(
        term in str(node.get("class_type") or "").lower()
        for term in ("latentvideo", "wanimage", "wanvideo")
    )
    for control, names in {
        "width": ("width",),
        "height": ("height",),
        "num_frames": ("length", "num_frames", "frame_count"),
    }.items():
        found = candidates(latent_predicate, names)
        if found:
            bindings[control] = [
                {key: item[key] for key in ("node_id", "input")}
                for item in found
            ]
        evidence[control] = found

    sampler_nodes = candidates(
        lambda node: "sampler" in str(node.get("class_type") or "").lower(),
        ("noise_seed", "seed"),
    )
    if sampler_nodes:
        bindings["seed"] = [
            {key: item[key] for key in ("node_id", "input")}
            for item in sampler_nodes
        ]
    evidence["seed"] = sampler_nodes

    output_predicate = lambda node: (
        "savevideo" in str(node.get("class_type") or "").lower()
        or "videocombine" in str(node.get("class_type") or "").lower()
        or "createvideo" in str(node.get("class_type") or "").lower()
    )
    for control, names in {
        "fps": ("fps", "frame_rate"),
        "output_prefix": ("filename_prefix", "output_prefix", "filename"),
    }.items():
        found = candidates(output_predicate, names)
        if len(found) == 1:
            bindings[control] = {key: found[0][key] for key in ("node_id", "input")}
        evidence[control] = found

    raw_workflow = json.dumps(workflow, ensure_ascii=False).lower()
    if any(marker in raw_workflow for marker in ("wan2.2-animate", "wan2_2_animate", "wan_2_2_animate", "wan-animate", "wan_animate", "wananimate")):
        model_profile = "wan_2_2_animate"
    elif any(marker in raw_workflow for marker in ("hunyuanvideo-avatar", "hunyuanvideo_avatar", "hunyuanvideoavatar")):
        model_profile = "hunyuanvideo_avatar"
    elif any(marker in raw_workflow for marker in ("hunyuan-custom", "hunyuan_custom", "hunyuancustom")):
        model_profile = "hunyuan_custom"
    elif any(marker in raw_workflow for marker in ("ltx-2", "ltx_2", "ltx2", "ltxvideo2")):
        model_profile = "ltx_2_keyframes"
    elif (
        any(marker in raw_workflow for marker in ("hunyuanvideo-1.5", "hunyuanvideo_1_5", "hunyuanvideo1.5"))
        and keyframe_nodes
    ):
        model_profile = "hunyuanvideo_1_5_keyframes"
    elif "hunyuanvideo" in raw_workflow or "hunyuan_video" in raw_workflow:
        model_profile = "hunyuanvideo_i2v"
    elif any(marker in raw_workflow for marker in ("wan2.2", "wan_2_2", "wan2_2")):
        model_profile = "wan_2_2"
    else:
        model_profile = "unknown"

    required = {
        "positive_prompt", "negative_prompt", "reference_image",
        "width", "height", "num_frames", "seed", "fps", "output_prefix",
    }
    has_temporal_keyframes = bool(
        "keyframe_images" in bindings and "keyframe_indices" in bindings
    )
    if not has_temporal_keyframes:
        required.add("end_image")
    unresolved = sorted(required - set(bindings))
    return {
        "manifest": {
            "version": 2,
            "model_profile": model_profile,
            "capabilities": {
                "temporal_keyframes": has_temporal_keyframes,
            },
            "bindings": bindings,
            "derived_controls": [
                "quality_mode", "repair_action", "quality_pipeline",
                "spatial_plan_json",
            ],
        },
        "unresolved": unresolved,
        "evidence": evidence,
        "status": "ready_for_review" if not unresolved else "needs_manual_binding",
    }
