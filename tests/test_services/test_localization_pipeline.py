import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.database.models import LocalizationJob, LocalizationJobStatus, LocalizationStage, Project, SourceVideo, User
from src.config import settings
from src.services.asr_service import ASRResult, ASRSegment
from src.services.localization_pipeline import LocalizationPipeline
from src.services.translation_service import TranslationResult


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


def test_run_translation_stores_translated_subtitle_dir(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.localization_pipeline.settings.STORAGE_PATH", str(tmp_path / "storage"))

    user = User(username="translate-user", email="translate@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    project = Project(name="translate project", user_id=user.id)
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

    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps({"segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    job = LocalizationJob(
        source_video_id=source_video.id,
        target_languages=json.dumps(["en", "es"]),
        status=LocalizationJobStatus.QUEUED,
        current_stage=LocalizationStage.UPLOADED,
        transcript_path=str(transcript),
    )
    db_session.add(job)
    db_session.commit()

    def fake_translate_transcript(_self, transcript_path, target_languages, output_dir):
        assert transcript_path == str(transcript)
        assert target_languages == ["en", "es"]
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return {
            language: TranslationResult(
                language=language,
                json_path=str(Path(output_dir) / f"{language}.json"),
                srt_path=str(Path(output_dir) / f"{language}.srt"),
                segments=[ASRSegment(start=0.0, end=1.0, text="hello")],
            )
            for language in target_languages
        }

    monkeypatch.setattr(
        "src.services.localization_pipeline.SubtitleTranslationService.translate_transcript",
        fake_translate_transcript,
    )

    output_dir = LocalizationPipeline(db_session).run_translation(job)

    db_session.refresh(job)
    assert job.translated_subtitle_dir == output_dir
    assert output_dir.endswith("translations")


def test_run_rendering_stores_rendered_video_dir(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.localization_pipeline.settings.STORAGE_PATH", str(tmp_path / "storage"))

    user = User(username="render-user", email="render@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    project = Project(name="render project", user_id=user.id)
    db_session.add(project)
    db_session.commit()

    clean_video = tmp_path / "clean.mp4"
    clean_video.write_bytes(b"fake-video")
    source_video = SourceVideo(
        project_id=project.id,
        original_filename="source.mp4",
        file_path=str(tmp_path / "source.mp4"),
        clean_video_path=str(clean_video),
    )
    db_session.add(source_video)
    db_session.commit()

    translated_dir = tmp_path / "translations"
    translated_dir.mkdir()
    job = LocalizationJob(
        source_video_id=source_video.id,
        target_languages=json.dumps(["en"]),
        status=LocalizationJobStatus.QUEUED,
        current_stage=LocalizationStage.UPLOADED,
        translated_subtitle_dir=str(translated_dir),
    )
    db_session.add(job)
    db_session.commit()

    def fake_render_all(_self, clean_video_path, translated_subtitle_dir, output_dir, target_languages):
        assert clean_video_path == str(clean_video)
        assert translated_subtitle_dir == str(translated_dir)
        assert target_languages == ["en"]
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return {}

    monkeypatch.setattr(
        "src.services.localization_pipeline.SubtitleRenderingService.render_all",
        fake_render_all,
    )

    output_dir = LocalizationPipeline(db_session).run_rendering(job)

    db_session.refresh(job)
    assert job.rendered_video_dir == output_dir
    assert output_dir.endswith("rendered")


def test_run_moderation_writes_quality_report(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("src.services.localization_pipeline.settings.STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr("src.services.localization_quality_service.settings.TRANSLATION_BACKEND", "command")

    user = User(username="qa-user", email="qa@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    project = Project(name="qa project", user_id=user.id)
    db_session.add(project)
    db_session.commit()

    source_video = SourceVideo(
        project_id=project.id,
        original_filename="source.mp4",
        file_path=str(tmp_path / "source.mp4"),
    )
    db_session.add(source_video)
    db_session.commit()

    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.0,
                        "text": "\u4e0a\u754c\u6765\u4eba\u4e86",
                        "source": "ocr",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    translated_dir = tmp_path / "translations"
    translated_dir.mkdir()
    (translated_dir / "en.json").write_text(
        json.dumps({"segments": [{"start": 0.0, "end": 2.0, "text": "Someone came from the upper realm."}]}),
        encoding="utf-8",
    )

    job = LocalizationJob(
        source_video_id=source_video.id,
        target_languages=json.dumps(["en"]),
        status=LocalizationJobStatus.QUEUED,
        current_stage=LocalizationStage.UPLOADED,
        transcript_path=str(transcript),
        translated_subtitle_dir=str(translated_dir),
    )
    db_session.add(job)
    db_session.commit()

    report_path = LocalizationPipeline(db_session).run_moderation(job)

    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["source_summary"]["segments"] == 1
    assert job.moderation_report_path == report_path


class _FakeDb:
    def __init__(self):
        self.project = type("ProjectStub", (), {"id": 7})()
        self.added = []

    def query(self, _model):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.project

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass

    def refresh(self, item):
        item.id = 1


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


def test_source_video_upload_uses_unique_atomic_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    db = _FakeDb()
    pipeline = LocalizationPipeline(db)

    first = pipeline.save_source_video(7, _upload("../episode.mp4", b"first"))
    second = pipeline.save_source_video(7, _upload("episode.mp4", b"second"))

    assert first.original_filename == "episode.mp4"
    assert second.original_filename == "episode.mp4"
    assert first.file_path != second.file_path
    assert first.file_path.endswith(".mp4")
    assert Path(first.file_path).read_bytes() == b"first"
    assert Path(second.file_path).read_bytes() == b"second"
    assert not list((tmp_path / "project_7" / "source_videos").glob("*.part"))


def test_source_video_upload_rejects_empty_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))

    with pytest.raises(ValueError, match="cannot be empty"):
        LocalizationPipeline(_FakeDb()).save_source_video(7, _upload("empty.mp4", b""))


def test_source_video_upload_enforces_configured_size_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "LOCALIZATION_MAX_SOURCE_VIDEO_SIZE_MB", 1)

    with pytest.raises(ValueError, match="upload limit"):
        LocalizationPipeline(_FakeDb()).save_source_video(
            7,
            _upload("large.mp4", b"x" * (1024 * 1024 + 1)),
        )

    assert not list((tmp_path / "project_7" / "source_videos").glob("*"))


def test_run_rendering_produces_localized_videos(db_session, tmp_path, monkeypatch):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")

    monkeypatch.setattr("src.services.localization_pipeline.settings.STORAGE_PATH", str(tmp_path / "storage"))
    user = User(username="render-user", email="render@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    project = Project(name="render project", user_id=user.id)
    db_session.add(project)
    db_session.commit()

    video_path = tmp_path / "clean.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(video_path),
        ],
        check=True,
    )
    source_video = SourceVideo(
        project_id=project.id,
        original_filename="clean.mp4",
        file_path=str(video_path),
        clean_video_path=str(video_path),
    )
    db_session.add(source_video)
    db_session.commit()

    subtitles = tmp_path / "subtitles"
    subtitles.mkdir()
    (subtitles / "en.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,200\nHello\n", encoding="utf-8"
    )
    job = LocalizationJob(
        source_video_id=source_video.id,
        target_languages=json.dumps(["en"]),
        translated_subtitle_dir=str(subtitles),
    )
    db_session.add(job)
    db_session.commit()

    output_dir = LocalizationPipeline(db_session).run_rendering(job)

    assert Path(output_dir) == (
        tmp_path / "storage" / f"project_{project.id}" / "localization" / f"job_{job.id}" / "rendered"
    )
    assert (Path(output_dir) / "en.mp4").is_file()
    assert (Path(output_dir) / "rendered_videos.json").is_file()
    assert job.rendered_video_dir == output_dir
