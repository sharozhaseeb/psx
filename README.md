# stocks

A personal workspace for PSX (Pakistan Stock Exchange) research tooling.

The only deliverable so far is **[psx-mcp](psx-mcp/)** — a local FastMCP server that exposes PSX research and on-demand alert tools to Claude (or any MCP-capable client). Free data sources only; everything 15+ minutes delayed; informational use only.

## What you can do with it

Once registered with Claude Code, you can ask things like:

- *"Refresh the market and show me the top 5 gainers."*
- *"Analyze SYS — quote, fundamentals, recent technicals, any open filings."*
- *"Compare LUCK and DGKC on price, P/E, RSI(14), and 50-day SMA."*
- *"Add OGDC to my watchlist and alert me if RSI(14) drops below 30."*
- *"Check my alerts."*

The server exposes ~24 tools across market data, fundamentals, announcements, news, watchlists, alert rules, and indicator/scan helpers. See [`psx-mcp/README.md`](psx-mcp/README.md) for the full tool list.

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

This repo was built spec-first, then plan-first:

1. **Spec** — `docs/superpowers/specs/2026-05-23-psx-mcp-design.md` — scope, architecture, tool surface, storage, error handling, testing strategy.
2. **Plan** — `docs/superpowers/plans/2026-05-23-psx-mcp-implementation.md` — 18 TDD tasks, each with failing tests written first and exact code shown.
3. **Implementation** — executed task-by-task via fresh subagents per task with two-stage review (spec compliance + code quality).

Both documents are versioned in git and remain the authoritative scope reference. If you're considering a change, read the spec first.

## Disclaimer

This tooling is for personal research only. Free PSX data is **delayed by 15+ minutes**, parsers are best-effort against an undocumented website, and the project explicitly does not handle portfolio P&L, backtesting, or order placement. Verify any figure against the official PSX filing before making a trading decision. Not investment advice.
