"""Probe: are PSX historical OHLC prices adjusted for bonus/splits, or raw?

Approach: pull the SYS history via both the HTML POST /historical endpoint and
the JSON /timeseries/eod/SYS endpoint, capture rows near a candidate ex-date,
and save the raw response + a small "neighborhood" excerpt for manual review.

The plan suggested SYS with EX_DATE 2024-04-25 as a placeholder — the actual
ex-date for SYS's most recent bonus is unverified from our side. We capture
what we can and document the indeterminacy honestly.

Saves: tests/fixtures/history_SYS_raw.txt
"""
from __future__ import annotations
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

SYMBOL = "SYS"
# Placeholder ex-date — to be verified against confirmed corporate action.
CANDIDATE_EX_DATE = date(2024, 4, 25)
WINDOW_DAYS = 10

HEADERS_GET = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP-probe/0.1",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
    "Accept-Language": "en-PK,en;q=0.9",
}
HEADERS_POST = {
    **HEADERS_GET,
    "Accept": "text/html, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


def _parse_month_name_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%b %d, %Y").date()
    except ValueError:
        return None


def html_rows_near(html: str, target: date, window: int) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return ["(no <table> found in HTML response)"]
    out = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        d = _parse_month_name_date(cells[0])
        if d is None:
            continue
        if abs((d - target).days) <= window:
            out.append(" | ".join(cells))
    return out or ["(no rows within window — full table may not extend back that far)"]


def json_rows_near(payload: str, target: date, window: int) -> list[str]:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return ["(payload was not JSON)"]
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [f"(unexpected JSON shape: top-level keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__})"]
    out = []
    for r in rows:
        if not isinstance(r, list) or len(r) < 2:
            continue
        try:
            d = datetime.fromtimestamp(int(r[0])).date()
        except (ValueError, OSError, TypeError):
            continue
        if abs((d - target).days) <= window:
            out.append(f"{d.isoformat()} | {r}")
    return out or ["(no rows within window in JSON series)"]


async def main():
    out_lines: list[str] = []
    out_lines.append("=" * 78)
    out_lines.append(f"Historical adjustment probe — symbol={SYMBOL}")
    out_lines.append(f"Candidate ex-date (UNVERIFIED placeholder): {CANDIDATE_EX_DATE.isoformat()}")
    out_lines.append(f"Window: +/- {WINDOW_DAYS} days")
    out_lines.append("")
    out_lines.append("NOTE: Without a CONFIRMED corporate-action ex-date, the comparison")
    out_lines.append("of 'close before ex-date' vs 'close on/after ex-date' is meaningless.")
    out_lines.append("This probe captures the raw rows so a human can compare once an")
    out_lines.append("ex-date is confirmed from PSX announcements or a third-party source.")
    out_lines.append("")

    async with httpx.AsyncClient(http2=True, timeout=20.0, follow_redirects=True) as c:
        # 1) HTML POST /historical
        try:
            r1 = await c.post(
                "https://dps.psx.com.pk/historical",
                data={"symbol": SYMBOL},
                headers=HEADERS_POST,
            )
            out_lines.append(f"[HTML] POST /historical -> {r1.status_code} ({r1.headers.get('content-type', '')}, {len(r1.text)} bytes)")
            out_lines.append(f"[HTML] rows near {CANDIDATE_EX_DATE.isoformat()}:")
            for row in html_rows_near(r1.text, CANDIDATE_EX_DATE, WINDOW_DAYS):
                out_lines.append(f"  {row}")
        except Exception as e:
            out_lines.append(f"[HTML] FAILED: {e}")

        out_lines.append("")

        # 2) JSON timeseries
        try:
            r2 = await c.get(
                f"https://dps.psx.com.pk/timeseries/eod/{SYMBOL}",
                headers=HEADERS_GET,
            )
            out_lines.append(f"[JSON] GET /timeseries/eod/{SYMBOL} -> {r2.status_code} ({r2.headers.get('content-type', '')}, {len(r2.text)} bytes)")
            out_lines.append(f"[JSON] rows near {CANDIDATE_EX_DATE.isoformat()}:")
            for row in json_rows_near(r2.text, CANDIDATE_EX_DATE, WINDOW_DAYS):
                out_lines.append(f"  {row}")
        except Exception as e:
            out_lines.append(f"[JSON] FAILED: {e}")

    out_lines.append("")
    out_lines.append("=" * 78)
    out_lines.append("CONCLUSION (until a confirmed ex-date is documented):")
    out_lines.append("  Historical price adjustment status is INDETERMINATE.")
    out_lines.append("  Revisit once a known corporate action ex-date is recorded in")
    out_lines.append("  the cached announcements table or sourced from a PSX disclosure.")

    out_path = Path("tests/fixtures/history_SYS_raw.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out_lines) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
