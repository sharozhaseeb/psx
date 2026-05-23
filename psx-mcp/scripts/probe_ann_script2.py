"""Find announcement fetch function in script.js."""
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

        # Find the Announcements page module definition
        idx = content.find("psx.page.Announcements=function")
        if idx >= 0:
            print("ANNOUNCEMENTS PAGE MODULE (first 3000 chars):")
            print(content[idx:idx+3000])
        else:
            print("Not found directly")
            # Try searching with different context
            idx2 = content.find("Announcements=function")
            if idx2 >= 0:
                print("Found at:", idx2)
                print(content[idx2:idx2+3000])

        # Also look for fetch calls with announcements
        matches = re.findall(r'fetch\(["\'][^"\']*ann[^"\']*["\']', content, re.I)
        print("\nAnnouncement fetch calls:")
        for m in matches:
            print(f"  {m}")

        # Look for XHR/ajax with announcements
        ann_sections = []
        for m in re.finditer(r'.{200}announcement.{200}', content, re.I):
            ann_sections.append(m.group())
        print(f"\nContexts with 'announcement' ({len(ann_sections)} found):")
        for s in ann_sections[:5]:
            print(f"  ...{s}...")

asyncio.run(main())
