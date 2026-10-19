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
        output: Path | None = None
        try:
            if not source.is_file():
                raise ImagePostprocessError(f"Input image does not exist: {source}")
            report["input_sha256"] = file_hash(source)
            with Image.open(source) as image:
                input_size = image.size
            report["input_size"] = list(input_size)
            if not self.command.strip():
                if self.required:
                    raise ImagePostprocessError("GENERATION_IMAGE_POSTPROCESS_COMMAND is required but not configured")
                write_report(report_file, report)
                return report

            output = source.with_name(f"{source.stem}.postprocessed-{uuid.uuid4().hex[:8]}{source.suffix}")
            command = self._build_command(
                source,
                output,
                prompt=prompt,
                negative_prompt=negative_prompt,
                reference_image=reference_image,
            )
            started = time.monotonic()
            result = subprocess.run(
                command if os.name == "nt" else shlex.split(command),
                shell=False,
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
            with Image.open(output) as image:
                output_size = image.size
            report["output_size"] = list(output_size)
            if output_size[0] < input_size[0] or output_size[1] < input_size[1]:
                raise ImagePostprocessError("Image postprocess reduced the accepted image resolution")
            if abs((output_size[0] / output_size[1]) / (input_size[0] / input_size[1]) - 1.0) > 0.01:
                raise ImagePostprocessError("Image postprocess changed the accepted framing aspect ratio")
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
        finally:
            if output is not None and output != source:
                output.unlink(missing_ok=True)
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
        return re.sub(
            r"\{(input|output|prompt|negative_prompt|reference)\}",
            lambda match: _shell_quote(str(replacements[match.group(1)])),
            self.command,
        )

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
