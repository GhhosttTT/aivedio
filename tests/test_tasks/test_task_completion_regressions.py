from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from celery.app.autoretry import add_autoretry_behaviour
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, ProjectStatus, Task, TaskStatus, User
from src.services.comfyui_service import ComfyUIWaitTimeout
from src.services.generation_review import ReviewError
from src.tasks.celery_app import BaseTask


@pytest.mark.parametrize("error", [ComfyUIWaitTimeout("job may still be active"), ReviewError("face identity failed"), ValueError("split this shot")])
def test_nonretryable_generation_failures_do_not_resubmit_gpu_work(error):
    class ProbeTask(BaseTask):
        name = "retry_probe"

        def run(self):
            raise error

    task = ProbeTask()
    task.retry = Mock(side_effect=AssertionError("must not retry"))
    add_autoretry_behaviour(task)
    with pytest.raises(type(error)):
        task.run()
    task.retry.assert_not_called()


def test_concurrent_success_callbacks_count_every_completed_step(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'progress.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    user = User(username="progress", email="progress@example.com", hashed_password="test")
    db.add(user)
    db.flush()
    project = Project(name="repair", user_id=user.id, status=ProjectStatus.IN_PRODUCTION)
    db.add(project)
    db.flush()
    record = Task(project_id=project.id, celery_task_id="repair", status=TaskStatus.RUNNING, total_steps=12, current_step=0)
    db.add(record)
    db.commit()
    record_id = record.id
    monkeypatch.setattr("src.database.session.get_db_session", lambda: iter([sessions()]))

    def completed(_index):
        task = BaseTask()
        task._production_record = lambda _args, _kwargs, session: session.get(Task, record_id)
        task.on_success({}, "step", (), {})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(completed, range(12)))
    db.expire_all()
    assert db.get(Task, record_id).current_step == 12
    assert db.get(Task, record_id).progress == 100.0
    assert db.get(Task, record_id).status == TaskStatus.COMPLETED
    assert db.get(Project, project.id).status == ProjectStatus.SCRIPT_GENERATED
    db.close()
    engine.dispose()
