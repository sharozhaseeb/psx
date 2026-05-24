"""Audit existing company HTML fixtures for balance-sheet & dividend payload.

Reads tests/fixtures/profile_LUCK.html and tests/fixtures/financial_LUCK.html,
scans the text for keyword categories, and prints a small report. Run from
psx-mcp/ working directory; redirect stdout to tests/fixtures/company_payload_audit.txt.
"""
from __future__ import annotations
from pathlib import Path
import re

from bs4 import BeautifulSoup

KEYWORDS = {
    "balance_sheet": [
        "total assets",
        "current liabilit",
        "long term debt",
        "long-term debt",
        "share capital",
        "current ratio",
    ],
    "dividend": [
        "dividend",
        "payout",
        "cash dividend",
        "interim",
        "final",
    ],
}

FIXTURES = [
    Path("tests/fixtures/profile_LUCK.html"),
    Path("tests/fixtures/financial_LUCK.html"),
]


def scan(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "html.parser")
    visible = soup.get_text(" ", strip=True)
    lower = visible.lower()

    report = {
        "path": str(path),
        "size_bytes": len(raw),
        "visible_chars": len(visible),
        "table_count": len(soup.find_all("table")),
        "categories": {},
    }
    for cat, words in KEYWORDS.items():
        hits = {}
        for w in words:
            count = lower.count(w)
            if count:
                # capture up to 3 short snippets around each hit
                snippets = []
                for m in list(re.finditer(re.escape(w), lower))[:3]:
                    start = max(0, m.start() - 40)
                    end = min(len(visible), m.end() + 80)
                    snippets.append(visible[start:end].replace("\n", " "))
                hits[w] = {"count": count, "snippets": snippets}
        report["categories"][cat] = hits
    return report


def render(report: dict) -> list[str]:
    lines = [
        "=" * 78,
        f"FILE: {report['path']}",
        f"  raw_size={report['size_bytes']}  visible_chars={report['visible_chars']}  tables={report['table_count']}",
    ]
    for cat, hits in report["categories"].items():
        lines.append(f"  CATEGORY: {cat}")
        if not hits:
            lines.append("    (no hits)")
            continue
        for w, info in hits.items():
            lines.append(f"    - {w!r}: {info['count']} hit(s)")
            for i, snip in enumerate(info["snippets"], 1):
                lines.append(f"        [{i}] ...{snip}...")
    return lines


def main():
    all_lines: list[str] = []
    for p in FIXTURES:
        if not p.exists():
            all_lines.append(f"MISSING FIXTURE: {p}")
            continue
        report = scan(p)
        all_lines.extend(render(report))
    out_path = Path("tests/fixtures/company_payload_audit.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(all_lines) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
