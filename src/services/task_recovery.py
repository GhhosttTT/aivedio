"""Safe recovery helpers for provider tasks accepted before a worker failed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from src.utils.storage import get_scene_video_path
from src.utils.storage import storage_manager


_PRODUCTION_OPTION_KEYS = (
    "provider",
    "request_mode",
    "multi_shot",
    "sequence_level_multi_shot",
    "native_audio",
    "model",
    "resolution",
    "output_format",
    "return_last_frame",
    "camera_fixed",
    "watermark",
    "duration_seconds",
)


def _production_options_path(project_id: int) -> Path:
    return storage_manager.get_project_path(project_id) / "production_options.json"


def save_production_video_options(project_id: int, task_id: int | str, options: dict) -> None:
    """Persist the effective per-run video controls for later repair tasks."""
    payload = {
        "task_id": str(task_id),
        "options": {
            key: options[key]
            for key in _PRODUCTION_OPTION_KEYS
            if key in options and options[key] is not None
        },
    }
    path = _production_options_path(project_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_production_video_options(project_id: int) -> dict | None:
    """Load the last successful run's controls, if a valid snapshot exists."""
    path = _production_options_path(project_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    options = payload.get("options") if isinstance(payload, dict) else None
    if not isinstance(options, dict):
        return None
    return {
        key: options[key]
        for key in _PRODUCTION_OPTION_KEYS
        if key in options and options[key] is not None
    } or None


def load_pending_video_options(
    project_id: int,
    scene_ids: Iterable[int],
    local_task_id: int | str | None = None,
) -> dict | None:
    """Return one consistent set of provider options from pending sidecars.

    A sidecar proves that a provider task was accepted, but it does not prove
    that every scene in a production run used the same controls. Recovery is
    therefore enabled only when all discovered sidecars carry identical,
    complete option records. Older sidecars safely fall back to the normal
    full retry path.
    """
    records: list[dict] = []
    pending_paths: list[tuple[Path, str | None]] = []
    scene_ids = list(scene_ids)
    for scene_id in scene_ids:
        output = Path(get_scene_video_path(project_id, int(scene_id)))
        pending_paths.append((output.with_suffix(".provider.pending.json"), None))
    if scene_ids:
        video_dir = Path(get_scene_video_path(project_id, int(scene_ids[0]))).parent
        pending_paths.extend(
            (path, path.name.removesuffix(".provider.pending.json") + ".mp4")
            for path in sorted(video_dir.glob("sequence_*.provider.pending.json"))
        )
    for sidecar, sequence_output_path in pending_paths:
        if not sidecar.is_file():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if local_task_id is not None and str(payload.get("local_task_id")) != str(local_task_id):
            continue
        options = payload.get("request_options") if isinstance(payload, dict) else None
        if not isinstance(options, dict) or not options.get("provider"):
            continue
        normalized = dict(options)
        if sequence_output_path:
            normalized["sequence_level_multi_shot"] = True
            normalized["sequence_output_path"] = str(sidecar.parent / sequence_output_path)
        records.append(normalized)

    if not records:
        return None
    first = records[0]
    comparable = json.dumps(first, ensure_ascii=False, sort_keys=True, default=str)
    if any(
        json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) != comparable
        for record in records[1:]
    ):
        return None
    return dict(first)
