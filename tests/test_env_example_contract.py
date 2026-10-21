"""Keep .env.example limited to Settings fields or known runtime-only keys."""

import re
from pathlib import Path

from src.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# Read directly by scripts or provider adapters rather than the Settings model.
RUNTIME_ONLY_KEYS = {
    "DEFAULT_ADMIN_EMAIL",
    "DEFAULT_ADMIN_PASSWORD",
    "DEFAULT_ADMIN_USERNAME",
    "ENCRYPTION_KEY",
    "ENABLE_DRAFT_MEDIA_FALLBACK",
    "HTTP_VIDEO_IDEMPOTENCY_ENABLED",
    "HTTP_VIDEO_IDEMPOTENCY_KEY_HEADER",
    "HTTP_VIDEO_VALIDATE_OUTPUT",
    "SDXL_MODEL_PATH",
    "SEEDANCE_IDEMPOTENCY_ENABLED",
    "SEEDANCE_IDEMPOTENCY_KEY_HEADER",
}


def _example_keys() -> set[str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))


def test_env_example_has_no_unknown_variables():
    extras = _example_keys() - set(Settings.model_fields)
    assert extras == RUNTIME_ONLY_KEYS
