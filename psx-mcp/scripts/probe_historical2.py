"""Understand historical/EOD format."""
import json
from pathlib import Path
from datetime import datetime

data_raw = json.loads(Path("tests/fixtures/historical_LUCK.json").read_text(encoding="utf-8"))
print("Top-level keys:", list(data_raw.keys()) if isinstance(data_raw, dict) else "LIST")
print("Status:", data_raw.get("status"))
print("Message:", data_raw.get("message"))
data = data_raw.get("data", [])
print(f"Total rows: {len(data)}")
print("First 5 rows:")
for row in data[:5]:
    print(" ", row)
    # Try converting timestamp
    if isinstance(row, list) and len(row) > 0:
        ts = row[0]
        dt = datetime.fromtimestamp(ts)
        print(f"    -> timestamp {ts} = {dt}")

# Check if this matches format: [timestamp, ldcp, volume, close]
print("\nLast 5 rows:")
for row in data[-5:]:
    print(" ", row)
