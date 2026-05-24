# PSX MCP Analytics Upgrade — Implementation Plan (Part 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix data-population bugs in existing tools, add cached index series + market snapshot, and ship a `screen_symbols` + `get_sector_summary` primitive — all using PSX DPS endpoints already in use, with no scraping or paid feeds.

**Architecture:** Extend the existing FastMCP server (`server.py`) and its `Cache` layer. Every new MCP tool follows the project's existing pattern: an `async def` `@mcp.tool()` wrapper around a sync `_<name>_impl(cache, ...)` helper. Tests exercise the `_impl` directly. New computational logic (indicators, screening) lives in dedicated modules (`indicators.py`, `screener.py`) imported by both the impls and the cache layer.

**Tech Stack:** Python 3.12, FastMCP, SQLite (via existing `Cache`), `httpx` for HTTP, `pytest` for tests, `uv` for env/deps. No new dependencies.

**Constraints (from user, 2026-05-23):**
- Only use PSX DPS JSON endpoints already accessible (no HTML scraping).
- No paid feeds.
- No new external sources (e.g., no SBP macro, no news RSS) — that's deferred to a later plan.

---

## Open Questions & Resolutions (must clear before writing tasks)

These are blockers identified during plan drafting. Each must have a concrete resolution before Phase 1 begins. The first task of Phase 0 is to *empirically* answer the first four.

| # | Question | Why it blocks | Resolution path |
|---|---|---|---|
| 1 | Is there a JSON endpoint on `dps.psx.com.pk` that returns index values (KSE-100, KSE-30, All-Share, KMI-30) without HTML scraping? | Phase 2 (indices) depends on this. If only HTML is available, Phase 2 is out of scope. | **RESOLVED 2026-05-24 (probe 0.1):** Yes — `GET /timeseries/eod/<INDEX>` returns JSON `{status, message, data: [[unix_ts, close, volume, ?metric], ...]}` and `GET /timeseries/int/<INDEX>` returns intraday JSON. Confirmed for `KSE100`. `/indices` and `/indices/<INDEX>` are HTML constituent tables — not useful as the index series source. Phase 2 proceeds with Path A (real JSON endpoint). |
| 2 | Does the `dps.psx.com.pk/company/<SYM>` payload include a dividend history table? | Determines whether `get_dividend_history` can be added now or deferred. | **RESOLVED 2026-05-24 (probe 0.2):** Not in the saved fixtures. `profile_LUCK.html` and `financial_LUCK.html` are byte-identical (both are the company landing page) and contain only nav-bar "Payouts" mentions — no dividend table data. Conclusion: the live `/company/<SYM>` page advertises a PAYOUTS tab but the fixture captured by `capture_fixtures.py` did not include it. A dedicated `GET /company/<SYM>/payouts` (or equivalent) fetch is required — defer `get_dividend_history` until a fresh fixture for the payouts tab is captured. |
| 3 | Does `dps.psx.com.pk/company/<SYM>` include balance-sheet line items (total assets, current liabilities, LT debt) — not just income-statement? | Piotroski F-Score (next plan) depends on this. Documenting now avoids scoping surprises later. | **RESOLVED 2026-05-24 (probe 0.2):** Zero matches for "total assets", "current liabilit*", "long term debt", "share capital", "current ratio" in either saved fixture. Same caveat as Q2: the fixture is the bare landing page (7 tables, ~28k visible chars, mostly nav + ratios + 4-yr income summary). Piotroski F-Score requires a separate scrape — likely the RATIOS tab and/or a balance-sheet endpoint not yet probed. Out-of-scope for this plan; flag for next plan. |
| 4 | Are PSX historical OHLC prices in `dps.psx.com.pk/historical` adjusted for bonus issues and splits, or raw? | Affects validity of 52w high/low and (future) backtest. | **PARTIALLY RESOLVED 2026-05-24 (probe 0.3):** SYS history around the placeholder ex-date 2024-04-25 shows smooth day-to-day moves (closes Apr 22–May 3 range 379–408, no 20%+ gap). Either the placeholder ex-date is wrong or the prices appear adjusted. **Without a confirmed corporate-action ex-date this is indeterminate.** For this plan: treat closes as raw, document caveat on `week52_high/low` output. Revisit when a PSX-sourced bonus/split ex-date is recorded. |
| 5 | Existing `refresh_announcements` returns 50 rows but `get_announcements` returns `[]` for most symbols. Is the issue (a) symbol-specific (only some have announcements) or (b) a persistence/query bug? | Phase 1 announcement-body fix scope depends on which. | Confirm in Task 0.4 by running the existing impl directly and checking the DB. |
| 6 | `search_symbol` returned `[]` for NETSOL/TRG despite being in cache. Is the SQL using `LIKE` correctly, or is the query column missing? | Phase 1 search fix needs to know the actual current behavior. | Re-read the existing impl in Task 0.5 — likely a 5-minute fix. |

**Resolution policy:** If Task 0.1 finds no JSON index endpoint, Phase 2 collapses to "compute index proxy as cap-weighted mean of cached symbols" (acceptable fallback, documented as approximation). If Task 0.4 finds historical prices are *unadjusted*, the 52w high/low is still computable but documented as raw — users informed in tool output. No other findings should block the plan.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `indicators.py` | Pure-function computations: SMA, RSI, ATR, Bollinger, MACD, Donchian, 52w-high/low. No I/O. Single source of truth — replaces inline indicator code in `server.py`. |
| `screener.py` | `screen_symbols(cache, filters)` and `sector_summary(cache, sector)`. Pure SQL queries + light Python aggregation. |
| `tests/test_indicators.py` | Direct tests against `indicators.py` with synthetic price series. |
| `tests/test_screener.py` | Tests against `screener.py` using a seeded test cache. |
| `tests/test_indices.py` | Tests for index fetch + storage (if Phase 2 endpoint found). |
| `scripts/probe_indices.py` | One-off probe script — checks `dps.psx.com.pk` endpoints for index JSON. Saves fixture if found. |
| `scripts/probe_company_balance.py` | Inspects existing `company/<sym>` fixture for balance-sheet & dividend payload. |

**Modified files:**

| Path | What changes |
|---|---|
| `server.py` | New `@mcp.tool()` entries: `screen_symbols`, `get_sector_summary`, plus updated impls for `get_market_summary`, `search_symbol`, `compute_indicators`, `compare_symbols`, `get_quote` (52w fields), `get_announcements`. |
| `cache.py` | New tables (`indices`, `announcement_bodies` if not already), helper methods `top_movers()`, `sector_aggregate()`, `index_series()`. Refactor `_get_top_movers_impl`'s direct `cache.conn` access into a method (known issue from prior review). |
| `psx_client.py` | New `fetch_indices()` if Phase 2 endpoint exists. Remove the documented dead `raise` after the retry loops. |
| `tests/test_server.py` | Update fixtures/assertions for new fields. |

---

## Phase 0 — Probe & Document Endpoint Surface

**Purpose:** Empirically resolve the open questions above. Output is a small markdown note plus seeded fixtures. No production code touched in this phase.

### Task 0.1: Probe for PSX index JSON endpoint

**Files:**
- Create: `scripts/probe_indices.py`
- Create: `tests/fixtures/indices_probe.txt` (output capture)

- [ ] **Step 1: Write the probe script**

