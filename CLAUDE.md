# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A single Python project — `psx-mcp/` — that runs a local FastMCP server exposing PSX (Pakistan Stock Exchange) research tools over HTTP/SSE for a single user. Free-data only (15+ min delayed), local SQLite cache, on-demand alerts (no background poller). Everything else in the repo (`docs/superpowers/`) is the spec and implementation plan that produced it.

The full spec is at `docs/superpowers/specs/2026-05-23-psx-mcp-design.md`; the task-by-task TDD plan that built it is at `docs/superpowers/plans/2026-05-23-psx-mcp-implementation.md`. Read those before changing scope.

## Commands (run from `psx-mcp/`)

| Task | Command |
|---|---|
| Install / sync deps | `uv sync --extra dev` |
| Run full test suite (~70+ tests, offline) | `uv run pytest` |
| Run a single test file | `uv run pytest tests/test_alerts.py -v` |
| Run a single test | `uv run pytest tests/test_alerts.py::test_price_rule_triggers -v` |
| Live smoke test (hits real PSX) | `$env:PSX_LIVE="1"; uv run pytest tests/test_live.py` |
| Start the MCP server | `.\run-psx-mcp.ps1` (or `uv run python server.py`) |
| Re-capture PSX fixtures (rare) | `uv run python scripts/capture_fixtures.py` |
| Re-capture RSS fixtures (rare) | `uv run python scripts/capture_rss.py` |
| Register with Claude Code | `claude mcp add --transport sse psx http://127.0.0.1:8765/sse` |

Server listens on `http://127.0.0.1:8765/sse` — both host and port are pinned in `FastMCP(..., host="127.0.0.1", port=8765)`. FastMCP otherwise defaults to port 8000.

## Architecture — the load-bearing patterns

### 1. Module boundaries are strict
- `psx_client.py` is the **only** module that touches the network.
- `cache.py` is the **only** module that touches SQLite.
- `indicators.py` is pure math on `pd.Series` — no I/O.
- `df_utils.bars_df()` is the **single** helper that loads bars into a DataFrame; reuse it instead of inlining queries.
- `alerts.py` composes `cache + indicators + watchlist`.
- `server.py` is glue.

When adding a feature, place the network call in `psx_client`, the persistence in `cache`, and the math in `indicators` or a new pure-math module.

### 2. Tool = thin async wrapper around a sync `_impl` helper
Every `@mcp.tool()` in `server.py` follows this pattern:

```python
def _<name>_impl(cache: Cache, ...) -> Model:
    # actual logic, sync, fully testable
    ...

@mcp.tool()
async def <name>(...) -> Model:
    return _<name>_impl(_cache, ...)
```

Tests exercise the `_impl` helpers directly (see `tests/test_server.py`). **Never** add an `_async` helper or call `loop.run_until_complete` from a tool body — that was a known critic-flagged blocker. If a tool needs to await network I/O, the impl itself is `async def` and the tool body uses `return await _<name>_impl(...)`.

### 3. PSX endpoint URLs and methods differ from intuition
Fixture capture revealed these surprises — keep them in mind when editing `psx_client.py`:

- `fetch_historical` → **POST** `https://dps.psx.com.pk/historical` with `{symbol: SYM}` form body (not GET on `/historical/<SYM>`).
- `fetch_announcements` → **POST** `https://dps.psx.com.pk/announcements` with `{type: "C", offset: 0, count: 50}`.
- `fetch_profile` and `fetch_financials` → **GET** `https://dps.psx.com.pk/company/<SYM>` (same page; not on `www.psx.com.pk`).
- `fetch_market_watch` → GET `https://dps.psx.com.pk/market-watch` (HTML table, ~540 rows).
- `fetch_symbols` → GET `https://dps.psx.com.pk/symbols` (JSON; key is `sectorName`, not `sector`).

Parsers use `_try_json()` to handle either JSON or HTML payloads. Dates appear in mixed formats (`"May 22, 2026"`, `"2026-05-22"`); use `_parse_date_flex()` rather than ad-hoc parsing.

### 4. Tests run on captured fixtures, not the live network
`tests/fixtures/` holds real PSX HTML/JSON responses captured by `scripts/capture_fixtures.py`. Parser tests load those and assert structured output. When PSX changes shape and a test breaks, **re-capture fixtures and adapt the parser to match the real shape** — do not weaken the test. The one exception is `tests/test_live.py`, gated behind `PSX_LIVE=1`, which makes a real request.

### 5. Pydantic v2 validators must be classmethods, not lambdas
Every model in `models.py` that needs to uppercase its `symbol` field uses:

```python
@field_validator("symbol", mode="before")
@classmethod
def _u(cls, v):
    return v.strip().upper() if isinstance(v, str) else v
```

The lambda-wrapping form (`field_validator("x")(lambda cls, v: ...)`) raises `PydanticUserError` in Pydantic v2.

### 6. SQLite timestamps are ISO TEXT strings
`cache.py` deliberately does **not** pass `detect_types=sqlite3.PARSE_DECLTYPES` — Python 3.12 deprecates the default `timestamp` converter. All timestamps round-trip through `_iso()` and `datetime.fromisoformat()` explicitly.

### 7. Disclaimer is structural, not decorative
Models in `models.py` that surface market data inherit from `Disclaimer`, which adds `disclaimer: str = DEFAULT_DISCLAIMER`. Don't strip the disclaimer field from response models — it's the project's compliance posture ("informational only — not investment advice; 15+ min delayed").

### 8. `last_crosses(a, b, op)` checks ONLY the latest bar
A previous bug had it scan the entire series and return True for any historical cross — which would make alert rules fire continuously. The correct semantic compares `iloc[-2]` vs. `iloc[-1]`. Tests in `test_indicators.py` lock this in.

## Adding a new MCP tool

1. Add the response model to `src/psx_mcp/models.py` (inherit `Disclaimer` if it surfaces market data).
2. If new persistence is needed, extend `cache.py` (it owns the SQLite connection).
3. If new network calls are needed, extend `psx_client.py` (`PSXClient.fetch_*` returning `str` plus a `parse_*` function).
4. Write the sync `_<name>_impl(cache, ...)` helper in `server.py` and a test against it in `tests/test_server.py` using the existing `deps` / `deps_with_client` fixtures.
5. Add the `@mcp.tool() async def <name>(...)` wrapper at the bottom of the `server.py` tools section.
6. Update the tool table in `psx-mcp/README.md`.

## Operational notes

- The server is one process; state lives in `data/psx.db` (SQLite) and `data/watchlist.json`. Both are gitignored. Deleting them resets the cache; the next call will re-fetch.
- Cache TTLs (per spec §6): quotes 5 min, market snapshot 5 min, daily bars until end of day, fundamentals 1 day, announcements 30 min, news RSS 15 min, symbol master 7 days. Tools assume callers run `refresh_*` first when freshness matters.
- `scripts/probe_*.py` are throwaway exploratory scripts used while reverse-engineering PSX endpoints — keep them around for reference but don't depend on them.

## What's explicitly out of scope (per spec §2)
Portfolio P&L tracking, backtesting, order placement, web UI, multi-user / auth. Don't add these without revising the spec first.
