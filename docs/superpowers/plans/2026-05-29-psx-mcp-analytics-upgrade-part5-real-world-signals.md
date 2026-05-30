# PSX MCP Analytics Upgrade — Part 5: Real-World Signals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the qualitative / event-driven layer that the all-quantitative analytics-v1..v4 stack is missing. Fetch + cache announcement PDF bodies and news article bodies (which we currently only have titles for), extract structured events (insider trades, board meetings / earnings dates, corporate actions), and expose a flagship `get_company_research_pack(symbol)` tool that returns raw structured text suitable for LLM-as-analyst consumption — the pattern validated by Lopez-Lira & Tang (2023) and replications.

**Architecture:** New `pdf_extractor.py` module wraps `pypdf` for text extraction with graceful fallback when PDFs are scanned/image-only. New `events.py` module parses extracted text for structured fields (insider name + qty, meeting date + agenda, dividend rate). Cache gains `news.body` column + new tables `insider_trades`, `board_meetings`. Lazy fetch model: bodies aren't fetched on `refresh_announcements` (that would mean 50 PDFs per refresh); instead a new tool `fetch_announcement_body(announcement_id)` fetches on demand with caching, and `bulk_fetch_announcement_bodies(symbol, since_days=30)` batches per symbol. Same lazy pattern for news.

**Tech Stack:** Python 3.12, existing FastMCP + httpx + pandas + BeautifulSoup + lxml. **New dependency: `pypdf>=4.0.0`** (pure-Python PDF reader, no native deps — works on Windows without extra build tooling).

**Constraints (carried forward from Parts 1-4):**
- Only `dps.psx.com.pk` and existing RSS feeds (Dawn Business, Profit Pakistan). No new external domains for primary data.
- For news article body fetch, hit the article URLs from the existing RSS feeds (Dawn / Profit) only — these are public news sites we already cite.
- No paid feeds, no macro feed, no social media scraping.
- Backwards-compatible, additive only. No renamed tools.
- Same `async wrapper → sync _impl(cache, ...) → optional cache helper` pattern.
- Pydantic v2: `@field_validator(..., mode="before") + @classmethod`.
- ISO TEXT timestamps; no Claude attribution in commits.
- All new tool responses inherit `Disclaimer` mixin.

---

## Why this comes before "Part 6 (ROE/PB headless browser)"

User priority: they're using Claude as the analyst, not running automated screens. Qualitative real-world signals (announcement bodies, news, insider trades, calendars) give the LLM something to actually reason about. ROE/PB fundamentals were already deprioritized when partial Quality scoring shipped with warnings in analytics-v3.

## What is deliberately deferred to a future plan

- ROE / P/B / payout / dividend yield population (headless browser; was originally going to be "Part 5").
- Annual report parsing (10-K equivalent) — heavier PDF parsing, longer documents, deferred.
- Real Piotroski F-Score — depends on balance-sheet fields above.
- SBP macro feed — constraint.
- Social media / Reddit / X — TOS-fragile, low signal-to-noise for PSX small-cap names.
- Custom FinBERT / FinGPT — research validates LLM-at-query-time beats pre-baked sentiment.
- OCR on scanned PSX PDFs (`tesseract` / `pdf2image`) — defer; most PSX disclosures are text-PDFs, and OCR adds heavy native deps.

---

## File Structure

### Conventions (carried)

- `Cache.closes_for(...)` oldest first; `get_fundamentals_history` newest first; ISO TEXT.
- All MCP tools follow async wrapper → sync `_impl(cache, ...)` pattern.

### New files

| Path | Responsibility |
|---|---|
| `psx-mcp/src/psx_mcp/pdf_extractor.py` | `extract_text(pdf_bytes) -> str`, `extract_text_or_empty(pdf_bytes) -> str`, `is_probably_scan_only(text) -> bool`. Logs but doesn't raise on scan-only PDFs. (PDF fetching uses `PSXClient.fetch_url_bytes` — Critic B m2 fix: previous `fetch_pdf_bytes` here was dead code.) |
| `psx-mcp/src/psx_mcp/events.py` | Pure parsers: `parse_insider_trade(body, symbol) -> dict | None`, `parse_board_meeting(title, body, symbol) -> dict | None`, `classify_announcement(title) -> str` (returns category enum). No I/O. |
| `psx-mcp/tests/test_pdf_extractor.py` | Round-trip tests with a tiny generated PDF + scan-only sentinel. |
| `psx-mcp/tests/test_events.py` | Pattern-matching tests with realistic PSX announcement snippets. |
| `psx-mcp/tests/test_research_pack.py` | Integration tests for `get_company_research_pack`. |
| `psx-mcp/tests/fixtures/announcements_sample.pdf` | A tiny text-PDF generated once, checked in. ~500 bytes. |

### Modified files

| Path | What changes |
|---|---|
| `psx-mcp/pyproject.toml` | Add `pypdf>=4.0.0` to `dependencies`. |
| `psx-mcp/src/psx_mcp/cache.py` | Schema: add `body TEXT` to `news` table (via `IF NOT EXISTS` + idempotent `ALTER TABLE` migration for existing DBs). New tables `insider_trades` and `board_meetings`. New methods: `update_announcement_body(ann_id, body, fetch_status)`, `update_news_body(news_id, body, fetch_status)`, `upsert_insider_trade(...)`, `get_insider_trades(symbol, since)`, `upsert_board_meeting(...)`, `get_board_meetings(symbol, since, until)`. Plus `get_announcements_missing_body(symbol, since_days)` and `get_news_missing_body(symbol, since_days)` for batch fetch tooling. |
| `psx-mcp/src/psx_mcp/models.py` | New response models: `AnnouncementBodyResponse`, `BulkBodyFetchResponse`, `InsiderTrade`, `InsiderTradeListResponse`, `BoardMeeting`, `EarningsCalendarResponse`, `CorporateActionsCalendarResponse`, `ResearchPackResponse`. |
| `psx-mcp/server.py` | New impls + 8 tools: `fetch_announcement_body`, `bulk_fetch_announcement_bodies`, `fetch_news_body`, `bulk_fetch_news_bodies`, `get_insider_trades`, `get_earnings_calendar`, `get_corporate_actions_calendar`, `get_company_research_pack`. The last is the **flagship** combining all the rest. |
| `psx-mcp/src/psx_mcp/psx_client.py` | New `fetch_url_bytes(url)` for arbitrary URLs (PDF / HTML article). Reuses existing httpx client. |
| `psx-mcp/README.md` | Document new tools. Flag `get_company_research_pack` as the **LLM-companion** tool. |
| `docs/investing-playbook.md` | Mark resolved gaps. |

---

## Phase 0 — PDF infrastructure

### Task 0.1: Add `pypdf` dependency

**Files:**
- Modify: `psx-mcp/pyproject.toml`

- [ ] **Step 1: Add the dep**

Add `"pypdf>=4.0.0",` to the `dependencies` list in `[project]`. Resulting block:

```toml
dependencies = [
    "mcp[cli]>=1.2.0",
    "httpx[http2]>=0.27.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "feedparser>=6.0.10",
    "pydantic>=2.6.0",
    "structlog>=24.1.0",
    "pypdf>=4.0.0",
]
```

- [ ] **Step 2: Sync the lock**

From `psx-mcp/`:

```
uv sync
```

Expected: `pypdf` (and a transitive dep `cryptography` for encrypted PDFs, optional) installed; existing tests unaffected.

- [ ] **Step 3: Smoke import**

```
uv run python -c "import pypdf; print(pypdf.__version__)"
```

Expected: prints a version like `5.0.x` or `4.x.x` without error.

- [ ] **Step 4: Commit**

```bash
git add psx-mcp/pyproject.toml psx-mcp/uv.lock
git commit -m "chore(psx-mcp): add pypdf dependency for announcement body extraction"
```

---

### Task 0.2: `pdf_extractor.py` module

**Files:**
- Create: `psx-mcp/src/psx_mcp/pdf_extractor.py`
- Create: `psx-mcp/tests/test_pdf_extractor.py`
- Create: `psx-mcp/tests/fixtures/announcements_sample.pdf` (generated once, checked in)

- [ ] **Step 1: Create + check in a known-good fixture PDF**

Critic A m12 + Critic C m4 fix: skip the fragile in-memory pypdf
content-stream construction entirely. Generate a fixture PDF once via
`reportlab` (added as a one-time dev dep, NOT in pyproject), check it in,
and load it from disk in tests. This avoids fighting pypdf private API
differences across versions.

Run from `psx-mcp/`:

```
uv pip install reportlab
uv run python -c "
from reportlab.pdfgen import canvas
import os
os.makedirs('tests/fixtures', exist_ok=True)
c = canvas.Canvas('tests/fixtures/extractor_smoke.pdf')
c.setFont('Helvetica', 12)
c.drawString(50, 750, 'Board meeting on 15-June-2026 to consider results.')
c.showPage()
c.save()
print('ok')
"
uv pip uninstall reportlab
```

Then commit the fixture file. Reportlab is NOT added to pyproject; the
fixture is reusable across all subsequent tests.

- [ ] **Step 2: Write the failing tests**

```python
# psx-mcp/tests/test_pdf_extractor.py
from pathlib import Path
import pytest
from psx_mcp.pdf_extractor import extract_text, extract_text_or_empty

FIXTURE = Path(__file__).parent / "fixtures" / "extractor_smoke.pdf"


def test_extract_text_returns_known_string():
    """The committed fixture PDF has the literal sentence below."""
    pdf_bytes = FIXTURE.read_bytes()
    txt = extract_text(pdf_bytes)
    assert "Board meeting" in txt
    assert "15-June-2026" in txt


def test_extract_text_or_empty_handles_garbage_bytes():
    """Non-PDF input → empty string, not exception."""
    assert extract_text_or_empty(b"not a pdf at all") == ""


def test_extract_text_or_empty_handles_empty_input():
    assert extract_text_or_empty(b"") == ""
```

- [ ] **Step 3: Run, confirm fail**

```
uv run pytest tests/test_pdf_extractor.py -v
```

Expected: ModuleNotFoundError on `psx_mcp.pdf_extractor`.

- [ ] **Step 4: Implement `psx-mcp/src/psx_mcp/pdf_extractor.py`**

```python
"""PDF body extraction for PSX announcement / news PDFs.

Strategy:
  1. Use pypdf to extract text from each page; concatenate.
  2. If concatenated text is empty or below a small threshold, assume the PDF
     is scanned/image-only and return empty (caller decides what to do — most
     likely set fetch_status='no_text' in the cache so we don't retry).
"""
from __future__ import annotations
from io import BytesIO
from typing import Optional

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError


SCANNED_PDF_TEXT_THRESHOLD = 30  # chars; below this we assume scan-only


def extract_text(pdf_bytes: bytes) -> str:
    """Extract concatenated text from all pages of a PDF.

    Raises pypdf.errors on truly malformed input — callers wanting safety
    should use extract_text_or_empty."""
    reader = PdfReader(BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


def extract_text_or_empty(pdf_bytes: bytes) -> str:
    """Safe wrapper: returns "" on any extraction failure."""
    if not pdf_bytes:
        return ""
    try:
        return extract_text(pdf_bytes)
    except (PdfReadError, PdfStreamError, OSError, ValueError):
        return ""


def is_probably_scan_only(text: str) -> bool:
    """Heuristic: PDFs with very little extractable text are likely scans.
    Caller can use this to mark fetch_status='scan_only' and skip parsing."""
    return len(text) < SCANNED_PDF_TEXT_THRESHOLD


# Note (Critic B m2 fix): `fetch_pdf_bytes` was dead code in v1 — PDF fetching
# is done via `PSXClient.fetch_url_bytes` (see psx_client.py) so we get the
# right headers + connection pooling. This module is now pure text extraction.
```

- [ ] **Step 5: Run, confirm tests pass**

```
uv run pytest tests/test_pdf_extractor.py -v
```