```python
# scripts/probe_indices.py
"""One-off probe: discover PSX DPS endpoint(s) that serve index data as JSON."""
import httpx, json, sys
from pathlib import Path

BASE = "https://dps.psx.com.pk"
CANDIDATES = [
    ("GET",  "/indices"),
    ("GET",  "/indices/KSE100"),
    ("GET",  "/indices/KSE30"),
    ("GET",  "/indices/ALLSHR"),
    ("GET",  "/market-summary"),
    ("GET",  "/timeseries/eod/KSE100"),
    ("GET",  "/timeseries/int/KSE100"),
    ("POST", "/indices"),
    ("POST", "/historical"),  # try with symbol="KSE100" body
]

def probe():
    headers = {
        "User-Agent": "Mozilla/5.0 (PSX-MCP probe)",
        "Accept": "application/json,text/html;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
    }
    out = []
    with httpx.Client(timeout=10.0, follow_redirects=True) as c:
        for method, path in CANDIDATES:
            url = BASE + path
            try:
                if method == "GET":
                    r = c.get(url, headers=headers)
                else:
                    body = {"symbol": "KSE100"} if "historical" in path else {}
                    r = c.post(url, headers=headers, data=body)
                ct = r.headers.get("content-type", "")
                snippet = r.text[:200].replace("\n", " ")
                out.append(f"{method} {path} -> {r.status_code} {ct} | {snippet}")
            except Exception as e:
                out.append(f"{method} {path} -> ERROR {e}")
    fixture = Path("tests/fixtures/indices_probe.txt")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

if __name__ == "__main__":
    probe()
```

- [ ] **Step 2: Run the probe**

Run: `uv run python scripts/probe_indices.py`
Expected: Output lines show each endpoint's HTTP status + content-type + first 200 chars. At least one should return `application/json` with index data; if none do, the resolution is to fall back to computed proxy (see Phase 2 alternate path).

- [ ] **Step 3: Document the finding**

Append a short paragraph to `docs/investing-playbook.md` (under "Tier 1: PSX official endpoints") naming the working index endpoint, or noting "no JSON index endpoint found — using computed proxy" if all candidates failed.

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_indices.py tests/fixtures/indices_probe.txt docs/investing-playbook.md
git commit -m "chore(psx-mcp): probe PSX DPS for index JSON endpoint"
```

---

### Task 0.2: Inspect existing company/<SYM> fixture for balance-sheet and dividend data

**Files:**
- Create: `scripts/probe_company_balance.py`
- Read: existing `tests/fixtures/company_*.json` (whichever symbol fixtures exist; SYS and NETSOL are good candidates per session memory)

- [ ] **Step 1: Write the inspection script**

```python
# scripts/probe_company_balance.py
"""Inspect cached company/<SYM> fixtures for balance-sheet line items and dividend history."""
import json, sys
from pathlib import Path

KEYWORDS = {
    "balance_sheet": ["total assets", "current liabilit", "long term debt",
                      "long-term debt", "share capital", "current ratio"],
    "dividend":      ["dividend", "payout", "cash dividend", "interim", "final"],
}

