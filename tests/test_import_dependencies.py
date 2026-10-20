"""Every third-party import in src/ must be declared as required, optional, or transitive."""

import ast
import re
import sys
from pathlib import Path

from setuptools.config.pyprojecttoml import read_configuration

ROOT = Path(__file__).resolve().parents[1]

# import name -> (distribution, kind)
IMPORTS = {
    "GPUtil": ("gputil", "optional"),
    "PIL": ("Pillow", "required"),
    "bcrypt": ("bcrypt", "transitive"),  # pulled in by passlib[bcrypt]
    "celery": ("celery", "required"),
    "cv2": ("opencv-python", "required"),
    "diffusers": ("diffusers", "required"),
    "dotenv": ("python-dotenv", "required"),
    "fastapi": ("fastapi", "required"),
    "faster_whisper": ("faster-whisper", "optional"),
    "httpx": ("httpx", "required"),
    "jose": ("python-jose", "required"),
    "kombu": ("kombu", "transitive"),  # celery dependency
    "llama_cpp": ("llama-cpp-python", "required"),
    "loguru": ("loguru", "required"),
    "numpy": ("numpy", "required"),
    "openai": ("openai", "optional"),
    "prometheus_client": ("prometheus-client", "required"),
    "psutil": ("psutil", "required"),
    "pydantic": ("pydantic", "required"),
    "pydantic_settings": ("pydantic-settings", "required"),
    "redis": ("redis", "required"),
    "sqlalchemy": ("SQLAlchemy", "required"),
    "starlette": ("starlette", "transitive"),  # fastapi dependency
    "torch": ("torch", "required"),
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _requirement_name(line: str) -> str:
    return re.split(r"[<>=!~\[;\s]", line.strip(), 1)[0]


def _requirements() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {
        _normalize(_requirement_name(line))
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    }


def _extras() -> set[str]:
    config = read_configuration(ROOT / "pyproject.toml")
    grouped = config["project"]["optional-dependencies"]
    return {
        _normalize(_requirement_name(requirement))
        for requirements in grouped.values()
        for requirement in requirements
    }


def _imported_modules() -> set[str]:
    stdlib = set(sys.stdlib_module_names)
    modules: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".", 1)[0])
    return {
        module
        for module in modules
        if module not in stdlib and module not in {"src", "scripts"}
    }


def test_import_inventory_matches_the_reviewed_list():
    assert _imported_modules() == set(IMPORTS)


def test_required_and_optional_imports_are_declared():
    required = _requirements()
    optional = _extras()
    for module, (distribution, kind) in IMPORTS.items():
        normalized = _normalize(distribution)
        if kind == "required":
            assert normalized in required, f"{module} needs {distribution} in requirements.txt"
        elif kind == "optional":
            assert normalized in optional, f"{module} needs an optional extra for {distribution}"
