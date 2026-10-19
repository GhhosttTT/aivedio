"""Public callback receiver for native Volcano Ark video tasks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the atomic replace fallback.
    fcntl = None

from fastapi import APIRouter, HTTPException, Request, status

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
_TERMINAL_STATES = {
    "succeeded", "success", "completed", "complete", "done",
    "failed", "error", "expired", "cancelled", "canceled",
}
_KNOWN_STATES = {"queued", "running", *_TERMINAL_STATES}
_CALLBACK_STATE_RANK = {
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


def _callback_secret() -> str:
    return str(
        os.getenv("SEEDANCE_CALLBACK_SECRET")
        or getattr(settings, "SEEDANCE_CALLBACK_SECRET", "")
        or ""
    ).strip()


def _unsigned_callbacks_allowed() -> bool:
    value = os.getenv("SEEDANCE_CALLBACK_ALLOW_UNSIGNED")
    if value is None:
        value = getattr(settings, "SEEDANCE_CALLBACK_ALLOW_UNSIGNED", False)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _secret_is_valid(request: Request, token: str | None) -> bool:
    expected = _callback_secret()
    if not expected:
        # Never expose an unauthenticated production webhook by accident. A
        # local gateway can explicitly opt in when it cannot send a header.
        return _unsigned_callbacks_allowed()
    provided = request.headers.get("x-seedance-callback-secret") or token or ""
    return hmac.compare_digest(provided, expected)


def _pending_sidecars() -> list[Path]:
    root = Path(
        os.getenv("STORAGE_PATH")
        or getattr(settings, "STORAGE_PATH", "./storage")
        or "./storage"
    )
    if not root.exists():
        return []
    return [path for path in root.glob("projects/*/**/*.provider.pending.json") if path.is_file()]


def _callback_path(sidecar: Path) -> Path:
    return sidecar.with_name(sidecar.name.replace(
        ".provider.pending.json", ".provider.callback.json",
    ))


@contextmanager
def _callback_lock(target: Path):
    """Serialize callback read/compare/write across web workers."""
    lock_path = target.with_name(f".{target.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _persist_callback(sidecar: Path, payload: dict) -> None:
    target = _callback_path(sidecar)
    incoming_state = str(payload.get("status") or payload.get("state") or "").strip().lower()
    with _callback_lock(target):
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                existing = None
            existing_state = (
                str(existing.get("status") or existing.get("state") or "").strip().lower()
                if isinstance(existing, dict) else ""
            )
            # Provider callbacks can arrive out of order. A terminal failure
            # may be superseded by a later success, but no state can regress
            # to an older lifecycle phase or downgrade a successful result.
            if _CALLBACK_STATE_RANK.get(existing_state, 0) > _CALLBACK_STATE_RANK.get(incoming_state, 0):
                return
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


@router.post("/seedance", status_code=status.HTTP_200_OK)
async def receive_seedance_callback(request: Request, token: str | None = None):
    if not _secret_is_valid(request, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Seedance callback secret")
    try:
        payload = await request.json()
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Seedance callback must be JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Seedance callback body must be an object")
    task_id = str(
        payload.get("draft_task_id")
        or payload.get("draft_id")
        or payload.get("id")
        or payload.get("task_id")
        or payload.get("job_id")
        or ""
    ).strip()
    state = str(payload.get("status") or payload.get("state") or "").strip().lower()
    if not task_id or state not in _KNOWN_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Seedance callback requires id and a supported status",
        )

    stored = 0
    for sidecar in _pending_sidecars():
        try:
            pending = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(pending, dict) or str(pending.get("provider_task_id") or "") != task_id:
            continue
        if pending.get("provider") not in {None, "seedance_api"}:
            continue
        try:
            _persist_callback(sidecar, payload)
            stored += 1
        except OSError as exc:
            logger.warning("Could not persist Seedance callback for {}: {}", sidecar, exc)

    return {
        "accepted": True,
        "task_id": task_id,
        "status": state,
        "matched_pending_tasks": stored,
        "callback_secret_configured": bool(_callback_secret()),
        "unsigned_callbacks_allowed": _unsigned_callbacks_allowed(),
    }