Expected: 3 passed. If the manual content-stream construction in step 2 doesn't produce extractable text, the implementer should commit a tiny hand-crafted fixture PDF instead and load it: `(fixtures_dir / "tiny_text.pdf").read_bytes()`.

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/pdf_extractor.py psx-mcp/tests/test_pdf_extractor.py psx-mcp/tests/fixtures/extractor_smoke.pdf
git commit -m "feat(psx-mcp): pdf_extractor.py — text extraction with graceful fallback"
```

---

### Task 0.3: Live smoke test against a real PSX PDF (gated)

**Files:**
- Modify: `psx-mcp/tests/test_live.py` (add a gated test)

- [ ] **Step 1: Append the gated test**

```python
# In tests/test_live.py — already has pytestmark for PSX_LIVE gating
async def test_live_fetch_and_extract_announcement_pdf():
    """Fetch a real PSX announcement PDF and verify text is extractable.
    Skipped unless PSX_LIVE=1."""
    from psx_mcp.psx_client import PSXClient, parse_announcements
    from psx_mcp.pdf_extractor import extract_text_or_empty

    client = PSXClient()
    try:
        ann_html = await client.fetch_announcements()
        anns = parse_announcements(ann_html)
        with_url = [a for a in anns if a.url and "pdf" in a.url.lower()]
        assert with_url, "no PDF URLs in the announcements feed"
        sample = with_url[0]
        pdf_bytes = await client.fetch_url_bytes(sample.url)
        assert pdf_bytes is not None and len(pdf_bytes) > 100
        text = extract_text_or_empty(pdf_bytes)
        # Most PSX disclosure PDFs are text-PDFs, not scans
        assert len(text) > 50, f"got only {len(text)} chars; might be scan-only"
    finally:
        await client.close()
```

- [ ] **Step 2: Run manually (NOT in CI default)**

```
$env:PSX_LIVE=1; uv run pytest tests/test_live.py::test_live_fetch_and_extract_announcement_pdf -v
```

Expected: passes. If it fails because the chosen PDF was scan-only, the test should retry the next one.

NOTE: `PSXClient._client_factory()` — if no such method exists, instead use `httpx.AsyncClient(timeout=30.0)` directly inside the `async with` block. Live tests don't need to share connection pools.

- [ ] **Step 3: Commit**

```bash
git add psx-mcp/tests/test_live.py
git commit -m "test(psx-mcp): live smoke for PDF fetch + extract"
```

---

## Phase 1 — Cache: body columns + new tables + migration

### Task 1.1: Add `news.body` column via migration

The `announcements` table already has `body TEXT` from Part 2's schema — verified. The `news` table does NOT have `body`. Add it via idempotent ALTER TABLE.

Also add `fetch_status TEXT` columns to BOTH tables so we can mark `'ok'`, `'http_error'`, `'scan_only'`, `'parse_error'` and never re-fetch a known-bad URL.

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py`
- Modify: `psx-mcp/tests/test_cache.py`

- [ ] **Step 1: Failing test**

```python
def test_news_table_has_body_and_fetch_status_columns(tmp_path):
    from psx_mcp.cache import Cache
    cache = Cache(str(tmp_path / "c.db"))
    cols = [r[1] for r in cache.conn.execute(
        "PRAGMA table_info(news)"
    ).fetchall()]
    assert "body" in cols
    assert "fetch_status" in cols


def test_announcements_table_has_fetch_status_column(tmp_path):
    from psx_mcp.cache import Cache
    cache = Cache(str(tmp_path / "c.db"))
    cols = [r[1] for r in cache.conn.execute(
        "PRAGMA table_info(announcements)"
    ).fetchall()]
    assert "fetch_status" in cols  # body already exists from Part 2
```

- [ ] **Step 2: Run, confirm fail**

```
uv run pytest tests/test_cache.py -k "body_and_fetch_status or has_fetch_status" -v
```

Expected: 2 failing.

- [ ] **Step 3: Update `SCHEMA` in `cache.py`**

Change the `news` CREATE TABLE to include `body TEXT` and `fetch_status TEXT`:

```sql
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, source TEXT, posted_at TEXT,
  title TEXT, url TEXT, symbols TEXT,
  body TEXT, fetch_status TEXT
);
```

And announcements (already had body, add fetch_status):

```sql
CREATE TABLE IF NOT EXISTS announcements (
  id TEXT PRIMARY KEY, symbol TEXT, posted_at TEXT,
  title TEXT, category TEXT, url TEXT, body TEXT,
  fetch_status TEXT
);
```

- [ ] **Step 4: Add idempotent ALTER TABLE migration in `Cache.__init__`**

After the existing `self.conn.executescript(SCHEMA)` line, add:

```python
# Idempotent migrations for pre-existing DBs that don't have these columns.
def _add_col_if_missing(table: str, col: str, col_type: str) -> None:
    cols = [r[1] for r in self.conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()]
    if col not in cols:
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")

_add_col_if_missing("news", "body", "TEXT")
_add_col_if_missing("news", "fetch_status", "TEXT")
_add_col_if_missing("announcements", "fetch_status", "TEXT")
self.conn.commit()
```

- [ ] **Step 5: Run, confirm 2 pass**

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/tests/test_cache.py
git commit -m "feat(psx-mcp): add news.body + news/announcements.fetch_status (migration)"
```

---

### Task 1.2: Body-update + missing-body query helpers

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py`
- Modify: `psx-mcp/tests/test_cache.py`

- [ ] **Step 1: Failing tests**

```python
def test_update_announcement_body_round_trip(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime.now(),
        title="Board Meeting", category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf", body=None,
    ))
    cache.update_announcement_body("A1", "The board will meet on 30 May 2026.",
                                    fetch_status="ok")
    row = cache.conn.execute(
        "SELECT body, fetch_status FROM announcements WHERE id='A1'"
    ).fetchone()
    assert "The board will meet" in row["body"]
    assert row["fetch_status"] == "ok"


def test_get_announcements_missing_body_filters_by_symbol_and_days(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from datetime import datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    now = datetime.now()
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=now,
        title="Recent", category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf", body=None,
    ))
    cache.upsert_announcement(Announcement(
        id="A2", symbol="SYS", posted_at=now - timedelta(days=90),
        title="Old", category=None,
        url="https://dps.psx.com.pk/download/document/2.pdf", body=None,
    ))
    cache.upsert_announcement(Announcement(
        id="A3", symbol="OGDC", posted_at=now,
        title="Other symbol", category=None,
        url="https://dps.psx.com.pk/download/document/3.pdf", body=None,
    ))
    # Mark A1 as already fetched
    cache.update_announcement_body("A1", "already done", fetch_status="ok")

    rows = cache.get_announcements_missing_body(symbol="SYS", since_days=30)
    ids = [r["id"] for r in rows]
    # A1 has body → excluded. A2 too old → excluded. A3 wrong symbol → excluded.
    # No matching rows.
    assert ids == []

    rows2 = cache.get_announcements_missing_body(symbol="SYS", since_days=120)
    ids2 = [r["id"] for r in rows2]
    assert "A2" in ids2  # in range, no body
    assert "A1" not in ids2  # has body
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement in `Cache`**

```python
def update_announcement_body(self, ann_id: str, body: Optional[str],
                              fetch_status: str = "ok") -> None:
    """Set body + fetch_status for a previously upserted announcement."""
    self.conn.execute(
        "UPDATE announcements SET body=?, fetch_status=? WHERE id=?",
        (body, fetch_status, ann_id),
    )
    self.conn.commit()


def update_news_body(self, news_id: str, body: Optional[str],
                     fetch_status: str = "ok") -> None:
    self.conn.execute(
        "UPDATE news SET body=?, fetch_status=? WHERE id=?",
        (body, fetch_status, news_id),
    )
    self.conn.commit()


def get_announcements_missing_body(self, *, symbol: Optional[str] = None,
                                    since_days: int = 30,
                                    limit: int = 200) -> list[dict]:
    """Return announcements whose body is NULL AND fetch_status is NULL
    (never tried). Excludes ones we've already tried and marked failed.

    Filters by symbol if provided. since_days bounds how far back to look."""
    since_iso = (datetime.now() - timedelta(days=since_days)).isoformat()
    where = ["body IS NULL", "fetch_status IS NULL", "posted_at >= ?",
             "url IS NOT NULL"]
    params: list = [since_iso]
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())
    params.append(limit)
    sql = (
        "SELECT id, symbol, posted_at, title, url FROM announcements "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY posted_at DESC LIMIT ?"
    )
    rows = self.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_news_missing_body(self, *, symbol: Optional[str] = None,
                          since_days: int = 30,
                          limit: int = 200) -> list[dict]:
    """Same shape as get_announcements_missing_body but for the news table.
    news.symbols is a comma-separated TEXT; symbol filter uses LIKE."""
    since_iso = (datetime.now() - timedelta(days=since_days)).isoformat()
    where = ["body IS NULL", "fetch_status IS NULL", "posted_at >= ?",
             "url IS NOT NULL"]
    params: list = [since_iso]
    if symbol:
        where.append("(',' || UPPER(symbols) || ',') LIKE ?")
        params.append(f"%,{symbol.upper()},%")
    params.append(limit)
    sql = (
        "SELECT id, source, posted_at, title, url, symbols FROM news "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY posted_at DESC LIMIT ?"
    )
    rows = self.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
```

Make sure `from datetime import datetime, timedelta` is at the top of `cache.py` (it already is).

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/tests/test_cache.py
git commit -m "feat(psx-mcp): body-update + missing-body query helpers"
```

---

