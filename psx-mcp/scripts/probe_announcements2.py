"""Probe announcements fixture more deeply."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

def main():
    html = Path("tests/fixtures/announcements.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    # Print text around "announcement" keywords
    text = soup.get_text(" ")
    idx = text.find("Announcement")
    if idx >= 0:
        print("AROUND 'Announcement':", text[max(0, idx-50):idx+500])

    # Look for any element with "symbol" or "date" in class or data attrs
    print("\n=== ALL SCRIPT TAGS ===")
    for tag in soup.find_all("script"):
        src = tag.get("src", "")
        if not src:
            txt = (tag.string or "")[:200]
            if txt.strip():
                print(f"Script: {txt[:200]}")

    # Print raw HTML around table-like structures
    print("\n=== CONTENT DIVS ===")
    for div in soup.find_all("div")[:30]:
        cls = " ".join(div.get("class", []))
        if any(kw in cls for kw in ["content", "main", "ann", "list", "data", "tbl", "table"]):
            print(f"<div class='{cls}'>: {div.get_text(' ', strip=True)[:200]}")

    # Print raw HTML sections
    print("\n=== RAW HTML SECTIONS (first 2000 chars) ===")
    # Find where the main content starts
    body = soup.find("body")
    if body:
        # Get all top-level divs
        for i, div in enumerate(body.find_all("div", recursive=False)[:5]):
            cls = " ".join(div.get("class", []))
            print(f"TOP DIV {i} class='{cls}':", div.get_text(" ", strip=True)[:300])

main()
