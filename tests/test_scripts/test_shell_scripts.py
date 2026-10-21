"""Contract checks for repository shell launchers."""

import os
import subprocess
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_shell_scripts_have_valid_syntax():
    failures = []
    for path in sorted(SCRIPTS.glob("*.sh")):
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.append(f"{path.name}: {result.stderr.strip()}")
    assert failures == []


def test_shell_scripts_are_executable():
    non_executable = [path.name for path in sorted(SCRIPTS.glob("*.sh")) if not os.access(path, os.X_OK)]

    assert non_executable == []
