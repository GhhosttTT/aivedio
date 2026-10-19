import json
from concurrent.futures import ThreadPoolExecutor

from src.utils.atomic_json import write_json_atomic


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
