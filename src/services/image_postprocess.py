"""Optional production image post-processing for accepted keyframes."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from src.config import settings
from src.services.generation_review import file_hash, write_report


class ImagePostprocessError(RuntimeError):
    pass


class ImagePostprocessor:
    """Run a local face/detail/upscale post-process command on selected images."""

    def __init__(
        self,
        command: str | None = None,
        required: bool | None = None,
        timeout: int | None = None,
    ):
        self.command = settings.GENERATION_IMAGE_POSTPROCESS_COMMAND if command is None else command
        self.required = settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS if required is None else required
        self.timeout = (
            settings.GENERATION_IMAGE_POSTPROCESS_TIMEOUT_SECONDS
            if timeout is None
            else timeout
        )

    def process(
        self,
        image_path: str | Path,
        *,
        prompt: str,
        negative_prompt: str,
        reference_image: str | None = None,
        report_path: str | Path | None = None,
        repair_plan: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source = Path(image_path)
        report_file = Path(report_path) if report_path else source.with_suffix(".postprocess.json")
        stages = self._normalize_repair_plan(repair_plan)
        workflow_configured = bool(
            str(getattr(settings, "COMFYUI_IMAGE_REPAIR_WORKFLOW_PATH", "") or "").strip()
        )
        backend = "command" if self.command.strip() else "comfyui" if workflow_configured else None
        report = {
            "kind": "image_postprocess",
            "status": "skipped",
            "required": self.required,
            "input_path": str(source),
            "command_configured": bool(self.command.strip()),
            "workflow_configured": workflow_configured,
            "backend": backend,
            "repair_plan": stages,
            "stages": [],
        }
        outputs: list[Path] = []
        comfyui = None
        try:
            if not source.is_file():
                raise ImagePostprocessError(f"Input image does not exist: {source}")
            report["input_sha256"] = file_hash(source)
            with Image.open(source) as image:
                input_size = image.size
            report["input_size"] = list(input_size)
            if repair_plan is not None and not stages:
                report["reason"] = "no_targeted_repairs"
                write_report(report_file, report)
                return report
            if backend is None:
                if self.required:
                    raise ImagePostprocessError(
                        "Image postprocess is required but not configured: neither "
                        "GENERATION_IMAGE_POSTPROCESS_COMMAND nor "
                        "COMFYUI_IMAGE_REPAIR_WORKFLOW_PATH is configured"
                    )
                report["reason"] = "postprocess_backend_not_configured"
                write_report(report_file, report)
                return report
            current = source
            for index, stage in enumerate(stages):
                output = source.with_name(
                    f"{source.stem}.postprocessed-{index + 1}-{uuid.uuid4().hex[:8]}{source.suffix}"
                )
                outputs.append(output)
                stage_prompt = self._append_terms(prompt, stage.get("positive_terms"))
                stage_negative = self._append_terms(
                    negative_prompt, stage.get("negative_terms")
                )
                started = time.monotonic()
                stage_report = {
                    "name": stage["name"],
                    "target": stage["target"],
                    "input_path": str(current),
                    "output_path": str(output),
                    "backend": backend,
                    "denoise": stage["denoise"],
                    "steps": stage["steps"],
                    "cfg": stage["cfg"],
                    "seed": stage["seed"],
                    "status": "running",
                }
                report["stages"].append(stage_report)
                if backend == "command":
                    command = self._build_command(
                        current,
                        output,
                        prompt=stage_prompt,
                        negative_prompt=stage_negative,
                        reference_image=reference_image,
                        stage=stage,
                    )
                    result = subprocess.run(
                        command if os.name == "nt" else shlex.split(command),
                        shell=False,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.timeout,
                    )
                    stage_report.update({
                        "command": command,
                        "returncode": result.returncode,
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    })
                    if result.returncode != 0:
                        raise ImagePostprocessError(
                            f"Image postprocess stage {stage['name']} failed with exit code "
                            f"{result.returncode}"
                        )
                else:
                    if comfyui is None:
                        from src.services.comfyui_service import ComfyUIService

                        comfyui = ComfyUIService(timeout=self.timeout)
                    comfyui.repair_image(
                        str(current),
                        output_path=str(output),
                        prompt=stage_prompt,
                        negative_prompt=stage_negative,
                        repair_target=stage["target"],
                        denoise=stage["denoise"],
                        steps=stage["steps"],
                        cfg_scale=stage["cfg"],
                        seed=stage["seed"],
                    )
                stage_report["elapsed_seconds"] = round(time.monotonic() - started, 2)
                self._verify_image(output)
                with Image.open(output) as image:
                    output_size = image.size
                if output_size != input_size:
                    raise ImagePostprocessError(
                        f"Image postprocess stage {stage['name']} changed accepted frame size "
                        f"from {input_size} to {output_size}"
                    )
                stage_report["output_size"] = list(output_size)
                stage_report["input_sha256"] = file_hash(current)
                stage_report["output_sha256"] = file_hash(output)
                if stage_report["output_sha256"] == stage_report["input_sha256"]:
                    raise ImagePostprocessError(
                        f"Image postprocess stage {stage['name']} output is identical to input"
                    )
                stage_report["status"] = "passed"
                current = output

            report["output_size"] = list(input_size)
            report["output_sha256"] = file_hash(current)
            if len(report["stages"]) == 1 and report["stages"][0].get("command"):
                report["command"] = report["stages"][0]["command"]
            current.replace(source)
            report["final_sha256"] = file_hash(source)
            report["status"] = "passed"
        except Exception as exc:
            if report["stages"] and report["stages"][-1].get("status") == "running":
                report["stages"][-1].update(status="failed", error=str(exc))
            report["status"] = "failed"
            report["error"] = str(exc)
            write_report(report_file, report)
            if self.required:
                raise ImagePostprocessError(str(exc)) from exc
            return report
        finally:
            for output in outputs:
                output.unlink(missing_ok=True)
            if comfyui is not None:
                comfyui.client.close()
        write_report(report_file, report)
        return report

    def _build_command(
        self,
        source: Path,
        output: Path,
        *,
        prompt: str,
        negative_prompt: str,
        reference_image: str | None,
        stage: dict[str, Any] | None = None,
    ) -> str:
        stage = stage or {}
        replacements = {
            "input": str(source),
            "output": str(output),
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "reference": reference_image or "",
            "repair_target": stage.get("target", ""),
            "denoise": stage.get("denoise", ""),
            "steps": stage.get("steps", ""),
            "cfg": stage.get("cfg", ""),
            "seed": stage.get("seed", ""),
            "stage": stage.get("name", ""),
        }
        return re.sub(
            r"\{(input|output|prompt|negative_prompt|reference|repair_target|denoise|steps|cfg|seed|stage)\}",
            lambda match: _shell_quote(str(replacements[match.group(1)])),
            self.command,
        )

    @staticmethod
    def _append_terms(value: str, terms: Any) -> str:
        suffix = str(terms or "").strip(" ,")
        return f"{value.strip(' ,')}, {suffix}" if suffix and value.strip(" ,") else suffix or value

    @staticmethod
    def _normalize_repair_plan(
        repair_plan: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if repair_plan is None:
            return [{
                "name": "legacy_postprocess",
                "target": "face, eyes",
                "denoise": float(settings.GENERATION_IMAGE_REPAIR_DEFAULT_DENOISE),
                "steps": int(settings.GENERATION_IMAGE_REPAIR_DEFAULT_STEPS),
                "cfg": float(settings.GENERATION_IMAGE_REPAIR_DEFAULT_CFG),
                "seed": 0,
                "positive_terms": "",
                "negative_terms": "",
            }]
        normalized = []
        seen = set()
        for index, raw in enumerate(repair_plan):
            if not isinstance(raw, dict):
                raise ImagePostprocessError("Image repair plan stages must be objects")
            name = str(raw.get("name") or f"repair_{index + 1}").strip()
            target = str(raw.get("target") or "").strip()
            if not target:
                raise ImagePostprocessError(f"Image repair stage {name} has no target")
            if name in seen:
                continue
            seen.add(name)
            denoise = float(raw.get("denoise", settings.GENERATION_IMAGE_REPAIR_DEFAULT_DENOISE))
            steps = int(raw.get("steps", settings.GENERATION_IMAGE_REPAIR_DEFAULT_STEPS))
            cfg = float(raw.get("cfg", settings.GENERATION_IMAGE_REPAIR_DEFAULT_CFG))
            if not 0.0 < denoise <= 0.6 or steps < 1 or cfg <= 0:
                raise ImagePostprocessError(f"Invalid controls for image repair stage {name}")
            stage_evidence = raw.get("evidence") or []
            if isinstance(stage_evidence, str):
                stage_evidence = [stage_evidence]
            normalized.append({
                "name": name,
                "target": target,
                "denoise": denoise,
                "steps": steps,
                "cfg": cfg,
                "seed": int(raw.get("seed", index)),
                "positive_terms": str(raw.get("positive_terms") or ""),
                "negative_terms": str(raw.get("negative_terms") or ""),
                "evidence": list(stage_evidence),
            })
        return normalized

    @staticmethod
    def _verify_image(path: Path) -> None:
        if not path.is_file():
            raise ImagePostprocessError(f"Image postprocess did not create output: {path}")
        with Image.open(path) as image:
            image.verify()


def _shell_quote(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)
