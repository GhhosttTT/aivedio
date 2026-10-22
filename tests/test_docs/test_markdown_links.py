"""Keep relative documentation links resolvable."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = [REPO / "README.md", *sorted((REPO / "docs").glob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def test_relative_markdown_links_resolve():
    broken = []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for match in LINK.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            if not (doc.parent / target).resolve().exists():
                broken.append(f"{doc.relative_to(REPO)} -> {target}")

    assert not broken, "Broken relative links:\n" + "\n".join(broken)
