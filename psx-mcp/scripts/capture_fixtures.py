"""One-off: capture real PSX responses into tests/fixtures/.

Run from psx-mcp/:  uv run python scripts/capture_fixtures.py

Endpoint notes (discovered 2026-05-23):
- market_watch:   GET  https://dps.psx.com.pk/market-watch         -> HTML
- historical:     POST https://dps.psx.com.pk/historical            -> HTML fragment (OHLCV table)
- symbols:        GET  https://dps.psx.com.pk/symbols               -> JSON
- announcements:  POST https://dps.psx.com.pk/announcements         -> HTML fragment
- profile:        GET  https://dps.psx.com.pk/company/<SYM>         -> HTML
- financial:      GET  https://dps.psx.com.pk/company/<SYM>         -> HTML (same page, has ratios/financials)
"""
import asyncio
import httpx
from pathlib import Path

FIX = Path("tests/fixtures")
FIX.mkdir(parents=True, exist_ok=True)

BASE = "https://dps.psx.com.pk"

GET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}
POST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "text/html, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


def _ext_from(response: httpx.Response) -> str:
    ctype = response.headers.get("content-type", "").lower()
    if "json" in ctype:
        return "json"
    return "html"


async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=30) as c:
        # 1. Market watch (GET)
        url = f"{BASE}/market-watch"
        stem = "market_watch"
        r = await c.get(url, headers=GET_HEADERS)
        ext = _ext_from(r)
        out = FIX / f"{stem}.{ext}"
        print(f"{url} -> {r.status_code} ({len(r.content)} bytes) -> {out.name}")
        if r.status_code == 200:
            out.write_text(r.text, encoding="utf-8")
        else:
            print(f"  WARN: non-200; adapt URL in psx_client.py before continuing")

        # 2. Historical OHLCV (POST → HTML fragment)
        url = f"{BASE}/historical"
        stem = "historical_LUCK"
        headers2 = dict(POST_HEADERS)
        headers2["Referer"] = f"{BASE}/historical"
        r = await c.post(url, data={"symbol": "LUCK"}, headers=headers2)
        ext = _ext_from(r)
        out = FIX / f"{stem}.{ext}"
        print(f"POST {url} symbol=LUCK -> {r.status_code} ({len(r.content)} bytes) -> {out.name}")
        if r.status_code == 200:
            out.write_text(r.text, encoding="utf-8")
        else:
            print(f"  WARN: non-200; adapt URL in psx_client.py before continuing")

        # 3. Symbols (GET)
        url = f"{BASE}/symbols"
        stem = "symbols"
        r = await c.get(url, headers=GET_HEADERS)
        ext = _ext_from(r)
        out = FIX / f"{stem}.{ext}"
        print(f"{url} -> {r.status_code} ({len(r.content)} bytes) -> {out.name}")
        if r.status_code == 200:
            out.write_text(r.text, encoding="utf-8")
        else:
            print(f"  WARN: non-200; adapt URL in psx_client.py before continuing")

        # 4. Announcements (POST → HTML fragment)
        url = f"{BASE}/announcements"
        stem = "announcements"
        headers4 = dict(POST_HEADERS)
        headers4["Referer"] = f"{BASE}/announcements/companies"
        r = await c.post(url, data={"type": "C", "offset": "0", "count": "50"}, headers=headers4)
        ext = _ext_from(r)
        out = FIX / f"{stem}.{ext}"
        print(f"POST {url} type=C -> {r.status_code} ({len(r.content)} bytes) -> {out.name}")
        if r.status_code == 200:
            out.write_text(r.text, encoding="utf-8")
        else:
            print(f"  WARN: non-200; adapt URL in psx_client.py before continuing")

        # 5. Company profile (GET) — used for both profile and financial fixtures
        url = f"{BASE}/company/LUCK"
        r = await c.get(url, headers=GET_HEADERS)
        ext = _ext_from(r)
        print(f"{url} -> {r.status_code} ({len(r.content)} bytes)")
        if r.status_code == 200:
            # Save as both profile and financial (same page has both)
            for stem in ("profile_LUCK", "financial_LUCK"):
                out = FIX / f"{stem}.{ext}"
                out.write_text(r.text, encoding="utf-8")
                print(f"  -> {out.name}")
        else:
            print(f"  WARN: non-200; adapt URL in psx_client.py before continuing")


if __name__ == "__main__":
    asyncio.run(main())
