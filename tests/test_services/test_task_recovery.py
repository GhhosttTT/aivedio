import json
from pathlib import Path

from src.services import task_recovery


def _write_sidecar(path: Path, options: dict, local_task_id=None):
    path.with_suffix(".provider.pending.json").write_text(
        json.dumps({
            "provider_task_id": "remote-task",
            "local_task_id": local_task_id,
            "request_options": options,
        }),
        encoding="utf-8",
    )


def test_load_pending_video_options_requires_consistent_records(tmp_path, monkeypatch):
    outputs = {1: tmp_path / "scene-1.mp4", 2: tmp_path / "scene-2.mp4"}
    monkeypatch.setattr(task_recovery, "get_scene_video_path", lambda _project, scene_id: str(outputs[scene_id]))
    options = {"provider": "seedance_api", "model": "doubao-seedance-2-5-260628"}
    _write_sidecar(outputs[1], options)
    _write_sidecar(outputs[2], options)

    assert task_recovery.load_pending_video_options(7, [1, 2]) == options

    _write_sidecar(outputs[2], {**options, "model": "doubao-seedance-2-0-260128"})
    assert task_recovery.load_pending_video_options(7, [1, 2]) is None


def test_load_pending_video_options_ignores_legacy_sidecars(tmp_path, monkeypatch):
    output = tmp_path / "scene.mp4"
    monkeypatch.setattr(task_recovery, "get_scene_video_path", lambda *_args: str(output))
    output.with_suffix(".provider.pending.json").write_text(
        json.dumps({"provider_task_id": "old-task"}), encoding="utf-8",
    )

    assert task_recovery.load_pending_video_options(7, [1]) is None


def test_load_pending_video_options_finds_sequence_sidecar(tmp_path, monkeypatch):
    output = tmp_path / "scene-1.mp4"
    monkeypatch.setattr(task_recovery, "get_scene_video_path", lambda *_args: str(output))
    sequence = tmp_path / "sequence_42.mp4"
    _write_sidecar(sequence, {"provider": "seedance_api", "model": "doubao-seedance-2-5-260628"})

    options = task_recovery.load_pending_video_options(7, [1])

    assert options["sequence_level_multi_shot"] is True
    assert options["sequence_output_path"] == str(sequence)


def test_load_pending_video_options_rejects_sidecar_from_another_task(tmp_path, monkeypatch):
    output = tmp_path / "scene-1.mp4"
    monkeypatch.setattr(task_recovery, "get_scene_video_path", lambda *_args: str(output))
    _write_sidecar(output, {"provider": "seedance_api"}, local_task_id=41)

    assert task_recovery.load_pending_video_options(7, [1], local_task_id=42) is None
    assert task_recovery.load_pending_video_options(7, [1], local_task_id=41) == {
        "provider": "seedance_api",
    }


def test_production_video_options_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(task_recovery.storage_manager, "get_project_path", lambda project_id: tmp_path)

    task_recovery.save_production_video_options(7, 42, {
        "provider": "seedance_api",
        "model": "doubao-seedance-2-5-260628",
        "resolution": "1080p",
        "sequence_level_multi_shot": True,
        "draft_task_ids": {1: "draft-1", 2: "draft-2"},
        "add_bgm": True,
        "bgm_path": "/tmp/project/music/bgm.mp3",
        "bgm_volume": 0.25,
        "duration_seconds": None,
        "draft": True,
    })

    assert task_recovery.load_production_video_options(7) == {
        "provider": "seedance_api",
        "model": "doubao-seedance-2-5-260628",
        "resolution": "1080p",
        "sequence_level_multi_shot": True,
        "draft_task_ids": {1: "draft-1", 2: "draft-2"},
        "add_bgm": True,
        "bgm_path": "/tmp/project/music/bgm.mp3",
        "bgm_volume": 0.25,
    }

    assert task_recovery.load_production_video_options(7, task_id=42) == {
        "provider": "seedance_api",
        "model": "doubao-seedance-2-5-260628",
        "resolution": "1080p",
        "sequence_level_multi_shot": True,
        "draft_task_ids": {1: "draft-1", 2: "draft-2"},
        "add_bgm": True,
        "bgm_path": "/tmp/project/music/bgm.mp3",
        "bgm_volume": 0.25,
    }
    assert task_recovery.load_production_video_options(7, task_id=41) is None


def test_production_video_options_normalize_task_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(task_recovery.storage_manager, "get_project_path", lambda project_id: tmp_path)

    task_recovery.save_production_video_options(7, 43, {
        "provider": "seedance_api",
        "MODEL": "doubao-seedance-2-5-260628",
        "RESOLUTION": "1080p",
        "OUTPUT_FORMAT": "mp4",
        "SEQUENCE_OUTPUT_PATH": "/tmp/sequence.mp4",
    })

    assert task_recovery.load_production_video_options(7, task_id=43) == {
        "provider": "seedance_api",
        "model": "doubao-seedance-2-5-260628",
        "resolution": "1080p",
        "output_format": "mp4",
        "sequence_output_path": "/tmp/sequence.mp4",
    }
