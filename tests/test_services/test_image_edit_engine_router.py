import json
from pathlib import Path

import pytest

from src.services.image_edit_engine_router import ImageEditEngineError, ImageEditEngineRouter


def _registry(tmp_path: Path, engines: list[dict]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"engines": engines}), encoding="utf-8")
    return path


def test_router_prefers_gpu_fit_then_priority(tmp_path):
    for name in ("flux.json", "qwen.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    registry = _registry(tmp_path, [
        {"id": "qwen", "workflow_path": "qwen.json", "tasks": ["identity_edit"], "minimum_vram_gb": 12, "priority": 20},
        {"id": "flux", "workflow_path": "flux.json", "tasks": ["identity_edit"], "minimum_vram_gb": 10, "priority": 10},
    ])
    route = ImageEditEngineRouter(str(registry), vram_budget_gb=12).select("identity_edit")
    assert route.engine_id == "flux"
    assert Path(route.workflow_path) == (tmp_path / "flux.json").resolve()


def test_router_allows_cpu_offload_but_ranks_native_fit_first(tmp_path):
    for name in ("native.json", "offload.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    registry = _registry(tmp_path, [
        {"id": "offload", "workflow_path": "offload.json", "tasks": ["semantic_edit"], "minimum_vram_gb": 16, "cpu_offload": True, "priority": 1},
        {"id": "native", "workflow_path": "native.json", "tasks": ["semantic_edit"], "minimum_vram_gb": 12, "priority": 50},
    ])
    route = ImageEditEngineRouter(str(registry), vram_budget_gb=12, allow_cpu_offload=True).select("semantic_edit")
    assert route.engine_id == "native"


def test_router_rejects_missing_or_over_budget_engine(tmp_path):
    registry = _registry(tmp_path, [
        {"id": "qwen", "workflow_path": "missing.json", "tasks": ["identity_edit"], "minimum_vram_gb": 16, "cpu_offload": False},
    ])
    with pytest.raises(ImageEditEngineError, match="No image-edit engine"):
        ImageEditEngineRouter(str(registry), vram_budget_gb=12).select("identity_edit")


def test_bundled_12gb_registry_resolves_existing_workflows():
    root = Path(__file__).resolve().parents[2]
    router = ImageEditEngineRouter(
        str(root / "configs" / "local_image_edit_engine_registry.12gb.example.json"),
        vram_budget_gb=12,
    )
    routes = router.routes()
    assert {route.family for route in routes} == {"flux_kontext", "qwen_image_edit"}
    assert all(Path(route.workflow_path).is_file() for route in routes)

