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


def test_seedance_callback_is_queued_until_pending_sidecar_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "race-task", "status": "succeeded", "content": {"video_url": "https://media/video.mp4"}},
    )

    assert response.status_code == 200
    assert response.json()["matched_pending_tasks"] == 0
    assert response.json()["queued_for_pending_task"] is True

    from src.services.seedance_callback_store import claim_early_callback
    assert claim_early_callback("race-task")["status"] == "succeeded"
    assert claim_early_callback("race-task") is None


def test_seedance_callback_rejects_invalid_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "wrong"},
        json={"id": "cgt-123", "status": "running"},
    )

    assert response.status_code == 401


def test_seedance_callback_rejects_missing_secret_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.delenv("SEEDANCE_CALLBACK_SECRET", raising=False)
    monkeypatch.delenv("SEEDANCE_CALLBACK_ALLOW_UNSIGNED", raising=False)

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        json={"id": "cgt-123", "status": "running"},
    )

    assert response.status_code == 401


def test_seedance_callback_unsigned_mode_requires_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.delenv("SEEDANCE_CALLBACK_SECRET", raising=False)
    monkeypatch.setenv("SEEDANCE_CALLBACK_ALLOW_UNSIGNED", "true")

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        json={"id": "cgt-123", "status": "running"},
    )

    assert response.status_code == 200
    assert response.json()["unsigned_callbacks_allowed"] is True


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


def test_seedance_callback_allows_success_to_upgrade_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")
    pending = tmp_path / "projects" / "7" / "videos" / "scene.provider.pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps({
        "provider": "seedance_api",
        "provider_task_id": "recoverable-task",
    }), encoding="utf-8")
    client = TestClient(create_app())

    client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "recoverable-task", "status": "failed"},
    )
    client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "recoverable-task", "status": "succeeded"},
    )

    callback = pending.with_name("scene.provider.callback.json")
    assert json.loads(callback.read_text(encoding="utf-8"))["status"] == "succeeded"


def test_seedance_callback_accepts_provider_completed_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")
    pending = tmp_path / "projects" / "7" / "videos" / "scene.provider.pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps({
        "provider": "seedance_api",
        "provider_task_id": "completed-task",
    }), encoding="utf-8")
    client = TestClient(create_app())

    response = client.post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"id": "completed-task", "status": "completed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert pending.with_name("scene.provider.callback.json").is_file()


def test_seedance_callback_matches_draft_task_id(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("SEEDANCE_CALLBACK_SECRET", "callback-secret")
    pending = tmp_path / "projects" / "7" / "videos" / "scene.provider.pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps({
        "provider": "seedance_api",
        "provider_task_id": "draft-promotable-1",
    }), encoding="utf-8")

    response = TestClient(create_app()).post(
        "/api/webhooks/seedance",
        headers={"X-Seedance-Callback-Secret": "callback-secret"},
        json={"draft_task_id": "draft-promotable-1", "status": "succeeded"},
    )

    assert response.status_code == 200
    assert response.json()["matched_pending_tasks"] == 1
    assert pending.with_name("scene.provider.callback.json").is_file()