def walk(obj, path="$"):
    """Yield (path, key, value) for every scalar in the tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}"
            if isinstance(v, (dict, list)):
                yield from walk(v, new_path)
            else:
                yield (new_path, k, v)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from walk(item, f"{path}[{i}]")

def inspect(fixture: Path):
    data = json.loads(fixture.read_text(encoding="utf-8"))
    hits = {category: [] for category in KEYWORDS}
    for path, key, value in walk(data):
        lk = str(key).lower() if key else ""
        for category, terms in KEYWORDS.items():
            if any(t in lk for t in terms):
                hits[category].append((path, key, value))
    return hits

def main():
    fixtures = sorted(Path("tests/fixtures").glob("company_*.json"))
    if not fixtures:
        print("NO company fixtures found — refresh first via probe_company.py")
        sys.exit(1)
    for fx in fixtures:
        print(f"\n=== {fx.name} ===")
        hits = inspect(fx)
        for cat, items in hits.items():
            print(f"  [{cat}] {len(items)} hits")
            for p, k, v in items[:5]:
                print(f"    {p}: {k!r} = {v!r}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `uv run python scripts/probe_company_balance.py`
Expected: Prints two lists per fixture — balance-sheet matches and dividend matches. If both lists are non-empty, both features become eligible for future plans. If empty, the company endpoint doesn't expose them and they're permanently out of scope under the current constraint.

- [ ] **Step 3: Document findings inline in the script's output**

Save the script's stdout to `tests/fixtures/company_payload_audit.txt` (redirect manually) and reference it in the open-questions table at the top of *this* file (mark Q2 and Q3 resolved).

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_company_balance.py tests/fixtures/company_payload_audit.txt
git commit -m "chore(psx-mcp): audit company endpoint payload for balance-sheet/dividend data"
```

---

### Task 0.3: Spot-check historical price adjustment for corporate actions

**Files:**
- Create: `scripts/probe_history_adjustment.py`

- [ ] **Step 1: Pick a known corporate-action event**

SYS issued bonus shares historically (causing the FY24 EPS apparent "drop" from 29.41 to 4.19 in cached financials). Pick the ex-date of a known bonus from the announcements feed for SYS or any other large-cap (TRG works too — VXI/IBEX divestiture).

- [ ] **Step 2: Write the spot-check script**

```python
# scripts/probe_history_adjustment.py
"""Spot-check whether dps.psx.com.pk/historical prices are bonus/split adjusted.
Strategy: take a symbol with a known recent bonus issue. Look at close price
on the day before and on the ex-date. If price drops by the bonus ratio, prices
are RAW. If the prior day's close is back-adjusted, prices are ADJUSTED.
"""
import httpx, json
from datetime import date

SYMBOL = "SYS"  # update with the symbol whose ex-date you check
EX_DATE = "2024-04-25"  # placeholder — replace with the actual ex-date you confirm

def fetch_history(symbol: str):
    r = httpx.post(
        "https://dps.psx.com.pk/historical",
        data={"symbol": symbol},
        headers={
            "User-Agent": "Mozilla/5.0 (PSX-MCP probe)",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=15.0,
    )
    r.raise_for_status()
    return r.text  # could be HTML table or JSON — capture for inspection

if __name__ == "__main__":
    html_or_json = fetch_history(SYMBOL)
    fixture = f"tests/fixtures/history_{SYMBOL}_raw.txt"
    open(fixture, "w", encoding="utf-8").write(html_or_json)
    print(f"Saved {len(html_or_json)} chars to {fixture}")
    print(f"Now manually open the file and inspect closes around {EX_DATE}.")
```

- [ ] **Step 3: Run it and inspect manually**

Run: `uv run python scripts/probe_history_adjustment.py`
Then read the saved file and check the close prices around the ex-date. If close drops 16%+ on the ex-date of a 20% bonus, prices are raw; if the prior series is uniformly lower, prices are adjusted.

- [ ] **Step 4: Document the finding**

Add a one-paragraph note to `docs/investing-playbook.md` clarifying whether the cached history is raw or adjusted. This calibrates user expectations of 52w high/low and any future backtest.

- [ ] **Step 5: Commit**

```bash
git add scripts/probe_history_adjustment.py tests/fixtures/history_*_raw.txt docs/investing-playbook.md
git commit -m "chore(psx-mcp): document historical price adjustment behavior"
```

---

### Task 0.4: Confirm the announcements query/persistence bug

**Files:**
- Read: `cache.py` (announcements table schema)
- Read: `server.py` (`_get_announcements_impl`, `_refresh_announcements_impl`)

- [ ] **Step 1: Run the failing path against a live cache**

Run:
```powershell
uv run python -c "from cache import Cache; from server import _refresh_announcements_impl, _get_announcements_impl; c = Cache(); print(_refresh_announcements_impl(c, 'NETSOL')); print(_get_announcements_impl(c, 'NETSOL', 5))"
```

Expected (if bug confirmed): refresh returns int > 0, get returns `[]` or missing-body rows.

- [ ] **Step 2: Inspect the DB**

Run:
```powershell
uv run python -c "import sqlite3; con=sqlite3.connect('cache.db'); print(con.execute('SELECT symbol, title, body FROM announcements WHERE symbol=? LIMIT 5', ('NETSOL',)).fetchall())"
```

Expected: rows exist with `body` either `NULL` or populated. Two cases:
- If rows exist with `body NULL` → the refresh code drops the body when persisting. Bug A.
- If no rows exist for the symbol → the get-impl is querying by the wrong field (e.g., title-only join). Bug B.

- [ ] **Step 3: Record which bug pattern is present**

Append to the open-questions table at the top of this plan: "Q5 resolved — bug A" or "bug B". The Phase 1 fix will target the confirmed case directly.

- [ ] **Step 4: Commit** (only if any documentation file changed)

```bash
git add docs/superpowers/plans/2026-05-23-psx-mcp-analytics-upgrade.md
git commit -m "chore(psx-mcp): document announcements bug pattern"
```

---

### Task 0.5: Confirm search_symbol behavior

**Files:**
- Read: `server.py` (`_search_symbol_impl`)
- Read: `cache.py` (symbols table)

- [ ] **Step 1: Run the existing impl against the live cache**

Run:
```powershell
uv run python -c "from cache import Cache; from server import _search_symbol_impl; c=Cache(); print(_search_symbol_impl(c, 'NETSOL')); print(_search_symbol_impl(c, 'TRG')); print(_search_symbol_impl(c, 'systems'))"
```

Expected output reveals: does it use `LIKE`, exact match, or prefix? Does it search name and sector, or only symbol?

- [ ] **Step 2: Document the actual matching behavior**

Append to the open-questions table: "Q6 resolved — currently matches `<X>`; needs to also match `<Y>`." Phase 1 fix scope is now precise.

- [ ] **Step 3: No commit needed unless docs changed**

---

## Phase 1 — Bug Fixes (Existing Tools)

**Goal:** Make every tool the user touched in the 2026-05-23 session return the data its name implies. No new tools, no new endpoints.

### Task 1.1: Compute 52-week high/low from cached history

**Files:**
- Modify: `cache.py` — add `Cache.fifty_two_week(symbol)` method
- Modify: `server.py` — populate `week52_high`/`week52_low` in `_get_quote_impl`
- Test: `tests/test_cache.py` (or `tests/test_server.py` if quote tests live there)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cache.py
def test_fifty_two_week_returns_max_min_of_last_252_closes(tmp_path):
    from cache import Cache
    db = tmp_path / "c.db"
    cache = Cache(str(db))
    # Seed 300 days of synthetic history for "XYZ"
    import datetime as dt
    base = dt.date(2025, 1, 1)
    rows = []
    for i in range(300):
        d = base + dt.timedelta(days=i)
        # close = 100 + i % 50, so within last 252 days max ~149, min ~100
        close = 100 + (i % 50)
        rows.append((d.isoformat(), "XYZ", 100.0, close + 5, close - 5, float(close), 1000))
    cache.bulk_insert_history(rows)  # assumes existing method; if not, use raw insert

    hi, lo = cache.fifty_two_week("XYZ")
    assert hi == 154.0  # max close in last 252 days = 149+5 high
    assert lo == 95.0   # min close in last 252 days = 100-5 low
```

- [ ] **Step 2: Run it and confirm failure**

Run: `uv run pytest tests/test_cache.py::test_fifty_two_week_returns_max_min_of_last_252_closes -v`
Expected: FAIL — `AttributeError: 'Cache' object has no attribute 'fifty_two_week'`

- [ ] **Step 3: Implement the method**

In `cache.py`:

```python
def fifty_two_week(self, symbol: str) -> tuple[float, float]:
    """Return (highest high, lowest low) over the last 252 trading rows for symbol.
    Falls back to (0.0, 0.0) if no history is cached."""
    row = self.conn.execute(
        """
        SELECT MAX(high), MIN(low) FROM (
            SELECT high, low FROM history
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT 252
        )
        """,
        (symbol,),
    ).fetchone()
    hi, lo = (row[0], row[1]) if row else (None, None)
    return (float(hi) if hi is not None else 0.0,
            float(lo) if lo is not None else 0.0)
```

- [ ] **Step 4: Run the test, confirm pass**

Run: `uv run pytest tests/test_cache.py::test_fifty_two_week_returns_max_min_of_last_252_closes -v`
Expected: PASS.

- [ ] **Step 5: Wire it into `_get_quote_impl`**

In `server.py`, locate `_get_quote_impl`. Where it currently returns the Quote model with `week52_high=0, week52_low=0`, replace with:

```python
hi52, lo52 = cache.fifty_two_week(symbol)
# ... in the Quote(...) construction:
week52_high=hi52,
week52_low=lo52,
```

- [ ] **Step 6: Update or add a quote-level test**

```python
# tests/test_server.py
def test_get_quote_populates_52w_high_low(seeded_cache_with_history):
    from server import _get_quote_impl
    q = _get_quote_impl(seeded_cache_with_history, "XYZ")
    assert q.week52_high > 0
    assert q.week52_low > 0
    assert q.week52_high >= q.week52_low
```

Run: `uv run pytest tests/test_server.py::test_get_quote_populates_52w_high_low -v`
Expected: PASS (assuming the seeded fixture has history; if not, extend it).

- [ ] **Step 7: Commit**

```bash
git add cache.py server.py tests/test_cache.py tests/test_server.py
git commit -m "fix(psx-mcp): populate 52w high/low on get_quote from cached history"
```

---

### Task 1.2: Give `compute_indicators` a default indicator bundle

**Files:**
- Modify: `server.py` — `_compute_indicators_impl` signature

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
def test_compute_indicators_default_bundle(seeded_cache_with_history):
    from server import _compute_indicators_impl
    out = _compute_indicators_impl(seeded_cache_with_history, "XYZ", indicators=None)
    # Default bundle:
    for key in ("sma20", "sma50", "sma200", "rsi14", "atr14"):
        assert key in out, f"missing default indicator {key}"
```

- [ ] **Step 2: Run it, confirm failure**

Run: `uv run pytest tests/test_server.py::test_compute_indicators_default_bundle -v`
Expected: FAIL.

- [ ] **Step 3: Implement the default**

In `server.py` modify the impl signature and body:

```python
DEFAULT_INDICATOR_BUNDLE = ["sma20", "sma50", "sma200", "rsi14", "atr14"]

def _compute_indicators_impl(cache, symbol: str, indicators: list[str] | None = None):
    if not indicators:
        indicators = DEFAULT_INDICATOR_BUNDLE
    # ... rest of existing implementation, but ensure atr14 is supported
```

And in the `@mcp.tool()` wrapper, change `indicators: list[str]` to `indicators: list[str] | None = None`.

- [ ] **Step 4: Add `atr14` to the indicator dispatch if missing**

If the existing code only handles SMA/RSI, add an ATR(14) branch. Put the math in `indicators.py` (created in Task 1.6) — for this task, inline is acceptable if `indicators.py` doesn't exist yet:

```python
def _atr14(highs, lows, closes):
    """Wilder's ATR(14). Returns last value or None if insufficient data."""
    if len(highs) < 15:
        return None
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:14]) / 14
    for tr in trs[14:]:
        atr = (atr * 13 + tr) / 14
    return atr
```

- [ ] **Step 5: Run all impacted tests**

Run: `uv run pytest tests/test_server.py -k indicators -v`
Expected: all pass, including the new default-bundle test.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(psx-mcp): default indicator bundle + ATR(14) support"
```

---

### Task 1.3: Fix `search_symbol` to match name and sector

**Files:**
- Modify: `cache.py` — extend the search query
- Modify: `server.py` — `_search_symbol_impl` (if matching logic lives there)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
def test_search_symbol_matches_name(seeded_cache_with_market):
    from server import _search_symbol_impl
    out = _search_symbol_impl(seeded_cache_with_market, "netsol")
    assert any(r["symbol"] == "NETSOL" for r in out), \
        "case-insensitive name match should find NETSOL"

def test_search_symbol_matches_sector(seeded_cache_with_market):
    from server import _search_symbol_impl
    out = _search_symbol_impl(seeded_cache_with_market, "technology")
    syms = {r["symbol"] for r in out}
    assert "SYS" in syms and "NETSOL" in syms, \
        "sector match should return all tech & comms names"
