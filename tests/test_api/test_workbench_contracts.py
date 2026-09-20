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
    assert payload["checks"]["visual_format"]["status"] == "not_vertical"
    assert any(item["code"] == "too_few_atomic_scenes" for item in payload["blockers"])
    assert any(item["code"] == "image_review_not_required" for item in payload["warnings"])
    assert any(item["code"] == "non_mobile_short_drama_format" for item in payload["warnings"])
    assert any(item["code"] == "workflow_profile_not_ready" for item in payload["blockers"])
    assert any(item["code"] == "missing_visual_style_asset_pack" for item in payload["blockers"])
    assert "video_engine" not in payload["checks"]


def test_visual_style_freeze_clears_readiness_visual_style_blocker(setup):
    client, _, _ = setup

    before = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert before["checks"]["visual_style"]["status"] == "missing"
    assert any(item["code"] == "missing_visual_style_asset_pack" for item in before["blockers"])

    frozen = client.post(
        "/api/projects/1/freeze-visual-style",
        json={
            "style_prompt": "consistent premium red-and-teal short drama look",
            "negative_prompt": "random color grade",
            "notes": "approved look bible",
        },
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"
    assert frozen.json()["asset_pack"]["style_prompt"] == "consistent premium red-and-teal short drama look"

    after = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert after["checks"]["visual_style"]["status"] == "valid"
    assert not any(item["code"] == "missing_visual_style_asset_pack" for item in after["blockers"])


def test_workflow_profile_freeze_clears_readiness_workflow_profile_blocker(setup, monkeypatch):
    client, _, path = setup
    image = path / "image_workflow.json"
    video = path / "video_workflow.json"
    profile = path / "production_workflow_profile.json"
    image.write_text('{"1":{"class_type":"KSampler"}}', encoding="utf-8")
    video.write_text('{"1":{"class_type":"VHS_VideoCombine"}}', encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_PRODUCTION_PROFILE_PATH", str(profile))

    before = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert before["checks"]["workflow_profile"]["status"] == "missing"
    assert any(item["code"] == "workflow_profile_not_ready" for item in before["blockers"])

    frozen = client.post("/api/projects/workflow-profile/freeze", json={"notes": "approved"})
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "approved"

    after = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert after["checks"]["workflow_profile"]["status"] == "valid"
    assert not any(item["code"] == "workflow_profile_not_ready" for item in after["blockers"])


def test_production_readiness_accepts_vertical_mobile_format(setup, monkeypatch):
    client, _, _ = setup
    monkeypatch.setattr("src.services.production_readiness.settings.GENERATION_WIDTH", 768)
    monkeypatch.setattr("src.services.production_readiness.settings.GENERATION_HEIGHT", 1344)

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["checks"]["visual_format"]["status"] == "mobile_short_drama"
    assert not any(item["code"] == "non_mobile_short_drama_format" for item in payload["warnings"])


def test_production_readiness_reports_weak_story_rhythm(setup):
    client, db, _ = setup
    project = db.query(Project).filter(Project.id == 1).one()
    db.query(Scene).filter(Scene.project_id == 1).delete()
    for index in range(1, 5):
        db.add(Scene(
            project_id=1,
            scene_number=index,
            visual_description=f"A calm room with people standing quietly scene {index}",
            dialogue="" if index % 2 else "They talk calmly.",
        ))
    project.script = json.dumps({"scenes": [{"scene_number": index, "characters": []} for index in range(1, 5)]})
    db.commit()

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    rhythm = payload["checks"]["story_rhythm"]
    assert rhythm["status"] in {"warn", "weak"}
    assert {"hook", "escalation", "reversal", "ending_hook"}.issubset(set(rhythm["missing"]))
    story_room = payload["checks"]["story_room"]
    assert story_room["status"] == "weak"
    assert "market_brief" in story_room["missing"]
    assert story_room["rewrite_actions"]
    assert any(item["code"] == "weak_story_rhythm" for item in payload["warnings"])
    assert any(item["code"] == "weak_story_room_quality" for item in payload["warnings"])


def test_production_readiness_requires_real_sample_validation_summary(setup):
    client, _, _ = setup

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["checks"]["sample_validation"]["status"] == "missing"
    assert any(item["code"] == "missing_sample_validation" for item in payload["warnings"])


def test_production_readiness_accepts_passing_sample_validation_summary(setup):
    client, _, path = setup
    validation_dir = path / "storage" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    (validation_dir / "validation_summary.json").write_text(json.dumps({
        "status": "ready_for_seed_dance_candidate",
        "checks": {
            "video_review_passed": True,
            "video_identity_gate_passed": True,
            "video_temporal_gate_passed": True,
            "baseline_comparison_passed": True,
            "manual_review_covers_rendered_cases": True,
            "manual_review_missing_case_ids": [],
            "manual_review_passed": True,
        },
        "action_items": [],
    }), encoding="utf-8")

    response = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False})

    assert response.status_code == 200, response.text
    payload = response.json()
    validation = payload["checks"]["sample_validation"]
    assert validation["status"] == "ready_for_seed_dance_candidate"
    assert validation["checks"]["video_identity_gate_passed"] is True
    assert validation["checks"]["manual_review_covers_rendered_cases"] is True
    assert validation["checks"]["manual_review_missing_case_ids"] == []
    assert not any(item["code"] == "missing_sample_validation" for item in payload["warnings"])
    assert not any(item["code"] == "sample_validation_not_ready" for item in payload["warnings"])


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


