import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.database.models import LocalizationJob, LocalizationJobStatus, LocalizationStage, Project, SourceVideo, User
from src.services.asr_service import ASRResult, ASRSegment
from src.services.localization_pipeline import LocalizationPipeline


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'localization.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_run_asr_stores_transcript_path(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.localization_pipeline.settings.STORAGE_PATH", str(tmp_path / "storage"))

    user = User(username="asr-user", email="asr@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    project = Project(name="source project", user_id=user.id)
    db_session.add(project)
    db_session.commit()

    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"fake-video")
    source_video = SourceVideo(
        project_id=project.id,
        original_filename="source.mp4",
        file_path=str(video_path),
    )
    db_session.add(source_video)
    db_session.commit()

    job = LocalizationJob(
        source_video_id=source_video.id,
        target_languages=json.dumps(["en"]),
        status=LocalizationJobStatus.QUEUED,
        current_stage=LocalizationStage.UPLOADED,
    )
    db_session.add(job)
    db_session.commit()

    def fake_transcribe_video(_self, input_video_path, output_dir):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        transcript = out / "transcript.json"
        srt = out / "transcript.zh.srt"
        transcript.write_text("{}", encoding="utf-8")
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        assert input_video_path == str(video_path)
        return ASRResult(
            audio_path=str(out / "source.wav"),
            transcript_json_path=str(transcript),
            srt_path=str(srt),
            language="zh",
            segments=[ASRSegment(start=0.0, end=1.0, text="你好")],
        )

    monkeypatch.setattr("src.services.localization_pipeline.LocalASRService.transcribe_video", fake_transcribe_video)

    srt_path = LocalizationPipeline(db_session).run_asr(job)

    db_session.refresh(job)
    assert job.transcript_path.endswith("transcript.json")
    assert srt_path.endswith("transcript.zh.srt")
