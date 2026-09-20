"""Optional production image post-processing for accepted keyframes."""

from __future__ import annotations

import os
import shlex
import subprocess
import time
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
    ) -> dict[str, Any]:
        source = Path(image_path)
        report_file = Path(report_path) if report_path else source.with_suffix(".postprocess.json")
        report = {
            "kind": "image_postprocess",
            "status": "skipped",
            "required": self.required,
            "input_path": str(source),
            "command_configured": bool(self.command.strip()),
        }
        try:
            if not source.is_file():
                raise ImagePostprocessError(f"Input image does not exist: {source}")
            report["input_sha256"] = file_hash(source)
            if not self.command.strip():
                if self.required:
                    raise ImagePostprocessError("GENERATION_IMAGE_POSTPROCESS_COMMAND is required but not configured")
                write_report(report_file, report)
                return report

            output = source.with_name(f"{source.stem}.postprocessed{source.suffix}")
            command = self._build_command(
                source,
                output,
                prompt=prompt,
                negative_prompt=negative_prompt,
                reference_image=reference_image,
            )
            started = time.monotonic()
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            report.update({
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "output_path": str(output),
            })
            if result.returncode != 0:
                raise ImagePostprocessError(f"Image postprocess failed with exit code {result.returncode}")
            self._verify_image(output)
            report["output_sha256"] = file_hash(output)
            if report["output_sha256"] == report["input_sha256"]:
                raise ImagePostprocessError("Image postprocess output is identical to input")
            output.replace(source)
            report["final_sha256"] = file_hash(source)
            report["status"] = "passed"
        except Exception as exc:
            report["status"] = "failed"
            report["error"] = str(exc)
            write_report(report_file, report)
            if self.required:
                raise ImagePostprocessError(str(exc)) from exc
            return report
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
    ) -> str:
        replacements = {
            "input": str(source),
            "output": str(output),
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "reference": reference_image or "",
        }
        command = self.command
        for key, value in replacements.items():
            command = command.replace("{" + key + "}", _shell_quote(str(value)))
        return command

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
