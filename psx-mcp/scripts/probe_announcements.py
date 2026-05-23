"""Probe announcements fixture."""
from pathlib import Path
from bs4 import BeautifulSoup

def main():
    html = Path("tests/fixtures/announcements.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    print("=== TABLES ===")
    for i, t in enumerate(soup.find_all("table")[:5]):
        headers = [th.get_text(strip=True) for th in t.find_all("th")[:10]]
        rows = t.find_all("tr")
        print(f"TABLE {i}: headers={headers}, rows={len(rows)}")
        for row in rows[:4]:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if cells:
                print(f"  ROW: {cells[:6]}")

    print("\n=== SCRIPT TAGS (data) ===")
    for tag in soup.find_all("script"):
        src = tag.get("src", "")
        if not src:
            txt = tag.string or ""
            if "announcement" in txt.lower() or "symbol" in txt.lower() or "data" in txt.lower():
                print(f"INLINE SCRIPT (first 500):\n{txt[:500]}")

main()
