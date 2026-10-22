"""Every CLI helper should support --help without touching runtime state."""

import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPTS = [
    "cleanup_old_files.py",
    "compare_video_baseline.py",
    "init_database.py",
    "ocr_subtitles.py",
    "recover_stale_tasks.py",
    "serve_ui_validation.py",
]


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_help_exits_zero(script):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / script), "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
