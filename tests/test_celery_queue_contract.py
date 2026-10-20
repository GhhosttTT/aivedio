"""Keep Celery queue declarations, routes, and the Compose worker aligned."""

from pathlib import Path

import yaml

from src.tasks.celery_app import celery_app

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _declared_queues() -> set[str]:
    return {queue.name for queue in celery_app.conf.task_queues}


def _compose_worker_queues() -> set[str]:
    config = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    command = str(config["services"]["celery-worker"]["command"])
    marker = "--queues"
    assert marker in command, "compose worker must declare its queue list"
    value = command.split(marker, 1)[1].split()[0].lstrip("=")
    return set(value.split(","))


def test_compose_worker_consumes_every_declared_queue():
    assert _compose_worker_queues() == _declared_queues()


def test_every_task_route_targets_a_declared_queue():
    declared = _declared_queues()
    for pattern, route in celery_app.conf.task_routes.items():
        assert route.get("queue") in declared, f"{pattern} routes to an undeclared queue"
