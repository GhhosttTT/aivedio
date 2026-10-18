import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, ProjectStatus, Scene, Task, TaskStatus, User
from src.tasks import draft_tasks


def test_finalize_draft_generation_keeps_project_unpublished(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    user = User(username="draft-user", email="draft@example.com", hashed_password="x")
    session.add(user)
    session.commit()
    project = Project(name="draft-project", user_id=user.id, status=ProjectStatus.IN_PRODUCTION)
    session.add(project)
    session.commit()
    scene_video = tmp_path / "scene.mp4"
    scene_video.write_bytes(b"draft-video")
    scene = Scene(project_id=project.id, scene_number=1, visual_description="A shot", video_path=str(scene_video))
    task = Task(project_id=project.id, celery_task_id="draft-task", status=TaskStatus.RUNNING, total_steps=2)
    session.add_all([scene, task])
    session.commit()
    provider_path = scene_video.with_suffix(".provider.json")
    provider_path.write_text(json.dumps({"provider_task_id": "draft-remote", "requested_draft": True}), encoding="utf-8")
    project_id, task_id = project.id, task.id
    session.close()

    monkeypatch.setattr(draft_tasks, "get_db", lambda: iter((session_factory(),)))
    monkeypatch.setattr(draft_tasks.storage_manager, "get_project_path", lambda _id: Path(tmp_path))

    result = draft_tasks.finalize_draft_generation_task.run(project_id, task_id)

    check = session_factory()
    saved_project = check.get(Project, project_id)
    saved_task = check.get(Task, task_id)
    assert result["status"] == "draft_ready"
    assert saved_project.status == ProjectStatus.SCRIPT_GENERATED
    assert saved_project.final_video_path is None
    assert saved_task.status == TaskStatus.COMPLETED
    assert Path(saved_task.result_path).is_file()
    report = json.loads(Path(saved_task.result_path).read_text(encoding="utf-8"))
    assert report["publishable"] is False
    assert report["scenes"][0]["provider_task_id"] == "draft-remote"
    check.close()
