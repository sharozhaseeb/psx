"""Capture RSS feeds into tests/fixtures/.
Run from psx-mcp/:  uv run python scripts/capture_rss.py
"""
import httpx
from pathlib import Path

FIX = Path("tests/fixtures")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

FEEDS = [
    ("https://www.dawn.com/feeds/business", "dawn_business_feed.xml"),
    ("https://profit.pakistantoday.com.pk/feed/", "profit_feed.xml"),
]

for url, out in FEEDS:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        print(url, r.status_code, len(r.content))
        if r.status_code == 200:
            (FIX / out).write_text(r.text, encoding="utf-8")
    except Exception as e:
        print(f"{url} ERROR {e}")
