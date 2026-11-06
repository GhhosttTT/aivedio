import sys
from unittest.mock import patch

import pytest
from PIL import Image

from src.services.image_postprocess import ImagePostprocessError, ImagePostprocessor


def test_image_postprocess_command_replaces_selected_image(tmp_path):
    image = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(image)
    command = (
        f'"{sys.executable}" -c "from PIL import Image; import sys; '
        'Image.new(\'RGB\', (64, 64), (200, 10, 10)).save(sys.argv[2])" {input} {output}'
    )

    report = ImagePostprocessor(command=command, required=True, timeout=30).process(
        image,
        prompt="commercial short drama close-up",
        negative_prompt="bad crop",
    )

    assert report["status"] == "passed"
    assert report["input_sha256"] != report["final_sha256"]
    with Image.open(image) as result:
        assert result.getpixel((0, 0)) == (200, 10, 10)


def test_required_image_postprocess_blocks_when_unconfigured(tmp_path):
    image = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(image)

    with pytest.raises(ImagePostprocessError, match="not configured"):
        ImagePostprocessor(command="", required=True).process(
            image,
            prompt="prompt",
            negative_prompt="negative",
        )

    report = image.with_suffix(".postprocess.json").read_text(encoding="utf-8")
    assert "failed" in report


def test_optional_image_postprocess_skips_when_unconfigured(tmp_path):
    image = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(image)

    report = ImagePostprocessor(command="", required=False).process(
        image,
        prompt="prompt",
        negative_prompt="negative",
    )

    assert report["status"] == "skipped"


def test_placeholder_like_text_inside_prompt_is_not_expanded_again(tmp_path):
    processor = ImagePostprocessor(command="tool --prompt {prompt} --reference {reference}")
    cmd = processor._build_command(
        tmp_path / "input.png", tmp_path / "output.png",
        prompt="an actor holding a {reference} label", negative_prompt="",
        reference_image="actor.png",
    )
    assert "{reference} label" in cmd
    assert cmd.endswith("actor.png")


def test_failed_image_postprocess_cleans_generated_temporary_output(tmp_path):
    image = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(image)
    command = (
        f'"{sys.executable}" -c "from PIL import Image; import sys; '
        'Image.new(\'RGB\', (64, 64), (200, 10, 10)).save(sys.argv[2]); sys.exit(7)" '
        "{input} {output}"
    )

    report = ImagePostprocessor(command=command, required=False, timeout=30).process(
        image,
        prompt="prompt",
        negative_prompt="negative",
    )

    assert report["status"] == "failed"
    assert not list(tmp_path.glob("scene.postprocessed-*.png"))


def test_explicit_empty_repair_plan_skips_legacy_command(tmp_path):
    image = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(image)

    report = ImagePostprocessor(command="missing-tool {input} {output}").process(
        image,
        prompt="prompt",
        negative_prompt="negative",
        repair_plan=[],
    )

    assert report["status"] == "skipped"
    assert report["reason"] == "no_targeted_repairs"


def test_comfyui_repair_stages_are_chained_and_promoted_atomically(tmp_path, monkeypatch):
    image = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (10, 10, 10)).save(image)
    calls = []

    class FakeClient:
        def close(self):
            pass

    class FakeComfyUIService:
        def __init__(self, **_kwargs):
            self.client = FakeClient()

        def repair_image(self, source_image, **kwargs):
            calls.append((source_image, kwargs))
            color = (100 + len(calls), 20, 20)
            Image.new("RGB", (64, 64), color).save(kwargs["output_path"])
            return kwargs["output_path"]

    monkeypatch.setattr(
        "src.services.image_postprocess.settings.COMFYUI_IMAGE_REPAIR_WORKFLOW_PATH",
        "repair.json",
    )
    with patch("src.services.comfyui_service.ComfyUIService", FakeComfyUIService):
        report = ImagePostprocessor(command="", required=True).process(
            image,
            prompt="same actor",
            negative_prompt="identity drift",
            repair_plan=[
                {"name": "face", "target": "face, eyes", "denoise": 0.2},
                {"name": "hands", "target": "hands, fingers", "denoise": 0.3},
            ],
        )

    assert report["status"] == "passed"
    assert [stage["name"] for stage in report["stages"]] == ["face", "hands"]
    assert calls[0][0] == str(image)
    assert calls[1][0] == calls[0][1]["output_path"]
    assert calls[0][1]["repair_target"] == "face, eyes"
    assert calls[1][1]["repair_target"] == "hands, fingers"
    with Image.open(image) as result:
        assert result.getpixel((0, 0)) == (102, 20, 20)
