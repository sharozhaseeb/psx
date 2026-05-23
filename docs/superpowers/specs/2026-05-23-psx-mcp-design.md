# PSX MCP Server — Design

**Date:** 2026-05-23
**Status:** Spec — awaiting user approval before implementation plan
**Owner:** sharozhaseeb1@gmail.com

## 1. Purpose

A locally-run MCP server that lets Claude (in Claude Code, Claude Desktop, or any MCP-capable client) research Pakistan Stock Exchange (PSX) securities and surface on-demand trading signals from a user-defined watchlist. Free data sources only; informational use only — not investment advice.

## 2. Constraints & non-goals

**Hard constraints**
- Free data only. PSX free feed is **15+ minutes delayed**. Any "live" framing is bounded by this.
- Single-user, localhost-only HTTP/SSE on `127.0.0.1:8765`.
- Web scraping is fragile — design must degrade gracefully when PSX changes HTML.

**Out of scope (explicit YAGNI)**
- Portfolio P&L tracking
- Backtesting engine
- Order placement / broker integration
- Web UI
- Multi-user / auth

## 3. Architecture

Single Python process running FastMCP over HTTP/SSE. Stateless request handlers; all state in SQLite (`data/psx.db`) and a JSON config (`data/watchlist.json`).

```
psx-mcp/
├── pyproject.toml
├── README.md
├── server.py                       # FastMCP entrypoint, tool registrations
├── src/psx_mcp/
│   ├── psx_client.py               # async httpx scraper
│   ├── cache.py                    # SQLite + TTL logic
│   ├── indicators.py               # RSI, MACD, SMA/EMA, Bollinger, vol z-score
│   ├── watchlist.py                # JSON load/save
│   ├── alerts.py                   # rule evaluation
│   ├── symbols.py                  # symbol master lookup/search
│   └── models.py                   # Pydantic types
├── data/                           # gitignored
│   ├── psx.db
│   ├── watchlist.json
│   ├── server.log
│   └── errors.log
└── tests/
    ├── fixtures/                   # captured HTML/JSON snapshots
    ├── test_psx_client.py
    ├── test_indicators.py
    ├── test_alerts.py
    └── test_cache.py
```

### Module boundaries
- `psx_client` is the **only** module that touches the network.
- `cache` is the **only** module that touches SQLite.
- `indicators` is pure math on numpy arrays — no I/O.
- `alerts` composes `cache + indicators + watchlist`.
- Tools in `server.py` are thin: validate input → call modules → return Pydantic models.

### Process model
`uv run python server.py` starts FastMCP on `http://127.0.0.1:8765/sse`. Optionally registered in Claude Code via `claude mcp add` so it can be auto-started.

## 4. MCP tool surface

### Market data
| Tool | Returns |
|---|---|
| `search_symbol(query)` | `list[SymbolMatch]` — fuzzy ticker/name match |
| `get_quote(symbol)` | `Quote` — last price, change, volume, day/52w H/L, timestamp |
| `get_market_summary()` | `MarketSummary` — KSE-100/30/ALLSHR + sector heatmap |
| `get_top_movers(kind, limit=10)` | `list[Mover]` — gainers/losers/volume |
| `get_history(symbol, from_date, to_date, interval="1d")` | `list[Bar]` — OHLCV; daily only on free data |

### Fundamentals
| Tool | Returns |
|---|---|
| `get_company_info(symbol)` | `CompanyInfo` |
| `get_fundamentals(symbol)` | `Fundamentals` — EPS, P/E, P/B, div yield, payout, ROE (where available) |
| `get_financials(symbol, period)` | `list[FinancialStatement]` — best-effort from PSX filings |

### Announcements & news
| Tool | Returns |
|---|---|
| `get_announcements(symbol?, since_days=7)` | `list[Announcement]` from `dps.psx.com.pk` |
| `get_news(symbol?, since_days=3)` | `list[NewsItem]` from Business Recorder + Profit Pakistan RSS |

