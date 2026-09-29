from src.services.video_quality_metrics import video_technical_score


def test_video_technical_score_prefers_readable_motion_and_sharpness():
    weak = video_technical_score({
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 0.2,
        "sharpness": 2.0,
        "brightness": 40.0,
        "brightness_variance": 900.0,
    })
    strong = video_technical_score({
        "duration_seconds": 3.0,
        "width": 768,
        "height": 1344,
        "fps": 24,
        "sampled_frames": 8,
        "motion_energy": 10.0,
        "sharpness": 80.0,
        "brightness": 128.0,
        "brightness_variance": 12.0,
    })

    assert strong > weak
    assert strong >= 4.0
    assert weak < 3.0
