import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.services.parameter_optimizer import ParameterOptimizer
from src.services.production_readiness import ProductionReadinessService
from src.services.prompt_optimizer import OptimizationMode, PromptOptimizer
from src.services.quality_loop import build_quality_loop_plan, scene_number_from_repair_item


def test_vertical_resolution_is_preserved_when_fitting_a_smaller_gpu():
    optimizer = ParameterOptimizer()
    width, height = optimizer._optimize_resolution(4, 768, 1344, {})
    assert width < height
    assert width * height <= 768 * 768
    assert abs(width / height - 768 / 1344) < 0.01
    assert width % 8 == height % 8 == 0


def test_portrait_inside_the_pixel_budget_is_not_squashed_to_a_square():
    assert ParameterOptimizer()._optimize_resolution(8, 768, 1344, {}) == (768, 1344)


@pytest.mark.parametrize("mode", [OptimizationMode.QUALITY, OptimizationMode.BALANCED])
def test_stylized_scene_optimization_keeps_subject_first_and_does_not_force_photo(mode):
    prompt = "Alice with short black hair and a green jacket, watercolor illustration, wide doorway shot"
    result = PromptOptimizer().optimize(prompt, mode)
    assert result.positive_prompt.startswith(prompt)
    assert result.optimization_mode == OptimizationMode.ARTISTIC
    assert "photorealistic" not in result.positive_prompt
    assert "watercolor illustration" in result.positive_prompt
    assert "anime" not in result.negative_prompt


def test_keyframe_dependency_wins_even_if_video_repair_has_higher_priority():
    plan = build_quality_loop_plan({"repair_queue": {"items": [
        {"scene_number": 1, "action": "lower_motion_and_regenerate_video", "stage": "video", "execution": "auto", "priority": "high"},
        {"scene_number": 1, "action": "regenerate_keyframe_with_identity_lock", "stage": "image", "execution": "auto", "priority": "low"},
    ]}}, 5)
    assert [item["action"] for item in plan["selected"]] == ["regenerate_keyframe_with_identity_lock"]
    assert plan["skipped"][0]["reason"] == "keyframe_repair_required"


def test_repair_action_priority_does_not_depend_on_report_filename():
    plan = build_quality_loop_plan({"repair_queue": {"items": [
        {"scene_number": 1, "action": "refine_prompt_composition", "stage": "image", "execution": "auto", "source_report": "aaa.json"},
        {"scene_number": 1, "action": "regenerate_keyframe_with_identity_lock", "stage": "image", "execution": "auto", "source_report": "zzz.json"},
    ]}}, 5)
    assert plan["selected"][0]["action"] == "regenerate_keyframe_with_identity_lock"


@pytest.mark.parametrize("scene_number", [True, False, 1.5, float("nan"), float("inf")])
def test_repair_scene_numbers_cannot_silently_target_a_different_scene(scene_number):
    assert scene_number_from_repair_item({"scene_number": scene_number}) is None


def test_readiness_reports_missing_regional_workflow_before_rendering(monkeypatch):
    monkeypatch.setattr(settings, "COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH", "")
    project = SimpleNamespace(script=json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]}))
    blockers = []
    result = ProductionReadinessService(None)._regional_identity_check(project, [SimpleNamespace(scene_number=1)], blockers)
    assert result["status"] == "blocked"
    assert result["required_character_counts"] == [2]
    assert blockers[0].code == "regional_identity_workflow_missing"


def test_readiness_detects_an_unsupported_cast_count(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "configs/comfyui_workflow_sdxl_regional_two_character.json"
    monkeypatch.setattr(settings, "COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH", str(path))
    project = SimpleNamespace(script=json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob", "Carol"]}]}))
    result = ProductionReadinessService(None)._regional_identity_check(project, [SimpleNamespace(scene_number=1)], [])
    assert result["status"] == "blocked"
    assert "unsupported cast counts" in result["error"]
