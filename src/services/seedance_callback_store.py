"""Durable handoff for Seedance callbacks that race task-sidecar creation."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses atomic replace.
    fcntl = None

from src.config import settings


_STATE_RANK = {
    "queued": 1,
    "running": 2,
    "failed": 3,
    "error": 3,
    "expired": 3,
    "cancelled": 3,
    "canceled": 3,
    "succeeded": 4,
    "success": 4,
    "completed": 4,
    "complete": 4,
    "done": 4,
}


def _storage_root() -> Path:
    return Path(
        os.getenv("STORAGE_PATH")
        or getattr(settings, "STORAGE_PATH", "./storage")
        or "./storage"
    )


def _ttl_seconds() -> float:
    raw = os.getenv("SEEDANCE_CALLBACK_INBOX_TTL_SECONDS")
    if raw is None:
        raw = getattr(settings, "SEEDANCE_CALLBACK_INBOX_TTL_SECONDS", 900)
    try:
        return max(60.0, float(raw))
    except (TypeError, ValueError):
        return 900.0


def _inbox_path(task_id: str) -> Path:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return _storage_root() / "seedance_callbacks" / "inbox" / f"{digest}.json"


@contextmanager
def _lock(target: Path):
    lock_path = target.with_name(f".{target.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as stream:
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _state(payload: dict) -> str:
    return str(payload.get("status") or payload.get("state") or "").strip().lower()


def persist_early_callback(task_id: str, payload: dict) -> bool:
    """Store a callback until the matching provider pending sidecar exists.

    Returns whether the inbox was written. The provider task id is hashed in
    the filename so callback payloads cannot expose arbitrary task ids in the
    storage layout.
    """
    task_id = str(task_id or "").strip()
    if not task_id or not isinstance(payload, dict):
        return False
    target = _inbox_path(task_id)
    with _lock(target):
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                existing = None
            if isinstance(existing, dict):
                try:
                    stale = time.time() - target.stat().st_mtime > _ttl_seconds()
                except OSError:
                    stale = False
                if not stale and _STATE_RANK.get(_state(existing), 0) > _STATE_RANK.get(_state(payload), 0):
                    return False
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def claim_early_callback(task_id: str) -> dict | None:
    """Atomically claim and remove a callback queued before sidecar creation."""
    task_id = str(task_id or "").strip()
    if not task_id:
        return None
    target = _inbox_path(task_id)
    with _lock(target):
        if not target.is_file():
            return None
        try:
            if time.time() - target.stat().st_mtime > _ttl_seconds():
                target.unlink(missing_ok=True)
                return None
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            target.unlink(missing_ok=True)
            return None
        target.unlink(missing_ok=True)
        return payload if isinstance(payload, dict) else None
