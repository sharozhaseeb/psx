"""Find announcement fetch in script.js."""
import asyncio
import httpx
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=15) as c:
        r = await c.get("https://dps.psx.com.pk/static/script.js?v=1.72", headers=HEADERS)
        content = r.text

        # Find function around Announcements - look 2000 chars after "Announcements"
        idx = content.find("psx.page.Announcements")
        if idx >= 0:
            print("ANNOUNCEMENTS PAGE FUNCTION:")
            print(content[idx:idx+3000])

asyncio.run(main())