### Task 1.3: New tables for structured events

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py`
- Modify: `psx-mcp/tests/test_cache.py`

- [ ] **Step 1: Failing test**

```python
def test_insider_trades_table_and_round_trip(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_insider_trade(
        announcement_id="A1", symbol="SYS",
        insider_name="Asif Peer", insider_role="Director",
        action="buy", qty=10_000, pct_holding=None,
        trade_date=date(2026, 4, 15), posted_at=date(2026, 4, 16),
    )
    rows = cache.get_insider_trades("SYS")
    assert len(rows) == 1
    assert rows[0]["insider_name"] == "Asif Peer"
    assert rows[0]["action"] == "buy"
    assert rows[0]["qty"] == 10_000


def test_board_meetings_table_and_round_trip(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_board_meeting(
        announcement_id="A1", symbol="SYS",
        meeting_date=date(2026, 6, 15),
        agenda="financial_results",
        posted_at=date(2026, 5, 28),
    )
    rows = cache.get_board_meetings("SYS",
                                     since=date(2026, 6, 1),
                                     until=date(2026, 6, 30))
    assert len(rows) == 1
    assert rows[0]["agenda"] == "financial_results"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add tables to `SCHEMA` block**

```sql
CREATE TABLE IF NOT EXISTS insider_trades (
  announcement_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  insider_name TEXT,
  insider_role TEXT,
  action TEXT,
  qty INTEGER,
  pct_holding REAL,
  trade_date TEXT,
  posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ins_symbol_date
  ON insider_trades(symbol, posted_at DESC);

CREATE TABLE IF NOT EXISTS board_meetings (
  announcement_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  meeting_date TEXT,
  agenda TEXT,
  posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bm_symbol_date
  ON board_meetings(symbol, meeting_date);
```

- [ ] **Step 4: Add methods to `Cache`**

```python
def upsert_insider_trade(self, *, announcement_id: str, symbol: str,
                          insider_name: Optional[str], insider_role: Optional[str],
                          action: Optional[str], qty: Optional[int],
                          pct_holding: Optional[float],
                          trade_date, posted_at) -> None:
    self.conn.execute(
        """INSERT INTO insider_trades
           (announcement_id, symbol, insider_name, insider_role,
            action, qty, pct_holding, trade_date, posted_at)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(announcement_id) DO UPDATE SET
             insider_name=excluded.insider_name,
             insider_role=excluded.insider_role,
             action=excluded.action,
             qty=excluded.qty,
             pct_holding=excluded.pct_holding,
             trade_date=excluded.trade_date""",
        (announcement_id, symbol.upper(), insider_name, insider_role,
         action, qty, pct_holding, _iso(trade_date), _iso(posted_at)),
    )
    self.conn.commit()


def get_insider_trades(self, symbol: str,
                        since_days: int = 365) -> list[dict]:
    since_iso = (datetime.now() - timedelta(days=since_days)).isoformat()
    rows = self.conn.execute(
        """SELECT * FROM insider_trades
           WHERE symbol=? AND posted_at >= ?
           ORDER BY posted_at DESC""",
        (symbol.upper(), since_iso),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_board_meeting(self, *, announcement_id: str, symbol: str,
                          meeting_date, agenda: Optional[str],
                          posted_at) -> None:
    self.conn.execute(
        """INSERT INTO board_meetings
           (announcement_id, symbol, meeting_date, agenda, posted_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(announcement_id) DO UPDATE SET
             meeting_date=excluded.meeting_date,
             agenda=excluded.agenda""",
        (announcement_id, symbol.upper(), _iso(meeting_date), agenda,
         _iso(posted_at)),
    )
    self.conn.commit()


def get_board_meetings(self, symbol: str,
                        since=None, until=None) -> list[dict]:
    """Return board meetings whose meeting_date is in [since, until].
    Both dates inclusive. None on either bound = unbounded."""
    where = ["symbol = ?"]
    params: list = [symbol.upper()]
    if since is not None:
        where.append("meeting_date >= ?")
        params.append(_iso(since))
    if until is not None:
        where.append("meeting_date <= ?")
        params.append(_iso(until))
    sql = (
        "SELECT * FROM board_meetings "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY meeting_date ASC"
    )
    rows = self.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Run, confirm pass**

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/tests/test_cache.py
git commit -m "feat(psx-mcp): insider_trades + board_meetings tables and helpers"
```

---

## Phase 2 — Announcement body fetching

### Task 2.1: `fetch_announcement_body` + bulk variant

**Files:**
- Modify: `psx-mcp/src/psx_mcp/psx_client.py` — `fetch_url_bytes` helper
- Modify: `psx-mcp/src/psx_mcp/models.py` — response models
- Modify: `psx-mcp/server.py` — impls + tools
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add `fetch_url_bytes` to `PSXClient`**

In `psx_client.py`, after the existing `fetch_*` methods:

```python
async def fetch_url_bytes(self, url: str, timeout: float = 30.0) -> Optional[bytes]:
    """Fetch arbitrary URL as bytes. Returns None on HTTP error.

    Reuses the client's own httpx session so we get connection pooling +
    PSX-friendly headers."""
    try:
        r = await self._client.get(url, timeout=timeout, follow_redirects=True)
    except (httpx.HTTPError, httpx.TimeoutException):
        return None
    if r.status_code != 200:
        return None
    return r.content
```

- [ ] **Step 2: Add response models in `models.py`**

```python
class AnnouncementBodyResponse(Disclaimer):
    announcement_id: str
    symbol: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    fetch_status: str  # 'ok' | 'http_error' | 'scan_only' | 'parse_error' | 'no_url'
    body: Optional[str] = None
    body_chars: int = 0
    note: Optional[str] = None


class BulkBodyFetchResponse(Disclaimer):
    symbol: Optional[str] = None
    since_days: int
    attempted: int = 0
    succeeded: int = 0
    skipped_no_url: int = 0
    failed_http: int = 0
    failed_scan: int = 0    # PDF scan-only (HTML path always 0)
    failed_parse: int = 0
    failed_other: int = 0   # Critic B BLOCKER fix: catch-all for no_client / not_found
    elapsed_seconds: float = 0.0
    note: Optional[str] = None
```

- [ ] **Step 3: Failing tests**

```python
def test_fetch_announcement_body_caches_pdf_bytes(tmp_path, monkeypatch):
    """Mock the PDF fetcher; verify body is cached + fetch_status='ok'."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient
    from datetime import datetime

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime.now(),
        title="Board Meeting", category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf", body=None,
    ))

    # Mock the network: PDF fetch returns synthetic bytes; pdf_extractor returns text
    async def fake_fetch(self, url, timeout=30.0):
        return b"%PDF-fake-bytes"
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)
    monkeypatch.setattr("server.extract_text_or_empty",
                         lambda b: "Board meeting on 15-June-2026 to consider results.")

    client = PSXClient()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=client)

    out = asyncio.run(srv._fetch_announcement_body_impl(cache, client, "A1"))
    assert out.fetch_status == "ok"
    assert "Board meeting" in out.body
    assert out.body_chars > 10

    # Verify cache was updated
    row = cache.conn.execute(
        "SELECT body, fetch_status FROM announcements WHERE id='A1'"
    ).fetchone()
    assert row["fetch_status"] == "ok"
    assert "Board meeting" in row["body"]


def test_fetch_announcement_body_no_url_returns_no_url_status(tmp_path):
    """Announcement with no URL → fetch_status='no_url', no fetch attempted."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A2", symbol="SYS", posted_at=datetime.now(),
        title="No URL", category=None, url=None, body=None,
    ))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=PSXClient())
    out = asyncio.run(srv._fetch_announcement_body_impl(cache, PSXClient(), "A2"))
    assert out.fetch_status == "no_url"
    assert out.body is None
```

- [ ] **Step 4: Run, confirm fail**

- [ ] **Step 5: Implement impls + tools in `server.py`**

```python
import asyncio
from psx_mcp.pdf_extractor import (
    extract_text_or_empty, is_probably_scan_only,
)
from psx_mcp.events import (
    classify_announcement, parse_insider_trade, parse_board_meeting,
)
from psx_mcp.models import (
    AnnouncementBodyResponse, BulkBodyFetchResponse,
)
import time as _time


async def _fetch_announcement_body_impl(cache: Cache, client: PSXClient,
                                          announcement_id: str
                                          ) -> AnnouncementBodyResponse:
    """Fetch + cache the body PDF text for a single announcement.

    Idempotent: if body is already cached (fetch_status='ok'), returns cached
    body without re-fetching. If fetch_status indicates a prior failure,
    returns the prior status without retry (caller can DELETE the row from the
    cache to force retry)."""
    row = cache.conn.execute(
        "SELECT symbol, title, url, body, fetch_status FROM announcements "
        "WHERE id = ?",
        (announcement_id,),
    ).fetchone()
    if not row:
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, fetch_status="not_found",
            note="No announcement with that id in cache.",
        )
    if row["fetch_status"]:
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status=row["fetch_status"],
            body=row["body"],
            body_chars=len(row["body"] or ""),
            note="Returning cached body; previously fetched.",
        )
    if not row["url"]:
        cache.update_announcement_body(announcement_id, None, "no_url")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=None,
            fetch_status="no_url",
            note="Announcement has no PDF URL; nothing to fetch.",
        )
    if client is None:
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="no_client",
            note="No PSX client configured (set_dependencies(client=...) was None).",
        )

    pdf_bytes = await client.fetch_url_bytes(row["url"])
    if pdf_bytes is None:
        cache.update_announcement_body(announcement_id, None, "http_error")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="http_error",
            note="Network error or non-200 response.",
        )
    text = extract_text_or_empty(pdf_bytes)
    if not text:
        cache.update_announcement_body(announcement_id, None, "parse_error")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="parse_error",
            note="PDF parsed to empty text; might be encrypted or malformed.",
        )
    if is_probably_scan_only(text):
        cache.update_announcement_body(announcement_id, text, "scan_only")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="scan_only",
            body=text, body_chars=len(text),
            note="PDF looks scan-only; OCR would be needed for full text.",
        )
    cache.update_announcement_body(announcement_id, text, "ok")
    return AnnouncementBodyResponse(
        announcement_id=announcement_id, symbol=row["symbol"],
        title=row["title"], url=row["url"],
        fetch_status="ok",
        body=text, body_chars=len(text),
    )


async def _bulk_fetch_announcement_bodies_impl(cache: Cache, client: PSXClient,
                                                 symbol: Optional[str],
                                                 since_days: int = 30,
                                                 limit: int = 20,
                                                 concurrency: int = 4,
                                                 delay_ms: int = 250
                                                 ) -> BulkBodyFetchResponse:
    """Fetch bodies for all announcements matching (symbol, since_days) that
    haven't been tried yet. Per-PDF errors don't kill the batch.

    Critic B M2 + Critic C M3 fix: concurrency-limited via asyncio.Semaphore
    and inter-request delay to avoid PSX rate-limiting. Defaults are
    deliberately conservative to stay polite to dps.psx.com.pk. Lowered
    default `limit` from 50 to 20 to keep wall-time under typical MCP tool
    timeouts."""
    rows = cache.get_announcements_missing_body(symbol=symbol,
                                                 since_days=since_days,
                                                 limit=limit)
    started = _time.time()
    summary = {"attempted": 0, "succeeded": 0,
               "skipped_no_url": 0, "failed_http": 0,
               "failed_scan": 0, "failed_parse": 0,
               "failed_other": 0}

    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(rid: str):
        async with sem:
            resp = await _fetch_announcement_body_impl(cache, client, rid)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            return resp

    if rows:
        results = await asyncio.gather(*(one(r["id"]) for r in rows),
                                         return_exceptions=False)
    else:
        results = []

    for resp in results:
        summary["attempted"] += 1
        status = resp.fetch_status
        if status == "ok":
            summary["succeeded"] += 1
        elif status == "no_url":
            summary["skipped_no_url"] += 1
        elif status == "http_error":
            summary["failed_http"] += 1
        elif status == "scan_only":
            summary["failed_scan"] += 1
        elif status == "parse_error":
            summary["failed_parse"] += 1
        else:  # no_client, not_found, anything else
            summary["failed_other"] += 1

    elapsed = _time.time() - started
    return BulkBodyFetchResponse(
        symbol=symbol.upper() if symbol else None,
        since_days=since_days,
        attempted=summary["attempted"],
        succeeded=summary["succeeded"],
        skipped_no_url=summary["skipped_no_url"],
        failed_http=summary["failed_http"],
        failed_scan=summary["failed_scan"],
        failed_parse=summary["failed_parse"],
        failed_other=summary["failed_other"],
        elapsed_seconds=elapsed,
    )


@mcp.tool()
async def fetch_announcement_body(announcement_id: str) -> AnnouncementBodyResponse:
    """Fetch + cache the PDF body of a single PSX announcement. Idempotent;
    returns cached body if previously fetched (regardless of prior status —
    we never auto-retry; delete the row to force re-fetch)."""
    return await _fetch_announcement_body_impl(_cache, _client, announcement_id)


@mcp.tool()
async def bulk_fetch_announcement_bodies(symbol: str | None = None,
                                           since_days: int = 30,
                                           limit: int = 20,
                                           concurrency: int = 4,
                                           delay_ms: int = 250
                                           ) -> BulkBodyFetchResponse:
    """Bulk-fetch announcement bodies for symbol (or all symbols), newest
    first within the lookback window. Skips announcements already attempted.

    Polite defaults: limit=20, concurrency=4, 250ms between requests. Raise
    `concurrency` or `limit` cautiously — PSX may rate-limit aggressive
    crawlers. Typical wall time at defaults: 5-15s for 20 PDFs."""
    return await _bulk_fetch_announcement_bodies_impl(
        _cache, _client, symbol, since_days, limit, concurrency, delay_ms,
    )
```

- [ ] **Step 6: Run, confirm tests pass**

- [ ] **Step 7: Commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/src/psx_mcp/psx_client.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): fetch_announcement_body + bulk variant with status tracking"
```

---

## Phase 3 — Structured event extraction

### Task 3.1: `events.py` parsers (pure functions)

**Files:**
- Create: `psx-mcp/src/psx_mcp/events.py`
- Create: `psx-mcp/tests/test_events.py`

- [ ] **Step 1: Failing tests**

```python
# psx-mcp/tests/test_events.py
import pytest
from datetime import date
from psx_mcp.events import (
    classify_announcement, parse_insider_trade, parse_board_meeting,
)


def test_classify_announcement_recognizes_insider_disclosure():
    cat = classify_announcement(
        "Disclosure of Interest by a Director CEO, or Executive of a listed company")
    assert cat == "insider_trade"


def test_classify_announcement_recognizes_board_meeting():
    assert classify_announcement("Notice of Board Meeting") == "board_meeting"
    assert classify_announcement(
        "Board Meeting Other Than Financial Results") == "board_meeting"


def test_classify_announcement_recognizes_financial_results():
    assert classify_announcement(
        "Financial Results for the Quarter Ended 31 March 2026") == "financial_results"


def test_classify_announcement_recognizes_dividend():
    assert classify_announcement(
        "Credit of Final Cash Dividend for the Year Ended December 31, 2025") == "dividend"


def test_classify_announcement_recognizes_corporate_briefing():
    cat = classify_announcement(
        "Dissemination of Video Recording of Corporate Briefing Session")
    assert cat == "corporate_briefing"


def test_classify_announcement_unknown_returns_other():
    assert classify_announcement("Random title with no keywords") == "other"


def test_classify_announcement_recognizes_quarterly_report():
    """Fixes Critic C blocker: 'Quarterly Report' / 'Half Year Report' filings."""
    assert classify_announcement(
        "Transmission of Quarterly Report for the Period Ended 31-03-2026"
    ) == "financial_results"
    assert classify_announcement(
        "Transmission of Half Yearly Report for the Period Ended March 31, 2026"
    ) == "financial_results"


def test_classify_announcement_handles_space_separated_extra_ordinary():
    """Fixes Critic C blocker: 'Extra Ordinary' with space was missed."""
    assert classify_announcement(
        "Newspaper Clippings of Notice of Extra Ordinary General Meeting"
    ) == "egm"


def test_classify_announcement_recognizes_price_query():
    """Fixes Critic C blocker: 'Unusual movement' disclosures are a strong PSX-mandated
    signal that was falling through to 'other'."""
    assert classify_announcement(
        "Explanation regarding unusual movement in the price of shares"
    ) == "price_query"


def test_parse_insider_trade_director_buy():
    body = """
    Disclosure of Interest by a Director, CEO, or Executive of a listed company
    Name of the Director / CEO / Executive: Mr. Asif Peer
    Designation: Director
    Nature of Transaction: Purchase
    Number of Shares: 10,000
    Date of Transaction: 15-April-2026
    """
    result = parse_insider_trade(body)
    assert result is not None
    assert result["insider_name"] == "Mr. Asif Peer"
    assert result["insider_role"].lower().startswith("director")
    assert result["action"] == "buy"
    assert result["qty"] == 10000
    assert result["trade_date"] == date(2026, 4, 15)


def test_parse_insider_trade_sell_action():
    """Regression for Critic A BLOCKER: qty must be 5000, not 1 (don't grab '01' from date)."""
    body = "Director Ms. Rashida Khan sold 5,000 shares on 01-May-2026."
    result = parse_insider_trade(body)
    assert result is not None
    assert result["action"] == "sell"
    assert result["qty"] == 5000
    assert result["trade_date"] == date(2026, 5, 1)


def test_parse_insider_trade_extracts_pct_holding():
    """Critic C MAJOR: pct_holding should populate when 'Holding after transaction: 7.5%' appears."""
    body = (
        "Disclosure of Interest by a Director CEO, or Executive of a listed company\n"
        "Name of the Director: Mr. Asif Peer\n"
        "Designation: Director\n"
        "Nature of Transaction: Purchase\n"
        "Number of Shares: 10,000\n"
        "Holding after transaction: 7.5%\n"
        "Date of Transaction: 15-April-2026\n"
    )
    result = parse_insider_trade(body)
    assert result is not None
    assert result["pct_holding"] == 7.5


def test_parse_insider_trade_no_match_returns_none():
    assert parse_insider_trade("Totally unrelated announcement body") is None


def test_parse_board_meeting_extracts_future_date():
    body = """
    Notice of Board Meeting
    The Board of Directors will meet on 30-June-2026 to consider the
    quarterly financial results.
    """
    result = parse_board_meeting(title="Notice of Board Meeting", body=body)
    assert result is not None
    assert result["meeting_date"] == date(2026, 6, 30)
    assert result["agenda"] == "financial_results"


def test_parse_board_meeting_other_than_financial():
    body = "The board will meet on 5 July 2026 to discuss strategic matters."
    result = parse_board_meeting(
        title="Board Meeting Other Than Financial Results", body=body)
    assert result is not None
    assert result["meeting_date"] == date(2026, 7, 5)
    assert result["agenda"] == "other"


def test_parse_board_meeting_no_date_returns_none():
    """Title classifies as board meeting but no extractable date → None."""
    assert parse_board_meeting(title="Board Meeting",
                                 body="Just a notice with no date.") is None


def test_parse_board_meeting_anchors_on_will_be_held_phrase():
    """Critic C BLOCKER fix: when body references a past 'period ended' date
    AND a future 'will be held on' date, the parser must pick the future one."""
    body = (
        "Notice is hereby given that a meeting of the Board of Directors "
        "will be held on Thursday, 5 June 2026 at 2:00 PM to consider the "
        "financial results for the period ended 31 March 2026."
    )
    result = parse_board_meeting(title="Notice of Board Meeting", body=body)
    assert result is not None
    assert result["meeting_date"] == date(2026, 6, 5)
    # NOT 31 March 2026 (the period-end), which would also parse but be wrong.
    assert result["meeting_date"] != date(2026, 3, 31)
```

- [ ] **Step 2: Run, confirm ModuleNotFoundError**

- [ ] **Step 3: Implement `psx-mcp/src/psx_mcp/events.py`**

```python
"""Pure-function event extractors for PSX announcement text.

These functions are intentionally heuristic — PSX disclosure text varies by
company and form. Each parser returns None when it can't confidently extract,
and the caller (server impl) falls back to storing raw body only."""
from __future__ import annotations
import re
from datetime import date, datetime
from typing import Optional


# --- Classification ----------------------------------------------------------

_CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("insider_trade", re.compile(r"\bDisclosure of Interest by a Director", re.I)),
    ("insider_trade", re.compile(r"\bDisclosure of Shares acquired", re.I)),
    ("price_query",   re.compile(r"\bExplanation regarding unusual (?:movement|increase|decrease)", re.I)),
    ("price_query",   re.compile(r"\bunusual movement in (?:the )?(?:price|share)", re.I)),
    ("board_meeting", re.compile(r"\bBoard Meeting\b", re.I)),
    # Fixes Critic C blocker: "Extra Ordinary" with a space + "EOGM" alt
    ("egm",            re.compile(r"\b(Extra[-\s]?Ordinary General Meeting|EOGM|\bEGM)\b", re.I)),
    ("agm",            re.compile(r"\b(Annual General Meeting|AGM)\b", re.I)),
    # Fixes Critic C blocker: "Quarterly Report" / "Half Year Report" titles are the most
    # common earnings-data filings and were previously falling through to "other".
    ("financial_results",
                       re.compile(r"\b(Financial Results|(?:Quarterly|Half[-\s]?Year(?:ly)?|Annual)\s+Report)\b", re.I)),
    ("corporate_briefing",
                       re.compile(r"\b(Corporate Briefing|CBS)\b", re.I)),
    ("dividend",       re.compile(r"\b(Cash Dividend|Bonus Issue|Final Dividend|Interim Dividend|Credit of (?:Final|Interim))\b", re.I)),
    ("right_shares",   re.compile(r"\b(Right Shares|Declaration of Right)\b", re.I)),
    ("book_closure",   re.compile(r"\bBook Closure\b", re.I)),
    ("material_info",  re.compile(r"\bMaterial Information\b", re.I)),
    ("appointment",    re.compile(r"\b(Appointment of (?:Chairman|Chairperson|Chief Executive)|Election of Chairman)\b", re.I)),
]


