"""Find the announcements data API."""
import asyncio
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
    "Referer": "https://dps.psx.com.pk/announcements/companies",
    "X-Requested-With": "XMLHttpRequest",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=15) as c:
        # Try various data API patterns
        urls = [
            "https://dps.psx.com.pk/announcements",
            "https://dps.psx.com.pk/announcements/companies",
            "https://dps.psx.com.pk/announcements/data",
            "https://dps.psx.com.pk/announcements/companies?offset=0&count=50",
            "https://dps.psx.com.pk/announcements?type=companies&offset=0&count=50",
        ]
        for url in urls:
            r = await c.get(url, headers=HEADERS)
            ctype = r.headers.get("content-type", "")
            print(f"{url}")
            print(f"  -> {r.status_code} ({len(r.content)} bytes) [{ctype[:60]}]")
            if r.status_code == 200:
                content_preview = r.text[:200]
                if content_preview.strip().startswith("[") or content_preview.strip().startswith("{"):
                    print(f"  JSON: {content_preview}")
                else:
                    # Try GET with X-Requested-With to get JSON
                    print(f"  HTML (first 100): {content_preview[:100].strip()}")

asyncio.run(main())
