# PSX MCP Analytics Upgrade — Part 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unlock long-term / quality-tilted research workflows on the PSX MCP. Fill the post-analytics-v1 gaps (ROE / P/B / dividend yield, multi-year fundamental trends, dividend history, index time series + beta, 4-quadrant composite score) and pay down the layering debt introduced by the screener. Same hard constraints as analytics-v1: only PSX DPS endpoints already accessible (JSON preferred, HTML allowed when no JSON exists), no paid feeds, no third-party scrape, no macro feed.

**Architecture:** Extend the existing FastMCP server. Every new MCP tool keeps the `async def @mcp.tool() → _<name>_impl(cache, ...) → optional Cache.<method>` shape established in analytics-v1. New domain modules (`quality.py`, `beta.py`, `score.py`) hold pure-function logic. Cache gains the right schema and helper methods so server impls never run raw SQL.

**Tech Stack:** Python 3.12, FastMCP, SQLite (existing `Cache`), `httpx` for HTTP, `pytest` for tests, `uv` for env/deps. No new dependencies.

**Constraints (carried forward from analytics-v1 + user reminder on 2026-05-24):**
- Only `dps.psx.com.pk` endpoints already in use, plus newly-probed sub-tabs of `/company/<SYM>` if they exist.
- No paid feeds, no third-party scrape (no Sarmaaya, scstrade, Mettis).
- No SBP / PBS macro scrape, no news/sentiment.
- Backwards-compatible: no removed fields, no renamed tools. Additive only.

---

## Open Questions & Resolutions (must clear before writing tasks)

These are blockers identified during plan drafting. Each must have a concrete resolution before Phase 2 begins. Phase 0 of *this* plan empirically answers them.

| # | Question | Why it blocks | Resolution path |
|---|---|---|---|
| 1 | Do `dps.psx.com.pk/company/<SYM>` sub-tabs (Financials, Ratios, Payouts, Financial Reports) have distinct URLs or AJAX endpoints, or are they all client-rendered from the same landing-page payload? | Phase 2/3 (ROE/dividend extraction) depends on fetching the sub-tabs. If they're SPA-rendered client-side from JSON we can hit directly, that's path A. If they require Selenium-style rendering, both phases collapse to a documented limitation. | Probe script in Task 0.1: inspect `<script>` tags in the landing-page HTML for embedded JSON, then probe common candidate URLs (`/company/<SYM>/financials`, `?tab=ratios`, `/ratios/<SYM>`, AJAX `/company/financial/<SYM>`). Capture findings + fixtures. |
| 2 | Does the (now-probed) Ratios sub-tab actually contain ROE, P/B, dividend yield, payout ratio, current ratio? | Phase 2 ROE/yield extraction depends on this. | Inspect captured fixture in Task 0.2 with keyword grep + visual inspection. |
| 3 | Does the Payouts sub-tab contain per-event dividend history (date, amount, type), or just a summary? | Phase 3 `get_dividend_history` shape depends on this. | Inspect captured fixture in Task 0.2. |
| 4 | Does the Financial Reports / Financials sub-tab include balance-sheet line items (total assets, current liabilities, LT debt, shares outstanding) sufficient for a Piotroski F-Score? | Phase 5 F-Score eligibility depends on this. | Inspect captured fixture in Task 0.2. |

**Resolution policy:** If Task 0.1 finds the sub-tabs are SPA-rendered with no fetchable backend, document and defer Phases 2.B, 3, and 5 to Part 3 (would need a headless browser, breaking the "lightweight" constraint). Phases 1, 2.A, 4, and 6 are independent of this finding and proceed regardless. If Task 0.2 finds balance-sheet items missing, deliver a partial (income-statement-only, 5-of-9 signal) F-Score in Phase 5 with a clear docstring; defer full F-Score.

### Resolutions (Phase 0 findings — 2026-05-24)

**Q1 resolved.** Only one fetchable sub-tab endpoint exists: `POST https://dps.psx.com.pk/company/payouts` with form body `symbol=<SYM>` returns a server-rendered `<table class="tbl">` HTML fragment. All other tested patterns (`/company/<SYM>/ratios`, `/company/<SYM>/financials`, `/company/<SYM>/financial-reports`, `POST /company/ratios`, `POST /company/financials`, `POST /company/financial-reports`, `POST /company/balancesheet`, `POST /company/keystats`, `/api/...`, `/data/...`) return **404**. The `GET /company/<SYM>?tab={financials|ratios|payouts}` URLs return **200** but serve the identical static landing-page HTML — the tab content is purely client-rendered JavaScript switching on the same in-page DOM/payload. The landing-page HTML's only AJAX hint is `'/payouts'`. See `psx-mcp/tests/fixtures/company_subtabs_probe.txt`.

**Q2 resolved (Ratios sub-tab).** All NO except gross_margin. — ROE: **no**, P/B: **no**, div_yield: **no**, payout: **no**, current_ratio: **no**. (The landing page does contain a small ratios table with `Gross Profit Margin (%)`, `Net Profit Margin (%)`, `EPS Growth (%)`, `PEG` across 4 years — useful but not enough for quality scoring.) ⇒ Task 2.B (parse_ratios for ROE/P/B/div_yield/payout) is **DEFERRED to Part 3** — would require a headless browser to render the Ratios sub-tab.

**Q3 resolved (Payouts sub-tab).** dividend per-event rows: **yes** (POST /company/payouts returns a real `<table>` with one row per announcement). Dates: **yes** (announcement date column + book-closure range). Per-share amount: **no** as a direct number, but **derivable** from the `<pct>%` cell × face_value (Rs 10) ÷ 100. Types (cash/bonus/right): **partial** — payouts_FFC.html shows only cash dividends, all rows tagged `(D)` (cash dividend). The 2nd letter in `Details` (`F`, `i`, `ii`, `iii`) maps to the announcement period (Final / interim Q1 / interim H1 / interim Q3); no `(B)` (bonus) or `(R)` (right) rows in the captured FFC sample, but the column shape suggests they would use the same `<pct>%(<code>) (B)` / `(R)` convention if present in other symbols. ⇒ Task 3.1 **proceeds** with the recipe documented below; bonus/right parsing built in defensively but only validated against cash for now.

**Q4 resolved (Financial Statements sub-tab).** From `financial_statements_LUCK.html` (= landing page): eps: **yes** (4y annual + 4q quarterly), net_income (Profit after Taxation): **yes**, revenue (Sales): **yes**, gross_margin (% only, not absolute): **yes**, cfo: **no**, total_assets: **no**, current_assets: **no**, current_liab: **no**, long_term_debt: **no**, shares_out: **no**. ⇒ Task 5.3 (Piotroski F-Score) is **DEFERRED to Part 3** — only 2 of the 9 Piotroski signals (net income > 0, accruals quality via CFO) are computable; the rest require balance-sheet items not present.

**Net impact on Part 2 scope:**
- **Proceeds as planned:** Phase 1 (hygiene), Phase 2.A (history schema), Phase 2.A.1 (get_fundamentals_history tool), Phase 3 (dividend history — recipe-driven), Phase 4 (indices_history + beta), Tasks 5.1/5.2 (quality.py + 4-quadrant on the income-statement-only fields we have).
- **Deferred to Part 3 (needs Playwright/Selenium):** Task 2.B (ratios extraction → ROE/P/B/div_yield/payout), Task 5.3 (full Piotroski). The screener will get the `roe_min` / `pb_max` / `div_yield_min` filter *fields* added (Task 2.C) so the API is stable, but they'll only match symbols populated via some future Part-3 ratios-fetcher.

---

## File Structure

### Time-series ordering conventions (consistent rules for all readers)

| Method | Order | Notes |
|---|---|---|
| `Cache.closes_for(symbol)` | oldest first | Correct for indicator math (rolling windows assume ascending date). |
| `Cache.closes_for_many(symbols)` | oldest first per symbol | Same convention. |
| `Cache.get_index_history(code)` | oldest first | EOD bars, date-keyed. |
| `Cache.get_fundamentals_history(symbol)` | newest year first | Mirrors how a user reads "latest annual results". |
| `Cache.get_dividend_history(symbol)` | newest ex-date first | Mirrors PSX site display. |
| `cache.get_bars(...)` (existing) | as the existing impl returns it | Don't change; see existing tests. |

Note: when `_build_snapshot` reads `fundamentals_history` (newest-first) and passes to `compute_quality_score` (which expects oldest-first EPS), it MUST reverse — see Task 5.2.

**New files:**

| Path | Responsibility |
|---|---|
| `psx-mcp/src/psx_mcp/quality.py` | Pure functions: `compute_quality_score(snapshot)`, `compute_value_score(snapshot, sector_median)`, `compute_momentum_score(closes)`, `compute_trend_score(closes)`, `compute_4quadrant_score(...)`. No I/O. |
| `psx-mcp/src/psx_mcp/beta.py` | Pure functions: `beta(stock_returns, index_returns, window=252)` returning beta, alpha, R². No I/O. |
| `psx-mcp/tests/test_quality.py` | Direct tests against `quality.py` with synthetic snapshots. |
| `psx-mcp/tests/test_beta.py` | Direct tests against `beta.py` with synthetic series. |
| `psx-mcp/tests/test_fundamentals_history.py` | Tests for `fundamentals_history` cache + retrieval. |
| `psx-mcp/tests/test_dividends.py` | Tests for `dividends` cache + retrieval. |
| `psx-mcp/scripts/probe_company_subtabs.py` | One-off probe — discovers PSX sub-tab endpoints. |
| `psx-mcp/scripts/probe_ratios_payouts.py` | One-off inspector for Ratios + Payouts fixtures. |

**Modified files:**

| Path | What changes |
|---|---|
| `psx-mcp/src/psx_mcp/cache.py` | New tables: `fundamentals_history`, `dividends`, `indices_history`. New methods: `upsert_fundamentals_history`, `get_fundamentals_history`, `upsert_dividend`, `get_dividend_history`, `upsert_index_bar`, `upsert_index_bars_bulk`, `get_index_history`. Helper for screener: `Cache.screen_candidates(where_sql, params)`, `Cache.closes_for(symbol, limit=None)`, `Cache.closes_for_many(symbols)`. |
| `psx-mcp/src/psx_mcp/psx_client.py` | New methods: `fetch_company_ratios`, `fetch_company_payouts`, `fetch_company_financials` (sub-tab specific) — exact URLs from Task 0.1. New parsers `parse_ratios`, `parse_payouts`, `parse_financial_statements_full`. |
| `psx-mcp/src/psx_mcp/screener.py` | Refactor `screen()` to call `Cache.screen_candidates` and `Cache.closes_for`. Remove raw `cache.conn.execute` calls. Add `roe_min`, `pb_max`, `div_yield_min` filter fields. Add `is not None` checks in place of truthiness in `sma20_gt_sma50` branch. |
| `psx-mcp/src/psx_mcp/models.py` | New models: `DividendEvent`, `FundamentalsSnapshot`, `BetaResponse`, `QualityScoreResponse`, `QuadrantScoreResponse`, `IndexHistoryPoint`. Extend `FilterSpec` mirror in `screen_symbols` wrapper. |
| `psx-mcp/server.py` | New impls + `@mcp.tool()` wrappers: `get_dividend_history`, `get_fundamentals_history`, `compute_beta`, `compute_quality_score`, `compute_4quadrant_score`, `get_index_history`. Wire `_refresh_market_impl` to also stamp the indices snapshot into `indices_history`. Wire `_refresh_market_impl` (or a new `refresh_company_fundamentals`) to populate `fundamentals_history` + `dividends` for symbols with fresh announcements. Tighten `_get_market_summary_impl` summary-string None guard. |
| `psx-mcp/tests/test_server.py` | Tests for each new MCP tool impl. |
| `psx-mcp/tests/test_cache.py` | Tests for new Cache methods. |
| `psx-mcp/tests/test_screener.py` | Tests for new filter fields + the screener-via-Cache refactor (regression: existing 7 tests still pass). |
| `docs/investing-playbook.md` | Mark resolved Part-1 gaps; update Part-5 P1/P2 sections. |
| `psx-mcp/README.md` | Document new tools in the tool table. |

---

## Phase 0 — Probe sub-tab endpoints

**Purpose:** Empirically resolve Q1–Q4. No production code modified.

### Task 0.1: Probe `/company/<SYM>` sub-tab endpoints

**Files:**
- Create: `psx-mcp/scripts/probe_company_subtabs.py`
- Create: `psx-mcp/tests/fixtures/company_subtabs_probe.txt`

- [ ] **Step 1: Write the probe script**