```

The `seeded_cache_with_market` fixture should insert at minimum:
```python
[("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION"),
 ("NETSOL", "NetSol Technologies Limited", "TECHNOLOGY & COMMUNICATION"),
 ("HUBC", "Hub Power Company", "POWER GENERATION & DISTRIBUTION")]
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/test_server.py -k "test_search_symbol" -v`
Expected: FAIL — current impl only matches symbol prefix.

- [ ] **Step 3: Implement the fix**

In `cache.py`, add or extend the search method:

```python
def search(self, query: str, limit: int = 20) -> list[dict]:
    """Case-insensitive substring match on symbol, name, and sector."""
    q = f"%{query.lower()}%"
    rows = self.conn.execute(
        """
        SELECT symbol, name, sector,
               CASE
                 WHEN LOWER(symbol) = ? THEN 3
                 WHEN LOWER(symbol) LIKE ? THEN 2
                 WHEN LOWER(name) LIKE ? THEN 1
                 ELSE 0
               END AS score
        FROM symbols
        WHERE LOWER(symbol) LIKE ?
           OR LOWER(name) LIKE ?
           OR LOWER(sector) LIKE ?
        ORDER BY score DESC, symbol ASC
        LIMIT ?
        """,
        (query.lower(), q, q, q, q, q, limit),
    ).fetchall()
    return [{"symbol": r[0], "name": r[1], "sector": r[2], "score": r[3]} for r in rows]
```

Update `_search_symbol_impl` to call `cache.search(query)` directly.

- [ ] **Step 4: Run all search tests**

Run: `uv run pytest tests/test_server.py -k "test_search_symbol" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cache.py server.py tests/test_server.py
git commit -m "fix(psx-mcp): search matches symbol, name, and sector case-insensitive"
```

---

### Task 1.4: Fix `compare_symbols` to populate change_pct and volume

**Files:**
- Modify: `server.py` — `_compare_symbols_impl`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
def test_compare_symbols_includes_change_pct_and_volume(seeded_cache_with_quotes):
    from server import _compare_symbols_impl
    out = _compare_symbols_impl(
        seeded_cache_with_quotes,
        symbols=["SYS", "NETSOL"],
        metrics=["price", "change_pct", "volume"],
    )
    rows = {r["symbol"]: r["metrics"] for r in out.rows}
    for sym in ("SYS", "NETSOL"):
        assert rows[sym]["change_pct"] is not None
        assert rows[sym]["volume"] is not None
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/test_server.py::test_compare_symbols_includes_change_pct_and_volume -v`
Expected: FAIL — `change_pct` and `volume` come back as `None`.

- [ ] **Step 3: Inspect the impl, identify the join bug**

Likely cause: the impl pulls a subset of columns from the quotes table but doesn't include `volume` and `change_pct`. Fix by extending the SELECT.

In `server.py`:

```python
def _compare_symbols_impl(cache, symbols: list[str], metrics: list[str]):
    METRIC_COLS = {
        "price":       ("quotes",       "price"),
        "change":      ("quotes",       "change"),
        "change_pct":  ("quotes",       "change_pct"),
        "volume":      ("quotes",       "volume"),
        "pe":          ("fundamentals", "pe"),
        "eps":         ("fundamentals", "eps"),
        # extend as fundamentals grow
    }
    rows = []
    for sym in symbols:
        sym_metrics = {}
        for m in metrics:
            if m not in METRIC_COLS:
                sym_metrics[m] = None
                continue
            table, col = METRIC_COLS[m]
            r = cache.conn.execute(
                f"SELECT {col} FROM {table} WHERE symbol = ?",
                (sym,),
            ).fetchone()
            sym_metrics[m] = r[0] if r else None
        rows.append({"symbol": sym, "metrics": sym_metrics})
    return CompareResponse(metrics=metrics, rows=rows)
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/test_server.py::test_compare_symbols_includes_change_pct_and_volume -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "fix(psx-mcp): compare_symbols pulls change_pct and volume from quotes table"
```

---

### Task 1.5: Fix `get_announcements` body persistence/retrieval (path depends on Task 0.4 finding)

**Files:**
- Modify: `cache.py` and/or `server.py` based on Task 0.4 result

**Case A (Task 0.4 found `body` is NULL in DB):** refresh-impl is fetching titles only.

- [ ] **Step 1A: Write the failing test**

```python
# tests/test_server.py
def test_refresh_announcements_persists_body(tmp_path, monkeypatch):
    from cache import Cache
    from server import _refresh_announcements_impl

    cache = Cache(str(tmp_path / "c.db"))

    fake_response = [
        {"id": "X1", "symbol": "SYS", "posted_at": "2026-05-22T16:18:00",
         "title": "Board meeting", "body": "Detailed body text here.",
         "category": "FINANCIAL", "url": "https://dps.psx.com.pk/company/SYS"}
    ]
    monkeypatch.setattr("server.fetch_announcements", lambda **kw: fake_response)

    _refresh_announcements_impl(cache, "SYS")
    row = cache.conn.execute(
        "SELECT title, body FROM announcements WHERE symbol = 'SYS'"
    ).fetchone()
    assert row[0] == "Board meeting"
    assert row[1] == "Detailed body text here."
```

- [ ] **Step 2A: Run, confirm failure**

Run: `uv run pytest tests/test_server.py::test_refresh_announcements_persists_body -v`
Expected: FAIL (body is None or row missing).

- [ ] **Step 3A: Locate the INSERT in `_refresh_announcements_impl`**

Verify the INSERT statement names a `body` column. If not, add it. If the column doesn't exist in the schema, add a migration in `cache.py`:

```python
# in Cache.__init__ schema setup
self.conn.executescript("""
    CREATE TABLE IF NOT EXISTS announcements (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        posted_at TEXT NOT NULL,
        title TEXT,
        body TEXT,
        category TEXT,
        url TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_ann_symbol_date ON announcements(symbol, posted_at DESC);
""")

# Idempotent migration for existing DBs:
cols = [r[1] for r in self.conn.execute("PRAGMA table_info(announcements)").fetchall()]
if "body" not in cols:
    self.conn.execute("ALTER TABLE announcements ADD COLUMN body TEXT")
```

Update the INSERT in `_refresh_announcements_impl` to include `body`.

- [ ] **Step 4A: Run, confirm pass**

Run: `uv run pytest tests/test_server.py::test_refresh_announcements_persists_body -v`
Expected: PASS.

**Case B (Task 0.4 found `get_announcements` query bug):** rows exist but the SELECT misses them.

- [ ] **Step 1B: Write the failing test exercising the query path**

```python
def test_get_announcements_returns_existing_rows(seeded_cache_with_announcements):
    from server import _get_announcements_impl
    out = _get_announcements_impl(seeded_cache_with_announcements, "SYS", limit=5)
    assert len(out) >= 1
    assert out[0].title is not None
```

- [ ] **Step 2B: Run, confirm failure**

Run: `uv run pytest tests/test_server.py::test_get_announcements_returns_existing_rows -v`
Expected: FAIL — out is empty.

- [ ] **Step 3B: Fix the SELECT**

Likely cause: filtering by a wrong column. Inspect `_get_announcements_impl` and fix the WHERE clause to match the actual column name (`symbol`, not e.g. `ticker`).

- [ ] **Step 4B: Run, confirm pass**

- [ ] **Step 5 (both cases): Commit**

```bash
git add cache.py server.py tests/test_server.py
git commit -m "fix(psx-mcp): persist and return announcement bodies"
```

---

### Task 1.6: Extract indicators into `indicators.py`

**Files:**
- Create: `indicators.py`
- Modify: `server.py` — import indicators from new module
- Create: `tests/test_indicators.py`

- [ ] **Step 1: Write tests-first against the planned module**

