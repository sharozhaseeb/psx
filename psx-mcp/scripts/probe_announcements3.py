"""Check for JS-loaded announcement data."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

def main():
    html = Path("tests/fixtures/announcements.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    # Look at the content div more carefully
    content_div = soup.find("div", class_="content")
    if content_div:
        print("CONTENT DIV HTML (first 3000 chars):")
        print(str(content_div)[:3000])

main()
