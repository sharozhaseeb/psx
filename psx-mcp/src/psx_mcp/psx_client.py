"""PSX endpoint shape matrix (captured 2026-05-23):

market-watch:
  GET  https://dps.psx.com.pk/market-watch
  HTML — single <table id="…"> with 11 columns:
    SYMBOL | SECTOR | LISTED IN | LDCP | OPEN | HIGH | LOW | CURRENT | CHANGE | CHANGE (%) | VOLUME
  ~486 rows in <tbody>; CURRENT is the last-trade price.

historical/<SYM>:
  POST https://dps.psx.com.pk/historical  {symbol: <SYM>}
  HTML fragment — <table id="historicalTable"> with 6 columns:
    DATE | OPEN | HIGH | LOW | CLOSE | VOLUME
  Date format: "May 22, 2026" (human-readable month name).
  ~2472 rows for LUCK (full history).

symbols:
  GET  https://dps.psx.com.pk/symbols
  JSON list of objects with keys: symbol, name, sectorName, isETF, isDebt, isGEM
  1048 items total.

announcements/companies:
  POST https://dps.psx.com.pk/announcements  {type: "C", offset: 0, count: 50}
  HTML fragment — <table id="announcementsTable"> with columns:
    DATE | TIME | SYMBOL | NAME | TITLE | (action links)
  Date "May 22, 2026", Time "5:06 PM" in separate columns.

company/<SYM> (profile):
  GET  https://dps.psx.com.pk/company/<SYM>
  HTML — company name from <title> or meta; sector in <div class="quote__sector">;
  shares/free-float in <div class="companyEquity">.

company/<SYM> (financials):
  GET  https://dps.psx.com.pk/company/<SYM>  (same page)
  HTML — P/E Ratio (TTM) in text; EPS in financial tables;
  TABLE 4: annual financials with year headers 2025/2024/2023/2022;
  TABLE 5: quarterly financials with Q-headers.
"""
from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime, date
from typing import Optional, Union

import httpx
from bs4 import BeautifulSoup

from .models import Bar, CompanyInfo, Fundamentals, Announcement, FinancialStatement
from .logging_config import get_logger

log = get_logger("psx_client")

BASE_DPS = "https://dps.psx.com.pk"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1"
GET_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}
POST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "text/html, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


class ParseError(Exception):
    pass


# ---------- low-level HTTP ----------

class PSXClient:
    """Async HTTP client for PSX endpoints. Polite: max 2 concurrent requests."""

    def __init__(self, *, timeout: float = 10.0):
        self._sem = asyncio.Semaphore(2)
        self._client = httpx.AsyncClient(
            http2=True, headers=GET_HEADERS, timeout=timeout, follow_redirects=True
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str) -> str:
        async with self._sem:
            for attempt in (1, 2):
                try:
                    r = await self._client.get(url)
                    r.raise_for_status()
                    return r.text
                except httpx.HTTPStatusError as e:
                    if 500 <= e.response.status_code < 600 and attempt == 1:
                        await asyncio.sleep(2.0)
                        continue
                    raise
                except (httpx.ConnectError, httpx.ReadTimeout):
                    if attempt == 1:
                        await asyncio.sleep(2.0)
                        continue
                    raise
            raise httpx.HTTPError(f"unreachable after retries: {url}")

    async def _post(self, url: str, data: dict) -> str:
        async with self._sem:
            for attempt in (1, 2):
                try:
                    r = await self._client.post(url, data=data, headers=POST_HEADERS)
                    r.raise_for_status()
                    return r.text
                except httpx.HTTPStatusError as e:
                    if 500 <= e.response.status_code < 600 and attempt == 1:
                        await asyncio.sleep(2.0)
                        continue
                    raise
                except (httpx.ConnectError, httpx.ReadTimeout):
                    if attempt == 1:
                        await asyncio.sleep(2.0)
                        continue
                    raise
            raise httpx.HTTPError(f"unreachable after retries: {url}")

    async def fetch_market_watch(self) -> str:
        return await self._get(f"{BASE_DPS}/market-watch")

    async def fetch_historical(self, symbol: str) -> str:
        """POST to /historical with symbol= returns HTML fragment with OHLCV table."""
        return await self._post(f"{BASE_DPS}/historical", {"symbol": symbol.upper()})

    async def fetch_symbols(self) -> str:
        return await self._get(f"{BASE_DPS}/symbols")

    async def fetch_announcements(self) -> str:
        """POST to /announcements with type=C returns HTML fragment."""
        return await self._post(
            f"{BASE_DPS}/announcements",
            {"type": "C", "offset": "0", "count": "50"},
        )

    async def fetch_profile(self, symbol: str) -> str:
        return await self._get(f"{BASE_DPS}/company/{symbol.upper()}")

    async def fetch_financials(self, symbol: str) -> str:
        """Same page as profile — company/<SYM> contains financial tables."""
        return await self._get(f"{BASE_DPS}/company/{symbol.upper()}")


