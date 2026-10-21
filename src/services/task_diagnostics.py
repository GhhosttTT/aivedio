"""Read-only discovery and explicit cleanup of abandoned task records."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from src.database.models import Task, TaskStatus


STALE_TASK_STATUSES = (TaskStatus.PENDING, TaskStatus.RUNNING)
DEFAULT_STALE_TASK_HOURS = 6


def _cutoff(now: datetime | None, older_than_hours: float) -> datetime:
    if older_than_hours <= 0:
        raise ValueError("older_than_hours must be positive")
    reference = now or datetime.utcnow()
    return reference - timedelta(hours=older_than_hours)


def find_stale_tasks(
    db: Session,
    *,
    older_than_hours: float = DEFAULT_STALE_TASK_HOURS,
    now: datetime | None = None,
    project_ids: Iterable[int] | None = None,
) -> list[Task]:
    """Return pending/running tasks whose last update is older than the limit."""
    query = db.query(Task).filter(
        Task.status.in_(STALE_TASK_STATUSES),
        Task.updated_at < _cutoff(now, older_than_hours),
    )
    if project_ids is not None:
        ids = list(project_ids)
        if not ids:
            return []
        query = query.filter(Task.project_id.in_(ids))
    return query.order_by(Task.updated_at.asc(), Task.id.asc()).all()


def mark_stale_tasks_failed(
    db: Session,
    *,
    older_than_hours: float = DEFAULT_STALE_TASK_HOURS,
    now: datetime | None = None,
    project_ids: Iterable[int] | None = None,
) -> int:
    """Mark stale tasks failed so they become retryable and the UI stops polling.

    This never re-queues work: a duplicate provider run could be charged twice.
    Operators should retry explicitly after checking the provider dashboard.
    """
    tasks = find_stale_tasks(
        db,
        older_than_hours=older_than_hours,
        now=now,
        project_ids=project_ids,
    )
    message = (
        f"任务超过 {older_than_hours:g} 小时未更新，已标记为失败；"
        "请确认供应商状态后手动重试"
    )
    for task in tasks:
        task.status = TaskStatus.FAILED
        task.error_message = message
        task.updated_at = now or datetime.utcnow()
    if tasks:
        db.commit()
    return len(tasks)
