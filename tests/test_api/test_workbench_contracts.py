import io
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.app import create_app
from src.api.auth import create_access_token
from src.database.models import Base, User, Project, Scene, Character, Task, ProjectStatus, TaskStatus
from src.database.session import get_db_session
from src.services.task_orchestrator import TaskOrchestrator
from src.utils.storage import storage_manager


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", True)
    monkeypatch.setattr("src.api.rate_limiter.get_redis_client", lambda: None)
    from src.services import character_service
    monkeypatch.setattr(character_service, "_character_manager", None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    db.add_all([User(id=i, username=f"user{i}", email=f"u{i}@example.com", hashed_password="test") for i in (1, 2)])
    db.add(Project(id=1, name="Owner project", theme="A letter", user_id=1, status=ProjectStatus.SCRIPT_GENERATED))
    db.flush()
    db.add(Scene(project_id=1, scene_number=1, visual_description="A sealed letter on a table", dialogue="Hello", image_path="old.png", video_path="old.mp4"))
    db.commit()
    app = create_app()
    def dependency():
        session = factory()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db_session] = dependency
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + create_access_token({"sub": "1"})
        yield client, db, tmp_path
    db.close()
    engine.dispose()


def test_project_crud_and_owner_isolation(setup):
    client, db, _ = setup
    assert client.get("/api/projects").json()["total"] == 1
    created = client.post("/api/projects", json={"name": "Another", "theme": "Drama"})
    assert created.status_code == 201
    pid = created.json()["id"]
    assert client.put(f"/api/projects/{pid}", json={"theme": "Changed"}).json()["theme"] == "Changed"
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    client.headers["Authorization"] = "Bearer " + create_access_token({"sub": "2"})
    assert client.get("/api/projects").json()["total"] == 0
    for method, url in [("get", "/api/projects/1"), ("delete", "/api/projects/1"), ("post", "/api/projects/1/produce"), ("get", "/api/projects/1/generation-review"), ("get", "/api/projects/1/production-readiness"), ("get", "/api/projects/1/characters")]:
        assert getattr(client, method)(url).status_code == 404


def test_scene_save_invalidates_media_and_rejects_manual_completion(setup):
    client, db, _ = setup
    result = client.put("/api/projects/1/scenes/1", json={"visual_description": "A new letter", "dialogue": "Changed"})
    assert result.status_code == 200
    scene = result.json()["scenes"][0]
    assert scene["visual_description"] == "A new letter"
    assert scene["image_path"] is None and scene["video_path"] is None
    assert client.put("/api/projects/1", json={"status": "completed"}).status_code == 400


def test_production_id_persistence_duplicate_submission_status_cancel(setup, monkeypatch):
    client, db, _ = setup
    submitted = []
    def build(self, project_id, task_id, *args, **kwargs):
        identifier = str(uuid4())
        def publish():
            record = self.db.query(Task).filter(Task.id == task_id).one()
            assert record.celery_task_id == identifier
            assert record.project.status == ProjectStatus.IN_PRODUCTION
            record.status = TaskStatus.RUNNING
            self.db.commit()
            submitted.append(task_id)
        return SimpleNamespace(freeze=lambda: SimpleNamespace(id=identifier), apply_async=publish)
    monkeypatch.setattr(TaskOrchestrator, "_build_task_chain", build)
    result = client.post("/api/projects/1/produce")
    assert result.status_code == 200, result.text
    identifier = result.json()["task_id"]
    assert len(identifier) == 36 and submitted
    assert client.get(f"/api/tasks/{identifier}/status").json()["status"] == "running"
    assert client.get("/api/projects/1/production-task").json()["celery_task_id"] == identifier
    assert client.post("/api/projects/1/produce").status_code == 409
    assert client.put("/api/projects/1/scenes/1", json={"visual_description": "edit"}).status_code == 409
    monkeypatch.setattr("src.services.task_orchestrator.celery_app.control.revoke", Mock())
    assert client.post(f"/api/tasks/{identifier}/cancel").status_code == 200
    assert client.get(f"/api/tasks/{identifier}/status").json()["status"] == "cancelled"


def test_broker_failure_sets_failed(setup, monkeypatch):
    client, db, _ = setup
    chain = Mock()
    chain.freeze.return_value.id = str(uuid4())
    chain.apply_async.side_effect = RuntimeError("broker offline")
    monkeypatch.setattr(TaskOrchestrator, "_build_task_chain", lambda *a, **k: chain)
    assert client.post("/api/projects/1/produce").status_code == 500
    latest = client.get("/api/projects/1/production-task").json()
    assert latest["status"] == "failed" and "broker offline" in latest["error_message"]
    assert client.get("/api/projects/1").json()["status"] == "failed"


def test_production_engine_block_returns_actionable_400(setup, monkeypatch):
    client, db, _ = setup
    monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", False)
    monkeypatch.setattr(
        "src.services.task_orchestrator.preflight_production_video_engine",
        lambda: {"status": "production_not_ready", "action_items": ["configure ComfyUI video workflow"]},
    )

    response = client.post("/api/projects/1/produce")

    assert response.status_code == 400
    assert "Production video engine is not ready" in response.json()["detail"]
    assert "configure ComfyUI video workflow" in response.json()["detail"]


