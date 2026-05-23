"""Fetch announcements via POST."""
import asyncio
import httpx
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "text/html, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://dps.psx.com.pk/announcements/companies",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=20) as c:
        # POST to /announcements with type=C (company announcements)
        data = {
            "type": "C",
            "offset": "0",
            "count": "50",
        }
        r = await c.post("https://dps.psx.com.pk/announcements", data=data, headers=HEADERS)
        print(f"Status: {r.status_code}, bytes: {len(r.content)}, ctype: {r.headers.get('content-type', '')}")
        content = r.text
        # Check if it's HTML or JSON
        if content.strip().startswith("<"):
            print("GOT HTML:")
            print(content[:3000])
        else:
            print("GOT:")
            print(content[:2000])

asyncio.run(main())
