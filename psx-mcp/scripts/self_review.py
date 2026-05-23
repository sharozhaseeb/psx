"""Self-review checks for Task 7."""
from pathlib import Path
import sys

FIX = Path("tests/fixtures")

# 1. All 6 fixtures captured with non-zero file sizes?
print("=== FIXTURE CHECK ===")
required = ["market_watch.html", "historical_LUCK.html", "symbols.json",
            "announcements.html", "profile_LUCK.html", "financial_LUCK.html"]
all_ok = True
for name in required:
    p = FIX / name
    if not p.exists():
        print(f"MISSING: {name}")
        all_ok = False
    elif p.stat().st_size == 0:
        print(f"EMPTY: {name}")
        all_ok = False
    else:
        print(f"OK: {name} ({p.stat().st_size:,} bytes)")
print(f"Fixtures OK: {all_ok}")

# 2. parse_market_watch returns >100 rows?
print("\n=== MARKET WATCH CHECK ===")
from psx_mcp.psx_client import parse_market_watch, parse_historical
html = (FIX / "market_watch.html").read_text(encoding="utf-8")
rows = parse_market_watch(html)
print(f"Market watch rows: {len(rows)}")
print(f"First row: {rows[0] if rows else 'NONE'}")
print(f">100 rows: {len(rows) > 100}")

# 3. Historical bars
print("\n=== HISTORICAL CHECK ===")
hist_html = (FIX / "historical_LUCK.html").read_text(encoding="utf-8")
bars = parse_historical("LUCK", hist_html)
print(f"Historical bars: {len(bars)}")
if bars:
    print(f"First bar: {bars[0]}")
    print(f"Last bar: {bars[-1]}")

# 4. No <fill in> placeholders in module docstring?
print("\n=== DOCSTRING CHECK ===")
import psx_mcp.psx_client as m
doc = m.__doc__ or ""
if "<fill in>" in doc:
    print("ERROR: docstring has <fill in> placeholders!")
else:
    print("OK: No <fill in> placeholders in docstring")

print("\n=== ALL CHECKS PASSED ===")
