from pathlib import Path

from src.services.subtitle_rendering_service import SubtitleRenderingService


def test_render_all_writes_per_language_outputs_and_manifest(tmp_path, monkeypatch):
    clean_video = tmp_path / "clean.mp4"
    clean_video.write_bytes(b"fake-video")
    subtitle_dir = tmp_path / "subtitles"
    subtitle_dir.mkdir()
    (subtitle_dir / "en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    (subtitle_dir / "ar.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nمرحبا\n", encoding="utf-8")

    def fake_run(command, check, capture_output, text, timeout):
        output = command[-1]
        Path(output).write_bytes(b"rendered")

        class Completed:
            returncode = 0
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.services.subtitle_rendering_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr("src.services.subtitle_rendering_service.subprocess.run", fake_run)

    results = SubtitleRenderingService().render_all(
        str(clean_video),
        str(subtitle_dir),
        str(tmp_path / "rendered"),
        ["en", "ar"],
    )

    assert set(results) == {"en", "ar"}
    assert Path(results["en"].video_path).exists()
    assert Path(results["ar"].video_path).exists()
    assert (tmp_path / "rendered" / "rendered_videos.json").exists()


def test_subtitle_filter_escapes_windows_drive_path():
    service = SubtitleRenderingService()

    filter_expr = service._build_subtitle_filter("C:/tmp/subtitles/en.srt", "en")

    assert "C\\:" in filter_expr
    assert "force_style=" in filter_expr