# ---------- shared helpers ----------

def _try_json(payload: str) -> tuple[Optional[Union[list, dict]], Optional[BeautifulSoup]]:
    """Return (json_obj, None) if payload parses as JSON; otherwise (None, BeautifulSoup)."""
    try:
        return json.loads(payload), None
    except (json.JSONDecodeError, ValueError):
        return None, BeautifulSoup(payload, "lxml")


def _f(x) -> Optional[float]:
    if x is None or x == "" or x == "-":
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _i(x) -> int:
    v = _f(x)
    return int(v) if v is not None else 0


def _parse_date_flex(s: str) -> Optional[date]:
    """Parse PSX dates in any common format. Strips any time suffix first."""
    raw = str(s).strip()
    # Drop any trailing time component (after first space or 'T')
    head = re.split(r"[ T]", raw, maxsplit=1)[0]
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d %b %Y", "%b %d, %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    # Last-ditch: ISO parse the first 10 chars
    try:
        return date.fromisoformat(head[:10])
    except ValueError:
        return None


def _parse_date_month_name(s: str) -> Optional[date]:
    """Parse 'May 22, 2026' style dates (full month name with spaces)."""
    raw = str(s).strip()
    # Try "Month DD, YYYY" format
    try:
        return datetime.strptime(raw, "%b %d, %Y").date()
    except ValueError:
        pass
    # Fall back to flex parser
    return _parse_date_flex(raw)


# ---------- parsers ----------

