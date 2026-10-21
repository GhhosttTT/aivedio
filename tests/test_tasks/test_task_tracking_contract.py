"""Every Celery task carrying a task_id must have a tracked Task row."""

import ast
from pathlib import Path

from src.tasks.celery_app import PRODUCTION_TASK_NAMES


def _decorated_task_names(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        name = None
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            if call is None:
                continue
            for keyword in call.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    name = keyword.value.value
        if name:
            yield name, [arg.arg for arg in node.args.args]


def test_tasks_with_task_id_are_tracked():
    missing = []
    for path in Path("src/tasks").glob("*_tasks.py"):
        for name, args in _decorated_task_names(path):
            if "task_id" in args and name not in PRODUCTION_TASK_NAMES:
                missing.append(f"{path.name}:{name}")

    assert missing == [], f"Celery tasks with task_id are not tracked: {missing}"
