"""Resolve image workflow stages from graph edges, independent of JSON order."""

from __future__ import annotations

import hashlib
from typing import Any


class ImageWorkflowGraphError(ValueError):
    pass


class ImageWorkflowGraph:
    def __init__(self, nodes: dict[str, dict[str, Any]]):
        self.nodes = nodes

    def link(self, value: Any) -> str | None:
        if (
            isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and value[0] in self.nodes
            and isinstance(value[1], int) and not isinstance(value[1], bool)
        ):
            return value[0]
        return None

    def ancestors(self, node_id: str) -> set[str]:
        visited: set[str] = set()
        pending = [node_id]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(
                ref for value in self.nodes[current].get("inputs", {}).values()
                if (ref := self.link(value)) is not None
            )
        return visited

    def output_node(self, preferred: str | None = None) -> str:
        outputs = {
            key: self.link(node.get("inputs", {}).get("images"))
            for key, node in self.nodes.items() if node.get("class_type") == "SaveImage"
        }
        if preferred:
            if preferred not in outputs or outputs[preferred] is None:
                raise ImageWorkflowGraphError("Configured output_node must be a connected SaveImage node")
            return preferred
        if len(outputs) == 1:
            return next(iter(outputs))
        anchors = {}
        for key, producer in outputs.items():
            node = self.nodes.get(producer, {})
            anchors[key] = (
                self.link(node.get("inputs", {}).get("samples"))
                if node.get("class_type") in {"VAEDecode", "VAEDecodeTiled"} else producer
            )
        # A base preview is superseded when its producer feeds a later image pass.
        final_outputs = [
            key for key, producer in anchors.items() if producer is not None
            and not any(
                producer != other and other is not None and producer in self.ancestors(other)
                for other in anchors.values()
            )
        ]
        if len(final_outputs) != 1:
            raise ImageWorkflowGraphError(
                "Workflow has ambiguous image outputs; set parameters.default.output_node"
            )
        return final_outputs[0]

    def base_sampler(self, output_node: str) -> str:
        active = self.ancestors(output_node)
        samplers = {key for key in active if self.nodes[key].get("class_type") == "KSampler"}
        base = [key for key in samplers if not ((self.ancestors(key) - {key}) & samplers)]
        if len(base) != 1:
            raise ImageWorkflowGraphError("Final image must depend on one base KSampler")
        return base[0]

    def prompt_nodes(self, sampler_id: str, role: str) -> set[str]:
        start = self.link(self.nodes[sampler_id].get("inputs", {}).get(role))
        if start is None:
            raise ImageWorkflowGraphError(f"Missing {role} conditioning link")
        pending = [start]
        visited: set[str] = set()
        text_nodes: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            node = self.nodes[current]
            if node.get("class_type") == "CLIPTextEncode":
                text_nodes.add(current)
                continue
            inputs = node.get("inputs", {})
            # ControlNetApplyAdvanced has both roles; do not walk into the other one.
            keys = [role] if role in inputs else [
                key for key in inputs if key.startswith("conditioning")
            ]
            pending.extend(ref for key in keys if (ref := self.link(inputs[key])) is not None)
        if not text_nodes:
            raise ImageWorkflowGraphError(f"Unsupported {role} conditioning graph; use CLIPTextEncode")
        return text_nodes

    def reference_binding(self, sampler_id: str) -> tuple[str, str]:
        active = self.model_ancestors(sampler_id)
        adapters = [key for key in active if self.nodes[key].get("class_type") in {
            "IPAdapterFaceID", "IPAdapterAdvanced",
        }]
        if len(adapters) != 1:
            raise ImageWorkflowGraphError(
                "Reference workflow must have one active IPAdapterFaceID or IPAdapterAdvanced; "
                "multi-character workflows need explicit regional reference bindings"
            )
        adapter = adapters[0]
        image = self.link(self.nodes[adapter].get("inputs", {}).get("image"))
        loaders = [key for key in (self.ancestors(image) if image else set())
                   if self.nodes[key].get("class_type") == "LoadImage"]
        if len(loaders) != 1:
            raise ImageWorkflowGraphError("Identity adapter image must depend on one LoadImage node")
        return adapter, loaders[0]

    def model_ancestors(self, sampler_id: str) -> set[str]:
        model = self.link(self.nodes[sampler_id].get("inputs", {}).get("model"))
        if model is None:
            raise ImageWorkflowGraphError("Image sampling stages need an explicit model link")
        return self.ancestors(model)

    def require_identity_stages(self, stages: set[str], adapters: set[str]) -> None:
        for stage in stages:
            if not adapters.issubset(self.model_ancestors(stage)):
                raise ImageWorkflowGraphError(
                    "Every image sampling/detail stage must retain all character identity adapters"
                )


def stage_seed(seed: int, stage_name: str) -> int:
    material = f"{seed}:{stage_name}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2 ** 63)