def parse_market_watch(html: str) -> list[dict]:
    """Returns list of {symbol, price, change, volume, day_high, day_low}.
    Uses header-row detection to map columns by name rather than fixed indices."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        raise ParseError("market-watch: no <table> found")

    # Build header → index map
    header_cells = []
    thead = table.find("thead")
    if thead:
        header_cells = [th.get_text(strip=True).upper() for th in thead.find_all(["th", "td"])]
    if not header_cells:
        first_tr = table.find("tr")
        if first_tr:
            header_cells = [th.get_text(strip=True).upper() for th in first_tr.find_all(["th", "td"])]

    def col(name_options: list[str]) -> Optional[int]:
        for i, h in enumerate(header_cells):
            for opt in name_options:
                if opt in h:
                    return i
        return None

    idx_sym = col(["SYMBOL", "SCRIP"])
    idx_price = col(["CURRENT", "PRICE", "LAST"])
    idx_change = col(["CHANGE"])  # absolute change (first match, not CHANGE %)
    idx_volume = col(["VOLUME", "VOL"])
    idx_high = col(["HIGH"])
    idx_low = col(["LOW"])

    # Fallback to positional if header detection fails (very old shape)
    if idx_sym is None:
        idx_sym, idx_price, idx_change, idx_volume, idx_high, idx_low = 0, 7, 8, 10, 5, 6

    rows = []
    body = table.find("tbody") or table
    needed = [i for i in (idx_sym, idx_price, idx_change, idx_volume, idx_high, idx_low) if i is not None]
    min_cells = (max(needed) + 1) if needed else 1
    for tr in body.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < min_cells:
            continue
        sym = cells[idx_sym].upper() if idx_sym is not None else ""
        if not sym or sym == "SYMBOL":
            continue
        # For change, prefer the absolute value (not the % change)
        change_raw = cells[idx_change] if idx_change is not None else None
        # Strip icon text like "↑ 0.37" or "↓ -0.22"
        change_clean = re.sub(r"[^\d.\-+]", "", (change_raw or "")).strip() if change_raw else None
        rows.append({
            "symbol": sym,
            "price": _f(cells[idx_price]) if idx_price is not None else None,
            "change": _f(change_clean) if change_clean else 0.0,
            "volume": _i(cells[idx_volume]) if idx_volume is not None else 0,
            "day_high": _f(cells[idx_high]) if idx_high is not None else None,
            "day_low": _f(cells[idx_low]) if idx_low is not None else None,
        })
    return rows


def parse_historical(symbol: str, payload: str) -> list[Bar]:
    """Daily OHLCV. Handles:
    - HTML table (POST to /historical): DATE, OPEN, HIGH, LOW, CLOSE, VOLUME
    - JSON (legacy timeseries/eod format): {status, data: [[ts, ldcp, vol, close], ...]}
    """
    data, soup = _try_json(payload)
    bars: list[Bar] = []

    if data is not None:
        # JSON path: handle {status, data: [[ts, ldcp, vol, close], ...]}
        if isinstance(data, dict) and "data" in data:
            rows = data["data"]
            for r in rows:
                if isinstance(r, list) and len(r) >= 4:
                    # Format: [timestamp_seconds, ldcp, volume, close]
                    ts, ldcp, vol, close = r[0], r[1], r[2], r[3]
                    try:
                        d = datetime.fromtimestamp(int(ts)).date()
                    except (ValueError, OSError):
                        continue
                    bars.append(Bar(
                        symbol=symbol.upper(), date=d,
                        open=_f(ldcp) or 0,
                        high=_f(close) or 0,
                        low=_f(close) or 0,
                        close=_f(close) or 0,
                        volume=_i(vol),
                    ))
                elif isinstance(r, dict):
                    d_raw = r.get("Date") or r.get("date") or r.get("DATE")
                    if not d_raw:
                        continue
                    d = _parse_date_flex(d_raw)
                    if not d:
                        continue
                    bars.append(Bar(
                        symbol=symbol.upper(), date=d,
                        open=_f(r.get("Open") or r.get("open")) or 0,
                        high=_f(r.get("High") or r.get("high")) or 0,
                        low=_f(r.get("Low") or r.get("low")) or 0,
                        close=_f(r.get("Close") or r.get("close")) or 0,
                        volume=_i(r.get("Volume") or r.get("volume")),
                    ))
        elif isinstance(data, list):
            for r in data:
                if isinstance(r, dict):
                    d_raw = r.get("Date") or r.get("date") or r.get("DATE")
                    if not d_raw:
                        continue
                    d = _parse_date_flex(d_raw)
                    if not d:
                        continue
                    bars.append(Bar(
                        symbol=symbol.upper(), date=d,
                        open=_f(r.get("Open") or r.get("open")) or 0,
                        high=_f(r.get("High") or r.get("high")) or 0,
                        low=_f(r.get("Low") or r.get("low")) or 0,
                        close=_f(r.get("Close") or r.get("close")) or 0,
                        volume=_i(r.get("Volume") or r.get("volume")),
                    ))
        return bars

    # HTML table path (POST /historical response)
    if soup is None:
        return bars
    table = soup.find("table")
    if not table:
        return bars

    # Build header map
    thead = table.find("thead")
    header_cells = [th.get_text(strip=True).upper() for th in (thead or table).find_all(["th", "td"])]

    def col(name: str) -> Optional[int]:
        return next((i for i, h in enumerate(header_cells) if name in h), None)

    i_d = col("DATE")
    i_o = col("OPEN")
    i_h = col("HIGH")
    i_l = col("LOW")
    i_c = col("CLOSE")
    i_v = col("VOL")

    for tr in (table.find("tbody") or table).find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells or i_d is None or len(cells) <= i_d:
            continue
        # Date format: "May 22, 2026" — use month-name parser
        d = _parse_date_month_name(cells[i_d])
        if not d:
            continue
        bars.append(Bar(
            symbol=symbol.upper(), date=d,
            open=_f(cells[i_o]) if i_o is not None and len(cells) > i_o else 0,
            high=_f(cells[i_h]) if i_h is not None and len(cells) > i_h else 0,
            low=_f(cells[i_l]) if i_l is not None and len(cells) > i_l else 0,
            close=_f(cells[i_c]) if i_c is not None and len(cells) > i_c else 0,
            volume=_i(cells[i_v]) if i_v is not None and len(cells) > i_v else 0,
        ))
    return bars


def parse_symbols(payload: str) -> list[dict]:
    """Symbol master. Handles JSON list (symbol, name, sectorName) and HTML table."""
    data, soup = _try_json(payload)
    out = []
    if data is not None:
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return out
        for r in data:
            if not isinstance(r, dict):
                continue
            sym = (r.get("symbol") or r.get("Symbol") or r.get("SYMBOL") or "").upper()
            name = r.get("name") or r.get("Name") or r.get("companyName") or ""
            # PSX symbols JSON uses "sectorName" (not "sector")
            sector = r.get("sectorName") or r.get("sector") or r.get("Sector")
            if sym:
                out.append({"symbol": sym, "name": name, "sector": sector})
        return out

    if soup is None:
        return out
    table = soup.find("table")
    if not table:
        return out
    for tr in (table.find("tbody") or table).find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) >= 2 and cells[0]:
            out.append({"symbol": cells[0].upper(), "name": cells[1],
                        "sector": cells[2] if len(cells) > 2 else None})
    return out


def parse_announcements(payload: str) -> list[Announcement]:
    """Corporate announcements.
    Handles HTML fragment from POST /announcements (columns: DATE, TIME, SYMBOL, NAME, TITLE).
    Also handles JSON list if the endpoint ever returns JSON.
    """
    data, soup = _try_json(payload)
    out: list[Announcement] = []

    def _push(*, sym, title, posted, category=None, url=None, body=None, ann_id=None):
        if not title:
            return
        sym_u = sym.upper() if sym else None
        aid = ann_id or f"{sym_u or 'X'}-{posted.isoformat()}-{title[:30]}"
        out.append(Announcement(
            id=str(aid), symbol=sym_u, posted_at=posted,
            title=title, category=category, url=url, body=body,
        ))

    if data is not None:
        # JSON path
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            return out
        for r in data:
            if not isinstance(r, dict):
                continue
            sym = (r.get("symbol") or r.get("Symbol") or "") or None
            title = r.get("title") or r.get("Title") or r.get("subject") or ""
            d_raw = r.get("date") or r.get("Date") or r.get("posted_at") or r.get("dateTime")
            posted = datetime.now()
            if d_raw:
                try:
                    posted = datetime.fromisoformat(str(d_raw))
                except ValueError:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
                        try:
                            posted = datetime.strptime(str(d_raw), fmt)
                            break
                        except ValueError:
                            continue
            _push(sym=sym, title=title, posted=posted, category=r.get("category"),
                  url=r.get("url") or r.get("URL") or r.get("link"),
                  body=r.get("body"), ann_id=r.get("id"))
        return out

    # HTML fragment path: <table id="announcementsTable">
    # Columns: DATE | TIME | SYMBOL | NAME | TITLE | (action)
    if soup is None:
        return out

    table = soup.find("table")
    if not table:
        return out

    # Build header map
    thead = table.find("thead")
    header_cells = [th.get_text(strip=True).upper() for th in (thead or table).find_all(["th", "td"])]

    def col(name: str) -> Optional[int]:
        return next((i for i, h in enumerate(header_cells) if name in h), None)

    i_date = col("DATE")
    i_time = col("TIME")
    i_sym = col("SYMBOL")
    i_title = col("TITLE")

    for tr in (table.find("tbody") or table).find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 3:
            continue
        date_str = cells[i_date] if i_date is not None and len(cells) > i_date else ""
        time_str = cells[i_time] if i_time is not None and len(cells) > i_time else ""
        sym = cells[i_sym].upper() if i_sym is not None and len(cells) > i_sym else None
        title = cells[i_title] if i_title is not None and len(cells) > i_title else cells[-2] if len(cells) >= 2 else ""

        if not date_str:
            continue

        # Parse date + time: "May 22, 2026" + "5:06 PM"
        posted = datetime.now()
        datetime_str = f"{date_str} {time_str}".strip()
        for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y"):
            try:
                posted = datetime.strptime(datetime_str, fmt)
                break
            except ValueError:
                continue

        # Get PDF link if available
        tds = tr.find_all("td")
        link = None
        for td in tds:
            a = td.find("a", href=True)
            if a and a["href"] and not a["href"].startswith("javascript"):
                link = a["href"]
                if not link.startswith("http"):
                    link = f"{BASE_DPS}{link}"
                break

        if sym and not sym.startswith("HTTP"):
            _push(sym=sym, title=title, posted=posted, url=link)

    return out


def parse_profile(symbol: str, html: str) -> CompanyInfo:
    """Parse company profile from dps.psx.com.pk/company/<SYM>.
    - Name: from <title> tag (format: 'SYM - Stock quote for Company Name - ...')
    - Sector: from <div class="quote__sector">
    - Listed shares: from <div class=... companyEquity> text containing 'Shares'
    """
    soup = BeautifulSoup(html, "lxml")

    # Name from title: "LUCK - Stock quote for Lucky Cement Limited - Pakistan Stock Exchange (PSX)"
    name = symbol.upper()
    title_tag = soup.find("title")
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        # Extract company name between "Stock quote for " and " - Pakistan"
        m = re.search(r"Stock quote for (.+?) -", title_text)
        if m:
            name = m.group(1).strip()
        elif " - " in title_text:
            # fallback: second segment
            parts = title_text.split(" - ")
            if len(parts) >= 2:
                name = parts[1].strip()

    # Also try h1/h2 if title parsing fails
    if name == symbol.upper():
        for tag in soup.find_all(["h1", "h2"]):
            txt = tag.get_text(strip=True)
            if txt and txt not in ("Company Profile", "Equity Profile", "Announcements",
                                   "Financials", "Ratios", "Payouts", "Financial Reports",
                                   "No record found", "Submitting ...", "Disclaimer"):
                name = txt
                break

    # Sector from <div class="quote__sector">
    sector = None
    sector_div = soup.find("div", class_="quote__sector")
    if sector_div:
        sector = sector_div.get_text(strip=True) or None

    # Shares from equity section: "Shares 1,465,000,000"
    listed = None
    equity_div = soup.find("div", class_=lambda c: c and "companyEquity" in " ".join(c if isinstance(c, list) else [c]))
    if equity_div:
        eq_text = equity_div.get_text(" ")
        m = re.search(r"Shares\s+([\d,]+)", eq_text)
        if m:
            listed = _i(m.group(1))

    # Also try free float
    free_float = None
    if equity_div:
        eq_text = equity_div.get_text(" ")
        m_ff = re.search(r"Free Float\s+([\d,]+)", eq_text)
        if m_ff:
            free_float = _i(m_ff.group(1))

    return CompanyInfo(
        symbol=symbol.upper(),
        name=name,
        sector=sector,
        listed_shares=listed if listed else None,
        free_float=free_float if free_float else None,
    )


def parse_financials(symbol: str, html: str) -> Fundamentals:
    """Parse EPS, P/E, P/B from dps.psx.com.pk/company/<SYM>.
    - P/E Ratio (TTM): appears as "P/E Ratio (TTM) ** 38.10"
    - EPS: in financial tables (Financials section), most recent annual
    - P/B: may appear as text in ratios or fundamentals section
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    def find(label_regex: str) -> Optional[float]:
        m = re.search(rf"{label_regex}[^0-9\-]*(-?\d+(?:\.\d+)?)", text, re.I)
        return float(m.group(1)) if m else None

    # P/E specifically looks like "P/E Ratio (TTM) ** 38.10"
    pe = find(r"P/E\s*Ratio\s*\(TTM\)")
    if pe is None:
        pe = find(r"P\s*/\s*E")

    # EPS from financial tables: look for "EPS" row in financial table
    # The financial table TABLE 4 has: Sales, Profit after Taxation, EPS
    eps = None
    for table in soup.find_all("table"):
        for tr in (table.find("tbody") or table).find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if cells and cells[0].strip().upper() == "EPS" and len(cells) >= 2:
                eps = _f(cells[1])  # most recent year
                if eps is not None:
                    break
        if eps is not None:
            break

    # Fallback: EPS from text
    if eps is None:
        eps = find(r"EPS\b")

    pb = find(r"P\s*/\s*B")
    div_yield = find(r"Dividend\s*Yield")
    payout = find(r"Payout\s*Ratio")
    roe = find(r"ROE\b")

    return Fundamentals(
        symbol=symbol.upper(),
        eps=eps,
        pe=pe,
        pb=pb,
        div_yield=div_yield,
        payout=payout,
        roe=roe,
        refreshed_at=datetime.now(),
    )


