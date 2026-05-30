# stocks

A personal workspace for PSX (Pakistan Stock Exchange) research tooling.

The only deliverable so far is **[psx-mcp](psx-mcp/)** — a local FastMCP server that exposes PSX research and on-demand alert tools to Claude (or any MCP-capable client). Free data sources only; everything 15+ minutes delayed; informational use only.

## What you can do with it

Once registered with Claude Code, you can ask things like:

- *"Refresh the market and show me the top 5 gainers."*
- *"Analyze SYS — quote, fundamentals, recent technicals, any open filings."*
- *"Compare LUCK and DGKC on price, P/E, RSI(14), and 50-day SMA."*
- *"Add OGDC to my watchlist and alert me if RSI(14) drops below 30."*
- *"What's going on with NETSOL?"* → `get_company_research_pack("NETSOL")` returns a markdown briefing combining quote, fundamentals, quadrant score, announcement bodies, news bodies, insider trades, and upcoming meetings.

The server exposes **63 tools** across five analytics tiers — see [`psx-mcp/README.md`](psx-mcp/README.md) for the full tool list.

| Tier | Focus | Headline tools |
|---|---|---|
| **analytics-v1** | Market data, quotes, watchlists, alerts | `get_quote`, `compute_indicators`, `set_alert_rule`, `check_alerts` |
| **analytics-v2** | Sector rotation, screening, composite scores | `screen_symbols`, `rank_universe`, `compute_4quadrant_score`, `get_full_analysis` |
| **analytics-v3** | Fundamentals history, dividends, sector summary | `refresh_fundamentals`, `refresh_dividends`, `get_sector_summary`, `backtest_simple` |
| **analytics-v4** | Risk/return deep-dive (Sortino, Calmar, capture ratios, sector RS) | `get_extended_risk_metrics`, `compute_distribution_stats`, `compute_drawdown_details`, `rank_sector_relative_strength` |
| **analytics-v5** | Qualitative real-world signals (PDF/news bodies, insider trades, calendars) | `get_company_research_pack` ⭐, `get_insider_trades`, `get_earnings_calendar`, `refresh_company_qualitative` |

⭐ `get_company_research_pack(symbol)` is the flagship LLM-companion tool — its `llm_briefing_text` field is a pre-concatenated markdown briefing meant to be handed to Claude directly.

## Quick start

```powershell
# 1. Install dependencies
cd psx-mcp
uv sync --extra dev

# 2. One-time: capture PSX endpoint fixtures (used by tests)
uv run python scripts/capture_fixtures.py
uv run python scripts/capture_rss.py

# 3. Run the server (listens on http://127.0.0.1:8765/sse)
.\run-psx-mcp.ps1

# 4. In another shell, register with Claude Code
claude mcp add --transport sse psx http://127.0.0.1:8765/sse
```

Now talk to Claude. The MCP shows up as `psx` in `claude mcp list`.

## Project layout

```
stocks/
├── CLAUDE.md                          # Guidance for future Claude Code sessions
├── README.md                          # You are here
├── docs/superpowers/
│   ├── specs/                         # Design specs (one per major decision)
│   └── plans/                         # Implementation plans driven from specs
└── psx-mcp/                           # The MCP server itself
    ├── server.py                      # FastMCP entrypoint
    ├── src/psx_mcp/                   # Library code
    ├── tests/                         # Fixture-driven tests (+ one gated live test)
    ├── scripts/                       # Fixture capture + endpoint-probing utilities
    └── README.md                      # Server-specific docs + tool table
```

## How it was built

This repo was built spec-first, then plan-first, then iteratively expanded in five tagged analytics releases:

1. **Spec** — `docs/superpowers/specs/2026-05-23-psx-mcp-design.md` — scope, architecture, tool surface, storage, error handling, testing strategy.
2. **Plans** — `docs/superpowers/plans/` — one plan per release (`analytics-v1` through `analytics-v5`); each plan is a sequence of TDD tasks with failing tests and exact code shown.
3. **Implementation** — executed task-by-task via fresh subagents per task with two-stage review (spec compliance + code quality), with parallel critic-pass reviews of each plan before execution starts.

Each release is an annotated git tag (`git tag -l "analytics*"`). The plans remain the authoritative scope reference — if you're considering a change, read the relevant plan first.

**Test suite:** 290 passing, 4 live-network smoke tests gated behind `PSX_LIVE=1`.

## Disclaimer

This tooling is for personal research only. Free PSX data is **delayed by 15+ minutes**, parsers are best-effort against an undocumented website, and the project explicitly does not handle portfolio P&L, backtesting, or order placement. Verify any figure against the official PSX filing before making a trading decision. Not investment advice.
