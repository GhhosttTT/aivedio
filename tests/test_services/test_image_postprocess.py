import sys

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
