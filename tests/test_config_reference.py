"""Keep the generated configuration reference in sync with Settings."""

from pathlib import Path

from scripts.generate_config_reference import build_document, OUTPUT_PATH


def test_configuration_reference_is_current():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == build_document()


def test_reserved_settings_are_marked_in_reference():
    text = Path("docs/configuration-reference.md").read_text(encoding="utf-8")

    assert "`FACE_DETAILER_ENABLED` | `bool` | `False`（预留，当前代码未读取）" in text
    assert "`GPU_MEMORY_FRACTION` | `float` | `0.95`（预留，当前代码未读取）" in text
    assert "`ENABLE_GPU_CACHE_CLEAR` | `bool` | `True`（预留" not in text
    assert "`FACEID_WEIGHT` | `float` | `0.85`（预留" not in text