def test_character_asset_pack_freeze_clears_readiness_asset_pack_blocker(setup):
    client, db, path = setup
    from src.services.character_identity_service import CharacterIdentityService

    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.character_name = "Alice"
    scene.visual_description = "Alice stands by the table and opens the sealed letter."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice"]}]})
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    character = Character(
        project_id=1,
        name="Alice",
        appearance=spec["identity_anchor"],
        visual_description=json.dumps(spec),
    )
    db.add(character)
    db.commit()
    db.refresh(character)

    image = io.BytesIO()
    Image.new("RGB", (64, 64), "purple").save(image, format="PNG")
    upload = client.post(
        f"/api/projects/1/characters/{character.id}/reference",
        files={"file": ("alice.png", image.getvalue(), "image/png")},
    )
    assert upload.status_code == 200, upload.text

    before = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert "Alice" in before["checks"]["characters"]["missing_asset_packs"]
    assert any(item["code"] == "missing_character_asset_pack" for item in before["blockers"])

    frozen = client.post(f"/api/projects/1/characters/{character.id}/freeze-asset-pack", json={"notes": "approved"})
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"

    after = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert after["checks"]["characters"]["missing_asset_packs"] == []
    assert not any(item["code"] == "missing_character_asset_pack" for item in after["blockers"])


def test_character_turnaround_album_freeze_clears_readiness_blocker(setup):
    client, db, path = setup
    from src.services.character_identity_service import CharacterIdentityService

    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.character_name = "Alice"
    scene.visual_description = "Alice stands by the table and opens the sealed letter."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice"]}]})
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    character = Character(
        project_id=1,
        name="Alice",
        appearance=spec["identity_anchor"],
        visual_description=json.dumps(spec),
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    views = {}
    for view, color in {"front": "red", "side": "green", "back": "blue"}.items():
        image_path = path / f"{view}.png"
        Image.new("RGB", (64, 64), color).save(image_path)
        views[view] = str(image_path)

    before = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert any(item["name"] == "Alice" for item in before["checks"]["characters"]["missing_turnaround_albums"])
    assert any(item["code"] == "missing_character_turnaround_album" for item in before["blockers"])

    frozen = client.post(
        f"/api/projects/1/characters/{character.id}/freeze-turnaround-album",
        json={"views": views, "notes": "approved three-view"},
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"
    assert frozen.json()["album"]["views"]["front"]["path"] == views["front"]

    after = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert after["checks"]["characters"]["missing_turnaround_albums"] == []
    assert not any(item["code"] == "missing_character_turnaround_album" for item in after["blockers"])


def test_generate_turnaround_album_can_freeze_generated_views(setup, monkeypatch):
    client, db, path = setup
    from src.services.character_identity_service import CharacterIdentityService

    class FakeTurnaroundGenerator:
        def generate_turnaround_album(self, **kwargs):
            selected = {}
            for view, color in {"front": "red", "side": "green", "back": "blue"}.items():
                image_path = path / f"generated_{view}.png"
                Image.new("RGB", (64, 64), color).save(image_path)
                selected[view] = str(image_path)
            return {
                "success": True,
                "selected_views": selected,
                "candidate_images": {view: [image] for view, image in selected.items()},
                "quality_reports": {view: {"status": "passed"} for view in selected},
            }

    monkeypatch.setattr("src.api.routes.characters.CharacterReferenceAutoGenerator", FakeTurnaroundGenerator)
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    character = Character(
        project_id=1,
        name="Alice",
        appearance=spec["identity_anchor"],
        visual_description=json.dumps(spec),
    )
    db.add(character)
    db.commit()
    db.refresh(character)

    response = client.post(
        f"/api/projects/1/characters/{character.id}/generate-turnaround-album",
        json={"count_per_view": 2, "freeze_album": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload["selected_views"]) == {"front", "side", "back"}
    assert payload["album"]["status"] == "frozen"
    assert payload["album"]["views"]["side"]["path"].endswith("generated_side.png")


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
    payload = response.json()
    spatial = payload["checks"]["spatial_continuity"]
    assert spatial["status"] == "planned"
    assert spatial["asset_pack"]["status"] == "missing"
    assert any(item["code"] == "missing_spatial_asset_pack" for item in payload["blockers"])
    assert spatial["scenes"][0]["shot_scale"] == "medium two-shot"
    assert spatial["scenes"][0]["character_positions"] == {"Alice": "frame left", "Bob": "frame right"}


def test_spatial_plan_freeze_clears_readiness_spatial_asset_blocker(setup):
    client, db, _ = setup
    project = db.query(Project).filter(Project.id == 1).one()
    scene = db.query(Scene).filter(Scene.project_id == 1).one()
    scene.visual_description = "Alice hands the sealed letter to Bob across the office table."
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    from src.services.character_identity_service import CharacterIdentityService
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

    before = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert before["checks"]["spatial_continuity"]["asset_pack"]["status"] == "missing"
    assert any(item["code"] == "missing_spatial_asset_pack" for item in before["blockers"])

    frozen = client.post("/api/projects/1/freeze-spatial-plan", json={"notes": "approved blocking"})
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"
    assert frozen.json()["asset_pack"]["scenes"][0]["control_references"]["pose_reference_prompt"]

    after = client.get("/api/projects/1/production-readiness", params={"include_engine_preflight": False}).json()
    assert after["checks"]["spatial_continuity"]["asset_pack"]["status"] == "valid"
    assert not any(item["code"] == "missing_spatial_asset_pack" for item in after["blockers"])


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