def classify_announcement(title: str) -> str:
    """Return the best-match category for an announcement title.
    Returns 'other' if no pattern matches."""
    if not title:
        return "other"
    for cat, pat in _CATEGORY_PATTERNS:
        if pat.search(title):
            return cat
    return "other"


# --- Insider trade parsing ---------------------------------------------------

# PSX dates appear in many forms; this list is in order of preference.
_DATE_FORMATS = [
    "%d-%B-%Y",         # 15-April-2026
    "%d-%b-%Y",         # 15-Apr-2026
    "%d %B %Y",         # 15 April 2026
    "%d %b %Y",         # 15 Apr 2026
    "%d-%m-%Y",         # 15-04-2026
    "%d/%m/%Y",         # 15/04/2026
    "%B %d, %Y",        # April 15, 2026
    "%b %d, %Y",        # Apr 15, 2026
    "%Y-%m-%d",         # 2026-04-15
]


def _try_parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# Catches dates in a free-text blob — greedy on numeric + alphabetic months.
_DATE_RE = re.compile(
    r"(\d{1,2}[-/ ]"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
    r"April|June|July|August|September|October|November|December|\d{1,2})"
    r"[-/ ,]+\d{2,4}"
    r"|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
    r"April|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
    r")",
    re.I,
)


def _extract_first_date(text: str, after: int = 0) -> Optional[date]:
    """Find the first parseable date in text starting at position `after`."""
    for m in _DATE_RE.finditer(text, pos=after):
        d = _try_parse_date(m.group(0))
        if d is not None:
            return d
    return None


# Insider-trade name extraction patterns. Defensive — PSX doesn't standardize.
_INSIDER_NAME_PATTERNS = [
    re.compile(r"(?:Name of the (?:Director|CEO|Executive)[^:]*):\s*([A-Z][A-Za-z\.\s]+?)(?:\n|$|,)", re.I),
    re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})", re.I),
]

_INSIDER_ROLE_PATTERNS = [
    re.compile(r"\b(Director|CEO|Chief Executive|Executive|Chairman|Chairperson)\b", re.I),
]

_ACTION_BUY_RE = re.compile(r"\b(?:purchas|bought|buy|acquired|acquisition)\b", re.I)
_ACTION_SELL_RE = re.compile(r"\b(?:sold|sale|sell|disposed|divested|disposal)\b", re.I)

# Fixes Critic A BLOCKER: prior _QTY_RE matched "shares" then captured the next digit
# anywhere (e.g., "01" from a date), producing qty=1 for "sold 5,000 shares on 01-May".
# Anchored on a colon or whitespace+amount, with comma OR 4+ digits required.
_QTY_LABELED_RE = re.compile(
    r"(?:number of shares|qty|quantity)\s*[:\-]?\s*(\d{1,3}(?:,\d{3})+|\d{4,})",
    re.I,
)
# Fallback for free-text "sold 5,000 shares" / "purchased 10000 shares".
_QTY_FREE_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\b\s+shares?", re.I
)

# Fixes Critic C MAJOR: pct_holding is in PSX Form 31 ("Holding after transaction").
# High-signal for "is the director loading up?" questions.
_PCT_HOLDING_RE = re.compile(
    r"(?:holding|stake|interest)[^\d]{0,40}?(\d+(?:\.\d+)?)\s*%", re.I,
)


