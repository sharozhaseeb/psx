"""Check for OHLCV endpoints."""
import asyncio
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=20) as c:
        urls = [
            "https://dps.psx.com.pk/timeseries/eod/LUCK?from=2024-01-01&to=2024-03-01",
            "https://dps.psx.com.pk/timeseries/LUCK",
            "https://dps.psx.com.pk/timeseries/int/LUCK",
            "https://dps.psx.com.pk/data/LUCK",
            "https://dps.psx.com.pk/historical",
            "https://dps.psx.com.pk/company/LUCK/historical",
        ]
        for url in urls:
            try:
                r = await c.get(url, headers=HEADERS)
                ctype = r.headers.get("content-type", "")
                content_preview = r.text[:200]
                print(f"{url}")
                print(f"  -> {r.status_code} ({len(r.content)} bytes) [{ctype[:40]}]")
                if r.status_code == 200:
                    print(f"  Preview: {content_preview[:100]}")
            except Exception as e:
                print(f"{url} -> ERROR: {e}")

asyncio.run(main())
