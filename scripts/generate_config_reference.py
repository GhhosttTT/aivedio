#!/usr/bin/env python3
"""Generate docs/configuration-reference.md from the Settings model."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings

SECRET_MARKERS = ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "ENCRYPTION_KEY")
# Declared for planned features or external tooling but not read by this codebase.
RESERVED_PREFIXES = ()
RESERVED_SETTINGS = {
    "FACE_DETAILER_FACEID_END_AT",
    "FACE_DETAILER_FACEID_WEIGHT",
    "FACEID_START_AT",
    "FACEID_END_AT",
    "GPU_MEMORY_FRACTION",
    "SUBTITLE_REMOVAL_BACKEND",
    "MODERATION_BACKEND",
    "LOCALIZATION_CONCURRENCY",
}
OUTPUT_PATH = ROOT / "docs/configuration-reference.md"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _is_reserved(name: str) -> bool:
    return name in RESERVED_SETTINGS or name.startswith(RESERVED_PREFIXES)


def _default_text(name: str, field) -> str:
    if any(marker in name for marker in SECRET_MARKERS):
        return "通过环境变量设置，勿提交"
    default = field.default
    if default is None:
        text = "`null`"
    else:
        value = str(default)
        text = f"`{value}`" if value else '`""`'
    if _is_reserved(name):
        text += "（预留，当前代码未读取）"
    return text


def _group_name(name: str) -> str:
    parts = name.split("_")
    if parts[0] == "GENERATION" and len(parts) > 1:
        return f"GENERATION_{parts[1]}"
    return parts[0]


def _anchor(group: str) -> str:
    return group.lower()


def build_document() -> str:
    groups: dict[str, list[tuple[str, object]]] = defaultdict(list)
    for name, field in Settings.model_fields.items():
        groups[_group_name(name)].append((name, field))

    lines = [
        "# 配置项参考",
        "",
        "本文件由 `scripts/generate_config_reference.py` 从 `src/config.py` 自动生成。",
        "完整默认值以 `Settings` 模型为准；`.env.example` 只列出常用项。",
        "",
        "加载优先级：进程环境变量 > `.env` > 代码默认值。",
        "",
        "另有少量由脚本或适配器直接读取、不属于 `Settings` 的变量"
        "（如 `DEFAULT_ADMIN_*`、`ENCRYPTION_KEY`），见 `.env.example`。",
        "",
        f"共 {len(Settings.model_fields)} 项，按变量前缀分组。",
        "",
        "## 目录",
        "",
    ]
    for group in sorted(groups):
        lines.append(f"- [{group}](#{_anchor(group)})（{len(groups[group])} 项）")
    lines.append("")

    for group in sorted(groups):
        lines.extend([
            f"## {group}",
            "",
            "| 变量 | 类型 | 默认值 |",
            "| --- | --- | --- |",
        ])
        for name, field in sorted(groups[group]):
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
