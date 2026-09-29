from pathlib import Path
import json
import pytest
from unittest.mock import Mock

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


class FakeDraftMediaService:
    def generate_video_from_image(self, image_path: str, output_path: str, duration: float = 4.0, fps: int = 24) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"draft video")
        return output_path

    def generate_silent_audio(self, output_path: str, duration: float = 1.0, **_kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"draft audio")
        return output_path, duration

    def estimate_dialogue_duration(self, text: str) -> float:
        return 1.0


def test_composition_requires_passed_video_quality_report(tmp_path):
    video = tmp_path / "scene_001.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".quality.json").write_text(json.dumps({
        "status": "needs_review",
        "repair_queue": [{"action": "lower_motion_and_regenerate_video"}],
    }), encoding="utf-8")
    scene = Mock(scene_number=1, video_path=str(video))

    with pytest.raises(ValueError, match="video quality status=needs_review"):
        composition_tasks._require_passed_scene_videos([scene])


def test_composition_accepts_passed_video_quality_report(tmp_path):
    video = tmp_path / "scene_001.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".quality.json").write_text(json.dumps({
        "status": "passed",
        "final_video_review": {
            "status": "passed",
            "average": 4.4,
            "gate_scores": {
                "facial_identity": 4.2,
                "identity_consistency": 4.2,
                "temporal_consistency": 4.1,
            },
            "platform_score": 4.2,
            "video_aesthetic_gate": {"status": "passed"},
            "character_distinctiveness_gate": {"status": "passed"},
            "video_performance_gate": {"status": "passed"},
        },
    }), encoding="utf-8")
    scene = Mock(scene_number=1, video_path=str(video))

    composition_tasks._require_passed_scene_videos([scene])


def test_composition_requires_final_normalized_video_review(tmp_path):
    video = tmp_path / "scene_001.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".quality.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    scene = Mock(scene_number=1, video_path=str(video))

    with pytest.raises(ValueError, match="missing final normalized video review"):
        composition_tasks._require_passed_scene_videos([scene])


def test_composition_blocks_failed_final_normalized_video_gate(tmp_path):
    video = tmp_path / "scene_001.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".quality.json").write_text(json.dumps({
        "status": "passed",
        "final_video_review": {
            "status": "passed",
            "average": 4.4,
            "platform_score": 4.2,
            "video_aesthetic_gate": {"status": "passed"},
            "video_performance_gate": {"status": "needs_review"},
        },
    }), encoding="utf-8")
    scene = Mock(scene_number=1, video_path=str(video))

    with pytest.raises(ValueError, match="final normalized video performance gate failed"):
        composition_tasks._require_passed_scene_videos([scene])


def passed_composition_review():
    return {
        "status": "passed",
        "average": 4.4,
        "batches": [{
            "status": "passed",
            "average": 4.4,
            "platform_score": 4.2,
            "video_aesthetic_gate": {"status": "passed"},
            "character_distinctiveness_gate": {"status": "passed"},
            "video_performance_gate": {"status": "passed"},
            "review": {
                "facial_identity": {"score": 4.2, "evidence": "faces match"},
                "identity_consistency": {"score": 4.2, "evidence": "identity stable"},
                "temporal_consistency": {"score": 4.1, "evidence": "cuts are coherent"},
            },
        }],
    }


def test_final_composed_video_review_payload_tracks_episode_context(tmp_path, monkeypatch):
    captured = {}
    final_video = tmp_path / "final.mp4"
    final_video.write_bytes(b"final video")
    project = Mock(id=7, name="premium-drama")
    scenes = [
        Mock(
            scene_number=1,
            character_name="Alice",
            visual_description="Alice confronts Bob in an office doorway",
            image_prompt="Alice close-up",
            dialogue="你为什么骗我",
            audio_path=str(tmp_path / "scene1.mp3"),
            subtitle_path=str(tmp_path / "scene1.srt"),
        ),
        Mock(
            scene_number=2,
            character_name="Bob",
            visual_description="Bob hides the contract",
            image_prompt="Bob reaction",
            dialogue="我没有选择",
            audio_path=str(tmp_path / "scene2.mp3"),
            subtitle_path=str(tmp_path / "scene2.srt"),
        ),
    ]

    class FakeReviewService:
        def review_video(self, video, payload, report_path, reference=None):
            captured["video"] = video
            captured["payload"] = payload
            captured["report_path"] = report_path
            captured["reference"] = reference
            return passed_composition_review()

    monkeypatch.setattr(composition_tasks, "GenerationReviewService", FakeReviewService)

    report = composition_tasks._review_final_composed_video(project, scenes, str(final_video))

    assert report["path"].endswith(".composition_review.json")
    assert captured["video"] == str(final_video)
    assert captured["report_path"] == final_video.with_suffix(".composition_review.json")
    assert captured["payload"]["scene_number"] == "final_composition"
    assert captured["payload"]["shot_plan"]["shot_role"] == "final_composed_short_drama"
    assert captured["payload"]["platform_aesthetic_contract"]["video_features"]
    assert captured["payload"]["scenes"][0]["has_audio"] is True
    assert captured["payload"]["scenes"][0]["has_subtitle"] is True
    assert {item["name"] for item in captured["payload"]["visible_characters"]} == {"Alice", "Bob"}