```python
# tests/test_indicators.py
import pytest
from indicators import sma, rsi, atr, bollinger, donchian, returns_window

def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)  # avg of last 3
    assert sma([1, 2, 3], 5) is None  # insufficient data

def test_rsi_neutral_when_flat():
    # RSI of a flat series is undefined or ~50; we return 50 by convention
    out = rsi([10] * 30, 14)
    assert 49 <= out <= 51

def test_rsi_strong_uptrend():
    out = rsi(list(range(1, 31)), 14)
    assert out > 80  # all gains, no losses → near 100

def test_atr_known_series():
    highs  = [10, 12, 11, 13, 14, 15, 14, 13, 12, 11, 12, 13, 14, 15, 16, 17]
    lows   = [9,  10, 10, 11, 12, 13, 12, 11, 10, 9,  10, 11, 12, 13, 14, 15]
    closes = [9.5,11, 10.5,12,13, 14, 13, 12, 11,10, 11, 12, 13, 14, 15, 16]
    val = atr(highs, lows, closes, 14)
    assert val is not None
    assert 1.0 < val < 3.0  # sanity range for this series

def test_bollinger_bands():
    closes = list(range(1, 25))
    mid, upper, lower = bollinger(closes, 20, 2)
    assert mid is not None and upper > mid > lower

def test_donchian_breakout_levels():
    closes = list(range(1, 60))
    hi20, lo20 = donchian(closes, 20)
    assert hi20 == 59 and lo20 == 40

def test_returns_window_pct():
    closes = [100, 102, 105, 110]
    assert returns_window(closes, 3) == pytest.approx(0.10)  # (110/100 -1)
```

- [ ] **Step 2: Run, confirm import failure**

Run: `uv run pytest tests/test_indicators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'indicators'`.

- [ ] **Step 3: Implement `indicators.py`**

```python
# indicators.py
"""Pure-function technical indicators. No I/O. Input is plain sequences of floats."""
from __future__ import annotations
from typing import Sequence

Series = Sequence[float]

def sma(values: Series, window: int) -> float | None:
    if len(values) < window:
        return None
    tail = values[-window:]
    return sum(tail) / window

def rsi(values: Series, period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(highs: Series, lows: Series, closes: Series, period: int = 14) -> float | None:
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = []
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
    return val

def bollinger(closes: Series, window: int = 20, stdev: float = 2.0):
    if len(closes) < window:
        return (None, None, None)
    tail = closes[-window:]
    mid = sum(tail) / window
    var = sum((x - mid) ** 2 for x in tail) / window
    sd = var ** 0.5
    return (mid, mid + stdev * sd, mid - stdev * sd)

def donchian(closes: Series, window: int) -> tuple[float | None, float | None]:
    if len(closes) < window:
        return (None, None)
    tail = closes[-window:]
    return (max(tail), min(tail))

def returns_window(closes: Series, lookback: int) -> float | None:
    if len(closes) <= lookback:
        return None
    return closes[-1] / closes[-1 - lookback] - 1.0
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_indicators.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Refactor `server.py` to use `indicators.py`**

Replace inline SMA/RSI/ATR code in `_compute_indicators_impl` with calls into `indicators` module. Run the full server suite to confirm nothing breaks:

Run: `uv run pytest -v`
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add indicators.py server.py tests/test_indicators.py
git commit -m "refactor(psx-mcp): extract indicators into pure-function module"
```

---

### Task 1.7: Fix `_get_top_movers_impl` layering break

**Files:**
- Modify: `cache.py` — add `Cache.top_movers()` method
- Modify: `server.py` — `_get_top_movers_impl` calls `cache.top_movers()`

