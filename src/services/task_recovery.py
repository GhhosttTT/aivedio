"""Safe recovery helpers for provider tasks accepted before a worker failed."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from src.utils.storage import get_scene_video_path
from src.utils.storage import storage_manager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses atomic replace without flock.
    fcntl = None


_PRODUCTION_OPTION_KEYS = (
    "provider",
    "request_mode",
    "multi_shot",
    "sequence_level_multi_shot",
    "native_audio",
    "draft",
    "draft_task_id",
    "draft_task_ids",
    "model",
    "resolution",
    "output_format",
    "return_last_frame",
    "camera_fixed",
    "watermark",
    "duration_seconds",
    "sequence_output_path",
    "add_bgm",
    "bgm_path",
    "bgm_volume",
    "readiness_snapshot_path",
    "readiness_task_record_id",
)

_PRODUCTION_OPTION_ALIASES = {
    "model": "MODEL",
    "resolution": "RESOLUTION",
    "output_format": "OUTPUT_FORMAT",
    "return_last_frame": "RETURN_LAST_FRAME",
    "camera_fixed": "CAMERA_FIXED",
    "watermark": "WATERMARK",
    "duration_seconds": "DURATION_SECONDS",
    "sequence_output_path": "SEQUENCE_OUTPUT_PATH",
}


def _production_options_path(project_id: int) -> Path:
    return storage_manager.get_project_path(project_id) / "production_options.json"


@contextmanager
def _options_lock(path: Path):
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as stream:
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def save_production_video_options(project_id: int, task_id: int | str, options: dict) -> None:
    """Persist the effective per-run video controls for later repair tasks."""
    normalized_options = dict(options or {})
    for canonical, alias in _PRODUCTION_OPTION_ALIASES.items():
        if canonical not in normalized_options and alias in normalized_options:
            normalized_options[canonical] = normalized_options[alias]
    payload = {
        "task_id": str(task_id),
        "options": {
            key: normalized_options[key]
            for key in _PRODUCTION_OPTION_KEYS
            if key in normalized_options and normalized_options[key] is not None
        },
    }
    path = _production_options_path(project_id)
    with _options_lock(path):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def load_production_video_options(
    project_id: int,
    task_id: int | str | None = None,
) -> dict | None:
    """Load production controls, optionally requiring an exact task snapshot.

    Repair tasks intentionally use the project's most recent controls. A retry
    of an older failed task must be stricter: using a newer snapshot can mix
    models or Draft IDs across paid provider requests.
    """
    path = _production_options_path(project_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    options = payload.get("options") if isinstance(payload, dict) else None
    if not isinstance(options, dict):
        return None
    if task_id is not None and str(payload.get("task_id")) != str(task_id):
        return None
    result = {
        key: options[key]
        for key in _PRODUCTION_OPTION_KEYS
        if key in options and options[key] is not None
    }
    draft_task_ids = result.get("draft_task_ids")
    if isinstance(draft_task_ids, dict):
        result["draft_task_ids"] = {
            int(key) if str(key).isdigit() else key: value
            for key, value in draft_task_ids.items()
        }
    return result or None


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