```python
# psx-mcp/scripts/probe_company_subtabs.py
"""One-off probe: find PSX /company/<SYM> sub-tab endpoints (Financials, Ratios, Payouts).

Approach:
  1. Fetch landing page /company/LUCK and grep for tab-related JS / AJAX URLs.
  2. Try a curated set of candidate URL patterns.
  3. Save every response's status + content-type + first 400 chars to a fixture.
"""
import re
import httpx
from pathlib import Path

BASE = "https://dps.psx.com.pk"
SYM = "LUCK"

CANDIDATES = [
    ("GET",  f"/company/{SYM}/financials"),
    ("GET",  f"/company/{SYM}/ratios"),
    ("GET",  f"/company/{SYM}/payouts"),
    ("GET",  f"/company/{SYM}/financial-reports"),
    ("GET",  f"/company/{SYM}/announcements"),
    ("GET",  f"/company/{SYM}?tab=financials"),
    ("GET",  f"/company/{SYM}?tab=ratios"),
    ("GET",  f"/company/{SYM}?tab=payouts"),
    ("GET",  f"/financials/{SYM}"),
    ("GET",  f"/ratios/{SYM}"),
    ("GET",  f"/payouts/{SYM}"),
    ("POST", f"/company/{SYM}/financials"),
    ("POST", f"/company/{SYM}/ratios"),
    ("POST", f"/company/{SYM}/payouts"),
    ("POST", "/financial/data"),
    ("POST", "/company/financial"),
    ("POST", "/company/ratios"),
    ("POST", "/company/payouts"),
    # /api/... style
    ("GET",  f"/api/company/{SYM}/ratios"),
    ("GET",  f"/api/company/{SYM}/payouts"),
    ("GET",  f"/api/company/{SYM}/financials"),
    # /data/... style
    ("GET",  f"/data/company/{SYM}/ratios"),
    ("POST", f"/data/company/ratios"),
]
# Each candidate is also probed WITHOUT the X-Requested-With header (see probe()).

def probe():
    headers = {
        "User-Agent": "Mozilla/5.0 (PSX-MCP-probe/0.2)",
        "Accept": "application/json,text/html;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/company/{SYM}",
    }
    out = []

    # First grab the landing page, grep for AJAX/tab hints.
    landing = httpx.get(f"{BASE}/company/{SYM}", headers=headers, timeout=10.0)
    out.append(f"=== LANDING {landing.status_code} {landing.headers.get('content-type')}")
    # Look for any URL fragments in inline JS that match tab patterns.
    hints = set(re.findall(r"['\"](/[^'\"<>\s]*?(?:financial|ratio|payout|tab)[^'\"<>\s]*?)['\"]",
                            landing.text, re.I))
    out.append(f"=== LANDING-AJAX-HINTS {sorted(hints)[:40]}")

    with httpx.Client(timeout=10.0, follow_redirects=True) as c:
        for method, path in CANDIDATES:
            url = BASE + path
            for header_variant_name, hdrs in (("ajax", headers),
                                              ("plain", {k: v for k, v in headers.items()
                                                         if k != "X-Requested-With"})):
                try:
                    if method == "GET":
                        r = c.get(url, headers=hdrs)
                    else:
                        body = {"symbol": SYM}
                        r = c.post(url, headers=hdrs, data=body)
                    ct = r.headers.get("content-type", "")
                    snippet = r.text[:400].replace("\n", " ")
                    out.append(f"[{header_variant_name}] {method} {path} -> "
                               f"{r.status_code} {ct} | {snippet}")
                except Exception as e:
                    out.append(f"[{header_variant_name}] {method} {path} -> ERROR {e!r}")

    fixture = Path("tests/fixtures/company_subtabs_probe.txt")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

if __name__ == "__main__":
    probe()
```

- [ ] **Step 2: Run the probe**

Run: `uv run python scripts/probe_company_subtabs.py`
Expected: each candidate's HTTP status + content-type + first 400 chars. The "LANDING-AJAX-HINTS" line names URL fragments found in the landing page's inline JS — likely contains the real sub-tab endpoint(s).

- [ ] **Step 3: Document the working endpoint(s)**

Append a paragraph to `docs/investing-playbook.md` under Part 4 Tier 1 listing the confirmed sub-tab URL(s). If none are reachable, note "no fetchable sub-tab endpoint — Part 2 Phases 2.B/3/5 depend on this and are deferred to Part 3 (would require headless browser)."

- [ ] **Step 4: If a working endpoint is found, capture rich fixtures**

Capture each working sub-tab to the **exact** file names that later tests reference. For LUCK (cement, dividend payer) and FFC (fertilizer, big dividend payer):
- `tests/fixtures/ratios_LUCK.html`              ← used by Task 2.B parser test
- `tests/fixtures/payouts_LUCK.html`             ← used in 0.2 audit
- `tests/fixtures/payouts_FFC.html`              ← used by Task 3.1 parser test
- `tests/fixtures/financial_statements_LUCK.html`← used by Task 2.B integration test (M1 fix)

Use whichever method (GET/POST, plain/AJAX) the probe found.

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/scripts/probe_company_subtabs.py psx-mcp/tests/fixtures/company_subtabs_probe.txt psx-mcp/tests/fixtures/ratios_*.html psx-mcp/tests/fixtures/payouts_*.html psx-mcp/tests/fixtures/financial_statements_*.html docs/investing-playbook.md
git commit -m "chore(psx-mcp): probe PSX DPS for /company sub-tab endpoints"
```

---

### Task 0.2: Audit Ratios + Payouts fixtures for required fields

**Files:**
- Create: `psx-mcp/scripts/probe_ratios_payouts.py`
- Create: `psx-mcp/tests/fixtures/ratios_payouts_audit.txt`

(Only proceed if Task 0.1 captured non-empty Ratios/Payouts fixtures.)

- [ ] **Step 1: Write the keyword audit script**

```python
# psx-mcp/scripts/probe_ratios_payouts.py
"""Audit captured Ratios + Payouts fixtures for the fields Part 2 needs."""
import re
from pathlib import Path
from bs4 import BeautifulSoup

RATIOS_KEYWORDS = {
    "roe":         ["return on equity", "roe"],
    "pb":          ["p/b", "price to book", "price-to-book", "book value"],
    "div_yield":   ["dividend yield"],
    "payout":      ["payout ratio"],
    "current_ratio": ["current ratio"],
    "debt_equity": ["debt to equity", "debt-to-equity", "d/e ratio"],
    "long_term_debt": ["long term debt", "long-term debt", "lt debt"],
    "total_assets": ["total assets"],
    "current_liab": ["current liabilit"],
    "gross_margin": ["gross margin", "gross profit margin"],
}

PAYOUTS_KEYWORDS = {
    "cash_dividend": ["cash dividend", "interim", "final"],
    "bonus":         ["bonus share", "bonus issue"],
    "right":         ["right share", "rights issue"],
    "date":          ["ex-date", "book closure", "announcement date"],
    "per_share":     ["per share", "per-share", "rs/share"],
}

FIN_STATEMENTS_KEYWORDS = {
    "eps":              ["eps", "earnings per share"],
    "net_income":       ["net income", "profit after tax", "profit after taxation"],
    "cfo":              ["cash flow from operations", "cash from operations", "operating cash"],
    "revenue":          ["sales", "revenue", "turnover"],
    "gross_profit":     ["gross profit", "gross margin"],
    "total_assets":     ["total assets"],
    "current_assets":   ["current assets"],
    "current_liab":     ["current liabilit"],
    "long_term_debt":   ["long term debt", "long-term debt", "non-current borrow"],
    "shares_out":       ["shares issued", "shares outstanding", "share capital"],
}

def audit(fixture_path: Path, keywords: dict, label: str) -> list[str]:
    out = [f"\n=== {label}: {fixture_path.name} ==="]
    if not fixture_path.exists():
        out.append("  MISSING fixture")
        return out
    text = BeautifulSoup(fixture_path.read_text(encoding="utf-8"), "lxml").get_text(" ", strip=True).lower()
    for category, terms in keywords.items():
        hits = sum(text.count(t) for t in terms)
        sample = next((re.search(r".{0,40}" + re.escape(t) + r".{0,40}", text).group(0)
                       for t in terms if t in text), "")
        out.append(f"  [{category:18s}] hits={hits:>3d}  sample={sample[:80]!r}")
    return out

def main():
    fx = Path("tests/fixtures")
    log = []
    for f in sorted(fx.glob("ratios_*.html")):
        log += audit(f, RATIOS_KEYWORDS, "RATIOS")
    for f in sorted(fx.glob("payouts_*.html")):
        log += audit(f, PAYOUTS_KEYWORDS, "PAYOUTS")
    for f in sorted(fx.glob("financial_statements_*.html")):
        log += audit(f, FIN_STATEMENTS_KEYWORDS, "FIN_STATEMENTS")
    text = "\n".join(log)
    Path("tests/fixtures/ratios_payouts_audit.txt").write_text(text, encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `uv run python scripts/probe_ratios_payouts.py`
Expected: per-fixture, per-category hit counts and a sample context snippet for each match.

- [ ] **Step 3: Record findings + payouts column recipe**

Append to the open-questions table at the top of *this* file:
- Q2 resolved — ROE: yes/no, P/B: yes/no, div_yield: yes/no, payout: yes/no, current_ratio: yes/no.
- Q3 resolved — dividend per-event rows: yes/no, dates: yes/no, per-share amount: yes/no, types (cash/bonus/right): yes/no.
- Q4 resolved — total_assets: yes/no, long_term_debt: yes/no, current_liab: yes/no, current_assets: yes/no, gross_margin: yes/no, net_income: yes/no, cfo: yes/no, revenue: yes/no, shares_out: yes/no.

**Also (critical for Task 3.1 to be implementable — fixes BLOCKER B1):** open the captured `payouts_FFC.html` fixture, find the actual payouts `<table>`, and write down a **column recipe** at the top of Task 3.1 in this plan, in the form:

```
PAYOUT TABLE RECIPE (from payouts_FFC.html):
  <th> labels (in order): ["Year", "Period", "Cash %", "Bonus %", "Right %", "Ex-Date", "Book Closure"]
  Column index → field:
    0 → year (int)
    1 → period (e.g. "Q1", "Final", "Interim")
    2 → cash_pct (float or "-")
    3 → bonus_pct (float or "-")
    4 → right_pct (float or "-")
    5 → ex_date (e.g. "15-Sep-2025")
  per_share derivation: cash_pct × face_value / 100 (face value PKR 10 for most PSX)
  payout_type derivation: pick first nonzero of (cash_pct → "cash"), (bonus_pct → "bonus"), (right_pct → "right")
  announcement_id derivation: f"{symbol}-{year}-{period}"
```

Replace the example with what the fixture actually shows. Without this, Task 3.1's `parse_payouts` cannot be implemented.

- [ ] **Step 4: Commit**

```bash
git add psx-mcp/scripts/probe_ratios_payouts.py psx-mcp/tests/fixtures/ratios_payouts_audit.txt docs/superpowers/plans/2026-05-24-psx-mcp-analytics-upgrade-part2.md
git commit -m "chore(psx-mcp): audit ratios + payouts fixture coverage"
```

---

## Phase 1 — Architectural hygiene

**Goal:** Pay down the layering debt the analytics-v1 reviewer flagged. Three small commits, low risk, no behavior change.

### Task 1.1: Move screener SQL into Cache methods

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py` — add `screen_candidates`, `closes_for`
- Modify: `psx-mcp/src/psx_mcp/screener.py` — replace raw `cache.conn.execute` with method calls
- Test: `psx-mcp/tests/test_cache.py` — verify the helper methods directly

- [ ] **Step 1: Write a failing test for `closes_for`**

Add to `psx-mcp/tests/test_cache.py`:

```python
def test_closes_for_returns_all_bars_ascending(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=i),
                open=100.0, high=110.0, low=90.0, close=100.0 + i, volume=1000)
            for i in range(10)]
    cache.upsert_bars(bars)
    closes = cache.closes_for("XYZ")
    assert len(closes) == 10
    # Ascending by date → oldest first
    assert closes == sorted(closes)
```

- [ ] **Step 2: Run, confirm `AttributeError`**

Run: `uv run pytest tests/test_cache.py::test_closes_for_returns_all_bars_ascending -v` with `timeout=60000`.
Expected: FAIL.

- [ ] **Step 3: Implement `closes_for` in `cache.py`**

Add to the `Cache` class (after `bars_latest_date`):

```python
def closes_for(self, symbol: str, limit: Optional[int] = None) -> list[float]:
    """Return cached close prices for symbol, oldest first.
    If limit is given, returns the most-recent `limit` closes (still oldest-first within window)."""
    sql = "SELECT close FROM bars_daily WHERE symbol = ? ORDER BY date ASC"
    params: tuple = (symbol.upper(),)
    if limit is not None:
        sql = ("SELECT close FROM (SELECT close, date FROM bars_daily "
               "WHERE symbol = ? ORDER BY date DESC LIMIT ?) ORDER BY date ASC")
        params = (symbol.upper(), limit)
    rows = self.conn.execute(sql, params).fetchall()
    return [r["close"] for r in rows]
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/test_cache.py::test_closes_for_returns_all_bars_ascending -v`
Expected: PASS.

- [ ] **Step 5: Add failing test for `screen_candidates`**

```python
def test_screen_candidates_filters_via_parameterized_sql(tmp_path):
    """screen_candidates returns joined symbols+quotes+fundamentals filtered by SQL."""
    from psx_mcp.cache import Cache
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    cache.upsert_symbol("SYS", "Systems", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_symbol("HUBC", "Hub Power", "POWER GENERATION & DISTRIBUTION", None)
    for sym, price, change, vol, pe in [
        ("SYS", 600.0, 5.0, 100_000, 12.0),
        ("HUBC", 200.0, 1.0, 200_000, 8.0),
    ]:
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change, volume=vol,
                           day_high=price+1, day_low=price-1, fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=pe, pb=None,
                                  div_yield=None, payout=None, roe=None)
    out = cache.screen_candidates("s.sector = ? AND f.pe <= ?",
                                  ["TECHNOLOGY & COMMUNICATION", 15.0])
    assert len(out) == 1
    assert out[0]["symbol"] == "SYS"
```

- [ ] **Step 6: Run, confirm fail**

- [ ] **Step 7: Implement `screen_candidates` in `cache.py`**

```python
def screen_candidates(self, where_clause: str, params: list) -> list[dict]:
    """Return [{symbol, name, sector, price, change, volume, pe, eps}, ...] for the
    latest-quote-per-symbol JOIN, filtered by an arbitrary parameterized WHERE clause.

    SECURITY: where_clause is treated as trusted SQL — callers MUST never include
    user input directly; only the `params` list carries user-provided values. The
    screener uses a closed-set of column names from FilterSpec, so this is safe in
    that caller. Anything else must validate inputs.
    """
    sql = f"""
        SELECT s.symbol, s.name, s.sector,
               q.price, q.change, q.volume,
               f.pe, f.eps, f.pb, f.div_yield, f.payout, f.roe
        FROM symbols s
        JOIN quotes q ON q.symbol = s.symbol
            AND q.ts = (SELECT MAX(ts) FROM quotes q2 WHERE q2.symbol = s.symbol)
        LEFT JOIN fundamentals f ON f.symbol = s.symbol
        WHERE {where_clause if where_clause else "1=1"}
        LIMIT 500
    """
    rows = self.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 8: Run, confirm pass**