def test_final_composed_video_review_blocks_failed_episode_gate(tmp_path, monkeypatch):
    final_video = tmp_path / "final.mp4"
    final_video.write_bytes(b"final video")
    project = Mock(id=7, name="premium-drama")
    scenes = [Mock(
        scene_number=1,
        character_name="Alice",
        visual_description="Alice reacts flatly",
        image_prompt="Alice close-up",
        dialogue="你为什么骗我",
        audio_path=None,
        subtitle_path=None,
    )]
    failed = passed_composition_review()
    failed["batches"][0]["video_performance_gate"] = {"status": "needs_review"}

    class FakeReviewService:
        def review_video(self, *_args, **_kwargs):
            return failed

    monkeypatch.setattr(composition_tasks, "GenerationReviewService", FakeReviewService)

    with pytest.raises(ValueError, match="composition review batch 1 performance gate failed"):
        composition_tasks._review_final_composed_video(project, scenes, str(final_video))
    written = json.loads(final_video.with_suffix(".composition_review.json").read_text(encoding="utf-8"))
    assert written["stage"] == "final_composition"
    assert written["error"] == "composition review batch 1 performance gate failed"
    assert written["repair_queue"][0]["action"] == "regenerate_video_with_performance_direction"
    assert written["repair_queue"][0]["execution"] == "auto"


def test_final_composed_video_review_blocks_episode_style_drift(tmp_path, monkeypatch):
    final_video = tmp_path / "final.mp4"
    final_video.write_bytes(b"final video")
    image = tmp_path / "scene_001.png"
    image.write_bytes(b"image")
    image.with_suffix(".quality.json").write_text(json.dumps({
        "status": "passed",
        "postprocess_review": {
            "status": "passed",
            "platform_aesthetic_gate": {
                "status": "needs_review",
                "scores": {
                    "style_consistency": {"score": 2.0, "evidence": "random color grade versus earlier shots"},
                    "color_grade": {"score": 2.5, "evidence": "cold grade breaks the episode look"},
                    "lighting_quality": {"score": 4.2, "evidence": "usable key light"},
                    "production_polish": {"score": 4.1, "evidence": "clean set"},
                },
                "low": {
                    "style_consistency": {"score": 2.0, "evidence": "random color grade versus earlier shots"},
                },
                "missing": [],
            },
        },
    }), encoding="utf-8")
    project = Mock(id=7, name="premium-drama")
    scenes = [Mock(
        scene_number=3,
        character_name="Alice",
        visual_description="Alice confronts Bob",
        image_prompt="Alice close-up",
        image_path=str(image),
        dialogue="你为什么骗我",
        audio_path=None,
        subtitle_path=None,
    )]

    class FakeReviewService:
        def review_video(self, *_args, **_kwargs):
            return passed_composition_review()

    monkeypatch.setattr(composition_tasks, "GenerationReviewService", FakeReviewService)

    with pytest.raises(ValueError, match="style consistency gate failed"):
        composition_tasks._review_final_composed_video(project, scenes, str(final_video))
    written = json.loads(final_video.with_suffix(".composition_review.json").read_text(encoding="utf-8"))
    assert written["episode_style_consistency_gate"]["status"] == "needs_review"
    assert written["repair_queue"][0]["action"] == "refine_project_style_consistency"
    assert written["repair_queue"][0]["scene_number"] == 3
    assert written["repair_queue"][0]["execution"] == "auto"


def test_draft_tasks_cannot_publish_an_unreviewed_final_video(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_DRAFT_MEDIA_FALLBACK", "true")
    monkeypatch.setattr(image_tasks, "get_generation_provider", lambda _provider=None: FailingImageProvider())
    monkeypatch.setattr(video_tasks, "get_svd_service", lambda: (_ for _ in ()).throw(RuntimeError("svd unavailable")))
    monkeypatch.setattr(audio_tasks, "get_tts_service", lambda: (_ for _ in ()).throw(RuntimeError("tts unavailable")))
    fake_draft = FakeDraftMediaService()
    monkeypatch.setattr(video_tasks, "get_draft_media_service", lambda: fake_draft)
    monkeypatch.setattr(audio_tasks, "get_draft_media_service", lambda: fake_draft)

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
    for task in [image_tasks.generate_image_task, video_tasks.generate_video_task, audio_tasks.generate_audio_task, subtitle_tasks.generate_subtitle_task, composition_tasks.compose_final_video_task]:
        monkeypatch.setattr(task, "update_state", Mock())

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

    image_tasks.generate_image_task.run(scene_id, "hero in upper realm", project_id, task_id)
    video_tasks.generate_video_task.run(scene_id, project_id, task_id)
    audio_tasks.generate_audio_task.run(scene_id, "上界来人了，他是仙尊。", "hero", project_id, task_id)
    subtitle_tasks.generate_subtitle_task.run(scene_id, project_id, task_id)
    with pytest.raises(Exception, match="Missing production story review"):
        composition_tasks.compose_final_video_task.run(project_id, task_id)
    with TestingSession() as session:
        project = session.get(Project, project_id)
        assert project.status == ProjectStatus.FAILED
        assert project.final_video_path is None
        assert session.get(Task, task_id).status == TaskStatus.FAILED
    engine.dispose()
