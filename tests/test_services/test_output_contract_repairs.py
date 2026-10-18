from pathlib import Path

from src.services.repair_plan import build_repair_execution_plan
from src.services.repair_queue import build_repair_queue, repair_execution_mode


def test_output_contract_failure_creates_setup_repair():
    queue = build_repair_queue(
        {
            "status": "needs_review",
            "error": "Video output contract failed: Requested 1080p but output short edge is 720px.",
            "candidates": [],
        },
        "video",
    )
    assert queue[0]["action"] == "fix_video_output_contract"
    assert repair_execution_mode(queue[0]["action"]) == "setup_required"


def test_output_contract_repair_plan_points_to_provider_validation(tmp_path):
    plan = build_repair_execution_plan(
        Path(tmp_path),
        [{
            "action": "fix_video_output_contract",
            "stage": "workflow",
            "execution": "setup_required",
            "reason": "model drift",
            "recommendation": "Fix provider settings",
        }],
    )
    assert plan["setup_required"][0]["parameter_hints"]["verify_native_audio"] is True
    assert any("validate_seedance_gateway" in command for command in plan["rerun_validation_commands"])
