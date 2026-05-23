"""Inspect the financial tables in company page."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

FIX = Path("tests/fixtures")
html = (FIX / "financial_LUCK.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "lxml")

print("=== ALL TABLES ===")
for i, table in enumerate(soup.find_all("table")):
    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    rows = table.find_all("tr")
    body_rows = (table.find("tbody") or table).find_all("tr")
    print(f"TABLE {i}: headers={headers[:8]}")
    print(f"  rows={len(rows)}, body_rows={len(body_rows)}")
    for row in body_rows[:3]:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if cells:
            print(f"  ROW: {cells[:6]}")
    print()

# Find "Financials" section specifically
print("=== FINANCIALS SECTION ===")
text = soup.get_text(" ")
idx = text.find("Financials")
if idx >= 0:
    print(text[idx:idx+600])
