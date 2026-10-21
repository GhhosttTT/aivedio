"""Keep blocking route handlers off the event loop."""

import ast
from pathlib import Path


def test_async_routes_contain_an_await():
    offenders = []
    for path in sorted(Path("src/api/routes").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and not any(
                isinstance(child, ast.Await) for child in ast.walk(node)
            ):
                offenders.append(f"{path.name}:{node.lineno}:{node.name}")

    assert offenders == [], (
        "Async route handlers without await run sync DB/CPU work on the event loop; "
        "declare them as regular def instead: " + ", ".join(offenders)
    )
