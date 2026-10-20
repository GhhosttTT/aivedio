"""Keep the generated configuration reference in sync with Settings."""

from scripts.generate_config_reference import build_document, OUTPUT_PATH


def test_configuration_reference_is_current():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == build_document()
