from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Base, Project, ProjectStatus, Scene, Task, TaskStatus, User
import src.tasks.audio_tasks as audio_tasks
import src.tasks.composition_tasks as composition_tasks
import src.tasks.image_tasks as image_tasks
import src.tasks.subtitle_tasks as subtitle_tasks
import src.tasks.video_tasks as video_tasks


class FailingImageProvider:
    def generate_image(self, _request):
        raise RuntimeError("image provider unavailable")


def test_generation_tasks_produce_final_video_with_draft_fallbacks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_DRAFT_MEDIA_FALLBACK", "true")
    monkeypatch.setattr(image_tasks, "get_generation_provider", lambda _provider=None: FailingImageProvider())
    monkeypatch.setattr(video_tasks, "get_svd_service", lambda: (_ for _ in ()).throw(RuntimeError("svd unavailable")))
    monkeypatch.setattr(audio_tasks, "get_tts_service", lambda: (_ for _ in ()).throw(RuntimeError("tts unavailable")))

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def get_test_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    for module in [image_tasks, video_tasks, audio_tasks, subtitle_tasks, composition_tasks]:
        monkeypatch.setattr(module, "get_db", get_test_db)

    session = TestingSession()
    user = User(username="smoke", email="smoke@example.com", hashed_password="x")
    session.add(user)
    session.commit()
    project = Project(name="draft-smoke", user_id=user.id, status=ProjectStatus.SCRIPT_GENERATED)
    session.add(project)
    session.commit()
    scene = Scene(
        project_id=project.id,
        scene_number=1,
        visual_description="hero in upper realm",
        image_prompt="hero in upper realm",
        dialogue="上界来人了，他是仙尊。",
        character_name="hero",
    )
    session.add(scene)
    session.commit()
    task = Task(project_id=project.id, celery_task_id="smoke", status=TaskStatus.RUNNING, total_steps=5)
    session.add(task)
    session.commit()
    scene_id, project_id, task_id = scene.id, project.id, task.id
    session.close()

    steps = [
        image_tasks.generate_image_task.apply(args=(scene_id, "hero in upper realm", project_id, task_id)),
        video_tasks.generate_video_task.apply(args=(scene_id, project_id, task_id)),
        audio_tasks.generate_audio_task.apply(args=(scene_id, "上界来人了，他是仙尊。", "hero", project_id, task_id)),
        subtitle_tasks.generate_subtitle_task.apply(args=(scene_id, project_id, task_id)),
        composition_tasks.compose_final_video_task.apply(args=(project_id, task_id)),
    ]

    for step in steps:
        assert not step.failed(), step.result

    final_path = Path(steps[-1].result["final_video_path"])
    assert final_path.exists()
    assert final_path.stat().st_size > 0