### Watchlist & alerts
| Tool | Returns |
|---|---|
| `list_watchlist()` | `list[WatchEntry]` |
| `add_to_watchlist(symbol, notes?)` | `WatchEntry` |
| `remove_from_watchlist(symbol)` | `bool` |
| `set_alert_rule(symbol, rule)` | `AlertRule` |
| `list_alert_rules(symbol?)` | `list[AlertRule]` |
| `remove_alert_rule(rule_id)` | `bool` |
| `check_alerts(symbols?)` | `list[AlertHit]` — **on-demand scan** |

### Analysis helpers
| Tool | Returns |
|---|---|
| `compute_indicators(symbol, indicators, lookback_days=200)` | `dict[str, float\|list]` |
| `scan_volume_spikes(symbols?, multiplier=2.0, lookback_days=20)` | `list[VolumeSpike]` |
| `compare_symbols(symbols, metrics)` | `ComparisonTable` |

### Alert rule schema (in `watchlist.json`)
```json
{
  "id": "luck-rsi-oversold",
  "symbol": "LUCK",
  "type": "indicator",
  "condition": {"indicator": "rsi14", "op": "<", "value": 30},
  "active": true,
  "created_at": "2026-05-23"
}
```
Supported `type` values:
- `price` — condition on last price (e.g., `price > 800`)
- `indicator` — condition on a computed indicator (`rsi14`, `macd`, `sma50`, etc.)
- `volume` — condition on today's volume vs N-day average multiplier
- `announcement` — triggers when any new announcement appears for the symbol since the rule was last checked

Supported `op` values: `<`, `<=`, `>`, `>=`, `==`, `crosses_above`, `crosses_below`. `crosses_*` operators compare the latest two daily bars and trigger only on the bar that crossed.

All tool responses include a `disclaimer` string and, where useful, a `summary` string giving Claude a one-line interpretation alongside the structured data.

## 5. Data sources

| Source | URL pattern | Notes |
|---|---|---|
| PSX Data Portal — time series | `dps.psx.com.pk/timeseries/int/<SYMBOL>` | JSON; intraday + daily |
| PSX Data Portal — historical | `dps.psx.com.pk/historical/<SYMBOL>` | Daily OHLCV |
| PSX Market Watch | `dps.psx.com.pk/market-watch` | Full ~540-symbol snapshot in one request |
| PSX Symbol Master | `dps.psx.com.pk/symbols` | Refreshed weekly |
| PSX Company Profile | `psx.com.pk/psx/profile/<SYMBOL>` | HTML |
| PSX Announcements | `dps.psx.com.pk/announcements/companies` | Corporate actions |
| PSX Financials | `psx.com.pk/psx/quote/financial-information/<SYMBOL>` | HTML, best-effort |
| Business Recorder RSS | `brecorder.com/feed` | News, symbol-mention filtered |
| Profit Pakistan RSS | `profit.pakistantoday.com.pk/feed` | News, symbol-mention filtered |

**HTTP client:** one shared `httpx.AsyncClient` with realistic User-Agent, `Accept-Language: en-PK`, 10 s timeout, and a semaphore limiting concurrency to ~2 req/sec.

## 6. Storage

### SQLite schema (`data/psx.db`)
```sql
CREATE TABLE symbols (
  symbol TEXT PRIMARY KEY, name TEXT, sector TEXT,
  listed_shares INTEGER, refreshed_at TIMESTAMP
);
CREATE TABLE quotes (
  symbol TEXT, ts TIMESTAMP, price REAL, change REAL,
  volume INTEGER, day_high REAL, day_low REAL,
  fetched_at TIMESTAMP, PRIMARY KEY(symbol, ts)
);
CREATE TABLE bars_daily (
  symbol TEXT, date DATE, open REAL, high REAL, low REAL,
  close REAL, volume INTEGER, PRIMARY KEY(symbol, date)
);
CREATE TABLE announcements (
  id TEXT PRIMARY KEY, symbol TEXT, posted_at TIMESTAMP,
  title TEXT, category TEXT, url TEXT, body TEXT
);
CREATE TABLE fundamentals (
  symbol TEXT PRIMARY KEY, eps REAL, pe REAL, pb REAL,
  div_yield REAL, payout REAL, roe REAL, refreshed_at TIMESTAMP
);
CREATE TABLE news (
  id TEXT PRIMARY KEY, source TEXT, posted_at TIMESTAMP,
  title TEXT, url TEXT, symbols TEXT
);
CREATE INDEX idx_bars_symbol_date ON bars_daily(symbol, date DESC);
CREATE INDEX idx_anns_symbol_posted ON announcements(symbol, posted_at DESC);
```

