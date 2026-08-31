"""Isolated UI fixtures. Never uses the production database or real models."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8010)
args = parser.parse_args()
workspace = ROOT / "storage" / "validation" / "ui-server"
workspace.mkdir(parents=True, exist_ok=True)
os.chdir(workspace)
os.environ["DATABASE_URL"] = "sqlite:///./ui-fixtures.db"
os.environ["STORAGE_PATH"] = str(workspace / "storage")
os.environ["JWT_SECRET_KEY"] = "isolated-ui-test-key-not-for-production"
os.environ["ENABLE_DRAFT_FALLBACK"] = "false"

from src.api.auth import hash_password
from src.database.database import engine, SessionLocal
from src.database.models import Base, Project, Scene, Task, User, Character, ProjectStatus, TaskStatus
from src.api.app import create_app
from src.tasks.celery_app import celery_app
from src.services.generation_review import write_report
from src.utils.storage import storage_manager

Base.metadata.create_all(engine)
db = SessionLocal()
if not db.query(User).filter_by(username="ui_validation").first():
    user = User(username="ui_validation", email="ui-validation@example.com", hashed_password=hash_password("local-validation-only"))
    db.add(user)
    db.flush()
    for index, status in enumerate([ProjectStatus.SCRIPT_GENERATED, ProjectStatus.IN_PRODUCTION, ProjectStatus.FAILED, ProjectStatus.COMPLETED]):
        project = Project(name=f"UI 验证夹具 {index + 1}", theme="未拆封的信", outline="林安在办公室发现一封未拆封的信。", user_id=user.id, status=status)
        db.add(project)
        db.flush()
        db.add(Character(project_id=project.id, name="林安", description="办公室职员", appearance="young adult, black hair, gray jacket"))
        scenes = [{"scene_number": i + 1, "description": "桌面上的一封未拆封的信，近景。", "dialogue": "", "characters": []} for i in range(5)]
        project.script = json.dumps({"script": project.outline, "scenes": scenes}, ensure_ascii=False)
        for scene in scenes:
            db.add(Scene(project_id=project.id, scene_number=scene["scene_number"], visual_description=scene["description"], dialogue=""))
        if status != ProjectStatus.SCRIPT_GENERATED:
            task_status = {ProjectStatus.IN_PRODUCTION: TaskStatus.RUNNING, ProjectStatus.FAILED: TaskStatus.FAILED, ProjectStatus.COMPLETED: TaskStatus.COMPLETED}[status]
            db.add(Task(project_id=project.id, celery_task_id=f"ui-fixture-task-{index}", total_steps=23, current_step=23 if status == ProjectStatus.COMPLETED else 21, progress=100 if status == ProjectStatus.COMPLETED else 91.3, status=task_status, error_message="UI fixture: sampled-frame review requires attention" if status == ProjectStatus.FAILED else None))
        root = storage_manager.get_project_path(project.id)
        if status == ProjectStatus.FAILED:
            write_report(root / "reviews" / "scene_1.json", {"status": "needs_review", "average": 2.5, "review": {"composition": {"score": 2, "evidence": "UI fixture: crop excludes the letter"}, "issues": []}})
        if status == ProjectStatus.COMPLETED:
            ffmpeg = shutil.which("ffmpeg") or next((ROOT / "storage" / "validation" / "ffmpeg").rglob("ffmpeg.exe"), None)
            if ffmpeg:
                video = root / "ui-fixture.mp4"
                subprocess.run([str(ffmpeg), "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24", "-t", "3", "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
                project.final_video_path = str(video)
    db.commit()
db.close()
# Unavailable broker is deliberate: exercise the real submission error path quickly.
celery_app.conf.update(broker_url="redis://127.0.0.1:6399/1", broker_connection_timeout=1, task_publish_retry=False, result_backend="cache+memory://")
app = create_app()
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
