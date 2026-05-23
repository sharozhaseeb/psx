"""Find the announcements API endpoint."""
import asyncio
import httpx
from bs4 import BeautifulSoup
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=15) as c:
        # Try to find the JS file that handles announcements
        r = await c.get("https://dps.psx.com.pk/static/script.js?v=1.72", headers=HEADERS)
        content = r.text
        # Search for announcement-related URLs/functions
        import re
        matches = re.findall(r'["\']([^"\']*announcement[^"\']*)["\']', content, re.I)
        print("Announcement URLs/patterns found in script.js:")
        for m in matches[:20]:
            print(f"  {m}")

        # Also look for fetch/ajax calls
        matches2 = re.findall(r'["\']([^"\']*\/ann[^"\']*)["\']', content, re.I)
        print("Other ann patterns:")
        for m in matches2[:20]:
            print(f"  {m}")

        # Look for dps endpoint patterns
        matches3 = re.findall(r'["\']\/([a-z][a-z/\-_]+)["\']', content)
        unique_paths = sorted(set(matches3))
        print("All DPS path patterns:")
        for p in unique_paths[:60]:
            print(f"  /{p}")

asyncio.run(main())