def parse_financial_statements(symbol: str, period: str, html: str) -> list[FinancialStatement]:
    """Scrape annual/quarterly financial statements from the PSX company page.
    Returns empty list if no statements found.

    Annual tables have year headers like '2025', '2024'.
    Quarterly tables have headers like 'Q3 2026', 'Q2 2026'.
    """
    if period not in ("annual", "quarterly"):
        raise ValueError("period must be 'annual' or 'quarterly'")
    soup = BeautifulSoup(html, "lxml")
    statements: list[FinancialStatement] = []

    for table in soup.find_all("table"):
        header = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        if not header or len(header) < 2:
            continue

        # For annual: look for year-only headers like "2025", "2024"
        # For quarterly: look for quarter headers like "Q3 2026", "Q2 2026"
        period_cols: list[tuple[int, date]] = []

        for i, h in enumerate(header):
            h_stripped = h.strip()
            if period == "annual":
                # Match standalone year: "2025" (not "Q3 2026")
                m = re.match(r"^(20\d{2})$", h_stripped)
                if m:
                    period_cols.append((i, date(int(m.group(1)), 6, 30)))
            else:  # quarterly
                # Match quarter patterns: "Q3 2026", "Q1 2025"
                m = re.match(r"Q(\d)\s+(20\d{2})", h_stripped)
                if m:
                    q, yr = int(m.group(1)), int(m.group(2))
                    # Quarter end month: Q1→Sep, Q2→Dec, Q3→Mar, Q4→Jun (PSX fiscal year Jul-Jun)
                    q_end_month = {1: 9, 2: 12, 3: 3, 4: 6}.get(q, 12)
                    q_yr = yr if q_end_month >= 7 else yr
                    period_cols.append((i, date(q_yr, q_end_month, 28)))

        if not period_cols:
            continue

        items_by_period: dict[date, dict[str, float]] = {pe: {} for _, pe in period_cols}
        for tr in (table.find("tbody") or table).find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            label = cells[0].strip()
            for col_idx, pe in period_cols:
                if col_idx < len(cells):
                    # Clean parentheses-wrapped negatives: "(56.08)" -> "-56.08"
                    raw_val = cells[col_idx].strip()
                    raw_val = re.sub(r"^\((.+)\)$", r"-\1", raw_val)
                    v = _f(raw_val)
                    if v is not None and label:
                        items_by_period[pe][label] = v

        for pe, items in items_by_period.items():
            if items:
                statements.append(FinancialStatement(
                    symbol=symbol.upper(), period=period, period_end=pe, line_items=items,
                ))
    return statements