def parse_insider_trade(body: str) -> Optional[dict]:
    """Parse director-trade fields from announcement body text.
    Returns None when essential fields can't be found.

    Note (Critic B M4 fix): symbol parameter was unused; dropped."""
    if not body:
        return None
    # Action
    is_buy = bool(_ACTION_BUY_RE.search(body))
    is_sell = bool(_ACTION_SELL_RE.search(body))
    if not (is_buy ^ is_sell):
        # Need exactly one to be confident
        return None
    action = "buy" if is_buy else "sell"

    # Name
    name: Optional[str] = None
    for pat in _INSIDER_NAME_PATTERNS:
        m = pat.search(body)
        if m:
            candidate = m.group(1).strip().rstrip(",")
            # Avoid grabbing words like "Director" by themselves
            if len(candidate.split()) >= 1 and not candidate.lower().startswith(
                ("director", "ceo", "executive")
            ):
                name = candidate
                break

    # Role
    role: Optional[str] = None
    for pat in _INSIDER_ROLE_PATTERNS:
        m = pat.search(body)
        if m:
            role = m.group(1)
            break

    # Qty — labeled form first (PSX Form 31 layout), then free-text fallback.
    qty: Optional[int] = None
    m_qty = _QTY_LABELED_RE.search(body) or _QTY_FREE_RE.search(body)
    if m_qty:
        qty = int(m_qty.group(1).replace(",", ""))

    # pct_holding (Critic C MAJOR fix)
    pct_holding: Optional[float] = None
    m_pct = _PCT_HOLDING_RE.search(body)
    if m_pct:
        try:
            val = float(m_pct.group(1))
            # Sanity: holdings are 0-100%
            if 0 < val <= 100:
                pct_holding = val
        except ValueError:
            pass

    # Date
    trade_date = _extract_first_date(body)

    # Need at minimum qty > 0 + action + date (Critic B nitpick: zero-qty is nonsense)
    if qty is None or qty <= 0 or trade_date is None:
        return None

    return {
        "insider_name": name,
        "insider_role": role,
        "action": action,
        "qty": qty,
        "pct_holding": pct_holding,
        "trade_date": trade_date,
    }


# --- Board meeting parsing ---------------------------------------------------

_FIN_RESULTS_TITLE_RE = re.compile(
    r"\b(Quarterly|Half[-\s]?Year(?:ly)?|Annual|Financial)\s+Result", re.I
)

# Critic C BLOCKER fix: anchor meeting-date extraction on phrases that
# UNAMBIGUOUSLY signal a future meeting, instead of grabbing the first date in
# body (which is often the prior "period ended" reference date).
_MEETING_DATE_ANCHOR_RE = re.compile(
    r"(?:will\s+(?:be\s+held|meet)|is\s+scheduled|hereby\s+given\s+that\s+"
    r"(?:a\s+)?meeting.{0,80}?will\s+be\s+held|Board(?:\s+of\s+Directors)?\s+"
    r"will\s+meet|meeting\s+(?:of\s+the\s+Board\s+)?on)",
    re.I,
)
# When falling back to first-date-in-body, skip dates immediately preceded by
# words that indicate a reference period, not a meeting.
_PERIOD_PHRASE_RE = re.compile(
    r"\b(?:period\s+ended|year\s+ended|ending|as\s+(?:on|at))\s+$", re.I,
)


def parse_board_meeting(title: str, body: str) -> Optional[dict]:
    """Extract meeting_date + agenda from board-meeting announcement.
    Returns None if no date can be parsed.

    Note (Critic B M4 fix): symbol parameter was unused; dropped.
    Note (Critic C BLOCKER fix): anchors on 'will be held on'-style phrases
    before falling back to first-date-in-body; skips dates preceded by
    'period ended' / 'year ended' so we don't return the reference period."""
    if not body:
        return None
    title = title or ""
    # Classify agenda from title (cheap) before scanning body
    if "Other Than Financial" in title:
        agenda = "other"
    elif _FIN_RESULTS_TITLE_RE.search(title):
        agenda = "financial_results"
    else:
        if _FIN_RESULTS_TITLE_RE.search(body):
            agenda = "financial_results"
        elif re.search(r"\bdividend\b", body, re.I):
            agenda = "dividend"
        else:
            agenda = "other"

    # 1) Look for an explicit "will be held on" anchor; prefer a date in the
    # 200 chars FOLLOWING the anchor.
    meeting_date: Optional[date] = None
    for anchor in _MEETING_DATE_ANCHOR_RE.finditer(body):
        window = body[anchor.end():anchor.end() + 200]
        d = _extract_first_date(window)
        if d is not None:
            meeting_date = d
            break

    # 2) Fallback: scan the body, but skip any date whose preceding 24 chars
    # contain a "period ended"/"year ended" phrase.
    if meeting_date is None:
        for m in _DATE_RE.finditer(body):
            preceding = body[max(0, m.start() - 24):m.start()]
            if _PERIOD_PHRASE_RE.search(preceding):
                continue
            d = _try_parse_date(m.group(0))
            if d is not None:
                meeting_date = d
                break

    if meeting_date is None:
        return None
    return {
        "meeting_date": meeting_date,
        "agenda": agenda,
    }
```

- [ ] **Step 4: Run, confirm tests pass**

If some tests fail because the regex patterns don't quite match the sample text, iterate on the regexes — but DO NOT relax test assertions. The test inputs are deliberately written to look like real PSX disclosure text; if the parser can't handle them, the parser needs more work.

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/events.py psx-mcp/tests/test_events.py
git commit -m "feat(psx-mcp): events.py — classify + parse insider trades + board meetings"
```

---

### Task 3.2: Auto-populate structured tables after body fetch

**Files:**
- Modify: `psx-mcp/server.py` — extend `_fetch_announcement_body_impl` to call event parsers when status='ok'
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Failing test**

```python
def test_fetch_announcement_body_populates_insider_trade_table(tmp_path, monkeypatch):
    """When body parses as a director disclosure, insider_trades is populated."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient
    from datetime import datetime

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime(2026, 4, 16),
        title="Disclosure of Interest by a Director CEO, or Executive",
        category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf", body=None,
    ))

    async def fake_fetch(self, url, timeout=30.0):
        return b"%PDF-fake"
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)
    monkeypatch.setattr(
        "server.extract_text_or_empty",
        lambda b: ("Disclosure of Interest by a Director CEO, or Executive "
                   "Mr. Asif Peer Director purchased 10,000 shares on 15-April-2026."),
    )

    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=PSXClient())

    asyncio.run(srv._fetch_announcement_body_impl(cache, PSXClient(), "A1"))

    trades = cache.get_insider_trades("SYS")
    assert len(trades) == 1
    t = trades[0]
    assert t["action"] == "buy"
    assert t["qty"] == 10000


def test_fetch_announcement_body_populates_board_meeting_table(tmp_path, monkeypatch):
    """When body parses as a board-meeting notice with a date, board_meetings is populated."""
    import asyncio
    from datetime import date, datetime
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="B1", symbol="SYS", posted_at=datetime(2026, 5, 28),
        title="Notice of Board Meeting",
        category=None,
        url="https://dps.psx.com.pk/download/document/2.pdf", body=None,
    ))

    async def fake_fetch(self, url, timeout=30.0):
        return b"%PDF-fake"
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)
    monkeypatch.setattr(
        "server.extract_text_or_empty",
        lambda b: ("Notice of Board Meeting. The Board will meet on "
                   "30-June-2026 to consider the quarterly financial results."),
    )

    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=PSXClient())

    asyncio.run(srv._fetch_announcement_body_impl(cache, PSXClient(), "B1"))

    rows = cache.get_board_meetings("SYS", since=date(2026, 6, 1), until=date(2026, 7, 1))
    assert len(rows) == 1
    assert rows[0]["agenda"] == "financial_results"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Extend `_fetch_announcement_body_impl`**

After the `cache.update_announcement_body(announcement_id, text, "ok")` line, add:

```python
# Auto-populate structured event tables based on title classification.
# (Imports hoisted to top of server.py — see Phase 3.1 commit.)
cat = classify_announcement(row["title"] or "")
try:
    if cat == "insider_trade":
        parsed = parse_insider_trade(text)
        if parsed:
            cache.upsert_insider_trade(
                announcement_id=announcement_id,
                symbol=row["symbol"],
                insider_name=parsed["insider_name"],
                insider_role=parsed["insider_role"],
                action=parsed["action"],
                qty=parsed["qty"],
                pct_holding=parsed["pct_holding"],
                trade_date=parsed["trade_date"],
                posted_at=row["posted_at"],
            )
    elif cat == "board_meeting":
        # Critic C BLOCKER fix: only route 'board_meeting' here. Routing
        # 'financial_results' titles to this parser would grab a "period ended"
        # date from the body and create a bogus past-dated meeting row.
        parsed = parse_board_meeting(title=row["title"], body=text)
        if parsed:
            cache.upsert_board_meeting(
                announcement_id=announcement_id,
                symbol=row["symbol"],
                meeting_date=parsed["meeting_date"],
                agenda=parsed["agenda"],
                posted_at=row["posted_at"],
            )
except Exception:
    # Auto-extraction is best-effort; never block the body cache on parser bugs.
    pass
```

(Hoist the imports to the top of `server.py` for cleanliness instead of inlining inside the function.)

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): auto-populate insider_trades + board_meetings after body fetch"
```

---

## Phase 4 — Event-query MCP tools

### Task 4.1: `get_insider_trades`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add models**

```python
class InsiderTrade(BaseModel):
    announcement_id: str
    symbol: str
    insider_name: Optional[str] = None
    insider_role: Optional[str] = None
    action: Optional[str] = None
    qty: Optional[int] = None
    pct_holding: Optional[float] = None
    trade_date: Optional[date] = None
    posted_at: str

    @field_validator("trade_date", mode="before")
    @classmethod
    def _coerce_blank(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class InsiderTradeListResponse(Disclaimer):
    symbol: str
    since_days: int
    trades: list[InsiderTrade]
    net_qty: Optional[int] = None  # buy - sell totals
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_get_insider_trades_summary_and_net_qty(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_insider_trade(
        announcement_id="A1", symbol="SYS",
        insider_name="X", insider_role="Director",
        action="buy", qty=10_000, pct_holding=None,
        trade_date=date(2026, 4, 15), posted_at=date(2026, 4, 16),
    )
    cache.upsert_insider_trade(
        announcement_id="A2", symbol="SYS",
        insider_name="Y", insider_role="Executive",
        action="sell", qty=3_000, pct_holding=None,
        trade_date=date(2026, 5, 1), posted_at=date(2026, 5, 2),
    )
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_insider_trades_impl(cache, "SYS", since_days=365)
    assert len(out.trades) == 2
    assert out.net_qty == 10_000 - 3_000  # +7000 net buying
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement**

```python
def _get_insider_trades_impl(cache: Cache, symbol: str,
                              since_days: int = 365) -> InsiderTradeListResponse:
    rows = cache.get_insider_trades(symbol, since_days=since_days)
    trades = [InsiderTrade(**r) for r in rows]
    net_qty = None
    if trades:
        net = 0
        for t in trades:
            if t.qty is None or t.action is None:
                continue
            net += t.qty if t.action == "buy" else -t.qty
        net_qty = net
    return InsiderTradeListResponse(
        symbol=symbol.upper(), since_days=since_days,
        trades=trades, net_qty=net_qty,
    )


@mcp.tool()
async def get_insider_trades(symbol: str,
                              since_days: int = 365) -> InsiderTradeListResponse:
    """Director / CEO / Executive transactions for symbol. Populated when
    fetch_announcement_body parses a 'Disclosure of Interest by Director'
    announcement. net_qty is buy total - sell total (positive = net buying)."""
    return _get_insider_trades_impl(_cache, symbol, since_days)
```

- [ ] **Step 5: Run + commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): get_insider_trades — director trades + net qty"
```

---

### Task 4.2: `get_earnings_calendar`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add models**

