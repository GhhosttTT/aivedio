"""Create a reviewable binding sidecar for an exported ComfyUI API workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.video_workflow_binding import discover_video_workflow_bindings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path, help="ComfyUI API-format workflow JSON")
    parser.add_argument("--output", type=Path, help="Defaults to <workflow>.bindings.json")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing sidecar")
    args = parser.parse_args()

    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        raise ValueError("Workflow JSON root must be an object")
    report = discover_video_workflow_bindings(workflow)
    output = args.output or args.workflow.with_suffix(".bindings.json")
    if output.exists() and not args.force:
        raise FileExistsError(f"Binding sidecar already exists: {output}; use --force to replace it")
    output.write_text(
        json.dumps(report["manifest"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "output": str(output),
        "unresolved": report["unresolved"],
        "evidence": report["evidence"],
    }, ensure_ascii=False, indent=2))
    return 0 if not report["unresolved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