### Cache TTLs

| Data type | TTL | Strategy |
|---|---|---|
| Symbol master | 7 days | Lazy on next call after TTL |
| Live quote | 5 min (data is 15-min delayed) | Lazy |
| Daily bars | Until end of trading day | Lazy, append-only |
| Announcements | 30 min | Lazy |
| Fundamentals | 1 day | Lazy |
| News RSS | 15 min | Lazy |
| Market snapshot | 5 min | Lazy — one fetch populates all ~540 quotes |

**Bulk-fetch optimisation:** `check_alerts` over many symbols first refreshes the market snapshot (one request), then only fetches history for symbols whose rules need it.

## 7. Error handling

- Every PSX fetch wrapped in `try/except` distinguishing `httpx.HTTPError` (network) from `ParseError` (HTML changed).
- Network error → return cached data if any with `stale: true`. Log to `data/errors.log`.
- Parse error → `null` for affected field, never fail the whole call. Log offending snippet.
- Hard fail only when no cache *and* network errored — return structured `ToolError`.
- Retry policy: 1 retry, 2 s backoff on 5xx/connection errors. No retry on 4xx.

## 8. Disclaimers

Every tool response involving prices, signals, or fundamentals includes:

> `disclaimer: "Informational only — not investment advice. Data is 15+ min delayed; verify before trading."`

The MCP server's own description (visible to Claude in the tool catalog) repeats this so Claude frames responses accordingly.

## 9. Testing

- **Unit tests on captured fixtures**, not network. Snapshot each PSX endpoint once into `tests/fixtures/`; parser tests assert structured output from them. This is the primary defence against silent scraper rot.
- **Indicator tests** against published reference values for RSI/MACD/Bollinger.
- **Cache tests** with `:memory:` SQLite — schema, TTL, append-only invariants.
- **Alert rule tests** with synthetic bar series — each rule type triggers exactly when it should.
- **One smoke test** that hits real PSX, gated by `PSX_LIVE=1` env var. Run locally; skipped in CI.
- Target: offline suite under 2 seconds. `pytest -q`.

## 10. Dependencies

Managed by `uv` via `pyproject.toml`:
- `mcp[cli]` — official MCP Python SDK (FastMCP)
- `httpx[http2]` — async HTTP client
- `beautifulsoup4` + `lxml` — HTML parsing
- `pandas` + `numpy` — bar math & indicator inputs
- `ta` (technical-analysis library) — RSI/MACD/Bollinger
- `feedparser` — RSS for news
- `pydantic>=2` — models
- `structlog` — JSON logs
- Dev: `pytest`, `pytest-asyncio`, `respx` (httpx mocking)

## 11. Registration

After install, register with Claude Code:

```bash
claude mcp add --transport sse psx http://127.0.0.1:8765/sse
```

A small `run-psx-mcp.ps1` script in the repo root starts the server with the right working dir and PYTHONPATH.

## 12. Open questions for future iterations

- Move to a paid feed (Mettis, broker FIX) for true real-time → unlocks tighter alerts.
- Background fetcher process (Approach B from brainstorming) if scraping latency becomes a bottleneck.
- Portfolio tracking (would need explicit user opt-in given compliance posture).
- Push notification surface (Windows toast, email) if on-demand alerts feel insufficient.
