"""Check historical page for OHLCV data."""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "text/html, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://dps.psx.com.pk/historical",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=20) as c:
        # POST to historical with symbol
        data = {
            "symbol": "LUCK",
        }
        r = await c.post("https://dps.psx.com.pk/historical", data=data, headers=HEADERS)
        print(f"Status: {r.status_code}, bytes: {len(r.content)}, ctype: {r.headers.get('content-type', '')}")
        content = r.text
        print(content[:3000])

asyncio.run(main())
