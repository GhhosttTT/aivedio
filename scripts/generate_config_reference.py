#!/usr/bin/env python3
"""Generate docs/configuration-reference.md from the Settings model."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings

SECRET_MARKERS = ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "ENCRYPTION_KEY")
OUTPUT_PATH = ROOT / "docs/configuration-reference.md"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _default_text(name: str, field) -> str:
    if any(marker in name for marker in SECRET_MARKERS):
        return "通过环境变量设置，勿提交"
    default = field.default
    if default is None:
        return "`null`"
    text = str(default)
    return f"`{text}`" if text else '`""`'


def build_document() -> str:
    fields = sorted(Settings.model_fields.items())
    lines = [
        "# 配置项参考",
        "",
        "本文件由 `scripts/generate_config_reference.py` 从 `src/config.py` 自动生成。",
        "完整默认值以 `Settings` 模型为准；`.env.example` 只列出常用项。",
        "",
        "加载优先级：进程环境变量 > `.env` > 代码默认值。",
        "",
        f"共 {len(fields)} 项。",
        "",
        "| 变量 | 类型 | 默认值 |",
        "| --- | --- | --- |",
    ]
    for name, field in fields:
        annotation = field.annotation
        if isinstance(annotation, type):
            annotation_text = annotation.__name__
        else:
            annotation_text = str(annotation).replace("typing.", "")
        lines.append(
            f"| `{name}` | `{_cell(annotation_text)}` | {_cell(_default_text(name, field))} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(build_document(), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(Settings.model_fields)} settings)")


if __name__ == "__main__":
    main()
