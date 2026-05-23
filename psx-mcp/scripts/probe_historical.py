"""Check timeseries/eod endpoint."""
import asyncio
import httpx
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=20) as c:
        r = await c.get("https://dps.psx.com.pk/timeseries/eod/LUCK", headers=HEADERS)
        print(f"Status: {r.status_code}, bytes: {len(r.content)}, ctype: {r.headers.get('content-type', '')}")
        content = r.text
        print(f"First 500 chars:")
        print(content[:500])
        # Save it
        out = Path("tests/fixtures/historical_LUCK.json")
        out.write_text(content, encoding="utf-8")
        print(f"Saved to {out}")

asyncio.run(main())