- [ ] **Step 9: Refactor `screen()` in `screener.py` (and propagate new fundamentals columns)**

Replace the two `cache.conn.execute(...)` calls. The candidate SELECT becomes:

```python
where = []
params: list = []
# ... (same filter-building code as before, building where + params) ...
rows = cache.screen_candidates(" AND ".join(where), params)
```

And per-symbol close fetch becomes:

```python
closes_list = cache.closes_for(sym)
```

**Fixes BLOCKER B5:** `screen_candidates` now SELECTs `f.pb`, `f.div_yield`, `f.payout`, `f.roe` in addition to `f.pe`, `f.eps`. The result-dict construction in `screen()` (the `results.append({...})` block) must be extended to include these new keys:

```python
results.append({
    "symbol": sym, "name": r["name"], "sector": r["sector"],
    "price": price, "change_pct": change_pct, "volume": r["volume"],
    "pe": r["pe"], "eps": r["eps"],
    "pb": r["pb"], "div_yield": r["div_yield"],
    "payout": r["payout"], "roe": r["roe"],
    "sma20": sma20, "sma50": sma50, "sma200": sma200, "rsi14": rsi14,
})
```

Add a regression test in `tests/test_screener.py` asserting that a seeded ROE value is present in the screen output:

```python
def test_screen_results_include_roe_and_pb(seeded_cache):
    """Regression: screen() must propagate ROE/P/B/div_yield/payout into result dicts."""
    seeded_cache.upsert_fundamentals(symbol="SYS", eps=5.46, pe=27.5, pb=4.0,
                                      div_yield=2.5, payout=40.0, roe=22.0)
    from psx_mcp.screener import screen, FilterSpec
    out = screen(seeded_cache, FilterSpec(sector="TECHNOLOGY & COMMUNICATION"))
    sys_row = next((r for r in out if r["symbol"] == "SYS"), None)
    assert sys_row is not None
    assert sys_row["roe"] == 22.0
    assert sys_row["pb"] == 4.0
    assert sys_row["div_yield"] == 2.5
    assert sys_row["payout"] == 40.0
```

Run `uv run pytest tests/test_screener.py -v` (`timeout=60000`) — all 8 existing tests (7 screener + 1 sector_summary) plus this new one must pass.

- [ ] **Step 10: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/src/psx_mcp/screener.py psx-mcp/tests/test_cache.py
git commit -m "refactor(psx-mcp): screener calls Cache methods instead of raw SQL"
```

---

### Task 1.2: Batch the per-symbol close fetch (fix N+1)

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py` — add `closes_for_many(symbols)`
- Modify: `psx-mcp/src/psx_mcp/screener.py` — use the batched fetch
- Test: `psx-mcp/tests/test_cache.py`

- [ ] **Step 1: Failing test**

```python
def test_closes_for_many_returns_dict_keyed_by_symbol(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    for sym in ("AAA", "BBB"):
        bars = [Bar(symbol=sym, date=today - timedelta(days=i),
                    open=100.0, high=110.0, low=90.0, close=100.0 + i, volume=1000)
                for i in range(5)]
        cache.upsert_bars(bars)
    out = cache.closes_for_many(["AAA", "BBB", "MISSING"])
    assert set(out.keys()) == {"AAA", "BBB", "MISSING"}
    assert len(out["AAA"]) == 5
    assert len(out["MISSING"]) == 0
    # Ascending by date
    assert out["AAA"] == sorted(out["AAA"])
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `closes_for_many` in `cache.py`**

```python
def closes_for_many(self, symbols: list[str]) -> dict[str, list[float]]:
    """Return {symbol: [closes_ascending], ...} for the given symbols.
    Symbols with no bars get an empty list (never missing-key)."""
    syms_upper = [s.upper() for s in symbols]
    if not syms_upper:
        return {}
    placeholders = ",".join("?" * len(syms_upper))
    rows = self.conn.execute(
        f"""SELECT symbol, close FROM bars_daily
            WHERE symbol IN ({placeholders})
            ORDER BY symbol ASC, date ASC""",
        syms_upper,
    ).fetchall()
    out: dict[str, list[float]] = {s: [] for s in syms_upper}
    for r in rows:
        out[r["symbol"]].append(r["close"])
    return out
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Refactor `screen()` to use the batched fetch**

In `screener.py`, replace the per-symbol loop fetch with a single up-front call:

```python
rows = cache.screen_candidates(" AND ".join(where), params)
all_symbols = [r["symbol"] for r in rows]
closes_by_sym = cache.closes_for_many(all_symbols)
# ... then in the loop:
for r in rows:
    sym = r["symbol"]
    closes_list = closes_by_sym.get(sym, [])
    # ... rest unchanged
```

- [ ] **Step 6: Run all screener tests + new cache test**

Run: `uv run pytest tests/test_cache.py tests/test_screener.py -v` (`timeout=60000`).
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/src/psx_mcp/screener.py psx-mcp/tests/test_cache.py
git commit -m "perf(psx-mcp): batch closes fetch in screener (one query, not N)"
```

---

### Task 1.3: UTC timestamps + small `_get_market_summary` guard

**Files:**
- Modify: `psx-mcp/src/psx_mcp/psx_client.py` — switch `fetch_indices` timestamp to UTC
- Modify: `psx-mcp/server.py` — switch `_refresh_market_impl` index upsert timestamp; tighten summary string
- Test: `psx-mcp/tests/test_indices.py`

- [ ] **Step 1: Failing test for UTC timestamp shape**

Add to `tests/test_indices.py`:

```python
def test_fetch_indices_refreshed_at_is_utc_iso(monkeypatch):
    """refreshed_at should be a UTC ISO string ending in '+00:00' or 'Z'."""
    import asyncio
    from psx_mcp.psx_client import PSXClient
    fake = {"data": [[1779360000, 167000.0, 100_000_000, 167000.0]]}
    async def fake_get(self, url):
        import json as _j
        return _j.dumps(fake)
    monkeypatch.setattr(PSXClient, "_get", fake_get)
    out = asyncio.run(PSXClient().fetch_indices(codes=["KSE100"]))
    assert len(out) == 1
    assert out[0]["refreshed_at"].endswith("+00:00") or out[0]["refreshed_at"].endswith("Z")
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Switch to UTC in `psx_client.py::fetch_indices`**

Replace `datetime.now().isoformat()` with `datetime.now(timezone.utc).isoformat()`. Add `from datetime import timezone` at top if missing.

- [ ] **Step 4: Same switch in `server.py::_refresh_market_impl`** for the index upsert call.

- [ ] **Step 5: Guard the summary string in `_get_market_summary_impl`**

Find the f-string `f"KSE-100 at {kse100.get('value'):.2f} ..."` (or similar). Change to:

```python
kse100_val = kse100.get('value') if kse100 else None
summary = (f"KSE-100 at {kse100_val:.2f} ..." if kse100_val is not None
           else "KSE-100 snapshot — call refresh_market() first if stale.")
```

- [ ] **Step 6: Run full server suite to confirm no regressions**

Run: `uv run pytest tests/test_server.py tests/test_indices.py -v` (`timeout=240000`).
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add psx-mcp/src/psx_mcp/psx_client.py psx-mcp/server.py psx-mcp/tests/test_indices.py
git commit -m "fix(psx-mcp): UTC timestamps for index snapshots; guard market_summary None"
```

---

## Phase 2 — Quality fundamentals

**Goal:** Populate ROE / P/B / dividend yield / payout for individual symbols, and add a multi-year `fundamentals_history` table so trend filters become possible. Branches on Task 0.1 outcome.

### Task 2.A: Refactor fundamentals upsert into a snapshot model (no-branch task — does NOT depend on Task 0.1)

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — add `FundamentalsSnapshot` model
- Modify: `psx-mcp/src/psx_mcp/cache.py` — add `fundamentals_history` table + `upsert_fundamentals_history` + `get_fundamentals_history`
- Test: `psx-mcp/tests/test_fundamentals_history.py`

The existing `fundamentals` table is single-row-per-symbol (overwritten on refresh). For trend filters we need history. This task adds the table and helpers without yet changing what gets written into them — Phase 2.B will populate them once we know what the sub-tab gives us.

- [ ] **Step 1: Failing test**

Create `psx-mcp/tests/test_fundamentals_history.py`:

```python
from datetime import datetime
import pytest
from psx_mcp.cache import Cache


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


def _full_kwargs(**overrides):
    """Helper to fill in the long required-kwarg list with Nones."""
    base = dict(
        symbol="X", fiscal_year=2024, eps=None, pe=None, pb=None,
        div_yield=None, payout=None, roe=None, gross_margin=None,
        net_income=None, cfo=None, revenue=None,
        total_assets=None, long_term_debt=None, current_liab=None,
        current_assets=None, shares_outstanding=None,
        source_url=None, refreshed_at=datetime.now(),
    )
    base.update(overrides)
    return base


def test_upsert_and_get_fundamentals_history_round_trip(cache):
    """Multiple years per symbol, retrieved newest-first."""
    cache.upsert_fundamentals_history(**_full_kwargs(
        symbol="LUCK", fiscal_year=2024, eps=29.41, roe=15.2,
        net_income=14500.0, cfo=18000.0, revenue=80000.0,
        source_url="https://dps.psx.com.pk/company/LUCK",
        refreshed_at=datetime(2026, 5, 24, 10, 0),
    ))
    cache.upsert_fundamentals_history(**_full_kwargs(
        symbol="LUCK", fiscal_year=2025, eps=4.19, roe=2.1,
        net_income=2100.0, cfo=2500.0, revenue=76000.0,
        source_url="https://dps.psx.com.pk/company/LUCK",
        refreshed_at=datetime(2026, 5, 24, 10, 0),
    ))
    rows = cache.get_fundamentals_history("LUCK")
    assert [r["fiscal_year"] for r in rows] == [2025, 2024]
    assert rows[0]["eps"] == 4.19
    assert rows[1]["roe"] == 15.2
    assert rows[1]["net_income"] == 14500.0


def test_upsert_replaces_same_year(cache):
    """Re-upserting the same (symbol, fiscal_year) replaces values."""
    for eps in [10.0, 11.5]:
        cache.upsert_fundamentals_history(**_full_kwargs(
            symbol="SYS", fiscal_year=2024, eps=eps,
        ))
    rows = cache.get_fundamentals_history("SYS")
    assert len(rows) == 1
    assert rows[0]["eps"] == 11.5


def test_get_fundamentals_history_empty_returns_empty_list(cache):
    assert cache.get_fundamentals_history("NOSUCH") == []
