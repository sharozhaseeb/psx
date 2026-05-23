"""Probe DPS company page for structure."""
import asyncio
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}

async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=15) as c:
        r = await c.get("https://dps.psx.com.pk/company/LUCK", headers=HEADERS)
        soup = BeautifulSoup(r.text, "lxml")
        # Look for headings
        print("=== HEADINGS ===")
        for tag in soup.find_all(["h1", "h2", "h3"]):
            txt = tag.get_text(strip=True)
            if txt:
                print(f"<{tag.name}>: {txt[:100]}")
        # Look for dt/dd pairs
        print("\n=== DT/DD PAIRS ===")
        for dt in soup.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                print(f"DT: {dt.get_text(strip=True)[:50]} | DD: {dd.get_text(strip=True)[:80]}")
        # Look for tables
        print("\n=== TABLES ===")
        for i, t in enumerate(soup.find_all("table")[:5]):
            headers = [th.get_text(strip=True) for th in t.find_all("th")[:10]]
            rows = t.find_all("tr")[:5]
            print(f"TABLE {i} headers: {headers}")
            for row in rows[:3]:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if cells:
                    print(f"  ROW: {cells[:5]}")
        # Print EPS/PE/PB related text
        print("\n=== FINANCIAL RATIOS ===")
        text = soup.get_text(" ")
        import re
        for kw in ["EPS", "P/E", "P/B", "ROE", "Yield", "Payout", "Revenue", "Profit", "EBITDA"]:
            idx = text.find(kw)
            if idx >= 0:
                print(f"{kw}: ...{text[max(0,idx-30):idx+80].strip()[:150]}...")

if __name__ == "__main__":
    asyncio.run(main())
