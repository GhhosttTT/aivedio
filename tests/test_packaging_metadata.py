"""Keep runtime dependency metadata wired to requirements.txt."""

from pathlib import Path

from setuptools.config.pyprojecttoml import read_configuration

ROOT = Path(__file__).resolve().parents[1]


def _requirements() -> list[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def test_project_dependencies_come_from_requirements():
    config = read_configuration(ROOT / "pyproject.toml")
    assert config["project"]["dependencies"] == _requirements()


def test_requirements_are_not_duplicated():
    requirements = _requirements()
    assert len(requirements) == len(set(requirements))
