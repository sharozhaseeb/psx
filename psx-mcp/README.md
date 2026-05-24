# PSX MCP Server

Local MCP server exposing PSX (Pakistan Stock Exchange) research tools and on-demand alerts.

**Data is 15+ minutes delayed.** Informational only — not investment advice.

## Install

    cd C:\Users\pc\work\stocks\psx-mcp
    uv sync --extra dev

## Capture fixtures (first time only)

    uv run python scripts/capture_fixtures.py
    uv run python scripts/capture_rss.py

## Run

    .\run-psx-mcp.ps1

Server listens on `http://127.0.0.1:8765/sse`.

## Register with Claude Code

    claude mcp add --transport sse psx http://127.0.0.1:8765/sse

## Test

    uv run pytest

Live smoke test (gated, hits real PSX):

    $env:PSX_LIVE="1"; uv run pytest tests/test_live.py

## Tools

| Tool | Purpose |
|---|---|
| `search_symbol` | fuzzy match on ticker, company name, and sector |
| `get_quote` | latest cached quote (includes 52w high/low computed from history) |
| `get_history` | daily OHLCV from cache |
| `get_market_summary` | KSE-100 / KSE-30 / All-Share snapshot (populated from cached indices). UTC timestamps; summary string is None-safe when index data is missing. |
| `get_top_movers` | gainers/losers/volume |
| `refresh_market` | force-pull market snapshot. Refreshes index snapshot **and** stamps per-index EOD bars into `indices_history` from `/timeseries/eod`. |
| `refresh_history` | force-pull history for one symbol |
| `refresh_announcements` | force-pull announcements |
| `refresh_news` | force-pull RSS feeds |
| `refresh_dividends(symbol)` | fetch & cache dividend history from PSX `/company/payouts` (one row per ex-date) |
| `get_announcements` | cached corporate announcements (incl. PSX detail URL; body text deferred) |
| `get_news` | cached news, filterable by symbol |
| `get_dividend_history(symbol)` | cached dividend events, newest ex-date first. Populated by `refresh_dividends`. |
| `get_company_info` | profile + listed shares |
| `get_fundamentals` | EPS, P/E, P/B, etc. |
| `get_fundamentals_history(symbol)` | cached per-fiscal-year fundamentals, newest year first. Populated by Part-3 `refresh_fundamentals`. |
| `get_financials` | annual/quarterly statements (best-effort) |
| `get_index_history(index_code, since=None)` | EOD index time series (`KSE100` / `KSE30` / `ALLSHR`). Populated by `refresh_market`. |
| `list_watchlist` / `add_to_watchlist` / `remove_from_watchlist` | watchlist mgmt |
| `set_alert_rule` / `list_alert_rules` / `remove_alert_rule` | rule mgmt |
| `check_alerts` | on-demand alert scan |
| `compute_indicators` | RSI/MACD/SMA/EMA/Bollinger/vol-z/ATR/Donchian/returns_window. Omit `indicators` for default bundle: `sma20`, `sma50`, `sma200`, `rsi14`, `atr14`. |
| `compute_beta(symbol, index_code="KSE100", window=252)` | OLS beta of symbol vs index over date-aligned EOD returns |
| `compute_quality_score(symbol)` | composite quality score in [0, 1] from ROE + EPS trend |
| `compute_4quadrant_score(symbol)` | Value / Quality / Momentum / Trend composite in [0, 4] (sub-scores + total) |
| `scan_volume_spikes` | volume-spike scanner |
| `compare_symbols` | side-by-side metric table; includes `change_pct` and `volume` from latest quote |
| `screen_symbols` | multi-criteria screener — filter by sector(s), PE, EPS, price, RSI, SMA stack, volume, turnover, **`roe_min`**, **`pb_max`**, **`div_yield_min`**; sort + limit. E.g. `screen_symbols(sector="TECHNOLOGY & COMMUNICATION", pe_max=15, roe_min=0.15, pb_max=3.0, above_sma200=True, sort_by="change_pct", desc=True, limit=20)` |
| `get_sector_summary` | sector-level aggregates: member count, breadth (% up / % above SMA200), median PE, top & bottom 5 by `change_pct` |

## Usage tips

- Call `refresh_market` before `check_alerts` for fresh quote-based rules.
- Indicator/volume rules need history — call `refresh_history` for watched symbols first.
- `data/psx.db` and `data/watchlist.json` persist between runs.
