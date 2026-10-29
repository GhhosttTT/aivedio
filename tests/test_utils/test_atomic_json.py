import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.utils.atomic_json import json_update_lock, write_json_atomic


def _increment_snapshot(path):
    for _ in range(5):
        with json_update_lock(path):
            payload = json.loads(path.read_text()) if path.exists() else {"count": 0}
            payload["count"] += 1
            write_json_atomic(path, payload)


def test_json_update_lock_serializes_processes_and_releases_after_error(tmp_path):
    path = tmp_path / "counter.json"
    with pytest.raises(RuntimeError):
        with json_update_lock(path):
            raise RuntimeError("interrupted transaction")
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_increment_snapshot, args=(path,)) for _ in range(3)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
    assert json.loads(path.read_text())["count"] == 15


def test_write_json_atomic_publishes_complete_document(tmp_path):
    path = tmp_path / "control.json"

    write_json_atomic(path, {"version": 1, "controls": ["pose", "depth"]})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "controls": ["pose", "depth"],
    }
    assert not list(tmp_path.glob("*.tmp"))


def test_write_json_atomic_concurrent_writers_leave_valid_snapshot(tmp_path):
    path = tmp_path / "control.json"

    def save(index):
        write_json_atomic(path, {
            "version": index,
            "scene_contracts": [f"scene-{index}"],
            "complete": True,
        })

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(8)))

    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert snapshot["complete"] is True
    assert snapshot["scene_contracts"] == [f"scene-{snapshot['version']}"]
    assert not list(tmp_path.glob("*.tmp"))