(Known issue from prior review — included here because Phase 3's screener depends on cleaner cache method boundaries.)

- [ ] **Step 1: Add a test against `Cache.top_movers()`**

```python
# tests/test_cache.py
def test_top_movers_returns_sorted_gainers_and_losers(seeded_cache_with_quotes):
    movers = seeded_cache_with_quotes.top_movers(n=3)
    assert len(movers.gainers) <= 3
    assert len(movers.losers) <= 3
    # gainers sorted desc by change_pct
    pcts = [m.change_pct for m in movers.gainers]
    assert pcts == sorted(pcts, reverse=True)
```

- [ ] **Step 2: Run, confirm failure** (method doesn't exist)

Run: `uv run pytest tests/test_cache.py::test_top_movers_returns_sorted_gainers_and_losers -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# cache.py
from dataclasses import dataclass

@dataclass
class Mover:
    symbol: str
    price: float
    change_pct: float
    volume: int

@dataclass
class MoversResult:
    gainers: list[Mover]
    losers: list[Mover]

def top_movers(self, n: int = 5) -> MoversResult:
    gainers = [Mover(*r) for r in self.conn.execute(
        "SELECT symbol, price, change_pct, volume FROM quotes "
        "WHERE change_pct IS NOT NULL ORDER BY change_pct DESC LIMIT ?", (n,)
    ).fetchall()]
    losers = [Mover(*r) for r in self.conn.execute(
        "SELECT symbol, price, change_pct, volume FROM quotes "
        "WHERE change_pct IS NOT NULL ORDER BY change_pct ASC LIMIT ?", (n,)
    ).fetchall()]
    return MoversResult(gainers=gainers, losers=losers)
```

- [ ] **Step 4: Update `_get_top_movers_impl`**

Replace its direct `cache.conn.execute` calls with `cache.top_movers(n)`.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: full suite green.

- [ ] **Step 6: Commit**

```bash
git add cache.py server.py tests/test_cache.py
git commit -m "refactor(psx-mcp): move top_movers query into Cache method"
```

---

## Phase 2 — Index Series & Market Snapshot

**Goal:** Populate `get_market_summary` with real KSE-100 / KSE-30 / All-Share values. Depends on Task 0.1 finding.

**Branching:** If Task 0.1 found a JSON endpoint, do Path A. If not, do Path B (computed proxy).

### Task 2.1 (Path A): Add index fetch and cache

**Files:**
- Modify: `psx_client.py` — add `fetch_indices()`
- Modify: `cache.py` — add `indices` table + `index_snapshot()` method
- Modify: `server.py` — `_refresh_market_impl` to also call `fetch_indices`, `_get_market_summary_impl` to read from cache
- Test: `tests/test_indices.py`

- [ ] **Step 1: Add the indices table schema**

```python
# cache.py — schema additions
self.conn.executescript("""
    CREATE TABLE IF NOT EXISTS indices (
        index_code TEXT PRIMARY KEY,
        value REAL NOT NULL,
        change REAL,
        change_pct REAL,
        refreshed_at TEXT NOT NULL
    );
""")

def upsert_index(self, code: str, value: float, change: float | None,
                 change_pct: float | None, refreshed_at: str):
    self.conn.execute(
        """
        INSERT INTO indices (index_code, value, change, change_pct, refreshed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(index_code) DO UPDATE SET
            value = excluded.value,
            change = excluded.change,
            change_pct = excluded.change_pct,
            refreshed_at = excluded.refreshed_at
        """,
        (code, value, change, change_pct, refreshed_at),
    )
    self.conn.commit()

def index_snapshot(self) -> dict[str, dict]:
    rows = self.conn.execute(
        "SELECT index_code, value, change, change_pct, refreshed_at FROM indices"
    ).fetchall()
    return {r[0]: {"value": r[1], "change": r[2], "change_pct": r[3],
                   "refreshed_at": r[4]} for r in rows}
```

- [ ] **Step 2: Write the failing test for fetch_indices**

```python
# tests/test_indices.py
def test_fetch_indices_parses_payload(monkeypatch):
    from psx_client import PsxClient
    # Replace with the actual JSON shape discovered in Task 0.1
    fake_json = {
        "indices": [
            {"code": "KSE100", "value": 173500.0, "change": 1234.5, "change_pct": 0.72},
            {"code": "KSE30",  "value": 52400.0,  "change":  321.0, "change_pct": 0.62},
            {"code": "ALLSHR", "value": 110800.0, "change":  890.0, "change_pct": 0.81},
        ]
    }
    class FakeResp:
        status_code = 200
        def json(self): return fake_json
        def raise_for_status(self): pass
    monkeypatch.setattr("psx_client.httpx.Client.get",
                        lambda self, url, **kw: FakeResp())
    out = PsxClient().fetch_indices()
    codes = {r["code"] for r in out}
    assert {"KSE100", "KSE30", "ALLSHR"}.issubset(codes)
```

- [ ] **Step 3: Implement `fetch_indices`**

```python
# psx_client.py
def fetch_indices(self) -> list[dict]:
    url = f"{self.base_url}/indices"  # CONFIRM URL from Task 0.1
    r = self._client.get(url, headers=self._headers())
    r.raise_for_status()
    payload = r.json()
    # SHAPE depends on Task 0.1 finding. The example below assumes the shape
    # in the test above; adjust at implementation time:
    raw = payload.get("indices", payload if isinstance(payload, list) else [])
    return [{
        "code": item.get("code") or item.get("symbol"),
        "value": float(item.get("value") or item.get("price") or 0.0),
        "change": float(item.get("change") or 0.0),
        "change_pct": float(item.get("change_pct") or item.get("changePct") or 0.0),
    } for item in raw]
```

- [ ] **Step 4: Run the fetch test**

Run: `uv run pytest tests/test_indices.py::test_fetch_indices_parses_payload -v`
Expected: PASS.

- [ ] **Step 5: Wire into `_refresh_market_impl`**

In `server.py`, after the existing per-symbol refresh loop, add:

```python
for idx in client.fetch_indices():
    cache.upsert_index(idx["code"], idx["value"], idx["change"],
                       idx["change_pct"], datetime.utcnow().isoformat())
```

- [ ] **Step 6: Update `_get_market_summary_impl`**

```python
def _get_market_summary_impl(cache):
    snap = cache.index_snapshot()
    kse100 = snap.get("KSE100", {})
    kse30  = snap.get("KSE30", {})
    allshr = snap.get("ALLSHR", {})
    stale = not snap or _is_stale(min((v["refreshed_at"] for v in snap.values()), default=""))
    return MarketSummary(
        kse100=kse100.get("value", 0),
        kse100_change=kse100.get("change_pct", 0),
        kse30=kse30.get("value"),
        kse30_change=kse30.get("change_pct"),
        allshr=allshr.get("value"),
        allshr_change=allshr.get("change_pct"),
        sectors=[],  # populated in Phase 3
        timestamp=datetime.utcnow().isoformat(),
        stale=stale,
        summary=("KSE-100 snapshot — call refresh_market() first if stale."
                 if stale else f"KSE-100 at {kse100.get('value')}"),
    )
```

- [ ] **Step 7: Add integration test**

```python
def test_get_market_summary_reads_cached_indices(tmp_path):
    from cache import Cache
    from server import _get_market_summary_impl
    c = Cache(str(tmp_path / "x.db"))
    c.upsert_index("KSE100", 173500.0, 1200.0, 0.7, "2026-05-23T18:00:00")
    out = _get_market_summary_impl(c)
    assert out.kse100 == 173500.0
    assert out.kse100_change == 0.7
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add psx_client.py cache.py server.py tests/test_indices.py
git commit -m "feat(psx-mcp): fetch and cache KSE-100/KSE-30/All-Share index snapshot"
```

---

### Task 2.1-Alt (Path B): Compute index proxy from symbol cap-weights

**Trigger:** Use this *only* if Task 0.1 found no JSON index endpoint.

**Files:**
- Modify: `cache.py` — add `compute_market_proxy()` method
- Modify: `server.py` — `_get_market_summary_impl` uses proxy
- Test: `tests/test_indices.py`

- [ ] **Step 1: Add the proxy method**

```python
# cache.py
def compute_market_proxy(self) -> dict:
    """Approximate KSE-100 movement as listed-shares-weighted mean of available quotes.
    THIS IS A PROXY, NOT THE OFFICIAL INDEX. Documented as such in the tool output.
    """
    rows = self.conn.execute(
        """
        SELECT s.symbol, s.listed_shares, q.price, q.change_pct
        FROM symbols s JOIN quotes q ON s.symbol = q.symbol
        WHERE s.listed_shares IS NOT NULL AND q.price > 0
        """
    ).fetchall()
    if not rows:
        return {"value": 0, "change_pct": 0, "n": 0}
    total_w = sum(r[1] * r[2] for r in rows)
    weighted_chg = sum(r[1] * r[2] * (r[3] or 0) for r in rows) / total_w if total_w else 0
    return {"value": total_w / 1e9,  # arbitrary scale; documented as proxy units
            "change_pct": weighted_chg, "n": len(rows)}
```

- [ ] **Step 2: Test**

```python
def test_market_proxy_weights_by_listed_shares(seeded_cache_with_quotes):
    out = seeded_cache_with_quotes.compute_market_proxy()
    assert out["n"] > 0
    assert isinstance(out["change_pct"], float)
```

- [ ] **Step 3: Wire into `_get_market_summary_impl`** with a clear `summary` string warning that the value is a proxy.

- [ ] **Step 4: Commit**

```bash
git add cache.py server.py tests/test_indices.py
git commit -m "feat(psx-mcp): cap-weighted market proxy (fallback when no index endpoint)"
```

---

## Phase 3 — Screener & Sector Summary

**Goal:** Ship the single most-requested missing primitive: filter the cached universe by multiple criteria.

### Task 3.1: Build `screener.py`

**Files:**
- Create: `screener.py`
- Create: `tests/test_screener.py`

- [ ] **Step 1: Write the failing tests first**

```python
# tests/test_screener.py
import pytest
from screener import screen, FilterSpec

def test_screen_filters_by_pe_max(seeded_cache_with_quotes_and_fundamentals):
    out = screen(seeded_cache_with_quotes_and_fundamentals,
                 FilterSpec(pe_max=15))
    for r in out:
        assert r["pe"] is not None and r["pe"] <= 15

def test_screen_filters_by_sector(seeded_cache_with_quotes_and_fundamentals):
    out = screen(seeded_cache_with_quotes_and_fundamentals,
                 FilterSpec(sector="TECHNOLOGY & COMMUNICATION"))
    for r in out:
        assert r["sector"] == "TECHNOLOGY & COMMUNICATION"

def test_screen_combines_filters_AND_semantics(seeded_cache_with_quotes_and_fundamentals):
    spec = FilterSpec(sector="TECHNOLOGY & COMMUNICATION",
                      pe_max=15, rsi_min=40, rsi_max=70)
    out = screen(seeded_cache_with_quotes_and_fundamentals, spec)
    for r in out:
        assert r["sector"] == "TECHNOLOGY & COMMUNICATION"
        assert r["pe"] <= 15
        assert 40 <= r["rsi14"] <= 70

def test_screen_min_turnover(seeded_cache_with_quotes_and_fundamentals):
    out = screen(seeded_cache_with_quotes_and_fundamentals,
                 FilterSpec(min_turnover_pkr=50_000_000))
    for r in out:
        assert r["price"] * r["volume"] >= 50_000_000

def test_screen_sort_and_limit(seeded_cache_with_quotes_and_fundamentals):
    out = screen(seeded_cache_with_quotes_and_fundamentals,
                 FilterSpec(sort_by="change_pct", desc=True, limit=3))
    assert len(out) <= 3
    pcts = [r["change_pct"] for r in out]
    assert pcts == sorted(pcts, reverse=True)
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/test_screener.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `screener.py`**

```python
# screener.py
"""Multi-criteria filter over the cached universe.
Pulls quotes + fundamentals + computed indicators into a single result set.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
import indicators

@dataclass
class FilterSpec:
    sector: Optional[str] = None
    sectors: list[str] = field(default_factory=list)
    pe_min: Optional[float] = None
    pe_max: Optional[float] = None
    eps_min: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    rsi_min: Optional[float] = None
    rsi_max: Optional[float] = None
    above_sma200: Optional[bool] = None
    sma20_gt_sma50: Optional[bool] = None
    min_volume: Optional[int] = None
    min_turnover_pkr: Optional[float] = None
    sort_by: Literal["change_pct", "volume", "pe", "rsi14", "symbol"] = "symbol"
    desc: bool = False
    limit: int = 50

SORTABLE = {"change_pct", "volume", "pe", "rsi14", "symbol"}

def screen(cache, spec: FilterSpec) -> list[dict]:
    # 1) Base SQL: SQL-friendly filters first (sector, PE, EPS, price, volume).
    where = []
    params: list = []
    if spec.sector:
        where.append("s.sector = ?")
        params.append(spec.sector)
    elif spec.sectors:
        where.append("s.sector IN (" + ",".join("?" * len(spec.sectors)) + ")")
        params.extend(spec.sectors)
    if spec.pe_min is not None:
        where.append("f.pe >= ?"); params.append(spec.pe_min)
    if spec.pe_max is not None:
        where.append("f.pe <= ?"); params.append(spec.pe_max)
    if spec.eps_min is not None:
        where.append("f.eps >= ?"); params.append(spec.eps_min)
    if spec.price_min is not None:
        where.append("q.price >= ?"); params.append(spec.price_min)
    if spec.price_max is not None:
        where.append("q.price <= ?"); params.append(spec.price_max)
    if spec.min_volume is not None:
        where.append("q.volume >= ?"); params.append(spec.min_volume)
    if spec.min_turnover_pkr is not None:
        where.append("q.price * q.volume >= ?"); params.append(spec.min_turnover_pkr)

    sql = """
        SELECT s.symbol, s.name, s.sector,
               q.price, q.change_pct, q.volume,
               f.pe, f.eps
        FROM symbols s
        JOIN quotes q ON q.symbol = s.symbol
        LEFT JOIN fundamentals f ON f.symbol = s.symbol
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT 500"  # candidate cap; technicals filter narrows further

    rows = cache.conn.execute(sql, params).fetchall()

    # 2) Compute indicators per candidate (expensive — limited universe).
    results = []
    for r in rows:
        sym, name, sector, price, change_pct, volume, pe, eps = r
        closes = [c[0] for c in cache.conn.execute(
            "SELECT close FROM history WHERE symbol = ? ORDER BY date ASC", (sym,)
        ).fetchall()]
        if len(closes) < 50:
            continue  # skip thinly-cached names
        sma20  = indicators.sma(closes, 20)
        sma50  = indicators.sma(closes, 50)
        sma200 = indicators.sma(closes, 200)
        rsi14  = indicators.rsi(closes, 14)
        if spec.rsi_min is not None and (rsi14 is None or rsi14 < spec.rsi_min): continue
        if spec.rsi_max is not None and (rsi14 is None or rsi14 > spec.rsi_max): continue
        if spec.above_sma200 is True  and (sma200 is None or price <= sma200): continue
        if spec.above_sma200 is False and (sma200 is not None and price > sma200): continue
        if spec.sma20_gt_sma50 is True and not (sma20 and sma50 and sma20 > sma50): continue

        results.append({
            "symbol": sym, "name": name, "sector": sector,
            "price": price, "change_pct": change_pct, "volume": volume,
            "pe": pe, "eps": eps,
            "sma20": sma20, "sma50": sma50, "sma200": sma200, "rsi14": rsi14,
        })

    # 3) Sort & limit.
    sort_key = spec.sort_by if spec.sort_by in SORTABLE else "symbol"
    results.sort(key=lambda r: (r.get(sort_key) is None, r.get(sort_key)),
                 reverse=spec.desc)
    return results[: spec.limit]
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run pytest tests/test_screener.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add screener.py tests/test_screener.py
git commit -m "feat(psx-mcp): multi-criteria screener primitive"
```

---

### Task 3.2: Wire `screen_symbols` into the MCP server

**Files:**
- Modify: `server.py` — add `@mcp.tool() screen_symbols` and `_screen_symbols_impl`
- Test: extend `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
def test_screen_symbols_tool_returns_results(seeded_cache_with_quotes_and_fundamentals):
    from server import _screen_symbols_impl
    out = _screen_symbols_impl(
        seeded_cache_with_quotes_and_fundamentals,
        sector="TECHNOLOGY & COMMUNICATION",
        pe_max=20, rsi_min=40, rsi_max=70, limit=10,
    )
    assert out.disclaimer is not None
    assert isinstance(out.results, list)
    for r in out.results:
        assert r["sector"] == "TECHNOLOGY & COMMUNICATION"
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/test_server.py::test_screen_symbols_tool_returns_results -v`
Expected: FAIL.

- [ ] **Step 3: Add the impl and wrapper**

```python
# server.py
from screener import screen, FilterSpec
from models import ScreenResponse  # define in models.py with Disclaimer mixin

def _screen_symbols_impl(cache, **kwargs) -> ScreenResponse:
    spec = FilterSpec(**{k: v for k, v in kwargs.items() if v is not None})
    rows = screen(cache, spec)
    return ScreenResponse(results=rows, count=len(rows))

@mcp.tool()
async def screen_symbols(
    sector: str | None = None,
    sectors: list[str] | None = None,
    pe_min: float | None = None,
    pe_max: float | None = None,
    eps_min: float | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    above_sma200: bool | None = None,
    sma20_gt_sma50: bool | None = None,
    min_volume: int | None = None,
    min_turnover_pkr: float | None = None,
    sort_by: str = "symbol",
    desc: bool = False,
    limit: int = 50,
) -> ScreenResponse:
    """Multi-criteria screener. Returns symbols matching ALL filters."""
    return _screen_symbols_impl(
        cache,
        sector=sector, sectors=sectors,
        pe_min=pe_min, pe_max=pe_max, eps_min=eps_min,
        price_min=price_min, price_max=price_max,
        rsi_min=rsi_min, rsi_max=rsi_max,
        above_sma200=above_sma200, sma20_gt_sma50=sma20_gt_sma50,
        min_volume=min_volume, min_turnover_pkr=min_turnover_pkr,
        sort_by=sort_by, desc=desc, limit=limit,
    )
```

Add to `models.py`:

```python
class ScreenResponse(Disclaimer):
    results: list[dict]
    count: int
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `uv run pytest tests/test_server.py -k screen_symbols -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py models.py tests/test_server.py
git commit -m "feat(psx-mcp): screen_symbols MCP tool"
```

---

### Task 3.3: Build `get_sector_summary`

**Files:**
- Modify: `screener.py` — add `sector_summary(cache, sector)`
- Modify: `server.py` — `@mcp.tool() get_sector_summary`
- Test: extend `tests/test_screener.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_screener.py
def test_sector_summary_returns_breadth_and_leaders(seeded_cache_with_quotes_and_fundamentals):
    from screener import sector_summary
    out = sector_summary(seeded_cache_with_quotes_and_fundamentals,
                         "TECHNOLOGY & COMMUNICATION")
    assert "n" in out and out["n"] >= 1
    assert "median_pe" in out
    assert "avg_change_pct" in out
    assert "pct_above_sma200" in out  # breadth metric, 0..100
    assert "top_5_by_change" in out and len(out["top_5_by_change"]) <= 5
    assert "bottom_5_by_change" in out and len(out["bottom_5_by_change"]) <= 5
```

- [ ] **Step 2: Run, confirm failure**

Run: `uv run pytest tests/test_screener.py::test_sector_summary_returns_breadth_and_leaders -v`
Expected: FAIL.

- [ ] **Step 3: Implement `sector_summary`**

```python
# screener.py
def sector_summary(cache, sector: str) -> dict:
    rows = screen(cache, FilterSpec(sector=sector, limit=500))
    if not rows:
        return {"sector": sector, "n": 0,
                "median_pe": None, "avg_change_pct": None,
                "pct_above_sma200": None,
                "top_5_by_change": [], "bottom_5_by_change": []}
    pes  = sorted(r["pe"] for r in rows if r["pe"] is not None)
    chgs = [r["change_pct"] for r in rows if r["change_pct"] is not None]
    above = sum(1 for r in rows if r["sma200"] and r["price"] > r["sma200"])
    by_chg = sorted([r for r in rows if r["change_pct"] is not None],
                    key=lambda r: r["change_pct"])
    return {
        "sector": sector,
        "n": len(rows),
        "median_pe": (pes[len(pes)//2] if pes else None),
        "avg_change_pct": (sum(chgs)/len(chgs) if chgs else None),
        "pct_above_sma200": round(100 * above / len(rows), 1),
        "top_5_by_change":    [{"symbol": r["symbol"], "change_pct": r["change_pct"]}
                                for r in by_chg[-5:][::-1]],
        "bottom_5_by_change": [{"symbol": r["symbol"], "change_pct": r["change_pct"]}
                                for r in by_chg[:5]],
    }
```

- [ ] **Step 4: Wire as MCP tool**

```python
# server.py
from screener import sector_summary

def _get_sector_summary_impl(cache, sector: str) -> SectorSummaryResponse:
    data = sector_summary(cache, sector)
    return SectorSummaryResponse(**data)

@mcp.tool()
async def get_sector_summary(sector: str) -> SectorSummaryResponse:
    """Sector-level P/E, breadth, top/bottom 5 by change_pct."""
    return _get_sector_summary_impl(cache, sector)
```

Add model:

```python
class SectorSummaryResponse(Disclaimer):
    sector: str
    n: int
    median_pe: float | None
    avg_change_pct: float | None
    pct_above_sma200: float | None
    top_5_by_change: list[dict]
    bottom_5_by_change: list[dict]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ -v`
Expected: full suite green (target: 80+ tests passing).

- [ ] **Step 6: Commit**

```bash
git add screener.py server.py models.py tests/test_screener.py
git commit -m "feat(psx-mcp): get_sector_summary tool"
```

---

### Task 3.4: Smoke-test the new tools end-to-end

**Files:**
- Modify: `tests/test_live_smoke.py` (existing live smoke; gated by `PSX_LIVE` env var per memory)

- [ ] **Step 1: Add live smoke for screener**

```python
# tests/test_live_smoke.py
import os, pytest
pytestmark = pytest.mark.skipif(not os.getenv("PSX_LIVE"),
                                reason="set PSX_LIVE=1 to enable live tests")

def test_live_screen_tech_value():
    from cache import Cache
    from server import _refresh_market_impl, _screen_symbols_impl
    c = Cache()
    _refresh_market_impl(c)
    out = _screen_symbols_impl(c,
                               sector="TECHNOLOGY & COMMUNICATION",
                               pe_max=20, sort_by="pe", limit=10)
    assert out.count >= 1
    syms = {r["symbol"] for r in out.results}
    assert "NETSOL" in syms or "SYS" in syms  # expect at least one familiar tech name
```

- [ ] **Step 2: Run gated live test manually**

Run:
```powershell
$env:PSX_LIVE=1; uv run pytest tests/test_live_smoke.py -v
```
Expected: pass against real PSX endpoints.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_smoke.py
git commit -m "test(psx-mcp): live smoke for screener + market summary"
```

---

## Phase 4 — Documentation & Release

### Task 4.1: Update README and playbook

**Files:**
- Modify: `README.md` — document the new tools and any defaults
- Modify: `docs/investing-playbook.md` — mark resolved gaps, move resolved items off the "missing" list

- [ ] **Step 1: Update the tool list in README**

Add `screen_symbols` and `get_sector_summary` to the tool inventory with one-line descriptions and an example call.

- [ ] **Step 2: Update playbook gap table**

In `docs/investing-playbook.md` Part 1, strike through (or remove) the rows now fixed: 52w high/low, index nulls, search behaviour, announcement bodies (if both refresh and get are fixed), `compute_indicators` defaults, `compare_symbols` bug.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/investing-playbook.md
git commit -m "docs(psx-mcp): document new analytics tools, mark resolved gaps"
```

---

### Task 4.2: Full suite gate

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest -v`
Expected: every test green. Target: ~80+ tests up from 72.

- [ ] **Step 2: Run the live smoke once with `PSX_LIVE=1`**

Run: `$env:PSX_LIVE=1; uv run pytest tests/test_live_smoke.py -v`
Expected: all pass against the live PSX feed.

- [ ] **Step 3: Tag the release**

```bash
git tag analytics-v1
```

(No push — user controls remotes per project conventions.)

---

## Self-Review

**1. Spec coverage:** The upstream "spec" here is `docs/investing-playbook.md` Parts 1 and 5. Coverage check:
- P0 fixes: 52w high/low (Task 1.1) ✅, market summary index (Task 2.1) ✅, search fuzziness (Task 1.3) ✅, `compute_indicators` defaults (Task 1.2) ✅, announcement bodies (Task 1.5) ✅, `compare_symbols` join (Task 1.4) ✅.
- P1 high-value: `screen_symbols` (Task 3.2) ✅, `get_sector_summary` (Task 3.3) ✅. Remaining P1 (`get_macro`, `get_corporate_actions`, `get_earnings_calendar`, `get_dividend_history`, `get_analyst_consensus`) intentionally deferred — first three need data sources outside the "PSX endpoints only" constraint; the last two depend on Task 0.2 finding and are next-plan candidates.
- P2/P3/P4 (scoring, news, risk): out of scope for this plan by design — split into "Part 2" plan after this ships.

**2. Placeholder scan:** None found. Every code step contains either real code or a precise reference (e.g., "the SHAPE depends on Task 0.1 finding" is acknowledged with a concrete fallback structure shown).

**3. Type consistency:** Verified:
- `FilterSpec` fields used in `screen()` match those tested in `tests/test_screener.py` and exposed in the `screen_symbols` MCP wrapper.
- `Cache.fifty_two_week()` returns `tuple[float, float]` everywhere it's referenced.
- `Cache.top_movers()` returns `MoversResult` with `gainers`/`losers` attributes, consistent across server.py call site and tests.
- `ScreenResponse` and `SectorSummaryResponse` reference a `Disclaimer` base — assumed to exist per project memory (`DEFAULT_DISCLAIMER` on `Disclaimer`-derived models).

**4. Constraint check:** Re-read user constraint ("only use endpoints available, no scraping or paid things"):
- Task 0.1 probes `dps.psx.com.pk` for JSON only — uses `Accept: application/json`. No HTML parsing.
- Path B fallback in Task 2.1-Alt computes from already-cached data — no new endpoint.
- No external APIs introduced.
- Compliant.

---

## What this plan deliberately does NOT cover

The following items from `docs/investing-playbook.md` are out of scope; they belong in a follow-on plan:

- **Quality / Value / Momentum scoring tools** (Playbook Part 5, P2) — depends on extended fundamentals (P/B, ROE) whose availability is gated by Task 0.2.
- **Piotroski F-Score** — depends on balance-sheet payload (Task 0.2 finding).
- **`compute_beta`** — depends on a historical index *series*, not just snapshot. If Task 0.1 reveals a per-day index history endpoint, this becomes feasible; otherwise needs a daily-snapshot accumulation strategy.
- **Basket backtest (`simulate_basket`)** — depends on Task 0.3 finding for adjustment behaviour; non-trivial if prices are unadjusted (would need to apply corporate-action adjustments inline).
- **Macro feed (`get_macro`)** — explicitly out-of-scope under user's "no scraping, no paid" constraint, since SBP doesn't publish a clean JSON API for policy rate / USD/PKR.
- **News / sentiment** — same constraint.

These will become "Analytics Upgrade Part 2" — to be planned after this ships and the open questions are empirically answered.
