import json

from fastapi.testclient import TestClient

from src.api.app import create_app


def test_seedance_callback_persists_matching_terminal_result(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")
    pending = tmp_path / "projects" / "7" / "videos" / "scene.provider.pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps({
        "provider": "seedance_api",
        "provider_task_id": "cgt-123",
    }), encoding="utf-8")

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "cgt-123", "status": "succeeded", "content": {"video_url": "https://media/video.mp4"}},
    )

    assert response.status_code == 200
    assert response.json()["matched_pending_tasks"] == 1
    callback = pending.with_name("scene.provider.callback.json")
    assert json.loads(callback.read_text(encoding="utf-8"))["status"] == "succeeded"


def test_seedance_callback_rejects_invalid_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "wrong"},
        json={"id": "cgt-123", "status": "running"},
    )

    assert response.status_code == 401


def test_seedance_callback_does_not_regress_terminal_state(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")
    pending = tmp_path / "projects" / "7" / "videos" / "scene.provider.pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps({
        "provider": "seedance_api",
        "provider_task_id": "cgt-123",
    }), encoding="utf-8")
    client = TestClient(create_app())

    first = client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "cgt-123", "status": "succeeded"},
    )
    second = client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "cgt-123", "status": "running"},
    )

    assert first.status_code == second.status_code == 200
    callback = pending.with_name("scene.provider.callback.json")
    assert json.loads(callback.read_text(encoding="utf-8"))["status"] == "succeeded"


def test_seedance_callback_does_not_replace_terminal_state_with_another(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")
    pending = tmp_path / "projects" / "7" / "videos" / "scene.provider.pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps({
        "provider": "seedance_api",
        "provider_task_id": "terminal-task",
    }), encoding="utf-8")
    client = TestClient(create_app())

    first = client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "terminal-task", "status": "succeeded"},
    )
    second = client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "terminal-task", "status": "failed"},
    )

    assert first.status_code == second.status_code == 200
    callback = pending.with_name("scene.provider.callback.json")
    assert json.loads(callback.read_text(encoding="utf-8"))["status"] == "succeeded"