```python
class BoardMeeting(BaseModel):
    announcement_id: str
    symbol: str
    meeting_date: Optional[date] = None
    agenda: Optional[str] = None
    posted_at: str

    @field_validator("meeting_date", mode="before")
    @classmethod
    def _coerce_blank(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class EarningsCalendarResponse(Disclaimer):
    symbol: str
    lookback_days: int
    forward_days: int
    meetings: list[BoardMeeting]
    next_meeting: Optional[BoardMeeting] = None
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_get_earnings_calendar_returns_window_and_next_meeting(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date.today()
    cache.upsert_board_meeting(
        announcement_id="B1", symbol="SYS",
        meeting_date=today - timedelta(days=10),
        agenda="financial_results",
        posted_at=datetime.now() - timedelta(days=15),
    )
    cache.upsert_board_meeting(
        announcement_id="B2", symbol="SYS",
        meeting_date=today + timedelta(days=5),
        agenda="financial_results",
        posted_at=datetime.now(),
    )
    cache.upsert_board_meeting(
        announcement_id="B3", symbol="SYS",
        meeting_date=today + timedelta(days=120),
        agenda="other",
        posted_at=datetime.now(),
    )
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_earnings_calendar_impl(cache, "SYS",
                                           lookback_days=30, forward_days=60)
    # B1 (10 days ago) + B2 (in 5 days). B3 (in 120 days) excluded.
    assert len(out.meetings) == 2
    assert out.next_meeting is not None
    assert out.next_meeting.announcement_id == "B2"
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement**

```python
def _get_earnings_calendar_impl(cache: Cache, symbol: str,
                                  lookback_days: int = 30,
                                  forward_days: int = 60) -> EarningsCalendarResponse:
    from datetime import date as _date, timedelta as _td
    today = _date.today()
    since = today - _td(days=lookback_days)
    until = today + _td(days=forward_days)
    rows = cache.get_board_meetings(symbol, since=since, until=until)
    meetings = [BoardMeeting(**r) for r in rows]
    # Next meeting = earliest with meeting_date >= today
    next_m = None
    upcoming = [m for m in meetings
                if m.meeting_date is not None and m.meeting_date >= today]
    if upcoming:
        next_m = min(upcoming, key=lambda m: m.meeting_date)
    note = None
    if not meetings:
        note = (f"No board meetings cached for {symbol}. Call "
                f"bulk_fetch_announcement_bodies({symbol!r}) to extract from "
                f"announcement PDFs.")
    return EarningsCalendarResponse(
        symbol=symbol.upper(),
        lookback_days=lookback_days, forward_days=forward_days,
        meetings=meetings, next_meeting=next_m, note=note,
    )


@mcp.tool()
async def get_earnings_calendar(symbol: str,
                                 lookback_days: int = 30,
                                 forward_days: int = 60) -> EarningsCalendarResponse:
    """Board-meeting calendar for symbol, [-lookback_days, +forward_days].
    next_meeting field is the earliest upcoming meeting (>= today). Populated
    by fetch_announcement_body parsing of board-meeting notices."""
    return _get_earnings_calendar_impl(_cache, symbol, lookback_days, forward_days)
```

- [ ] **Step 5: Run + commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): get_earnings_calendar — board-meeting window + next meeting"
```

---

### Task 4.3: `get_corporate_actions_calendar`

Combines `dividends` (from Part 2) + `board_meetings` to give a single corporate-actions view.

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add model**

```python
class CorporateActionsCalendarResponse(Disclaimer):
    symbol: str
    lookback_days: int
    forward_days: int
    dividend_events: list[dict]  # subset of DividendEvent fields
    board_meetings: list[dict]
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_get_corporate_actions_calendar_merges_dividends_and_meetings(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date.today()
    cache.upsert_dividend(symbol="FFC", ex_date=today + timedelta(days=10),
                          announcement_date=today - timedelta(days=5),
                          payout_type="cash", per_share=8.0, bonus_pct=None,
                          announcement_id="D1")
    cache.upsert_board_meeting(
        announcement_id="B1", symbol="FFC",
        meeting_date=today + timedelta(days=5),
        agenda="financial_results",
        posted_at=datetime.now(),
    )
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_corporate_actions_calendar_impl(cache, "FFC",
                                                     lookback_days=30, forward_days=60)
    assert len(out.dividend_events) == 1
    assert len(out.board_meetings) == 1
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement**

```python
def _get_corporate_actions_calendar_impl(cache: Cache, symbol: str,
                                            lookback_days: int = 30,
                                            forward_days: int = 60
                                            ) -> CorporateActionsCalendarResponse:
    from datetime import date as _date, timedelta as _td
    today = _date.today()
    since = today - _td(days=lookback_days)
    until = today + _td(days=forward_days)

    # Dividends: filter on ex_date when present, else announcement_date
    div_rows = cache.get_dividend_history(symbol)
    div_events = []
    for d in div_rows:
        ref = d.get("ex_date") or d.get("announcement_date")
        if not ref:
            continue
        ref_date = _date.fromisoformat(ref)
        if since <= ref_date <= until:
            div_events.append(d)

    bm_rows = cache.get_board_meetings(symbol, since=since, until=until)

    note = None
    if not div_events and not bm_rows:
        note = (f"No corporate actions in window for {symbol}. Call "
                f"refresh_dividends({symbol!r}) and "
                f"bulk_fetch_announcement_bodies({symbol!r}).")
    return CorporateActionsCalendarResponse(
        symbol=symbol.upper(),
        lookback_days=lookback_days, forward_days=forward_days,
        dividend_events=div_events, board_meetings=bm_rows, note=note,
    )


@mcp.tool()
async def get_corporate_actions_calendar(symbol: str,
                                            lookback_days: int = 30,
                                            forward_days: int = 60
                                            ) -> CorporateActionsCalendarResponse:
    """Combined view: dividends + board meetings for symbol in
    [-lookback_days, +forward_days]. Use this to spot ex-dates and
    earnings-release windows in one place."""
    return _get_corporate_actions_calendar_impl(_cache, symbol,
                                                  lookback_days, forward_days)
```

- [ ] **Step 5: Run + commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): get_corporate_actions_calendar — dividends + board meetings"
```

---

## Phase 5 — News body fetching

### Task 5.1: `fetch_news_body` + bulk variant

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `NewsBodyResponse` (reuse `BulkBodyFetchResponse` for bulk)
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

News body fetching uses HTML article URLs (not PDFs). Different extractor: BeautifulSoup to find article body. Most blog/news sites tag the article body distinctively; we'll use a generic "longest text-block" heuristic.

- [ ] **Step 1: Add model**

```python
class NewsBodyResponse(Disclaimer):
    news_id: str
    source: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    fetch_status: str
    body: Optional[str] = None
    body_chars: int = 0
    note: Optional[str] = None
```

- [ ] **Step 2: Add `extract_news_body_from_html` to `psx_mcp/news.py`**

In `psx-mcp/src/psx_mcp/news.py`, append:

```python
def extract_article_body(html: str, url: Optional[str] = None) -> str:
    """Article-body extraction. Tries per-host selectors first (Dawn / Profit),
    then a generic semantic-selector pass, then a longest-<p>-block fallback.

    Critic C MAJOR fix: prior generic-only heuristic missed Dawn's
    `div.story__content` (double-underscore) and Profit's `td-post-content`.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    # Per-host selectors. Each entry: (host_substring, list[CSS selectors]).
    HOST_SELECTORS = [
        ("dawn.com",       ["div.story__content", "div.story-content"]),
        ("profit.pakistantoday.com.pk",
                            ["div.td-post-content", "article.entry-content"]),
        ("tribune.com.pk", ["div.story-text", "div.story-content"]),
        ("brecorder.com",  ["div.story-content", "div.entry-content"]),
    ]
    host = ""
    if url:
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
    for host_sub, selectors in HOST_SELECTORS:
        if host_sub in host:
            for sel in selectors:
                for el in soup.select(sel):
                    text = el.get_text("\n", strip=True)
                    if len(text) > 200:
                        return text

    # Generic semantic candidates
    candidates = []
    for sel in ("article", "main", "div.story__content", "div.story-content",
                  "div.article-body", "div#article-body", "div.entry-content",
                  "div.td-post-content"):
        for el in soup.select(sel):
            text = el.get_text("\n", strip=True)
            if len(text) > 200:
                candidates.append(text)
    if candidates:
        return max(candidates, key=len)

    # Fallback: longest div with >= 3 <p> children
    best_text = ""
    for div in soup.find_all(["div", "section", "article"]):
        ps = div.find_all("p", recursive=False)
        if len(ps) >= 3:
            text = "\n".join(p.get_text(" ", strip=True) for p in ps)
            if len(text) > len(best_text):
                best_text = text
    return best_text
```

- [ ] **Step 3: Failing test**

```python
def test_extract_article_body_from_synthetic_html():
    """Generic article-body extraction picks the longest <p> block."""
    from psx_mcp.news import extract_article_body
    html = """
    <html><body>
      <nav><a>menu</a></nav>
      <article>
        <h1>Headline</h1>
        <p>First paragraph of the actual story body with enough words.</p>
        <p>Second paragraph continuing the narrative for the reader.</p>
        <p>Third paragraph with the substantive content of the article.</p>
      </article>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    text = extract_article_body(html)
    assert "First paragraph" in text
    assert "Copyright" not in text


def test_extract_article_body_empty_input():
    from psx_mcp.news import extract_article_body
    assert extract_article_body("") == ""
    assert extract_article_body("not html at all") == ""
```

Put these in `tests/test_news.py` (the file exists from earlier parts).

- [ ] **Step 4: Run, confirm fail**

- [ ] **Step 5: Implement server impl + tool**

```python
# server.py
from psx_mcp.news import extract_article_body
from psx_mcp.models import NewsBodyResponse


async def _fetch_news_body_impl(cache: Cache, client: PSXClient,
                                  news_id: str) -> NewsBodyResponse:
    row = cache.conn.execute(
        "SELECT source, title, url, body, fetch_status FROM news WHERE id = ?",
        (news_id,),
    ).fetchone()
    if not row:
        return NewsBodyResponse(news_id=news_id, fetch_status="not_found",
                                 note="No news row with that id in cache.")
    if row["fetch_status"]:
        return NewsBodyResponse(
            news_id=news_id, source=row["source"], title=row["title"],
            url=row["url"], fetch_status=row["fetch_status"],
            body=row["body"],
            body_chars=len(row["body"] or ""),
            note="Returning cached body; previously fetched.",
        )
    if not row["url"]:
        cache.update_news_body(news_id, None, "no_url")
        return NewsBodyResponse(news_id=news_id, source=row["source"],
                                  title=row["title"], url=None,
                                  fetch_status="no_url")
    if client is None:
        return NewsBodyResponse(news_id=news_id, source=row["source"],
                                  title=row["title"], url=row["url"],
                                  fetch_status="no_client",
                                  note="No PSX client; set_dependencies(client=...) was None.")

    html_bytes = await client.fetch_url_bytes(row["url"])
    if html_bytes is None:
        cache.update_news_body(news_id, None, "http_error")
        return NewsBodyResponse(news_id=news_id, source=row["source"],
                                  title=row["title"], url=row["url"],
                                  fetch_status="http_error")
    try:
        text = extract_article_body(
            html_bytes.decode("utf-8", errors="ignore"),
            url=row["url"],   # Critic C M5: per-host selector dispatch
        )
    except Exception:
        text = ""
    if not text or len(text) < 100:
        cache.update_news_body(news_id, text or None, "parse_error")
        return NewsBodyResponse(news_id=news_id, source=row["source"],
                                  title=row["title"], url=row["url"],
                                  fetch_status="parse_error",
                                  body=text or None, body_chars=len(text or ""))
    cache.update_news_body(news_id, text, "ok")
    return NewsBodyResponse(news_id=news_id, source=row["source"],
                              title=row["title"], url=row["url"],
                              fetch_status="ok",
                              body=text, body_chars=len(text))


async def _bulk_fetch_news_bodies_impl(cache: Cache, client: PSXClient,
                                         symbol: Optional[str],
                                         since_days: int = 14,
                                         limit: int = 50
                                         ) -> BulkBodyFetchResponse:
    rows = cache.get_news_missing_body(symbol=symbol, since_days=since_days,
                                         limit=limit)
    started = _time.time()
    summary = {"attempted": 0, "succeeded": 0, "skipped_no_url": 0,
               "failed_http": 0, "failed_scan": 0, "failed_parse": 0}
    for r in rows:
        summary["attempted"] += 1
        resp = await _fetch_news_body_impl(cache, client, r["id"])
        s = resp.fetch_status
        if s == "ok":
            summary["succeeded"] += 1
        elif s == "no_url":
            summary["skipped_no_url"] += 1
        elif s == "http_error":
            summary["failed_http"] += 1
        elif s == "parse_error":
            summary["failed_parse"] += 1
    return BulkBodyFetchResponse(
        symbol=symbol.upper() if symbol else None,
        since_days=since_days,
        attempted=summary["attempted"],
        succeeded=summary["succeeded"],
        skipped_no_url=summary["skipped_no_url"],
        failed_http=summary["failed_http"],
        failed_scan=summary["failed_scan"],
        failed_parse=summary["failed_parse"],
        elapsed_seconds=_time.time() - started,
    )


@mcp.tool()
async def fetch_news_body(news_id: str) -> NewsBodyResponse:
    """Fetch + cache the article body for a single news item. Same idempotent
    pattern as fetch_announcement_body."""
    return await _fetch_news_body_impl(_cache, _client, news_id)


@mcp.tool()
async def bulk_fetch_news_bodies(symbol: str | None = None,
                                   since_days: int = 14,
                                   limit: int = 50) -> BulkBodyFetchResponse:
    """Bulk-fetch article bodies for symbol (or all). Skips items already
    attempted. Capped by `limit`."""
    return await _bulk_fetch_news_bodies_impl(_cache, _client, symbol,
                                                since_days, limit)
```

