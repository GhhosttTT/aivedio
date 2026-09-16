from src.services.shot_complexity_service import ShotComplexityService


def test_simple_shot_is_ok():
    report = ShotComplexityService().diagnose(
        "Alice holds a red letter in an office doorway, medium shot",
        ["Alice"],
    )

    assert report.status == "ok"
    assert report.score < 3
    assert "one frozen instant" in report.prompt_constraint


def test_group_sequential_camera_move_needs_split():
    report = ShotComplexityService().diagnose(
        "Alice enters the room and then sits down while Bob and Cara fight as the camera pans around them",
        ["Alice", "Bob", "Cara"],
    )

    assert report.status == "needs_split"
    assert any("visible characters" in reason for reason in report.reasons)
    assert any("sequential" in reason for reason in report.reasons)
    assert any("camera movement" in reason for reason in report.reasons)
