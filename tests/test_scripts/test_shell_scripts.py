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


def test_comfyui_launcher_reports_missing_directory(tmp_path):
    env = os.environ.copy()
    env["COMFYUI_DIR"] = str(tmp_path / "missing-comfyui")

    result = subprocess.run(
        ["bash", str(SCRIPTS / "start_comfyui.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=SCRIPTS.parent,
    )

    assert result.returncode == 1
    assert "未找到 ComfyUI 目录" in result.stdout