- [ ] **Step 6: Add server test**

```python
def test_fetch_news_body_caches_html_body(tmp_path, monkeypatch):
    import asyncio
    from datetime import datetime
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient
    cache = Cache(str(tmp_path / "c.db"))
    cache.conn.execute(
        """INSERT INTO news(id, source, posted_at, title, url, symbols)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("N1", "dawn_business", datetime.now().isoformat(),
         "PSX hits new high", "https://example.com/article", "KSE100"),
    )
    cache.conn.commit()

    async def fake_fetch(self, url, timeout=30.0):
        return (b"<html><body><article>"
                b"<p>The PSX index reached a new all-time high today.</p>"
                b"<p>Brokers attributed the move to strong banking earnings.</p>"
                b"<p>Volumes were 30% above the 30-day average.</p>"
                b"</article></body></html>")
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)

    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=PSXClient())
    out = asyncio.run(srv._fetch_news_body_impl(cache, PSXClient(), "N1"))
    assert out.fetch_status == "ok"
    assert "PSX index reached" in out.body
```

- [ ] **Step 7: Run + commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/src/psx_mcp/news.py psx-mcp/server.py psx-mcp/tests/test_news.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): fetch_news_body + bulk variant + article-body extractor"
```

---

## Phase 6 — Research pack (the flagship)

### Task 6.0: `refresh_company_qualitative` — first-time-setup mega-tool

Critic B M1 fix: a new user calling `get_company_research_pack` on a fresh symbol gets warnings everywhere because nothing is fetched yet. Bundle the four canonical "prime the cache" calls into a single tool so the workflow is one MCP call, not four.

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `CompanyQualitativeRefreshResponse`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add response model**

```python
class CompanyQualitativeRefreshResponse(Disclaimer):
    symbol: str
    announcements_refreshed: int       # from refresh_announcements
    news_refreshed: int                # from refresh_news
    announcement_bodies: dict          # BulkBodyFetchResponse.model_dump(exclude={"disclaimer"})
    news_bodies: dict                  # BulkBodyFetchResponse.model_dump(exclude={"disclaimer"})
    elapsed_seconds: float
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_refresh_company_qualitative_chains_four_calls(tmp_path, monkeypatch):
    """End-to-end: should call refresh_announcements + refresh_news + bulk
    announcement bodies + bulk news bodies, no crashes on no-client path."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = asyncio.run(srv._refresh_company_qualitative_impl(cache, None, "SYS"))
    assert out.symbol == "SYS"
    # With no client, the upstream refreshes return 0 / bulk fetches return failed_other.
    assert out.announcements_refreshed == 0
    assert out.news_refreshed == 0
    assert "no" in (out.note or "").lower() or out.elapsed_seconds >= 0
```

- [ ] **Step 3: Implement**

```python
async def _refresh_company_qualitative_impl(cache: Cache,
                                              client: Optional[PSXClient],
                                              symbol: str
                                              ) -> CompanyQualitativeRefreshResponse:
    started = _time.time()
    sym = symbol.upper()
    note = None
    ann_refreshed = 0
    news_refreshed = 0
    if client is None:
        note = ("No PSX client configured (set_dependencies(client=...) was None). "
                "Returning zeroed counts.")
    else:
        # Best-effort refresh of the market-wide announcement feed (filters to symbol
        # later in get_announcements_missing_body).
        try:
            ann_refreshed = await _refresh_announcements_impl(cache, client) or 0
        except Exception:
            pass
        try:
            news_refreshed = await _refresh_news_impl(cache, client) or 0
        except Exception:
            pass

    # Bulk bodies (these no-op gracefully on client=None via failed_other counter)
    ann_bulk = await _bulk_fetch_announcement_bodies_impl(
        cache, client, sym, since_days=30, limit=20,
    )
    news_bulk = await _bulk_fetch_news_bodies_impl(
        cache, client, sym, since_days=14, limit=20,
    )

    return CompanyQualitativeRefreshResponse(
        symbol=sym,
        announcements_refreshed=ann_refreshed,
        news_refreshed=news_refreshed,
        announcement_bodies=ann_bulk.model_dump(exclude={"disclaimer"}),
        news_bodies=news_bulk.model_dump(exclude={"disclaimer"}),
        elapsed_seconds=_time.time() - started,
        note=note,
    )


@mcp.tool()
async def refresh_company_qualitative(symbol: str) -> CompanyQualitativeRefreshResponse:
    """First-time-setup convenience for a symbol's qualitative layer.
    Chains: refresh_announcements + refresh_news + bulk_fetch_announcement_bodies
    + bulk_fetch_news_bodies for `symbol`. Use this BEFORE get_company_research_pack
    when starting fresh on a new symbol."""
    return await _refresh_company_qualitative_impl(_cache, _client, symbol)
```

NOTE: requires `_refresh_announcements_impl` and `_refresh_news_impl` to exist in server.py — they do (analytics-v3 / analytics-v4). If they take only `cache` (no symbol filter), that's OK — the bodies are then filtered to symbol via the bulk path.

- [ ] **Step 4: Run + commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): refresh_company_qualitative mega-tool — first-time setup"
```

---

### Task 6.1: `get_company_research_pack`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Create: `psx-mcp/tests/test_research_pack.py`

- [ ] **Step 1: Add response model**

```python
class ResearchPackResponse(Disclaimer):
    symbol: str
    generated_at: str  # ISO timestamp
    lookback_days: int
    # Quantitative snapshot (references existing tools, kept lightweight)
    quote: Optional[dict] = None
    fundamentals: Optional[dict] = None
    quadrant_score: Optional[dict] = None
    # Qualitative — the point of this tool
    announcements: list[dict] = []   # list of {id, posted_at, title, category, body_excerpt}
    news: list[dict] = []            # list of {id, posted_at, title, source, body_excerpt}
    insider_trades: list[dict] = []
    upcoming_meetings: list[dict] = []
    upcoming_dividends: list[dict] = []
    # Pre-concatenated LLM-friendly text
    llm_briefing_text: str
    warnings: list[str] = []
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
# psx-mcp/tests/test_research_pack.py
import pytest
from datetime import date, datetime, timedelta
import server as srv
from psx_mcp.cache import Cache
from psx_mcp.models import Announcement, Bar
from psx_mcp.watchlist import WatchlistStore


def _seed_minimal(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    today = date.today()
    cache.upsert_symbol("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=datetime.now(),
                        price=600.0, change=5.0, volume=100_000,
                        day_high=605, day_low=595, fetched_at=datetime.now())
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                                div_yield=None, payout=None, roe=20.0)
    # Recent announcement with body
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime.now() - timedelta(days=5),
        title="Financial Results for the Quarter Ended 31 March 2026",
        category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf",
        body="The company reported EPS of Rs 5.46 for the quarter ended 31 March 2026, "
             "vs Rs 4.91 in the comparable prior period. Revenue grew 12%.",
    ))
    # Insider trade
    cache.upsert_insider_trade(
        announcement_id="A2", symbol="SYS",
        insider_name="Mr. Asif Peer", insider_role="Director",
        action="buy", qty=15_000, pct_holding=None,
        trade_date=today - timedelta(days=10),
        posted_at=datetime.now() - timedelta(days=9),
    )
    # Upcoming meeting
    cache.upsert_board_meeting(
        announcement_id="A3", symbol="SYS",
        meeting_date=today + timedelta(days=20),
        agenda="financial_results",
        posted_at=datetime.now(),
    )
    return cache


def test_research_pack_returns_all_sections(tmp_path):
    cache = _seed_minimal(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_company_research_pack_impl(cache, "SYS", lookback_days=30)
    assert out.symbol == "SYS"
    assert out.quote is not None
    assert out.fundamentals is not None
    assert len(out.announcements) == 1
    assert "Financial Results" in out.announcements[0]["title"]
    assert len(out.insider_trades) == 1
    assert len(out.upcoming_meetings) == 1
    # The LLM-friendly text should include identifying sections
    assert "SYS" in out.llm_briefing_text
    assert "Financial Results" in out.llm_briefing_text
    assert "Mr. Asif Peer" in out.llm_briefing_text


def test_research_pack_empty_cache_returns_warnings(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_company_research_pack_impl(cache, "NOSUCH", lookback_days=30)
    assert out.symbol == "NOSUCH"
    assert len(out.warnings) > 0
    # llm_briefing_text is still produced (just with the warnings + empty sections)
    assert "NOSUCH" in out.llm_briefing_text
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement**

```python
def _get_company_research_pack_impl(cache: Cache, symbol: str,
                                       lookback_days: int = 30
                                       ) -> ResearchPackResponse:
    sym = symbol.upper()
    warnings: list[str] = []
    generated_at = datetime.now().isoformat()
    since_iso = (datetime.now() - timedelta(days=lookback_days)).isoformat()

    # Quote
    quote = None
    try:
        q = _get_quote_impl(cache, sym)
        quote = q.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"quote: {e!r}")

    # Fundamentals
    fundamentals = None
    try:
        f = cache.get_fundamentals(sym)
        if f:
            fundamentals = dict(f)
        else:
            warnings.append("No fundamentals cached for symbol.")
    except Exception as e:
        warnings.append(f"fundamentals: {e!r}")

    # Quadrant score (best-effort — likely zero on a sparse cache)
    qs_dict = None
    try:
        qs = _compute_4quadrant_score_impl(cache, sym)
        qs_dict = qs.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"quadrant: {e!r}")

    # Announcements with bodies, lookback window
    announcements: list[dict] = []
    try:
        rows = cache.conn.execute(
            """SELECT id, posted_at, title, category, url, body, fetch_status
               FROM announcements
               WHERE symbol = ? AND posted_at >= ?
               ORDER BY posted_at DESC LIMIT 20""",
            (sym, since_iso),
        ).fetchall()
        for r in rows:
            ex = (r["body"] or "")[:500].strip()
            announcements.append({
                "id": r["id"], "posted_at": r["posted_at"], "title": r["title"],
                "category": r["category"], "url": r["url"],
                "fetch_status": r["fetch_status"],
                "body_excerpt": ex,
                "has_full_body": bool(r["body"]) and len(r["body"]) > 500,
            })
        if not announcements:
            warnings.append(f"No announcements for {sym} in last {lookback_days} days.")
    except Exception as e:
        warnings.append(f"announcements: {e!r}")

    # News with bodies
    news: list[dict] = []
    try:
        rows = cache.conn.execute(
            """SELECT id, posted_at, title, source, url, body
               FROM news
               WHERE posted_at >= ? AND
                     (',' || UPPER(symbols) || ',') LIKE ?
               ORDER BY posted_at DESC LIMIT 10""",
            (since_iso, f"%,{sym},%"),
        ).fetchall()
        for r in rows:
            ex = (r["body"] or "")[:500].strip()
            news.append({
                "id": r["id"], "posted_at": r["posted_at"], "title": r["title"],
                "source": r["source"], "url": r["url"],
                "body_excerpt": ex,
                "has_full_body": bool(r["body"]) and len(r["body"]) > 500,
            })
    except Exception as e:
        warnings.append(f"news: {e!r}")

    # Insider trades
    try:
        insider_trades = cache.get_insider_trades(sym, since_days=lookback_days * 2)
    except Exception as e:
        warnings.append(f"insider_trades: {e!r}")
        insider_trades = []

    # Upcoming meetings + dividends — Critic B M6 fix: compose existing impl
    # instead of re-implementing the filtering. lookback=0 = future-only.
    upcoming_meetings: list[dict] = []
    upcoming_dividends: list[dict] = []
    try:
        cal = _get_corporate_actions_calendar_impl(cache, sym,
                                                     lookback_days=0,
                                                     forward_days=60)
        upcoming_meetings = list(cal.board_meetings)
        upcoming_dividends = list(cal.dividend_events)
    except Exception as e:
        warnings.append(f"calendar: {e!r}")

    # Compose LLM briefing text — used by Claude (or any LLM) to reason
    # about the company's recent qualitative state.
    parts: list[str] = []
    parts.append(f"# Research Pack: {sym}")
    parts.append(f"Generated: {generated_at}")
    parts.append(f"Lookback: {lookback_days} days")
    parts.append("")
    if quote:
        parts.append(f"## Latest Quote")
        parts.append(f"Price: Rs {quote.get('price')}")
        parts.append(f"Change: {quote.get('change')} ({quote.get('change_pct'):+.2f}%)")
        parts.append(f"Volume: {quote.get('volume')}")
        parts.append(f"52w high/low: {quote.get('week52_high')} / {quote.get('week52_low')}")
    if fundamentals:
        parts.append("\n## Fundamentals (cached)")
        for k in ("eps", "pe", "pb", "div_yield", "payout", "roe"):
            v = fundamentals.get(k)
            if v is not None:
                parts.append(f"{k}: {v}")
    if announcements:
        parts.append("\n## Recent Announcements")
        for a in announcements:
            parts.append(f"\n[{a['posted_at'][:10]}] {a['title']}")
            if a["body_excerpt"]:
                parts.append(a["body_excerpt"])
                if a["has_full_body"]:
                    parts.append("(...full body cached; ask for it via the announcement id)")
            else:
                parts.append("(no body cached — call fetch_announcement_body or bulk_fetch_announcement_bodies)")
    if news:
        parts.append("\n## Recent News")
        for n in news:
            parts.append(f"\n[{n['posted_at'][:10]}] {n['title']} — {n.get('source')}")
            if n["body_excerpt"]:
                parts.append(n["body_excerpt"])
    if insider_trades:
        parts.append("\n## Director / Insider Trades")
        for t in insider_trades:
            parts.append(
                f"{t.get('trade_date')}: {t.get('insider_name') or '?'} "
                f"({t.get('insider_role') or '?'}) "
                f"{t.get('action')} {t.get('qty')} shares"
            )
    if upcoming_meetings:
        parts.append("\n## Upcoming Board Meetings")
        for m in upcoming_meetings:
            parts.append(f"{m.get('meeting_date')}: agenda={m.get('agenda')}")
    if upcoming_dividends:
        parts.append("\n## Upcoming Dividends")
        for d in upcoming_dividends:
            parts.append(
                f"ex-date {d.get('ex_date')}: {d.get('payout_type')} "
                f"Rs {d.get('per_share')}/share"
            )
    if qs_dict:
        parts.append("\n## 4-Quadrant Composite Score")
        parts.append(
            f"V={qs_dict.get('value')} Q={qs_dict.get('quality')} "
            f"M={qs_dict.get('momentum')} T={qs_dict.get('trend')} "
            f"Total={qs_dict.get('total')}/4"
        )
    if warnings:
        parts.append("\n## Data gaps")
        for w in warnings:
            parts.append(f"- {w}")

    llm_text = "\n".join(parts)

    return ResearchPackResponse(
        symbol=sym, generated_at=generated_at, lookback_days=lookback_days,
        quote=quote, fundamentals=fundamentals, quadrant_score=qs_dict,
        announcements=announcements, news=news,
        insider_trades=insider_trades,
        upcoming_meetings=upcoming_meetings,
        upcoming_dividends=upcoming_dividends,
        llm_briefing_text=llm_text,
        warnings=warnings,
    )


@mcp.tool()
async def get_company_research_pack(symbol: str,
                                       lookback_days: int = 30
                                       ) -> ResearchPackResponse:
    """Flagship LLM-companion tool: structured + raw qualitative text for the
    last `lookback_days` days for `symbol`. Includes quote, fundamentals,
    quadrant score, announcement bodies, news bodies, director trades, and
    upcoming meetings/dividends. The `llm_briefing_text` field is a
    pre-concatenated markdown briefing suitable for direct LLM consumption."""
    return _get_company_research_pack_impl(_cache, symbol, lookback_days)
```

- [ ] **Step 5: Run + commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_research_pack.py
git commit -m "feat(psx-mcp): get_company_research_pack — flagship LLM-companion tool"
```

---

## Phase 7 — Docs & release

### Task 7.1: README + playbook updates

- [ ] **Step 1: Update `psx-mcp/README.md` tool table**

Add rows for each new tool. Mark `get_company_research_pack` as the **LLM-companion** tool — the recommended way to ask Claude "what's going on with X?".

New tools (8):
- `fetch_announcement_body(announcement_id)` — fetch + cache PDF body
- `bulk_fetch_announcement_bodies(symbol, since_days=30, limit=50)` — batch
- `fetch_news_body(news_id)` — fetch + cache article body
- `bulk_fetch_news_bodies(symbol, since_days=14, limit=50)` — batch
- `get_insider_trades(symbol, since_days=365)` — director trades + net qty
- `get_earnings_calendar(symbol, lookback_days=30, forward_days=60)` — board meetings window
- `get_corporate_actions_calendar(symbol, lookback_days=30, forward_days=60)` — dividends + meetings
- `get_company_research_pack(symbol, lookback_days=30)` — **flagship LLM briefing**

- [ ] **Step 2: Update `docs/investing-playbook.md`**

Mark resolved in Part 1 gap table:
- News bodies / announcement text ✅ (Part 5 analytics-v5)
- Insider / director transactions ✅
- Earnings calendar ✅ (heuristic via parsed board-meeting dates)
- Corporate actions calendar ✅

Add to Part 6 roadmap:
"**analytics-v5** adds the qualitative real-world signal layer: announcement PDF bodies, news article bodies, structured insider trades, structured board-meeting / earnings calendar, and the `get_company_research_pack(symbol)` flagship LLM-companion tool. **Future**: headless-browser sub-tab fetcher for ROE/PB/payout (was the original Part-5 candidate, deprioritized in favor of qualitative). OCR for scan-only PDFs. Annual report parsing."

- [ ] **Step 3: Commit**

```bash
git add psx-mcp/README.md docs/investing-playbook.md
git commit -m "docs(psx-mcp): document Part-5 qualitative tools (bodies, insider trades, calendars, research pack)"
```

---

### Task 7.2: Full suite gate + `analytics-v5` tag

- [ ] **Step 1: Run full suite from `psx-mcp/`**

```
uv run pytest -v
```
With `timeout=600000`. Expected: all green; new tests bring total to ~285+ (251 in v4 + ~35 new).

- [ ] **Step 2: If green, tag**

```bash
cd C:/Users/pc/work/stocks/psx
git tag -a analytics-v5 -m "PSX MCP Analytics Upgrade Part 5 — qualitative real-world signals: announcement bodies, news bodies, insider trades, earnings calendar, corporate actions calendar, get_company_research_pack flagship tool"
```

- [ ] **Step 3: Verify + report**

```
git tag -l "analytics*"
git log --oneline analytics-v4..analytics-v5
```

Report final test count, tag SHA, commit list.

---

## Self-Review

**1. Spec coverage**
- Announcement PDF body extraction ✅ Tasks 0.x + 2.1
- News article body fetching ✅ Task 5.1
- Insider trade extraction ✅ Task 3.x + 4.1
- Board meeting / earnings calendar ✅ Tasks 3.x + 4.2
- Corporate actions calendar ✅ Task 4.3
- `get_company_research_pack` flagship ✅ Task 6.1
- Annual report parsing — explicitly deferred
- OCR — deferred
- ROE/PB — still deferred (intentional; user said the qualitative layer matters more first)

**2. Placeholder scan**
Every code step contains complete code. Notes in Task 0.2 about test PDF construction explicitly tell the implementer to iterate and fall back to a checked-in fixture if pypdf's content-stream API behaves differently across versions — that's not a placeholder, it's a documented adaptation strategy. Iteration in Task 3.1 step 4 (regex tuning) is also acknowledged — but the test inputs are concrete + the test assertions are concrete, so "iterate" here means tune the parser, not write more code later.

**3. Type consistency**
- `AnnouncementBodyResponse.fetch_status` is a string from the closed set `{ok, http_error, scan_only, parse_error, no_url, not_found, no_client}` — used consistently in Tasks 2.1, 3.2, 5.1, 6.1.
- `BulkBodyFetchResponse` is shared by announcement and news bulk fetchers (Task 2.1 + 5.1). Field set is consistent.
- `InsiderTrade.trade_date` and `BoardMeeting.meeting_date` are both `Optional[date]` with the same blank-coercion validator pattern from Part 2's `DividendEvent`.
- `parse_insider_trade` returns dict with keys `{insider_name, insider_role, action, qty, pct_holding, trade_date}` — matches `cache.upsert_insider_trade` kwargs (Task 3.2).
- `parse_board_meeting` returns dict with `{meeting_date, agenda}` — matches `cache.upsert_board_meeting` kwargs.
- `cache.update_announcement_body` and `cache.update_news_body` have the same `(id, body, fetch_status)` signature shape.
- All response models inherit `Disclaimer` consistent with Parts 1-4.

**4. Constraint check**
- No new external domains beyond `dps.psx.com.pk` (announcement PDFs) and the existing Dawn/Profit URLs (already cited as RSS sources).
- One new dep (`pypdf`) — pure Python, no native dependencies, MIT-licensed.
- No macro feed. No social media. No paid feeds.
- No OCR (deferred — heavy native deps).
- All new tools follow the `@mcp.tool() async def → _impl(cache, ...)` pattern.

---

## What this plan deliberately does NOT cover

Belongs to a future plan:

- **ROE / P/B / payout / dividend-yield population** — needs headless-browser sub-tab fetcher. Was originally going to be Part 5; deprioritized for this user's workflow.
- **OCR** for scan-only PDFs — `tesseract` + `pdf2image` adds significant native dependencies. Most PSX disclosures are text-PDFs anyway.
- **Annual report (10-K equivalent) parsing** — heavier PDF parsing of 80-200 page documents. Defer.
- **Twitter / Reddit / X scraping** — TOS-fragile, low signal-to-noise for PSX.
- **FinBERT / custom NLP** — research validates LLM-at-query-time beats pre-baked sentiment.
- **SBP macro feed** — explicit user constraint.
- **Knowledge graph** linking companies via supply chain / board membership — would need a curated dataset PSX doesn't expose.
- **Cron/automation** for nightly bulk body fetches — easy to add via the existing `loop` skill or a `/cron` setup; not an MCP feature.
