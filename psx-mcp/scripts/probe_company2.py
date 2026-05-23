"""Probe DPS company page for profile structure."""
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

        # Find sections with "sector", "company profile", "equity profile" etc
        print("=== CLASSES WITH PROFILE/COMPANY/SECTOR ===")
        for tag in soup.find_all(True):
            cls = " ".join(tag.get("class", []))
            if any(kw in cls.lower() for kw in ["profile", "info", "equity", "sector", "ratio"]):
                txt = tag.get_text(" ", strip=True)[:200]
                if txt:
                    print(f"<{tag.name} class='{cls}'>: {txt[:150]}")

        # Look for "Company Profile" section
        print("\n=== AROUND 'Equity Profile' ===")
        text = soup.get_text(" ")
        idx = text.find("Equity Profile")
        if idx >= 0:
            print(text[idx:idx+500])

        print("\n=== AROUND 'Company Profile' ===")
        idx2 = text.find("Company Profile")
        if idx2 >= 0:
            print(text[idx2:idx2+500])

        # Ratios section
        print("\n=== RATIOS SECTION ===")
        idx3 = text.find("Ratios")
        if idx3 >= 0:
            print(text[idx3:idx3+400])

        # P/E section
        print("\n=== P/E and EPS ===")
        idx4 = text.find("P/E Ratio")
        if idx4 >= 0:
            print(text[max(0, idx4-100):idx4+300])

if __name__ == "__main__":
    asyncio.run(main())