```

- [ ] **Step 2: Run, confirm fail (table doesn't exist)**

Run: `uv run pytest tests/test_fundamentals_history.py -v` (`timeout=60000`).

- [ ] **Step 3: Add schema + methods**

In `cache.py` `SCHEMA` block, append:

```sql
CREATE TABLE IF NOT EXISTS fundamentals_history (
  symbol TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  eps REAL,
  pe REAL,
  pb REAL,
  div_yield REAL,
  payout REAL,
  roe REAL,
  gross_margin REAL,
  net_income REAL,
  cfo REAL,
  revenue REAL,
  total_assets REAL,
  long_term_debt REAL,
  current_liab REAL,
  current_assets REAL,
  shares_outstanding REAL,
  source_url TEXT,
  refreshed_at TEXT NOT NULL,
  PRIMARY KEY(symbol, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_fundh_symbol_year
  ON fundamentals_history(symbol, fiscal_year DESC);
```

(Added `net_income`, `cfo`, `revenue` — required for Piotroski F-Score in Task 5.3. Resolves MAJOR M10.)

Add methods to `Cache`:

```python
def upsert_fundamentals_history(self, *, symbol: str, fiscal_year: int,
                                eps, pe, pb, div_yield, payout, roe,
                                gross_margin, net_income, cfo, revenue,
                                total_assets, long_term_debt,
                                current_liab, current_assets, shares_outstanding,
                                source_url, refreshed_at) -> None:
    self.conn.execute(
        """INSERT INTO fundamentals_history
           (symbol, fiscal_year, eps, pe, pb, div_yield, payout, roe,
            gross_margin, net_income, cfo, revenue,
            total_assets, long_term_debt, current_liab,
            current_assets, shares_outstanding, source_url, refreshed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(symbol, fiscal_year) DO UPDATE SET
             eps=excluded.eps, pe=excluded.pe, pb=excluded.pb,
             div_yield=excluded.div_yield, payout=excluded.payout, roe=excluded.roe,
             gross_margin=excluded.gross_margin,
             net_income=excluded.net_income, cfo=excluded.cfo, revenue=excluded.revenue,
             total_assets=excluded.total_assets,
             long_term_debt=excluded.long_term_debt, current_liab=excluded.current_liab,
             current_assets=excluded.current_assets,
             shares_outstanding=excluded.shares_outstanding,
             source_url=excluded.source_url, refreshed_at=excluded.refreshed_at""",
        (symbol.upper(), fiscal_year, eps, pe, pb, div_yield, payout, roe,
         gross_margin, net_income, cfo, revenue,
         total_assets, long_term_debt, current_liab,
         current_assets, shares_outstanding, source_url, _iso(refreshed_at)),
    )
    self.conn.commit()

def get_fundamentals_history(self, symbol: str) -> list[dict]:
    """Return all cached fiscal-year snapshots for symbol, newest year first."""
    rows = self.conn.execute(
        "SELECT * FROM fundamentals_history WHERE symbol=? ORDER BY fiscal_year DESC",
        (symbol.upper(),),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/test_fundamentals_history.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/tests/test_fundamentals_history.py
git commit -m "feat(psx-mcp): fundamentals_history table + upsert/get methods"
```

---

### Task 2.A.1: Wrap `get_fundamentals_history` as an MCP tool (no-branch)

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `FundamentalsHistoryPoint` model
- Modify: `psx-mcp/server.py` — `_get_fundamentals_history_impl` + `@mcp.tool() get_fundamentals_history`
- Test: `psx-mcp/tests/test_server.py`

Users should be able to inspect what `compute_quality_score` is using internally.

- [ ] **Step 1: Add model in `models.py`**

```python
class FundamentalsHistoryPoint(BaseModel):
    symbol: str
    fiscal_year: int
    eps: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    div_yield: Optional[float] = None
    payout: Optional[float] = None
    roe: Optional[float] = None
    gross_margin: Optional[float] = None
    net_income: Optional[float] = None
    cfo: Optional[float] = None
    revenue: Optional[float] = None
    total_assets: Optional[float] = None
    long_term_debt: Optional[float] = None
    current_liab: Optional[float] = None
    current_assets: Optional[float] = None
    shares_outstanding: Optional[float] = None
    source_url: Optional[str] = None
    refreshed_at: str  # ISO string
```

- [ ] **Step 2: Add impl + tool in `server.py`**

```python
from psx_mcp.models import FundamentalsHistoryPoint  # extend existing import

def _get_fundamentals_history_impl(cache: Cache, symbol: str) -> list[FundamentalsHistoryPoint]:
    rows = cache.get_fundamentals_history(symbol)
    return [FundamentalsHistoryPoint(**r) for r in rows]


@mcp.tool()
async def get_fundamentals_history(symbol: str) -> list[FundamentalsHistoryPoint]:
    """Cached per-fiscal-year fundamentals for a symbol, newest year first.
    Populated by refresh_fundamentals(symbol). Empty list if never refreshed."""
    return _get_fundamentals_history_impl(_cache, symbol)
```

- [ ] **Step 3: Test in `tests/test_server.py`**

```python
def test_get_fundamentals_history_returns_cached(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_fundamentals_history(
        symbol="LUCK", fiscal_year=2025, eps=4.19, pe=None, pb=None,
        div_yield=None, payout=None, roe=2.1, gross_margin=None,
        net_income=None, cfo=None, revenue=None,
        total_assets=None, long_term_debt=None, current_liab=None,
        current_assets=None, shares_outstanding=None,
        source_url=None, refreshed_at=datetime(2026, 5, 24),
    )
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_fundamentals_history_impl(cache, "LUCK")
    assert len(out) == 1
    assert out[0].eps == 4.19


def test_get_fundamentals_history_empty(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_fundamentals_history_impl(cache, "NOSUCH")
    assert out == []
```

- [ ] **Step 4: Run, commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): get_fundamentals_history MCP tool"
```

---

### Task 2.B: Fetch + parse sub-tabs, populate `fundamentals_history`

> **STATUS (2026-05-24, post-Phase-0): DEFERRED to Part 3.** Phase 0 confirmed the Ratios sub-tab is fully SPA-rendered — `POST /company/ratios` returns 404, `GET /company/<SYM>?tab=ratios` returns the same static landing-page HTML, and the landing page does NOT contain ROE / P/B / dividend yield / payout ratio / current ratio (only Gross Profit Margin %, Net Profit Margin %, EPS Growth %, PEG). Extracting the missing quality metrics would require a headless browser (Playwright/Selenium) to render the JS-injected tab content. See `psx-mcp/tests/fixtures/company_subtabs_probe.txt` + `ratios_payouts_audit.txt`. Subsequent tasks (Phase 3, Phase 4, Phase 5.1/5.2) proceed regardless.

**Branch:** Only proceed if Task 0.1 confirmed working sub-tab URLs. If not, skip to Phase 4 and document this task as "deferred to Part 3 — needs headless browser."

**Files:**
- Modify: `psx-mcp/src/psx_mcp/psx_client.py` — `fetch_company_ratios`, `fetch_company_financials_statements`, `parse_ratios`, `parse_financial_statements_full`
- Modify: `psx-mcp/server.py` — new `_refresh_fundamentals_impl(cache, client, symbol)` + `@mcp.tool() refresh_fundamentals(symbol)` wrapper
- Modify: `psx-mcp/src/psx_mcp/models.py` — `FundamentalsSnapshot` for the new richer single-symbol payload
- Test: `psx-mcp/tests/test_psx_client.py` (parser tests against fixtures from Task 0.1) + `psx-mcp/tests/test_server.py` (impl integration test)

- [ ] **Step 1: Failing parser test (fixture-driven)**

Add to `psx-mcp/tests/test_psx_client.py`:

```python
def test_parse_ratios_extracts_roe_and_pb(fixtures_dir):
    """Ratios sub-tab fixture should parse ROE, P/B, div_yield."""
    from psx_mcp.psx_client import parse_ratios
    html = (fixtures_dir / "ratios_LUCK.html").read_text(encoding="utf-8")
    out = parse_ratios("LUCK", html)
    # These assertions are based on what Task 0.2's audit found.
    # Use the actual LUCK values from the captured fixture.
    assert out["roe"] is not None
    assert out["pb"] is not None
    assert out["div_yield"] is not None
```

(Adapt the assertions to actual values in the fixture once it's captured.)

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add `fetch_company_ratios` to `PSXClient`**

```python
async def fetch_company_ratios(self, symbol: str) -> str:
    """Fetch the Ratios sub-tab for a company.
    URL: discovered in Task 0.1. Placeholder shown — replace with confirmed endpoint."""
    return await self._get(f"{BASE_DPS}/company/{symbol.upper()}/ratios")
```

(Replace the URL with whatever Task 0.1 confirmed — could be `?tab=ratios` or a POST to a different path.)

Similarly add `fetch_company_financials_statements` for the multi-year Financials sub-tab.

- [ ] **Step 4: Implement `parse_ratios` in `psx_client.py`**

```python
def parse_ratios(symbol: str, html: str) -> dict:
    """Extract ROE, P/B, div_yield, payout, current_ratio, debt_equity from the
    Ratios sub-tab HTML. Returns {field: float | None}.

    Uses two strategies:
      1. Table-row scan for rows where the label cell matches a known indicator name.
      2. Text-grep fallback for "Label: 12.34" patterns.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    out = {
        "roe": None, "pb": None, "div_yield": None, "payout": None,
        "current_ratio": None, "debt_equity": None,
    }
    label_map = {
        "return on equity": "roe", "roe": "roe",
        "price to book": "pb", "p/b": "pb", "p / b": "pb",
        "dividend yield": "div_yield",
        "payout ratio": "payout",
        "current ratio": "current_ratio",
        "debt to equity": "debt_equity", "debt/equity": "debt_equity",
    }
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            label = cells[0].lower()
            for key_phrase, field in label_map.items():
                if key_phrase in label:
                    val = _f(cells[1])  # _f already exists in this module
                    if val is not None:
                        out[field] = val
                    break
    return out
```

- [ ] **Step 5: Run parser test, confirm pass**

Run: `uv run pytest tests/test_psx_client.py::test_parse_ratios_extracts_roe_and_pb -v`

- [ ] **Step 6: Add `_refresh_fundamentals_impl` to `server.py`**

```python
async def _refresh_fundamentals_impl(cache: Cache, client: PSXClient,
                                      symbol: str) -> dict:
    """Fetch Ratios + Financial Statements sub-tabs and populate fundamentals_history.

    Returns {fiscal_years_upserted: [...], ratios_present: bool}.
    """
    from datetime import datetime
    sym = symbol.upper()
    out = {"fiscal_years_upserted": [], "ratios_present": False}

    # Ratios — gives ROE, P/B, div_yield, payout (current snapshot only).
    try:
        ratios_html = await client.fetch_company_ratios(sym)
        ratios = parse_ratios(sym, ratios_html)
        out["ratios_present"] = any(v is not None for v in ratios.values())
    except Exception:
        ratios = {}

    # Financial statements — gives multi-year income + balance sheet line items.
    try:
        fin_html = await client.fetch_company_financials_statements(sym)
        statements = parse_financial_statements_full(sym, fin_html)
    except Exception:
        statements = []

    now = datetime.now(timezone.utc)
    # Hoist max-year computation outside the loop (fixes M7 O(n²) smell).
    latest_year = max((s["fiscal_year"] for s in statements), default=None)

    for stmt in statements:
        is_latest = (stmt["fiscal_year"] == latest_year)
        cache.upsert_fundamentals_history(
            symbol=sym,
            fiscal_year=stmt["fiscal_year"],
            eps=stmt.get("eps"),
            pe=None,  # PE is point-in-time, not per-fiscal-year
            pb=ratios.get("pb") if is_latest else None,
            div_yield=ratios.get("div_yield") if is_latest else None,
            payout=ratios.get("payout") if is_latest else None,
            roe=ratios.get("roe") if is_latest else None,
            gross_margin=stmt.get("gross_margin"),
            net_income=stmt.get("net_income"),
            cfo=stmt.get("cfo"),
            revenue=stmt.get("revenue"),
            total_assets=stmt.get("total_assets"),
            long_term_debt=stmt.get("long_term_debt"),
            current_liab=stmt.get("current_liab"),
            current_assets=stmt.get("current_assets"),
            shares_outstanding=stmt.get("shares_outstanding"),
            source_url=f"https://dps.psx.com.pk/company/{sym}",
            refreshed_at=now,
        )
        out["fiscal_years_upserted"].append(stmt["fiscal_year"])

    # Ratios-only fallback (fixes M7's second concern): if we got ratios but no
    # statements, also write to the existing single-row `fundamentals` table so
    # the data isn't lost. The screener reads from `fundamentals`, not from
    # `fundamentals_history`, so this preserves backwards-compat.
    if out["ratios_present"] and not statements:
        cache.upsert_fundamentals(
            symbol=sym,
            eps=None, pe=None,
            pb=ratios.get("pb"),
            div_yield=ratios.get("div_yield"),
            payout=ratios.get("payout"),
            roe=ratios.get("roe"),
        )
    return out


@mcp.tool()
async def refresh_fundamentals(symbol: str) -> dict:
    """Refresh fundamentals_history for a single symbol from PSX sub-tabs.
    Call this before relying on get_fundamentals_history or compute_quality_score."""
    return await _refresh_fundamentals_impl(_cache, _client, symbol)
```

- [ ] **Step 7: Failing integration test in `tests/test_server.py`**

```python
def test_refresh_fundamentals_populates_history(tmp_path, monkeypatch):
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.psx_client import PSXClient
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))

    async def fake_ratios(self, sym):
        return (Path("tests/fixtures") / "ratios_LUCK.html").read_text(encoding="utf-8")
    async def fake_fin(self, sym):
        return (Path("tests/fixtures") / "financial_statements_LUCK.html").read_text(encoding="utf-8")
    monkeypatch.setattr(PSXClient, "fetch_company_ratios", fake_ratios)
    monkeypatch.setattr(PSXClient, "fetch_company_financials_statements", fake_fin)

    client = PSXClient()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=client)
    out = asyncio.run(srv._refresh_fundamentals_impl(cache, client, "LUCK"))
    assert out["ratios_present"]
    assert len(out["fiscal_years_upserted"]) >= 1
    hist = cache.get_fundamentals_history("LUCK")
    assert hist[0]["roe"] is not None  # latest year carries ROE from ratios
```

- [ ] **Step 8: Run, confirm pass**

- [ ] **Step 9: Commit**

```bash
git add psx-mcp/src/psx_mcp/psx_client.py psx-mcp/server.py psx-mcp/tests/test_psx_client.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): refresh_fundamentals tool — populates fundamentals_history from PSX sub-tabs"
```

---

### Task 2.C: Add ROE / P/B / div_yield filters to the screener

**Files:**
- Modify: `psx-mcp/src/psx_mcp/screener.py` — extend `FilterSpec` + SQL where-builder
- Modify: `psx-mcp/server.py` — extend `screen_symbols` wrapper signature
- Test: `psx-mcp/tests/test_screener.py`

- [ ] **Step 1: Failing test**

```python
def test_screen_filters_by_roe_min(seeded_cache):
    """seeded_cache should be extended in conftest or inline to include ROE values.
    For this test, manually upsert ROE."""
    # Update seed: SYS ROE=18, NETSOL ROE=5
    seeded_cache.upsert_fundamentals(symbol="SYS", eps=5.46, pe=27.5, pb=None,
                                      div_yield=None, payout=None, roe=18.0)
    seeded_cache.upsert_fundamentals(symbol="NETSOL", eps=10.0, pe=12.0, pb=None,
                                      div_yield=None, payout=None, roe=5.0)
    from psx_mcp.screener import screen, FilterSpec
    out = screen(seeded_cache, FilterSpec(roe_min=10.0))
    syms = {r["symbol"] for r in out}
    assert "SYS" in syms
    assert "NETSOL" not in syms
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Extend `FilterSpec` + where-builder**

```python
@dataclass
class FilterSpec:
    # ... (existing fields) ...
    roe_min: Optional[float] = None
    pb_max: Optional[float] = None
    div_yield_min: Optional[float] = None
```

In `screen()` add to the where-clause builder:

```python
if spec.roe_min is not None:
    where.append("f.roe >= ?"); params.append(spec.roe_min)
if spec.pb_max is not None:
    where.append("f.pb <= ?"); params.append(spec.pb_max)
if spec.div_yield_min is not None:
    where.append("f.div_yield >= ?"); params.append(spec.div_yield_min)
```

Also fix the consistency nit noted by the analytics-v1 reviewer: change

```python
if spec.sma20_gt_sma50 is True and not (sma20 and sma50 and sma20 > sma50):
```

to

```python
if spec.sma20_gt_sma50 is True and not (sma20 is not None and sma50 is not None and sma20 > sma50):
```

(And mirror for the `is False` case.)

- [ ] **Step 4: Extend `screen_symbols` wrapper in `server.py`**

Add `roe_min`, `pb_max`, `div_yield_min` to the signature and pass-through.

- [ ] **Step 5: Run all screener tests**

Run: `uv run pytest tests/test_screener.py tests/test_server.py -v` (`timeout=240000`).
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/screener.py psx-mcp/server.py psx-mcp/tests/test_screener.py
git commit -m "feat(psx-mcp): screener filters by ROE, P/B, dividend yield"
```

---

## Phase 3 — Dividend history

**Branch:** Only proceed if Task 0.1 + 0.2 confirmed dividend per-event rows in the Payouts fixture. Otherwise skip; document deferral.

### Task 3.1: Add `dividends` cache + `parse_payouts` + tool

```
PAYOUT TABLE RECIPE (from payouts_FFC.html, captured 2026-05-24):
  Endpoint: POST https://dps.psx.com.pk/company/payouts  (form body: symbol=<SYM>)
  Response: <table class="tbl"> with <thead class="tbl__head"> and <tbody class="tbl__body">

  <th> labels (in order): ["Date", "Financial Results", "Details", "Book Closure"]

  Column index → raw text (example FFC row):
    0 "Date"              → "April 29, 2026 2:58 PM"          (announcement_date + time)
    1 "Financial Results" → "31/03/2026(IQ)"                  (fiscal-period-end date + period code)
    2 "Details"           → " 85%(i) (D) "                    (percentage + period letter + payout-type code)
    3 "Book Closure"      → "12/05/2026  - 14/05/2026 "       (ex/book-closure date range "from - to")

  Period codes (col 1 parenthetical):
    YR   = Annual / year-end             (fiscal year ends on the col-1 date)
    HYR  = Half-year                     (announced ~mid fiscal year)
    IQ   = First quarter
    IIQ  = Second quarter   (inferred; not in FFC sample but mirrors IIIQ)
    IIIQ = Third quarter

  Details code (col 2):
    Pattern: r"\s*([\d.]+)%\s*\(([^)]+)\)\s*\(([A-Z])\)\s*"
       group 1 = percentage of face value (e.g. "85", "200", "120")
       group 2 = period letter: F=Final, i=interim Q1, ii=interim H1, iii=interim Q3
                 (correlates with col-1 period code but is the *announcement-timing* letter)
       group 3 = payout-type letter: D=cash Dividend, B=Bonus, R=Right
                 (FFC sample shows only D; B/R defensively parsed)

  Field mapping (output dict for cache.upsert_dividend(**event)):
    announcement_date = parse "April 29, 2026 2:58 PM" (col 0)   → datetime.date
    ex_date           = first half of col 3 range, e.g. "12/05/2026" (DD/MM/YYYY)
                        Note: PSX `Book Closure` is the share-register-shutdown window, which
                        is the closest proxy to ex-date in this payload. Treat the start of
                        that range as ex_date.
    payout_type       = {"D":"cash","B":"bonus","R":"right"}[group 3]
    per_share         = if payout_type=="cash":  float(group 1) * 10.0 / 100.0  (face value Rs 10)
                        else:                    None
    bonus_pct         = if payout_type=="bonus": float(group 1)
                        else:                    None
    fiscal_period_end = parse col-1 date "31/03/2026" → datetime.date  (for announcement_id)
    period_code       = col-1 parenthetical (e.g. "IQ", "YR")          (for announcement_id)
    announcement_id   = f"{symbol}-{fiscal_period_end.year}-{period_code}"
                        e.g. "FFC-2026-IQ", "FFC-2025-YR"
                        Uniqueness: PSX issues ≤1 payout per (fiscal_period_end, period_code, symbol),
                        so collisions are impossible within a normal year.

  Empty-table sentinel: payouts_LUCK.html has only ONE row (LUCK pays once annually, YR);
  this is valid output, not an error. parse_payouts returns [] only if the table is
  completely absent or all rows fail the Details regex.

  Source fixtures: tests/fixtures/payouts_LUCK.html (1 row), tests/fixtures/payouts_FFC.html (6 rows)
```

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py` — `dividends` table + `upsert_dividend` + `get_dividend_history`
- Modify: `psx-mcp/src/psx_mcp/psx_client.py` — `fetch_company_payouts` + `parse_payouts`
- Modify: `psx-mcp/src/psx_mcp/models.py` — `DividendEvent`
- Modify: `psx-mcp/server.py` — `_refresh_dividends_impl`, `_get_dividend_history_impl`, two `@mcp.tool()` wrappers
- Test: `psx-mcp/tests/test_dividends.py`, `psx-mcp/tests/test_psx_client.py`

- [ ] **Step 1: Failing cache test**

Create `psx-mcp/tests/test_dividends.py`:

```python
import pytest
from datetime import date
from psx_mcp.cache import Cache


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


def test_upsert_and_get_dividend_history(cache):
    cache.upsert_dividend(symbol="LUCK", ex_date=date(2025, 9, 15),
                          announcement_date=date(2025, 8, 30),
                          payout_type="cash", per_share=14.0, bonus_pct=None,
                          announcement_id="LUCK-2025-09")
    cache.upsert_dividend(symbol="LUCK", ex_date=date(2024, 9, 12),
                          announcement_date=date(2024, 8, 28),
                          payout_type="cash", per_share=10.0, bonus_pct=None,
                          announcement_id="LUCK-2024-09")
    rows = cache.get_dividend_history("LUCK")
    assert [r["per_share"] for r in rows] == [14.0, 10.0]  # newest first


def test_upsert_replaces_same_announcement_id(cache):
    for ps in (10.0, 12.0):
        cache.upsert_dividend(symbol="X", ex_date=date(2025, 1, 1),
                              announcement_date=date(2025, 1, 1),
                              payout_type="cash", per_share=ps, bonus_pct=None,
                              announcement_id="X-A1")
    rows = cache.get_dividend_history("X")
    assert len(rows) == 1
    assert rows[0]["per_share"] == 12.0
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add `dividends` table + methods**

In `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS dividends (
  announcement_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  ex_date TEXT,
  announcement_date TEXT,
  payout_type TEXT,
  per_share REAL,
  bonus_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_div_symbol_exdate
  ON dividends(symbol, ex_date DESC);
```

In `Cache`:

```python
def upsert_dividend(self, *, symbol: str, ex_date, announcement_date,
                    payout_type: str, per_share, bonus_pct,
                    announcement_id: str) -> None:
    self.conn.execute(
        """INSERT INTO dividends
           (announcement_id, symbol, ex_date, announcement_date,
            payout_type, per_share, bonus_pct)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(announcement_id) DO UPDATE SET
             ex_date=excluded.ex_date,
             announcement_date=excluded.announcement_date,
             payout_type=excluded.payout_type,
             per_share=excluded.per_share, bonus_pct=excluded.bonus_pct""",
        (announcement_id, symbol.upper(), _iso(ex_date), _iso(announcement_date),
         payout_type, per_share, bonus_pct),
    )
    self.conn.commit()

def get_dividend_history(self, symbol: str) -> list[dict]:
    rows = self.conn.execute(
        """SELECT * FROM dividends WHERE symbol=?
           ORDER BY COALESCE(ex_date, announcement_date) DESC""",
        (symbol.upper(),),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add `fetch_company_payouts` + `parse_payouts`**

In `psx_client.py`:

```python
async def fetch_company_payouts(self, symbol: str) -> str:
    """Fetch Payouts sub-tab — URL confirmed in Task 0.1."""
    return await self._get(f"{BASE_DPS}/company/{symbol.upper()}/payouts")

def parse_payouts(symbol: str, html: str) -> list[dict]:
    """Extract dividend events.

    CONTRACT: each returned dict has EXACTLY these keys (matching upsert_dividend
    kwargs verbatim — fixes BLOCKER B2):
      announcement_id (str), symbol (str, upper), ex_date (date|None),
      announcement_date (date|None), payout_type (str), per_share (float|None),
      bonus_pct (float|None).
    Caller invokes: cache.upsert_dividend(**event) — no extra kwargs needed.

    EXACT extraction logic per the column recipe documented in Task 0.2 Step 3.
    Common PSX payout table columns: Year | Period | Cash% | Bonus% | Right% | Ex-Date."""
    from bs4 import BeautifulSoup
    from datetime import date as _date
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any("dividend" in h or "cash" in h or "bonus" in h for h in headers):
            continue
        for tr in (table.find("tbody") or table).find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            # Construct announcement_id from (symbol, year, period, type) so
            # re-fetches deduplicate.
            # ... (adapt to actual column layout from Task 0.1 fixture) ...
            pass
    return out
```

- [ ] **Step 6: Failing parser test**

```python
def test_parse_payouts_extracts_events(fixtures_dir):
    from psx_mcp.psx_client import parse_payouts
    html = (fixtures_dir / "payouts_FFC.html").read_text(encoding="utf-8")
    events = parse_payouts("FFC", html)
    assert len(events) >= 1
    e = events[0]
    assert e["announcement_id"]
    assert e["payout_type"] in ("cash", "bonus", "right")
    assert e["per_share"] is not None or e["bonus_pct"] is not None
```

- [ ] **Step 7: Iterate on `parse_payouts` until test passes against the real captured fixture**

- [ ] **Step 8: Add `_refresh_dividends_impl` + `_get_dividend_history_impl` + tools in `server.py`**

```python
async def _refresh_dividends_impl(cache: Cache, client: PSXClient,
                                   symbol: str) -> int:
    """Fetch & cache dividend history for one symbol. Returns count upserted."""
    html = await client.fetch_company_payouts(symbol)
    events = parse_payouts(symbol, html)
    for e in events:
        # parse_payouts already includes `symbol` in each event dict — see contract.
        cache.upsert_dividend(**e)
    return len(events)


def _get_dividend_history_impl(cache: Cache, symbol: str) -> list[DividendEvent]:
    rows = cache.get_dividend_history(symbol)
    return [DividendEvent(**r) for r in rows]


@mcp.tool()
async def refresh_dividends(symbol: str) -> int:
    """Refresh dividend history for one symbol. Returns count cached."""
    return await _refresh_dividends_impl(_cache, _client, symbol)


@mcp.tool()
async def get_dividend_history(symbol: str) -> list[DividendEvent]:
    """Cached dividend events, newest ex-date first. Call refresh_dividends first."""
    return _get_dividend_history_impl(_cache, symbol)
```

Add `DividendEvent` to `models.py`:

```python
class DividendEvent(BaseModel):
    announcement_id: str
    symbol: str
    ex_date: Optional[date] = None
    announcement_date: Optional[date] = None
    payout_type: Optional[str] = None
    per_share: Optional[float] = None
    bonus_pct: Optional[float] = None

    # Fixes BLOCKER B3: cache may store empty-string dates that Pydantic refuses
    # to coerce to `date`. Normalize "" / whitespace → None before validation.
    @field_validator("ex_date", "announcement_date", mode="before")
    @classmethod
    def _coerce_blank_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v
```

- [ ] **Step 9: Integration test**

```python
def test_get_dividend_history_returns_cached(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_dividend(symbol="FFC", ex_date=date(2025, 9, 1),
                          announcement_date=date(2025, 8, 15),
                          payout_type="cash", per_share=8.0, bonus_pct=None,
                          announcement_id="FFC-2025-09")
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    events = srv._get_dividend_history_impl(cache, "FFC")
    assert len(events) == 1
    assert events[0].per_share == 8.0
```

- [ ] **Step 10: Run all tests, commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/src/psx_mcp/psx_client.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_dividends.py psx-mcp/tests/test_psx_client.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): dividend history (refresh_dividends, get_dividend_history)"
```

---

## Phase 4 — Index EOD history + Beta (no branch — independent of Phase 0)

**Design fix (BLOCKER B4 resolution):** The original plan stored one `indices_history` row per `refresh_market` call (per-snapshot). That's wrong: stock bars are daily, but snapshots are sub-daily/sporadic, so `compute_beta` would correlate misaligned series. Fix: source `indices_history` from the **full EOD payload** that `/timeseries/eod/<INDEX>` already returns (the analytics-v1 Q1 probe confirmed it's a multi-row JSON array, newest-first). One row per trading day, date-keyed — properly alignable with `bars_daily`. Beta works from day one.

### Task 4.1: Add `indices_history` table (EOD-keyed) + extract from full timeseries payload

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py` — `indices_history` table + `upsert_index_bar` + `get_index_history`
- Modify: `psx-mcp/src/psx_mcp/psx_client.py` — new `fetch_index_eod_history(code)` that returns the full parsed EOD list (existing `fetch_indices` keeps only the snapshot behavior)
- Modify: `psx-mcp/server.py` — `_refresh_market_impl` also calls the new fetch and bulk-upserts; new `_get_index_history_impl` + `@mcp.tool() get_index_history`
- Modify: `psx-mcp/src/psx_mcp/models.py` — `IndexHistoryPoint`
- Test: `psx-mcp/tests/test_indices.py`

- [ ] **Step 1: Failing cache test (date-keyed, one row per trading day)**

In `tests/test_indices.py`:

```python
def test_index_history_eod_round_trip(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_index_bar(index_code="KSE100", bar_date=date(2026, 5, 22),
                           close=170000.0, volume=110_000_000)
    cache.upsert_index_bar(index_code="KSE100", bar_date=date(2026, 5, 21),
                           close=168500.0, volume=100_000_000)
    rows = cache.get_index_history("KSE100")
    assert len(rows) == 2
    # Oldest first
    assert rows[0]["close"] == 168500.0
    assert rows[1]["close"] == 170000.0


def test_index_history_upsert_replaces_same_date(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    for close in (170000.0, 170500.0):  # same date, updated close
        cache.upsert_index_bar(index_code="KSE100", bar_date=date(2026, 5, 22),
                               close=close, volume=110_000_000)
    rows = cache.get_index_history("KSE100")
    assert len(rows) == 1
    assert rows[0]["close"] == 170500.0
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement schema + methods**

In `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS indices_history (
  index_code TEXT NOT NULL,
  bar_date TEXT NOT NULL,
  close REAL NOT NULL,
  volume REAL,
  PRIMARY KEY(index_code, bar_date)
);
CREATE INDEX IF NOT EXISTS idx_idxh_code_date
  ON indices_history(index_code, bar_date);
```

In `Cache`:

```python
def upsert_index_bar(self, *, index_code: str, bar_date,
                     close: float, volume) -> None:
    self.conn.execute(
        """INSERT INTO indices_history (index_code, bar_date, close, volume)
           VALUES(?,?,?,?)
           ON CONFLICT(index_code, bar_date) DO UPDATE SET
             close=excluded.close, volume=excluded.volume""",
        (index_code, _iso(bar_date), close, volume),
    )
    self.conn.commit()

def upsert_index_bars_bulk(self, index_code: str,
                           bars: list[dict]) -> int:
    """bars: [{bar_date: date, close: float, volume: float|None}, ...].
    Returns count of rows passed in (per-call, NOT connection-cumulative)."""
    self.conn.executemany(
        """INSERT INTO indices_history (index_code, bar_date, close, volume)
           VALUES(?,?,?,?)
           ON CONFLICT(index_code, bar_date) DO UPDATE SET
             close=excluded.close, volume=excluded.volume""",
        [(index_code, _iso(b["bar_date"]), b["close"], b.get("volume")) for b in bars],
    )
    self.conn.commit()
    return len(bars)

def get_index_history(self, index_code: str,
                      since: Optional[str] = None) -> list[dict]:
    """Return all (or since onward) EOD bars for an index, oldest first.
    `since` is a YYYY-MM-DD string."""
    if since:
        rows = self.conn.execute(
            """SELECT * FROM indices_history WHERE index_code=? AND bar_date>=?
               ORDER BY bar_date ASC""",
            (index_code, since),
        ).fetchall()
    else:
        rows = self.conn.execute(
            "SELECT * FROM indices_history WHERE index_code=? ORDER BY bar_date ASC",
            (index_code,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add `fetch_index_eod_history` to `psx_client.py`**

```python
async def fetch_index_eod_history(self, code: str) -> list[dict]:
    """Fetch the full EOD timeseries for an index. Returns
    [{bar_date: date, close: float, volume: float|None}, ...] sorted oldest first.
    Uses /timeseries/eod/<INDEX> JSON endpoint confirmed in analytics-v1 Q1 probe.

    Payload shape: {data: [[unix_ts, close, volume, ?metric], ...]} (NEWEST-first
    per analytics-v1 finding). We reverse to oldest-first for caller convenience.
    """
    from datetime import datetime as _dt, timezone as _tz, date as _date
    payload_str = await self._get(f"{BASE_DPS}/timeseries/eod/{code.upper()}")
    payload = _try_json(payload_str) or {}
    raw_rows = payload.get("data") or []
    bars = []
    for row in reversed(raw_rows):  # oldest first
        if not row or len(row) < 2:
            continue
        try:
            ts = int(row[0])
            close = float(row[1])
        except (ValueError, TypeError):
            continue
        vol = None
        if len(row) >= 3:
            try:
                vol = float(row[2])
            except (ValueError, TypeError):
                vol = None
        bars.append({
            "bar_date": _dt.fromtimestamp(ts, tz=_tz.utc).date(),
            "close": close,
            "volume": vol,
        })
    return bars
```

- [ ] **Step 6: Failing client test**

In `tests/test_indices.py`:

```python
def test_fetch_index_eod_history_parses_full_payload(monkeypatch):
    """Full EOD timeseries → list of dated bars, oldest first."""
    import asyncio
    from psx_mcp.psx_client import PSXClient
    # PSX returns NEWEST first; we reverse to oldest first.
    fake = {"data": [
        [1779447600, 167844.24, 170376043, 169539.16],  # newer
        [1779361200, 168514.44, 165000000, 168000.00],  # ...
        [1779274800, 164831.42, 160000000, 164000.00],  # older
    ]}
    async def fake_get(self, url):
        import json as _j
        return _j.dumps(fake)
    monkeypatch.setattr(PSXClient, "_get", fake_get)
    bars = asyncio.run(PSXClient().fetch_index_eod_history("KSE100"))
    assert len(bars) == 3
    # Oldest first after reversal
    assert bars[0]["close"] == 164831.42
    assert bars[-1]["close"] == 167844.24
    assert bars[0]["bar_date"] < bars[-1]["bar_date"]
```

- [ ] **Step 7: Wire `_refresh_market_impl` to populate `indices_history`**

In the existing `try:` block that calls `await client.fetch_indices(...)` in `_refresh_market_impl` (see analytics-v1 Task 2.1), add — inside the same try-block so the existing best-effort guarantee is preserved (fixes MINOR m10):

```python
for code in ("KSE100", "KSE30", "ALLSHR"):
    try:
        bars = await client.fetch_index_eod_history(code)
        if bars:
            cache.upsert_index_bars_bulk(code, bars)
    except Exception:
        continue  # one failed index doesn't kill the rest
```

- [ ] **Step 8: Add `_get_index_history_impl` + tool**

```python
def _get_index_history_impl(cache: Cache, index_code: str,
                            since: Optional[str] = None) -> list[IndexHistoryPoint]:
    rows = cache.get_index_history(index_code, since=since)
    return [IndexHistoryPoint(**r) for r in rows]


@mcp.tool()
async def get_index_history(index_code: str = "KSE100",
                             since: Optional[str] = None) -> list[IndexHistoryPoint]:
    """Cached EOD index history (one row per trading day).
    `since` is a YYYY-MM-DD string; omit for full history.
    History is populated from PSX's /timeseries/eod/<INDEX> endpoint on every refresh_market."""
    return _get_index_history_impl(_cache, index_code, since)
```

Add `IndexHistoryPoint` to `models.py`:

```python
class IndexHistoryPoint(BaseModel):
    index_code: str
    bar_date: date  # schema declares NOT NULL, so always present
    close: float
    volume: Optional[float] = None
    # No blank-coercion validator: bar_date is NOT NULL in the cache schema,
    # so an empty string is a corrupted-row scenario where loud failure is correct.
```

- [ ] **Step 9: Integration test**

```python
def test_get_index_history_after_refresh(tmp_path, monkeypatch):
    """End-to-end: fake fetch_index_eod_history, refresh_market, then get_index_history."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.psx_client import PSXClient
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))

    async def fake_market(self):
        return "<table></table>"  # empty market-watch HTML; parse returns 0 rows
    async def fake_indices(self, codes=None):
        return []  # no snapshot — just exercise the history branch
    async def fake_eod(self, code):
        from datetime import date as _d
        return [
            {"bar_date": _d(2026, 5, 20), "close": 168000.0, "volume": 1e8},
            {"bar_date": _d(2026, 5, 21), "close": 168500.0, "volume": 1e8},
            {"bar_date": _d(2026, 5, 22), "close": 170000.0, "volume": 1.1e8},
        ]
    monkeypatch.setattr(PSXClient, "fetch_market_watch", fake_market)
    monkeypatch.setattr(PSXClient, "fetch_indices", fake_indices)
    monkeypatch.setattr(PSXClient, "fetch_index_eod_history", fake_eod)

    client = PSXClient()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=client)
    asyncio.run(srv._refresh_market_impl(cache, client))
    rows = srv._get_index_history_impl(cache, "KSE100")
    assert len(rows) == 3
    # Oldest first
    assert rows[0].close == 168000.0
    assert rows[-1].close == 170000.0
```

- [ ] **Step 10: Run, commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/src/psx_mcp/psx_client.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_indices.py
git commit -m "feat(psx-mcp): indices_history table populated from /timeseries/eod (one row per trading day)"
```

---

### Task 4.2: `compute_beta(symbol, window=252)`

**Files:**
- Create: `psx-mcp/src/psx_mcp/beta.py`
- Create: `psx-mcp/tests/test_beta.py`
- Modify: `psx-mcp/src/psx_mcp/models.py` — `BetaResponse`
- Modify: `psx-mcp/server.py` — `_compute_beta_impl` + `@mcp.tool() compute_beta`
- Test: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Failing pure-function tests**

Create `psx-mcp/tests/test_beta.py`:

```python
import pytest
import pandas as pd
import numpy as np
from psx_mcp.beta import beta


def test_beta_of_identical_series_is_one():
    s = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    result = beta(stock_closes=s, index_closes=s, window=None)
    assert result["beta"] == pytest.approx(1.0)
    assert result["r_squared"] == pytest.approx(1.0)
    assert result["n"] == 9  # 10 closes → 9 returns


def test_beta_of_double_series_is_two():
    idx = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    # Stock returns are 2× index returns; build series in a single list (avoids
    # O(n²) pd.concat — addresses minor m7).
    stock_returns = idx.pct_change().dropna() * 2
    stock_vals = [100.0]
    for r in stock_returns:
        stock_vals.append(stock_vals[-1] * (1 + r))
    stock = pd.Series(stock_vals)
    result = beta(stock_closes=stock, index_closes=idx, window=None)
    assert result["beta"] == pytest.approx(2.0, abs=0.01)


def test_beta_returns_none_when_insufficient_overlap():
    s = pd.Series([100.0, 101.0])
    result = beta(stock_closes=s, index_closes=s, window=None)
    assert result["beta"] is None
    assert result["n"] == 1


def test_beta_window_limits_to_last_n_returns():
    idx = pd.Series([100.0 + i for i in range(100)])  # 100 closes, 99 returns
    stock = idx.copy()
    result = beta(stock_closes=stock, index_closes=idx, window=20)
    assert result["n"] == 20
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `beta.py`**

```python
"""Pure-function beta / alpha / R² over aligned close series."""
from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np


def beta(stock_closes: pd.Series, index_closes: pd.Series,
         window: Optional[int] = 252) -> dict:
    """Compute beta of stock_closes vs index_closes via OLS on returns.

    Args:
      stock_closes, index_closes: pandas Series of closes (need not be aligned by index;
        we align by position from the END of each).
      window: number of most-recent returns to use, or None for all available.

    Returns: {beta, alpha, r_squared, n}. beta/alpha/r_squared are None if n < 2.
    """
    stock_returns = stock_closes.pct_change().dropna().reset_index(drop=True)
    index_returns = index_closes.pct_change().dropna().reset_index(drop=True)
    # Align by tail length
    n_overlap = min(len(stock_returns), len(index_returns))
    if window is not None:
        n_overlap = min(n_overlap, window)
    if n_overlap < 2:
        return {"beta": None, "alpha": None, "r_squared": None, "n": n_overlap}
    s = stock_returns.iloc[-n_overlap:].values
    x = index_returns.iloc[-n_overlap:].values
    # OLS: y = a + b * x
    cov_xy = np.cov(x, s, ddof=1)[0, 1]
    var_x = np.var(x, ddof=1)
    if var_x == 0:
        return {"beta": None, "alpha": None, "r_squared": None, "n": n_overlap}
    b = float(cov_xy / var_x)
    a = float(s.mean() - b * x.mean())
    ss_res = float(np.sum((s - (a + b * x)) ** 2))
    ss_tot = float(np.sum((s - s.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else None
    return {"beta": b, "alpha": a, "r_squared": r2, "n": int(n_overlap)}
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add `_compute_beta_impl` + tool + model**

```python
# server.py
from psx_mcp.beta import beta
from psx_mcp.models import BetaResponse


def _compute_beta_impl(cache: Cache, symbol: str,
                       index_code: str = "KSE100",
                       window: int = 252) -> BetaResponse:
    """Date-align stock bars and index EOD history, then OLS on returns.

    Both `closes_for` and `get_index_history` return oldest-first. We intersect
    on date to compute aligned returns — required because stock and index may
    have different trading-day coverage in the cache.
    """
    # NOTE: Raw cache.conn.execute is used here because closes_for(symbol)
    # only returns floats without dates, and we need date-aligned pairs.
    # TODO (Part 3): add Cache.closes_for_with_dates(symbol) helper and switch
    # this back to use it — keeps the Phase-1 layering refactor intact.
    stock_rows = cache.conn.execute(
        "SELECT date, close FROM bars_daily WHERE symbol=? ORDER BY date ASC",
        (symbol.upper(),),
    ).fetchall()
    stock_by_date = {r["date"]: r["close"] for r in stock_rows}
    idx_rows = cache.get_index_history(index_code)
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
    common_dates = sorted(set(stock_by_date) & set(idx_by_date))
    if len(common_dates) < 2:
        return BetaResponse(
            symbol=symbol.upper(), index_code=index_code, window=window,
            beta=None, alpha=None, r_squared=None, n=0,
            note=(f"Insufficient overlap: stock has {len(stock_by_date)} bars, "
                  f"index has {len(idx_by_date)} bars, common dates {len(common_dates)}. "
                  f"Call refresh_history({symbol!r}) and refresh_market first."),
        )
    stock_closes = pd.Series([stock_by_date[d] for d in common_dates])
    idx_closes   = pd.Series([idx_by_date[d]   for d in common_dates])
    result = beta(stock_closes=stock_closes, index_closes=idx_closes, window=window)
    return BetaResponse(
        symbol=symbol.upper(), index_code=index_code, window=window,
        beta=result["beta"], alpha=result["alpha"],
        r_squared=result["r_squared"], n=result["n"],
        note=None,
    )


@mcp.tool()
async def compute_beta(symbol: str, index_code: str = "KSE100",
                       window: int = 252) -> BetaResponse:
    """Beta of symbol vs index, computed on date-aligned EOD returns.
    window=252 ≈ 1 trading year.
    Both series are sourced from cached daily data (bars_daily for the stock,
    indices_history for the index — populated from /timeseries/eod on each
    refresh_market call). Call refresh_history(symbol) and refresh_market once
    before this for full coverage."""
    return _compute_beta_impl(_cache, symbol, index_code, window)
```

Add to `models.py`:

```python
class BetaResponse(Disclaimer):
    symbol: str
    index_code: str
    window: int
    beta: Optional[float]
    alpha: Optional[float]
    r_squared: Optional[float]
    n: int
    note: Optional[str] = None
```

- [ ] **Step 6: Server-level test**

```python
def test_compute_beta_with_seeded_series(tmp_path):
    """Beta of a symbol whose returns equal index returns should be ~1.

    Seeds bars_daily AND indices_history with the SAME dates so the
    date-alignment in _compute_beta_impl actually finds overlap.
    """
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    bars = []
    for i in range(100):
        d = today - timedelta(days=99 - i)
        close = 100.0 * (1 + i * 0.01)
        bars.append(Bar(symbol="XYZ", date=d, open=close, high=close*1.01,
                        low=close*0.99, close=close, volume=1000))
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                               close=close, volume=1e8)
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_beta_impl(cache, "XYZ")
    assert out.beta == pytest.approx(1.0, abs=0.01)
    assert out.r_squared == pytest.approx(1.0, abs=0.01)


def test_compute_beta_insufficient_overlap_returns_none_with_note(tmp_path):
    """If bar dates and index dates don't overlap, beta is None and note explains."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    # Stock bars from January 2024, index from May 2026 — zero overlap.
    cache.upsert_bars([Bar(symbol="XYZ", date=date(2024, 1, 1) + timedelta(days=i),
                            open=100.0, high=101.0, low=99.0, close=100.0 + i, volume=1)
                       for i in range(50)])
    for i in range(50):
        cache.upsert_index_bar(index_code="KSE100",
                                bar_date=date(2026, 5, 1) + timedelta(days=i),
                                close=170000.0 + i, volume=1e8)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_beta_impl(cache, "XYZ")
    assert out.beta is None
    assert out.n == 0
    assert out.note and "overlap" in out.note.lower()
```

- [ ] **Step 7: Run, commit**

```bash
git add psx-mcp/src/psx_mcp/beta.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_beta.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_beta tool — OLS beta vs cached index history"
```

---

## Phase 5 — Composite quality / value / momentum scores

### Task 5.1: Build `quality.py` with the four score primitives

**Files:**
- Create: `psx-mcp/src/psx_mcp/quality.py`
- Create: `psx-mcp/tests/test_quality.py`

- [ ] **Step 1: Failing pure-function tests**

```python
import pytest
import pandas as pd
from psx_mcp.quality import (
    compute_value_score, compute_quality_score,
    compute_momentum_score, compute_trend_score,
    compute_4quadrant_score,
)


def test_value_score_cheaper_pe_scores_higher():
    cheap = {"pe": 5.0, "eps": 10.0, "price": 50.0}
    expensive = {"pe": 30.0, "eps": 1.0, "price": 30.0}
    sector_median = {"pe": 12.0}
    assert compute_value_score(cheap, sector_median) > compute_value_score(expensive, sector_median)


def test_quality_score_higher_roe_scores_higher():
    hi = {"roe": 25.0, "eps_history": [1.0, 1.1, 1.2, 1.3]}
    lo = {"roe": 5.0,  "eps_history": [1.0, 0.9, 0.8, 0.7]}
    assert compute_quality_score(hi) > compute_quality_score(lo)


def test_momentum_score_12_1_skips_recent_month():
    """12-1 momentum should equal return from -252 to -21."""
    n = 260
    closes = pd.Series([100.0 + i for i in range(n)])  # straight uptrend
    score = compute_momentum_score(closes)
    assert score is not None
    assert score > 0  # uptrend → positive


def test_momentum_returns_none_if_insufficient_history():
    closes = pd.Series([100.0, 101.0, 102.0])
    assert compute_momentum_score(closes) is None


def test_trend_score_above_sma200_and_stack_passes():
    n = 250
    closes = pd.Series([100.0 + i for i in range(n)])
    assert compute_trend_score(closes) > 0


def test_4quadrant_combines_to_0_to_4():
    snapshot = {
        "pe": 5.0, "eps": 10.0, "price": 50.0,
        "roe": 25.0, "eps_history": [1.0, 1.1, 1.2, 1.3],
        "closes": pd.Series([100.0 + i for i in range(260)]),
        "sector_median_pe": 12.0,
    }
    score = compute_4quadrant_score(snapshot)
    assert "total" in score
    assert 0 <= score["total"] <= 4
    assert set(score.keys()) >= {"value", "quality", "momentum", "trend", "total"}
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `quality.py`**

```python
"""Composite scoring primitives. Each returns either a 0/1 quadrant pass or a
continuous score; compute_4quadrant_score aggregates them into a 0–4 total."""
from __future__ import annotations
from typing import Optional
import pandas as pd
from psx_mcp.indicators import sma, rsi


def compute_value_score(snapshot: dict, sector_median: dict) -> float:
    """1.0 if P/E is below sector median and positive; 0.0 otherwise.
    Continuous: scaled by how far below median."""
    pe = snapshot.get("pe")
    med = sector_median.get("pe")
    if pe is None or med is None or pe <= 0:
        return 0.0
    if pe >= med:
        return 0.0
    return min(1.0, (med - pe) / med)


def compute_quality_score(snapshot: dict) -> float:
    """1.0 if ROE >= 15 AND EPS history is non-decreasing across last 3 years.
    Continuous: half-credit for either."""
    score = 0.0
    roe = snapshot.get("roe")
    if roe is not None and roe >= 15:
        score += 0.5
    eps_hist = snapshot.get("eps_history") or []
    if len(eps_hist) >= 3:
        # Last 3 entries non-decreasing
        recent = eps_hist[-3:]
        if all(a <= b for a, b in zip(recent, recent[1:])):
            score += 0.5
    return score


def compute_momentum_score(closes: pd.Series) -> Optional[float]:
    """12-1 momentum: return from t-252 to t-21. None if insufficient data.
    Returns the float return (e.g., 0.30 = +30%)."""
    if len(closes) < 252:
        return None
    past = closes.iloc[-252]
    skip = closes.iloc[-21]
    if past <= 0:
        return None
    return float(skip / past - 1.0)


def compute_trend_score(closes: pd.Series) -> float:
    """1.0 if price > SMA200 AND SMA20 > SMA50. 0.5 if only one. 0.0 if neither.
    Returns 0.0 if insufficient data for SMA200."""
    if len(closes) < 200:
        return 0.0
    price = closes.iloc[-1]
    s200 = float(sma(closes, 200).iloc[-1])
    s50  = float(sma(closes, 50).iloc[-1])
    s20  = float(sma(closes, 20).iloc[-1])
    score = 0.0
    if price > s200:
        score += 0.5
    if s20 > s50:
        score += 0.5
    return score


def compute_4quadrant_score(snapshot: dict) -> dict:
    """Synthesize Value/Quality/Momentum/Trend scores into one 0–4 total.

    Required keys in snapshot:
      pe, eps, price, roe, eps_history, closes (pd.Series), sector_median_pe.
    Missing keys → that quadrant scores 0.

    Each quadrant is binarized at threshold 0.5 → 0 or 1, so total ∈ {0,1,2,3,4}.
    """
    v = compute_value_score(snapshot, {"pe": snapshot.get("sector_median_pe")})
    q = compute_quality_score(snapshot)
    m_raw = compute_momentum_score(snapshot.get("closes", pd.Series(dtype=float)))
    m = 1.0 if (m_raw is not None and m_raw > 0) else 0.0
    t = compute_trend_score(snapshot.get("closes", pd.Series(dtype=float)))
    bin_v = 1 if v >= 0.5 else 0
    bin_q = 1 if q >= 0.5 else 0
    bin_m = 1 if m >= 0.5 else 0
    bin_t = 1 if t >= 0.5 else 0
    return {
        "value": bin_v, "quality": bin_q, "momentum": bin_m, "trend": bin_t,
        "total": bin_v + bin_q + bin_m + bin_t,
        "raw": {"value": v, "quality": q, "momentum_return": m_raw, "trend": t},
    }
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/quality.py psx-mcp/tests/test_quality.py
git commit -m "feat(psx-mcp): quality.py — value/quality/momentum/trend score primitives"
```

---

### Task 5.2: Wire `compute_quality_score` and `compute_4quadrant_score` MCP tools

**Files:**
- Modify: `psx-mcp/server.py` — `_compute_quality_score_impl`, `_compute_4quadrant_score_impl`, wrappers
- Modify: `psx-mcp/src/psx_mcp/models.py` — `QualityScoreResponse`, `QuadrantScoreResponse`
- Test: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Failing server-level test**

```python
def test_compute_4quadrant_score_returns_total_0_to_4(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    cache.upsert_symbol("SYS", "Systems", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=ts, price=600.0, change=5.0, volume=100_000,
                       day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    cache.upsert_fundamentals_history(symbol="SYS", fiscal_year=2023, eps=8.0,
                                       pe=None, pb=None, div_yield=None, payout=None, roe=None,
                                       gross_margin=None, total_assets=None,
                                       long_term_debt=None, current_liab=None,
                                       current_assets=None, shares_outstanding=None,
                                       source_url=None, refreshed_at=ts)
    cache.upsert_fundamentals_history(symbol="SYS", fiscal_year=2024, eps=9.0,
                                       pe=None, pb=None, div_yield=None, payout=None, roe=None,
                                       gross_margin=None, total_assets=None,
                                       long_term_debt=None, current_liab=None,
                                       current_assets=None, shares_outstanding=None,
                                       source_url=None, refreshed_at=ts)
    cache.upsert_fundamentals_history(symbol="SYS", fiscal_year=2025, eps=10.0,
                                       pe=None, pb=None, div_yield=None, payout=None, roe=None,
                                       gross_margin=None, total_assets=None,
                                       long_term_debt=None, current_liab=None,
                                       current_assets=None, shares_outstanding=None,
                                       source_url=None, refreshed_at=ts)
    # Seed 260 strictly-uptrending closes so momentum+trend both pass
    today = date(2026, 5, 23)
    bars = [Bar(symbol="SYS", date=today - timedelta(days=259 - i),
                open=100.0 + i, high=100.0 + i, low=100.0 + i,
                close=100.0 + i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_4quadrant_score_impl(cache, "SYS")
    assert 0 <= out.total <= 4
    assert out.value + out.quality + out.momentum + out.trend == out.total
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement impls + wrappers in `server.py`**

```python
from psx_mcp.quality import (
    compute_value_score, compute_quality_score,
    compute_momentum_score, compute_trend_score,
    compute_4quadrant_score,
)
from psx_mcp.screener import sector_summary
from psx_mcp.models import QualityScoreResponse, QuadrantScoreResponse


def _build_snapshot(cache: Cache, symbol: str) -> dict:
    """Assemble the dict snapshot expected by quality.py primitives."""
    sym = symbol.upper()
    quote = cache.get_latest_quote(sym) or {}
    fund = cache.get_fundamentals(sym) or {}
    hist = cache.get_fundamentals_history(sym) or []
    eps_history = list(reversed([h["eps"] for h in hist if h.get("eps") is not None]))
    sym_row = cache.get_symbol(sym) or {}
    sector = sym_row.get("sector")
    sector_med = None
    if sector:
        ss = sector_summary(cache, sector)
        sector_med = ss.get("median_pe")
    closes = pd.Series(cache.closes_for(sym))
    return {
        "pe": fund.get("pe"),
        "eps": fund.get("eps"),
        "price": quote.get("price"),
        "roe": fund.get("roe"),
        "eps_history": eps_history,
        "closes": closes,
        "sector_median_pe": sector_med,
    }


def _compute_quality_score_impl(cache: Cache, symbol: str) -> QualityScoreResponse:
    snap = _build_snapshot(cache, symbol)
    score = compute_quality_score(snap)
    return QualityScoreResponse(symbol=symbol.upper(), score=score, snapshot=snap_for_response(snap))


def _compute_4quadrant_score_impl(cache: Cache, symbol: str) -> QuadrantScoreResponse:
    snap = _build_snapshot(cache, symbol)
    sc = compute_4quadrant_score(snap)
    return QuadrantScoreResponse(
        symbol=symbol.upper(),
        value=sc["value"], quality=sc["quality"],
        momentum=sc["momentum"], trend=sc["trend"], total=sc["total"],
        raw=sc["raw"],
    )


def snap_for_response(snap: dict) -> dict:
    """Strip non-JSON-serializable parts of the snapshot."""
    return {k: v for k, v in snap.items() if k != "closes"}


@mcp.tool()
async def compute_quality_score(symbol: str) -> QualityScoreResponse:
    """Piotroski-flavored quality score (0..1) based on ROE + EPS trend."""
    return _compute_quality_score_impl(_cache, symbol)


@mcp.tool()
async def compute_4quadrant_score(symbol: str) -> QuadrantScoreResponse:
    """Composite Value/Quality/Momentum/Trend score (0..4). 3+ = high-conviction."""
    return _compute_4quadrant_score_impl(_cache, symbol)
```

In `models.py`:

```python
class QualityScoreResponse(Disclaimer):
    symbol: str
    score: float
    snapshot: dict


class QuadrantScoreResponse(Disclaimer):
    symbol: str
    value: int
    quality: int
    momentum: int
    trend: int
    total: int
    raw: dict
```

- [ ] **Step 4: Run, confirm pass; run full server suite**

Run: `uv run pytest tests/ -v` (`timeout=300000`).
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_quality_score + compute_4quadrant_score MCP tools"
```

---

### Task 5.3 (CONDITIONAL): Piotroski F-Score

> **STATUS (2026-05-24, post-Phase-0): DEFERRED to Part 3.** Phase 0 audit on `financial_statements_LUCK.html` (= landing page) confirmed only `eps`, `net_income` (Profit after Taxation), and `revenue` (Sales) are present. Missing: `cfo`, `total_assets`, `current_assets`, `current_liab`, `long_term_debt`, `shares_outstanding`. Only 2 of the 9 Piotroski signals (#1 Net income > 0; #4 CFO > Net income — but CFO itself is missing) are computable, so a partial F-Score would be misleading. Full F-Score requires balance-sheet items from the SPA-rendered Financial Statements sub-tab → headless browser needed. See `psx-mcp/tests/fixtures/ratios_payouts_audit.txt`.

**Branch:** Only proceed if Task 0.2 confirmed `total_assets`, `long_term_debt`, `current_liab`, `current_assets`, `net_income`, `cfo`, `revenue`, `shares_outstanding` are all present in the Financial Statements fixture (the audit's FIN_STATEMENTS_KEYWORDS scan).

If any of those is missing, SKIP this task and document at the bottom of this plan: "F-Score deferred to Part 3 — Financial Statements sub-tab missing field X." If only some are missing, deliver a PARTIAL F-Score using the signals that are computable (document which 9 signals are scored vs skipped).

If all confirmed:

- [ ] **Step 1: Failing pure-function test in `tests/test_quality.py`**

```python
def test_piotroski_fscore_high_quality_company_scores_8_or_9():
    """Improving on all 9 axes → near-perfect score.
    Field names match fundamentals_history row keys verbatim — fixes M10."""
    snapshot_y0 = {  # prior year
        "net_income": 50.0, "cfo": 60.0,
        "total_assets": 500.0, "long_term_debt": 100.0,
        "current_assets": 200.0, "current_liab": 130.0,
        "shares_outstanding": 1000.0,
        "gross_margin": 0.30, "revenue": 800.0,
    }
    snapshot_y1 = {  # current year, improving on each axis
        "net_income": 70.0, "cfo": 85.0,
        "total_assets": 510.0, "long_term_debt": 90.0,
        "current_assets": 240.0, "current_liab": 130.0,
        "shares_outstanding": 1000.0,
        "gross_margin": 0.33, "revenue": 900.0,
    }
    from psx_mcp.quality import piotroski_fscore
    score = piotroski_fscore(snapshot_y0, snapshot_y1)
    assert score >= 8


def test_piotroski_fscore_missing_field_skips_signal():
    """If a required field is None, that signal scores 0 (not 1)."""
    snapshot_y0 = {"net_income": 50.0, "cfo": None, "total_assets": 500.0,
                    "long_term_debt": 100.0, "current_assets": 200.0,
                    "current_liab": 130.0, "shares_outstanding": 1000.0,
                    "gross_margin": 0.30, "revenue": 800.0}
    snapshot_y1 = {"net_income": 70.0, "cfo": None, "total_assets": 510.0,
                    "long_term_debt": 90.0, "current_assets": 240.0,
                    "current_liab": 130.0, "shares_outstanding": 1000.0,
                    "gross_margin": 0.33, "revenue": 900.0}
    from psx_mcp.quality import piotroski_fscore
    score = piotroski_fscore(snapshot_y0, snapshot_y1)
    # Two CFO-dependent signals (positive CFO + CFO > Net Income) score 0.
    assert score <= 7
```

- [ ] **Step 2: Implement `piotroski_fscore(prev, current)` in `quality.py`**

```python
def piotroski_fscore(prev: dict, current: dict) -> int:
    """Piotroski's 9-signal fundamental quality score.

    Signals (1 point each if condition holds, 0 otherwise; missing field → 0):
      1. Net income > 0
      2. CFO > 0
      3. ROA (= net_income/total_assets) improving YoY
      4. CFO > Net income (accrual quality)
      5. Lower long-term debt YoY
      6. Higher current ratio (= current_assets/current_liab) YoY
      7. No new share issuance (shares_outstanding non-increasing YoY)
      8. Gross margin improving YoY
      9. Asset turnover (= revenue/total_assets) improving YoY

    Returns int 0..9. Missing fields silently score 0 on that signal so the
    function never raises — caller can compare against the max-possible score
    derived from which signals were skipped if they want a normalized version.
    """
    def f(d: dict, k: str):
        return d.get(k)

    def safe_div(a, b):
        if a is None or b is None or b == 0:
            return None
        return a / b

    score = 0
    # 1
    if (ni1 := f(current, "net_income")) is not None and ni1 > 0:
        score += 1
    # 2
    if (cfo1 := f(current, "cfo")) is not None and cfo1 > 0:
        score += 1
    # 3 ROA improving
    roa0 = safe_div(f(prev, "net_income"), f(prev, "total_assets"))
    roa1 = safe_div(f(current, "net_income"), f(current, "total_assets"))
    if roa0 is not None and roa1 is not None and roa1 > roa0:
        score += 1
    # 4 CFO > Net Income
    if cfo1 is not None and ni1 is not None and cfo1 > ni1:
        score += 1
    # 5 Lower LT debt
    ltd0, ltd1 = f(prev, "long_term_debt"), f(current, "long_term_debt")
    if ltd0 is not None and ltd1 is not None and ltd1 < ltd0:
        score += 1
    # 6 Higher current ratio
    cr0 = safe_div(f(prev, "current_assets"), f(prev, "current_liab"))
    cr1 = safe_div(f(current, "current_assets"), f(current, "current_liab"))
    if cr0 is not None and cr1 is not None and cr1 > cr0:
        score += 1
    # 7 No new shares
    so0, so1 = f(prev, "shares_outstanding"), f(current, "shares_outstanding")
    if so0 is not None and so1 is not None and so1 <= so0:
        score += 1
    # 8 Gross margin improving
    gm0, gm1 = f(prev, "gross_margin"), f(current, "gross_margin")
    if gm0 is not None and gm1 is not None and gm1 > gm0:
        score += 1
    # 9 Asset turnover improving
    at0 = safe_div(f(prev, "revenue"), f(prev, "total_assets"))
    at1 = safe_div(f(current, "revenue"), f(current, "total_assets"))
    if at0 is not None and at1 is not None and at1 > at0:
        score += 1
    return score
```

- [ ] **Step 3: Add MCP wrapper `compute_fscore(symbol)` in `server.py`**

```python
from psx_mcp.quality import piotroski_fscore
from psx_mcp.models import FScoreResponse


def _compute_fscore_impl(cache: Cache, symbol: str) -> FScoreResponse:
    hist = cache.get_fundamentals_history(symbol)  # newest first
    if len(hist) < 2:
        return FScoreResponse(
            symbol=symbol.upper(), score=None, prev_year=None, current_year=None,
            note="Need at least 2 fiscal years of fundamentals_history; "
                 "call refresh_fundamentals(symbol) first.",
        )
    current, prev = hist[0], hist[1]  # row dicts have the same keys piotroski_fscore expects
    score = piotroski_fscore(prev, current)
    return FScoreResponse(
        symbol=symbol.upper(), score=score,
        prev_year=prev["fiscal_year"], current_year=current["fiscal_year"],
        note=None,
    )


@mcp.tool()
async def compute_fscore(symbol: str) -> FScoreResponse:
    """Piotroski 9-signal fundamental score (0..9). 8+ is high quality.
    Needs at least 2 years of cached fundamentals_history."""
    return _compute_fscore_impl(_cache, symbol)
```

Add to `models.py`:

```python
class FScoreResponse(Disclaimer):
    symbol: str
    score: Optional[int]
    prev_year: Optional[int]
    current_year: Optional[int]
    note: Optional[str] = None
```

- [ ] **Step 4: Server-level test**

```python
def test_compute_fscore_high_quality_seeded(tmp_path):
    """Two fiscal years with improvements → fscore >= 8."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    # Common base kwargs
    def k(**ov):
        b = dict(symbol="LUCK", eps=None, pe=None, pb=None,
                 div_yield=None, payout=None, roe=None, gross_margin=None,
                 net_income=None, cfo=None, revenue=None,
                 total_assets=None, long_term_debt=None, current_liab=None,
                 current_assets=None, shares_outstanding=None,
                 source_url=None, refreshed_at=datetime.now())
        b.update(ov)
        return b
    cache.upsert_fundamentals_history(**k(fiscal_year=2024,
        net_income=50.0, cfo=60.0, total_assets=500.0, long_term_debt=100.0,
        current_assets=200.0, current_liab=130.0, shares_outstanding=1000.0,
        gross_margin=0.30, revenue=800.0))
    cache.upsert_fundamentals_history(**k(fiscal_year=2025,
        net_income=70.0, cfo=85.0, total_assets=510.0, long_term_debt=90.0,
        current_assets=240.0, current_liab=130.0, shares_outstanding=1000.0,
        gross_margin=0.33, revenue=900.0))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_fscore_impl(cache, "LUCK")
    assert out.score is not None and out.score >= 8
```

- [ ] **Step 5: Run, commit**

```bash
git add psx-mcp/src/psx_mcp/quality.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_quality.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): Piotroski F-Score (compute_fscore) — 9 signals over cached fundamentals_history"
```

---

## Phase 6 — Documentation & release

### Task 6.1: Update README + playbook

- [ ] **Step 1: Update `psx-mcp/README.md` tool table**

Add rows for:
- `refresh_fundamentals(symbol)` (if Phase 2.B shipped)
- `get_fundamentals_history(symbol)` (already wired in Task 2.A.1 — just document it here)
- `refresh_dividends(symbol)`, `get_dividend_history(symbol)` (if Phase 3 shipped)
- `get_index_history(index_code, since)`
- `compute_beta(symbol, index_code, window)`
- `compute_quality_score(symbol)`
- `compute_4quadrant_score(symbol)`
- `compute_fscore(symbol)` (if Phase 5.3 shipped)

For each, include the one-line description and a usage example.

- [ ] **Step 2: Update `docs/investing-playbook.md`**

In Part 1 gap table mark resolved: ROE/quality metrics ✅ (if Phase 2.B shipped), Dividend history ✅ (if Phase 3 shipped). In Part 5 P1/P2 sections strike-through delivered tools.

- [ ] **Step 3: Commit**

```bash
git add psx-mcp/README.md docs/investing-playbook.md
git commit -m "docs(psx-mcp): document Part 2 analytics tools"
```

---

### Task 6.2: Full-suite gate + tag

- [ ] **Step 1: Run the full suite from `psx-mcp/`**

```
uv run pytest -v
```
With `timeout=300000`.
Expected: all green (target ~130+ tests up from 109 in analytics-v1).

- [ ] **Step 2: Tag the release (no push)**

```bash
git tag -a analytics-v2 -m "PSX MCP Analytics Upgrade Part 2"
```
(Annotated tag, fails loudly if already present — fixes n10.)

- [ ] **Step 3: Report final test count, tag SHA, any failures.**

---

## Self-Review

**1. Spec coverage:** Re-read the Part-2 deferred-features list from the analytics-v1 plan and the user's clarifying message. Coverage check:
- Screener cache layering ✅ (Task 1.1)
- N+1 query in screener ✅ (Task 1.2)
- UTC timestamps + None guard ✅ (Task 1.3)
- Multi-year fundamentals snapshot ✅ (Task 2.A schema, 2.B population)
- ROE / P/B / dividend yield population ✅ (Task 2.B, conditional on Phase 0)
- Dividend history ✅ (Phase 3, conditional)
- Index history + Beta ✅ (Phase 4)
- 4-quadrant composite ✅ (Phase 5.1, 5.2)
- Piotroski F-Score ✅ (Phase 5.3, conditional)
- SBP macro feed, news/sentiment — explicitly deferred to Part 3 (per user's "no scraping/paid" constraint)
- Re-capture company-payload fixtures — implicit in Task 0.1 step 4

**2. Placeholder scan:** Every code step contains either real code or a concrete reference (e.g., "URL: discovered in Task 0.1 — replace with confirmed endpoint" is acknowledged with a fallback structure shown). The two conditional tasks (2.B and 5.3) explicitly document what to do if the prerequisite fails.

**3. Type consistency:** Verified across the plan:
- `Cache.closes_for(symbol, limit=None) → list[float]` consistent in Task 1.1, 4.2, 5.2.
- `Cache.closes_for_many(symbols) → dict[str, list[float]]` matches its usage in `screen()`.
- `Cache.screen_candidates(where_clause, params) → list[dict]` consistent in Task 1.1, 1.2.
- `Cache.get_fundamentals_history → list[dict]` consistent in 2.A and 5.2.
- `Cache.get_dividend_history → list[dict]` consistent in 3.1.
- `Cache.get_index_history → list[dict]` consistent in 4.1 and 4.2.
- `beta()` return shape `{beta, alpha, r_squared, n}` consistent in 4.2 tests and impl.
- `compute_4quadrant_score()` return shape `{value, quality, momentum, trend, total, raw}` consistent in 5.1 tests, 5.2 model, and `QuadrantScoreResponse`.
- All new tool wrappers follow the `@mcp.tool() async def name(...) -> ModelResponse: return _name_impl(_cache, ...)` shape from analytics-v1.

**4. Constraint check:** Re-read user constraints:
- "Only PSX DPS endpoints already accessible" — Task 0.1 probes only `dps.psx.com.pk` paths starting from sub-tabs of `/company/<SYM>` already in use. No new domains, no scraping outside the PSX site.
- "No paid feeds, no third-party scrape" — confirmed; Phases 6 deferral list explicitly excludes Sarmaaya/Mettis/scstrade.
- "No SBP / PBS macro" — explicitly deferred to Part 3.
- Compliant.

**5. Reviewer-flagged items from analytics-v1 final review:**
- Screener layering (Task 1.1) ✅
- N+1 query (Task 1.2) ✅
- `sma20_gt_sma50` `is not None` check (Task 2.C) ✅
- `_get_market_summary_impl` summary None guard (Task 1.3) ✅
- `refreshed_at` UTC switch (Task 1.3) ✅
- LIMIT 500 cap → still hardcoded; documented as acceptable for now; making it a FilterSpec field is a Part-3 candidate.

---

## What this plan deliberately does NOT cover

These belong to a future Part-3 plan:

- **SBP macro feed** (policy rate, USD/PKR, CPI) — user reaffirmed "no scraping" constraint on 2026-05-24.
- **News + sentiment** — same constraint.
- **Earnings calendar** — needs Board Meetings sub-tab or separate `/board-meetings` endpoint; deferable to Phase 0 of Part-3.
- **Sector rotation tool** — `compute_sector_rotation()` ranking sectors by 3m/6m relative strength. Easy add but adds another `@mcp.tool()` — keep this plan tight.
- **Backtest (`simulate_basket`)** — depends on confirmed historical-price adjustment status. Phase-0 Q4 of analytics-v1 was "indeterminate"; revisit with a known corporate-action ex-date.
- **Long-horizon return ranking** (mean-reversion) — needs 3y/5y rank functions; trivial to add but out of scope here.
- **Configurable LIMIT 500 candidate cap** in screener — Part 3.
- **Headless-browser SPA scraping** if Phase 0 finds sub-tabs are not directly fetchable.

When Part 3 starts, **first** revisit Q4 of analytics-v1 (historical adjustment) with a confirmed corporate action — that unblocks the backtest path.
