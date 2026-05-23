"""Inspect all fixtures to determine shapes."""
from pathlib import Path
from bs4 import BeautifulSoup
import json

FIX = Path("tests/fixtures")

# 1. market_watch.html
print("=" * 60)
print("1. market_watch.html")
print("=" * 60)
html = (FIX / "market_watch.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "lxml")
table = soup.find("table")
if table:
    thead = table.find("thead")
    headers = [th.get_text(strip=True) for th in (thead or table).find_all(["th", "td"])]
    print(f"Headers: {headers}")
    rows = (table.find("tbody") or table).find_all("tr")[:3]
    print(f"Total rows (approx from body): {len((table.find('tbody') or table).find_all('tr'))}")
    for row in rows[:2]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        print(f"  Sample row: {cells[:8]}")

# 2. historical_LUCK.html
print("\n" + "=" * 60)
print("2. historical_LUCK.html")
print("=" * 60)
html2 = (FIX / "historical_LUCK.html").read_text(encoding="utf-8")
soup2 = BeautifulSoup(html2, "lxml")
table2 = soup2.find("table")
if table2:
    thead2 = table2.find("thead")
    headers2 = [th.get_text(strip=True) for th in (thead2 or table2).find_all(["th", "td"])]
    print(f"Headers: {headers2}")
    rows2 = (table2.find("tbody") or table2).find_all("tr")
    print(f"Total rows: {len(rows2)}")
    for row in rows2[:3]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        print(f"  Sample row: {cells[:8]}")

# 3. symbols.json
print("\n" + "=" * 60)
print("3. symbols.json")
print("=" * 60)
sym_data = json.loads((FIX / "symbols.json").read_text(encoding="utf-8"))
print(f"Type: {type(sym_data).__name__}, len: {len(sym_data) if isinstance(sym_data, list) else 'N/A'}")
if isinstance(sym_data, list) and len(sym_data) > 0:
    print(f"Keys in first item: {list(sym_data[0].keys())}")
    print(f"Sample item: {sym_data[0]}")
    # Look for LUCK
    for s in sym_data:
        if s.get("symbol") == "LUCK":
            print(f"LUCK entry: {s}")
            break
elif isinstance(sym_data, dict):
    print(f"Dict keys: {list(sym_data.keys())}")

# 4. announcements.html
print("\n" + "=" * 60)
print("4. announcements.html")
print("=" * 60)
html4 = (FIX / "announcements.html").read_text(encoding="utf-8")
soup4 = BeautifulSoup(html4, "lxml")
table4 = soup4.find("table")
if table4:
    thead4 = table4.find("thead")
    headers4 = [th.get_text(strip=True) for th in (thead4 or table4).find_all(["th", "td"])]
    print(f"Headers: {headers4}")
    rows4 = (table4.find("tbody") or table4).find_all("tr")
    print(f"Total rows: {len(rows4)}")
    for row in rows4[:3]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        print(f"  Sample row: {cells[:6]}")
else:
    print("No table found")
    print(html4[:500])

# 5. profile_LUCK.html
print("\n" + "=" * 60)
print("5. profile_LUCK.html (same as financial_LUCK.html)")
print("=" * 60)
html5 = (FIX / "profile_LUCK.html").read_text(encoding="utf-8")
soup5 = BeautifulSoup(html5, "lxml")
# Company name
title = soup5.find("title")
print(f"Title: {title.get_text(strip=True) if title else 'N/A'}")
# Sector
sector_div = soup5.find("div", class_="quote__sector")
print(f"Sector (div.quote__sector): {sector_div.get_text(strip=True) if sector_div else 'N/A'}")
# Company profile
profile_div = soup5.find("div", class_="company__profile")
# Equity profile
equity_div = soup5.find("div", class_=lambda c: c and "companyEquity" in c)
if equity_div:
    print(f"Equity section: {equity_div.get_text(' ', strip=True)[:200]}")
# Ratios
ratios_div = soup5.find("div", class_="company__ratios")
if ratios_div:
    print(f"Ratios (first 200): {ratios_div.get_text(' ', strip=True)[:200]}")
# Look for EPS/PE
text5 = soup5.get_text(" ")
import re
for kw in ["EPS", "P/E Ratio", "P/B"]:
    idx = text5.find(kw)
    if idx >= 0:
        print(f"{kw}: ...{text5[max(0,idx-10):idx+100].strip()[:120]}")