def test_short_drama_scene_count_block_returns_actionable_400(setup, monkeypatch):
    client, db, _ = setup
    monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", False)
    monkeypatch.setattr(
        "src.services.task_orchestrator.preflight_production_video_engine",
        lambda: {"status": "ready_for_production_video_test", "action_items": []},
    )

    response = client.post("/api/projects/1/produce")

    assert response.status_code == 400
    assert "at least 16 atomic scenes" in response.json()["detail"]
    assert "current project has 1" in response.json()["detail"]


def test_repair_scene_keyframe_creates_targeted_task(setup, monkeypatch):
    client, db, _ = setup
    chain = Mock()
    chain.freeze.return_value.id = "repair-task-id"
    monkeypatch.setattr("src.services.task_orchestrator.generate_image_task.si", Mock(return_value=chain))

    response = client.post(
        "/api/projects/1/repair-scene",
        json={"scene_number": 1, "action": "refine_prompt_composition"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_id"] == "repair-task-id"
    scene = db.query(Scene).filter(Scene.project_id == 1, Scene.scene_number == 1).one()
    assert scene.image_path is None and scene.video_path is None
    chain.apply_async.assert_called_once()


def test_repair_scene_rejects_non_executable_action(setup):
    client, db, _ = setup

    response = client.post(
        "/api/projects/1/repair-scene",
        json={"scene_number": 1, "action": "split_scene"},
    )

    assert response.status_code == 400
    assert "拆" in response.json()["detail"]


def test_production_readiness_reports_scene_and_review_gaps(setup, monkeypatch):
    client, db, _ = setup
    monkeypatch.setattr("src.services.production_readiness.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", False)

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["checks"]["script"]["scene_count"] == 1
    assert any(item["code"] == "too_few_atomic_scenes" for item in payload["blockers"])
    assert any(item["code"] == "image_review_not_required" for item in payload["warnings"])
    assert "video_engine" not in payload["checks"]


def test_production_readiness_reports_missing_character_references(setup):
    client, db, _ = setup
    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.character_name = "Alice"
    scene.visual_description = "Alice stands by the table and opens the sealed letter."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice"]}]})
    db.add(Character(project_id=1, name="Alice", appearance="woman, black hair, red coat"))
    db.commit()

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(item["code"] == "missing_character_references" for item in payload["blockers"])
    assert payload["checks"]["characters"]["visible_character_names"] == ["Alice"]
    assert payload["checks"]["characters"]["missing_references"] == ["Alice"]


def test_production_readiness_requires_character_identity_bible(setup):
    client, db, _ = setup
    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.character_name = "Alice"
    scene.visual_description = "Alice stands by the table and opens the sealed letter."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice"]}]})
    db.add(Character(project_id=1, name="Alice", appearance="woman, black hair, red coat"))
    db.commit()

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(item["code"] == "missing_character_identity_bible" for item in payload["blockers"])
    assert payload["checks"]["characters"]["missing_identity_specs"] == ["Alice"]


def test_production_readiness_accepts_complete_identity_bible_but_requires_reference(setup):
    client, db, _ = setup
    from src.services.character_identity_service import CharacterIdentityService

    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.character_name = "Alice"
    scene.visual_description = "Alice stands by the table and opens the sealed letter."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice"]}]})
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    db.add(Character(
        project_id=1,
        name="Alice",
        appearance=spec["identity_anchor"],
        visual_description=json.dumps(spec),
    ))
    db.commit()

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert not payload["checks"]["characters"]["missing_identity_specs"]
    assert payload["checks"]["characters"]["characters"][0]["has_identity_spec"] is True
    assert any(item["code"] == "missing_character_references" for item in payload["blockers"])


def test_production_readiness_reports_spatial_continuity_plan(setup):
    client, db, _ = setup
    from src.services.character_identity_service import CharacterIdentityService

    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.character_name = "Alice"
    scene.visual_description = "Alice hands the sealed letter to Bob across the office table."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    service = CharacterIdentityService()
    for name in ("Alice", "Bob"):
        spec = service.build_identity_spec(name, "lead", project_id=1)
        db.add(Character(
            project_id=1,
            name=name,
            appearance=spec["identity_anchor"],
            visual_description=json.dumps(spec),
        ))
    db.commit()

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    spatial = response.json()["checks"]["spatial_continuity"]
    assert spatial["status"] == "planned"
    assert spatial["scenes"][0]["shot_scale"] == "medium two-shot"
    assert spatial["scenes"][0]["character_positions"] == {"Alice": "frame left", "Bob": "frame right"}


def test_reference_upload_and_signed_media_access(setup):
    client, db, path = setup
    c = client.post("/api/projects/1/characters", json={"name": "Actor"}).json()
    image = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(image, format="PNG")
    response = client.post(f"/api/projects/1/characters/{c['id']}/reference", files={"file": ("../../escape.png", image.getvalue(), "image/png")})
    assert response.status_code == 200, response.text
    assert not (path / "escape.png").exists()
    media = client.get("/api/projects/1/media-url", params={"path": response.json()["image_path"]})
    assert media.status_code == 200, media.text
    assert client.get(media.json()["url"]).headers["content-type"].startswith("image/")
    assert client.get("/api/projects/1/media-url", params={"path": "../outside.txt"}).status_code == 404
    assert client.get("/storage/characters/1/1/reference_1.png").status_code == 404
    expired = create_access_token({"kind": "media", "project_id": 1, "path": response.json()["image_path"]}, timedelta(seconds=-1))
    assert client.get("/api/media", params={"token": expired}).status_code == 401
    assert client.post(f"/api/projects/1/characters/{c['id']}/reference", files={"file": ("bad.png", b"bad", "image/png")}).status_code == 400
