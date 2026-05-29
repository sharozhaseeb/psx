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
| `set_alert_rule` / `list_alert_rules` / `remove_alert_rule` | rule mgmt — supports `type` in `{"price", "indicator", "volume", "fundamental"}`. New `"fundamental"` type triggers on PE / ROE / dividend-yield thresholds against cached fundamentals. |
| `check_alerts` | on-demand alert scan |
| `compute_indicators` | RSI/MACD/SMA/EMA/Bollinger/vol-z/ATR/Donchian/returns_window. **analytics-v4 adds:** `adx14` (trend strength), `stochastic` (%K/%D), `obv` (on-balance volume), `williams_r14` (oscillator). Omit `indicators` for default bundle: `sma20`, `sma50`, `sma200`, `rsi14`, `atr14`. |
| `compute_beta(symbol, index_code="KSE100", window=252)` | OLS beta of symbol vs index over date-aligned EOD returns |
| `compute_quality_score(symbol)` | composite quality score in [0, 1] — **2-signal (ROE + EPS trend), not the full 9-point Piotroski**. F-score deferred to Part 4 when balance-sheet items land. |
| `compute_4quadrant_score(symbol)` | Value / Quality / Momentum / Trend composite in [0, 4] (sub-scores + total). Response includes `warnings: list[str]` for silent-failure cases (e.g. missing fundamentals, insufficient history). |
| `compute_drawdown(symbol)` | current draw from rolling max + max trailing drawdown over cached daily closes |
| `compute_risk_metrics(symbol, rf_annual=0)` | annualized volatility, Sharpe ratio, and max drawdown from cached daily returns |
| `compute_relative_strength(symbol, index_code="KSE100", window=252)` | RS of symbol vs index over date-aligned EOD closes (last `window` overlapping days) |
| `compute_correlation(symbols)` | pairwise return correlation matrix across the supplied symbols (date-aligned closes) |
| `compute_position_size(symbol, portfolio_value, risk_pct=1.0, stop_atr_mult=2.0)` | ATR-based fixed-fractional position sizing — returns shares, rupee exposure, stop level |
| `rank_sectors(sectors?, by="avg_change_pct", desc=True)` | sector rotation table — ranks the 13 major PSX sectors (or a supplied subset) by `avg_change_pct` / `breadth_up` / `median_pe` |
| `rank_universe(by="composite", sector?, limit=20)` | cross-sectional top-N over the cached universe by `composite` / `change_pct` / `rsi14` / `pe` (optionally restricted to a sector) |
| `get_full_analysis(symbol)` | one-shot research dashboard composing quote, fundamentals, 52w, indicators, drawdown, risk, beta, RS, quadrant score, dividends, announcements; lifts `qs.warnings` into a top-level `warnings: list[str]` |
| `get_cache_status()` | per-table row count + freshness summary (last refresh timestamps across quotes / history / announcements / news / dividends / indices) |
| `refresh_universe(symbols?, sector?)` | bulk history refresh across an explicit symbol list or all symbols in a sector |
| `get_upcoming_events(lookback_days=14)` | title-pattern filter over cached announcements — Board Meeting / AGM / EGM / CBS / Ex-Date / Book Closure (heuristic; actual dates require PDF body extraction) |
| `list_watchlist_with_scores()` | watchlist entries joined with composite scores; each entry exposes per-symbol `warnings: list[str]` for silent-failure visibility |
| `backtest_simple(filter_spec, hold_days=63, since="2025-01-01")` | smoke-test backtest — applies a screener filter, holds matched names for `hold_days`, returns avg/median return vs KSE-100 (no transaction costs, no rebalancing, single entry — caveats documented in response) |
| `scan_volume_spikes` | volume-spike scanner |
| `compare_symbols` | side-by-side metric table; includes `change_pct` and `volume` from latest quote |
| `screen_symbols` | multi-criteria screener — filter by sector(s), PE, EPS, price, RSI, SMA stack, volume, turnover, **`roe_min`**, **`pb_max`**, **`div_yield_min`**; **analytics-v4 adds risk-adjusted filters: `sortino_min`, `calmar_min`, `max_dd_max_pct`**; sort + limit. Response includes `warnings: list[str]` for silent-failure cases (e.g. fundamentals filter requested but underlying column null). E.g. `screen_symbols(sector="TECHNOLOGY & COMMUNICATION", pe_max=15, roe_min=0.15, pb_max=3.0, above_sma200=True, sortino_min=1.0, max_dd_max_pct=30, sort_by="change_pct", desc=True, limit=20)` |
| `get_sector_summary` | sector-level aggregates: member count, breadth (% up / % above SMA200), median PE, top & bottom 5 by `change_pct` |
| **analytics-v4 — extended metric tools** | |
| `compute_return_stats(symbol, rolling_window_days=20)` | CAGR + win rate + rolling-N-day-return best/worst/median over cached daily closes |
| `compute_distribution_stats(symbol)` | return-distribution stats: skewness, excess kurtosis, 5% VaR, 5% CVaR, tail ratio |
| `compute_drawdown_details(symbol)` | drawdown deep-dive — max DD, peak/trough/recovery indices, durations, Ulcer Index, top-3 drawdowns |
| `compute_up_down_capture(symbol, index_code="KSE100")` | up/down capture ratios vs index (aggressive vs defensive profile) |
| `compute_cross_sectional_rank(symbol, metric="pe", scope="sector")` | z-score + percentile rank for `metric` within peer universe (`scope="sector"` or `"universe"`) |
| `get_sector_dispersion(sector, metric="pe")` | sector-wide dispersion (std / IQR) and outliers for `metric` |
| `rank_sector_relative_strength(sectors=None, window_days=60)` | sector RS vs KSE-100 over `window_days`, ranked across major PSX sectors |
| **`get_extended_risk_metrics(symbol)` — recommended one-shot dashboard** | composes return stats + distribution stats + drawdown deep-dive + up/down capture + cross-sectional rank into a single response. Preferred entry point for Part-4 analytics. |
| **analytics-v5 — qualitative real-world signals** | |
| `fetch_announcement_body(announcement_id)` | fetch + cache the PDF body of a PSX announcement on demand; sets `fetch_status` to one of `ok`/`http_error`/`scan_only`/`parse_error`/`no_url`/`not_found`/`no_client` |
| `bulk_fetch_announcement_bodies(symbol, since_days=30, limit=50)` | batch lazy-fetch announcement bodies for one symbol with throttling + per-status counters |
| `fetch_news_body(news_id)` | fetch + cache one news article body using per-host selectors (Dawn / Profit / Tribune / Brecorder) |
| `bulk_fetch_news_bodies(symbol, since_days=14, limit=50)` | batch lazy-fetch news bodies tagged with `symbol` |
| `get_insider_trades(symbol, since_days=365)` | director / insider transactions extracted from cached announcement bodies (buy/sell + qty + role + holding pct) |
| `get_earnings_calendar(symbol, lookback_days=30, forward_days=60)` | board meetings convened to consider financial results in window |
| `get_corporate_actions_calendar(symbol, lookback_days=30, forward_days=60)` | combined view: dividend events + board meetings for the symbol in window |
| `refresh_company_qualitative(symbol)` | first-time-setup convenience — chains refresh_announcements + refresh_news + bulk announcement-body + bulk news-body fetches for one symbol |
| **`get_company_research_pack(symbol, lookback_days=30)` — flagship LLM-companion tool** | structured + pre-concatenated markdown briefing of quote, fundamentals, quadrant score, announcement bodies, news bodies, insider trades, upcoming meetings/dividends; the `llm_briefing_text` field is what to hand Claude when asking "what's going on with X?" |

## Usage tips

- Call `refresh_market` before `check_alerts` for fresh quote-based rules.
- Indicator/volume rules need history — call `refresh_history` for watched symbols first.
- `data/psx.db` and `data/watchlist.json` persist between runs.
