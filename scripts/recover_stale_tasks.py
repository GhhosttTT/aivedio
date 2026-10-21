#!/usr/bin/env python3
"""Report or fail task records abandoned by a crashed worker.

Default mode is read-only. Use --apply to mark stale pending/running tasks as
failed; the tasks then become retryable from the UI. Nothing is re-queued here,
so an accepted provider task cannot be charged twice.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.session import SessionLocal  # noqa: E402
from src.services.task_diagnostics import (  # noqa: E402
    DEFAULT_STALE_TASK_HOURS,
    find_stale_tasks,
    mark_stale_tasks_failed,
)


def _positive_hours(value: str) -> float:
    try:
        hours = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if hours <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return hours


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--older-than-hours",
        type=_positive_hours,
        default=DEFAULT_STALE_TASK_HOURS,
        help="age threshold based on task.updated_at (default: 6)",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        action="append",
        dest="project_ids",
        help="limit to a project (repeatable)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="mark matching tasks failed instead of only listing them",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        try:
            tasks = find_stale_tasks(
                db,
                older_than_hours=args.older_than_hours,
                project_ids=args.project_ids,
            )
        except Exception as exc:
            detail = getattr(exc, "orig", exc)
            print(
                f"failed to inspect task records (database missing or unreachable): {detail}",
                file=sys.stderr,
            )
            return 2
        if args.json:
            print(json.dumps([
                {
                    "id": task.id,
                    "project_id": task.project_id,
                    "celery_task_id": task.celery_task_id,
                    "status": task.status.value if hasattr(task.status, "value") else task.status,
                    "progress": task.progress,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                }
                for task in tasks
            ], ensure_ascii=False, indent=2))
        else:
            print(f"stale tasks older than {args.older_than_hours:g}h: {len(tasks)}")
            for task in tasks:
                print(
                    f"  id={task.id} project={task.project_id} "
                    f"status={task.status} progress={task.progress:.0f}% "
                    f"updated_at={task.updated_at}"
                )
        if args.apply and tasks:
            count = mark_stale_tasks_failed(
                db,
                older_than_hours=args.older_than_hours,
                project_ids=args.project_ids,
            )
            print(f"marked {count} task(s) failed; retry them explicitly when safe")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
