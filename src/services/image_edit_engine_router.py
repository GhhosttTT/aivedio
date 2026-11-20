"""Route accepted keyframes to low-VRAM semantic image-edit workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ImageEditEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageEditEngineRoute:
    engine_id: str
    family: str
    workflow_path: str
    output_node: str
    quantization: str
    minimum_vram_gb: float
    cpu_offload: bool
    priority: int
    tasks: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "family": self.family,
            "workflow_path": self.workflow_path,
            "output_node": self.output_node,
            "quantization": self.quantization,
            "minimum_vram_gb": self.minimum_vram_gb,
            "cpu_offload": self.cpu_offload,
            "priority": self.priority,
            "tasks": list(self.tasks),
        }


class ImageEditEngineRouter:
    """Select an installed edit graph without loading it during seed search."""

    def __init__(self, registry_path: str, *, vram_budget_gb: float, allow_cpu_offload: bool = True):
        self.registry_path = Path(registry_path)
        if not self.registry_path.is_absolute():
            self.registry_path = Path.cwd() / self.registry_path
        self.vram_budget_gb = float(vram_budget_gb)
        self.allow_cpu_offload = bool(allow_cpu_offload)

    def select(self, task: str, preferred_engine: str = "auto") -> ImageEditEngineRoute:
        task = str(task or "semantic_edit").strip().lower()
        preferred_engine = str(preferred_engine or "auto").strip().lower()
        candidates = []
        for route in self.routes():
            if task not in route.tasks or not Path(route.workflow_path).is_file():
                continue
            fits_gpu = route.minimum_vram_gb <= self.vram_budget_gb
            if not fits_gpu and not (route.cpu_offload and self.allow_cpu_offload):
                continue
            if preferred_engine != "auto" and route.engine_id.lower() != preferred_engine:
                continue
            candidates.append(route)
        if not candidates:
            preference = "" if preferred_engine == "auto" else f" preferred={preferred_engine}"
            raise ImageEditEngineError(
                f"No image-edit engine can run task={task}{preference} within "
                f"{self.vram_budget_gb:g}GB VRAM"
            )
        return sorted(
            candidates,
            key=lambda item: (
                item.minimum_vram_gb > self.vram_budget_gb,
                item.priority,
                item.minimum_vram_gb,
                item.engine_id,
            ),
        )[0]

    def routes(self) -> list[ImageEditEngineRoute]:
        if not self.registry_path.is_file():
            raise ImageEditEngineError(f"Image-edit registry does not exist: {self.registry_path}")
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ImageEditEngineError(f"Cannot read image-edit registry: {exc}") from exc
        raw_engines = payload.get("engines") if isinstance(payload, dict) else None
        if not isinstance(raw_engines, list):
            raise ImageEditEngineError("Image-edit registry must contain an engines list")
        routes = []
        for raw in raw_engines:
            if not isinstance(raw, dict) or not raw.get("enabled", True):
                continue
            engine_id = str(raw.get("id") or "").strip()
            workflow = str(raw.get("workflow_path") or "").strip()
            tasks = tuple(str(item).strip().lower() for item in raw.get("tasks") or [] if str(item).strip())
            if not engine_id or not workflow or not tasks:
                raise ImageEditEngineError("Each enabled image-edit engine requires id, workflow_path and tasks")
            workflow_path = Path(workflow)
            if not workflow_path.is_absolute():
                workflow_path = self.registry_path.parent / workflow_path
            routes.append(ImageEditEngineRoute(
                engine_id=engine_id,
                family=str(raw.get("family") or engine_id),
                workflow_path=str(workflow_path.resolve()),
                output_node=str(raw.get("output_node") or ""),
                quantization=str(raw.get("quantization") or "unknown"),
                minimum_vram_gb=float(raw.get("minimum_vram_gb") or 0),
                cpu_offload=bool(raw.get("cpu_offload", False)),
                priority=int(raw.get("priority") or 100),
                tasks=tasks,
            ))
        return routes

