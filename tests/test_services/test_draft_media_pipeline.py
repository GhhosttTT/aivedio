from pathlib import Path

from src.services.draft_media_service import get_draft_media_service
from src.services.subtitle_generator import SubtitleGenerator
from src.services.video_composer import VideoComposer


def test_draft_media_pipeline_produces_playable_final_video(tmp_path):
    service = get_draft_media_service()

    image_path = service.generate_image(
        prompt="A short drama hero arrives in the upper realm",
        output_path=str(tmp_path / "scene.png"),
        scene_number=1,
    )
    audio_path, duration = service.generate_silent_audio(
        text="上界来人了，他是仙尊。",
        output_path=str(tmp_path / "scene.wav"),
    )
    video_path = service.generate_video_from_image(
        image_path=image_path,
        output_path=str(tmp_path / "scene.mp4"),
        duration=duration,
    )

    subtitle_generator = SubtitleGenerator()
    subtitle_path = subtitle_generator.generate_srt(
        dialogues=[
            {
                "text": "Upper realm visitors have arrived.",
                "start_time": 0.0,
                "duration": duration,
            }
        ],
        output_path=str(tmp_path / "scene.srt"),
    )
    subtitled_path = subtitle_generator.burn_subtitle(
        video_path=video_path,
        subtitle_path=subtitle_path,
        output_path=str(tmp_path / "scene_subtitled.mp4"),
    )
    final_path = VideoComposer().sync_audio_video(
        video_path=subtitled_path,
        audio_path=audio_path,
        output_path=str(tmp_path / "final.mp4"),
    )

    final = Path(final_path)
    assert final.exists()
    assert final.stat().st_size > 0
