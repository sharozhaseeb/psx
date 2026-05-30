# PSX MCP Analytics Upgrade — Part 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the remaining gaps that prevent the PSX MCP from being a complete investing companion: risk metrics (drawdown, vol, Sharpe, correlation), cross-sectional ranking (sector rotation, universe top-N), a unified per-symbol dashboard, position sizing, operational ergonomics (bulk refresh, cache freshness, upcoming events, watchlist scores), fundamental alert rules, silent-failure warnings, naming honesty, and a minimal backtest primitive.

**Architecture:** Same as Parts 1+2 — async `@mcp.tool()` wrappers over sync `_<name>_impl(cache, ...)` helpers. New pure-function modules `risk.py`, `ranking.py`, `backtest.py`. Cache gains a freshness-summary helper. No new external dependencies.

**Tech Stack:** Python 3.12, FastMCP, SQLite, httpx, pytest, uv. No new deps.

**Constraints (carried forward):**
- Only `dps.psx.com.pk` endpoints already in use.
- No paid feeds, no third-party scrape, no SBP/PBS macro, no news/sentiment models.
- Additive only — no removed fields, no renamed tools (existing renames blocked).
- Backwards-compatible response shapes.

---

## What's deliberately deferred to Part 4

Per Phase 0 of Part 2:
- **ROE / P/B / payout / current_ratio population** — Ratios sub-tab is SPA-rendered; needs headless browser.
- **Real 9-signal Piotroski F-Score** — balance-sheet line items unavailable without the above.
- **Macro feed** — SBP scraping forbidden.
- **News sentiment** — same constraint.

This plan calls out where the missing data limits a tool's usefulness rather than pretending it doesn't.

---

## File Structure

### Time-series ordering conventions (carried from Part 2)

| Method | Order |
|---|---|
| `Cache.closes_for(symbol)` | oldest first |
| `Cache.closes_for_many(symbols)` | oldest first per symbol |
| `Cache.get_index_history(code)` | oldest first |
| `Cache.get_fundamentals_history(symbol)` | newest year first |
| `Cache.get_dividend_history(symbol)` | newest ex-date first |

### New files

| Path | Responsibility |
|---|---|
| `psx-mcp/src/psx_mcp/risk.py` | Pure functions: `drawdown_current`, `drawdown_max`, `volatility_annualized`, `sharpe`, `relative_strength`, `correlation_matrix`. No I/O. |
| `psx-mcp/src/psx_mcp/ranking.py` | Pure-ish helpers: `rank_sectors(cache, by, sectors)`, `rank_universe(cache, by, sector, limit)`. Pull from cache, sort, return list. |
| `psx-mcp/src/psx_mcp/backtest.py` | Pure function: `backtest_simple(price_history_by_symbol, filter_passes_by_date, hold_days, weights="equal") -> {trades, returns, summary}`. |
| `psx-mcp/tests/test_risk.py` | Tests against `risk.py` with synthetic series. |
| `psx-mcp/tests/test_ranking.py` | Tests against `ranking.py` with seeded caches. |
| `psx-mcp/tests/test_backtest.py` | Tests against `backtest.py` with synthetic price series. |
| `psx-mcp/tests/test_dashboard.py` | Integration tests for `get_full_analysis`. |

### Modified files

| Path | What changes |
|---|---|
| `psx-mcp/src/psx_mcp/cache.py` | New methods: `closes_for_with_dates(symbol)` (paves over the Part-2 raw-SQL TODO), `cache_status() -> dict` summarizing row counts + freshness per table, `bars_dates_for(symbols)` if needed by backtest. |
| `psx-mcp/src/psx_mcp/models.py` | New models: `DrawdownResponse`, `RiskMetricsResponse`, `RelativeStrengthResponse`, `CorrelationMatrixResponse`, `SectorRankResponse`, `UniverseRankResponse`, `FullAnalysisResponse`, `PositionSizeResponse`, `BulkRefreshResponse`, `CacheStatusResponse`, `UpcomingEventsResponse`, `WatchlistWithScores`, `BacktestResponse`. Extend `AlertCondition` to support fundamental metrics. |
| `psx-mcp/src/psx_mcp/alerts.py` | New rule type `fundamental` (PE/ROE/div_yield). Update `evaluate_rule` dispatch. |
| `psx-mcp/src/psx_mcp/screener.py` | Add `warnings: list[str]` to screen output (e.g., "12 symbols skipped: insufficient bars"). |
| `psx-mcp/server.py` | New impls + tools: `compute_drawdown`, `compute_risk_metrics`, `compute_relative_strength`, `compute_correlation`, `rank_sectors`, `rank_universe`, `get_full_analysis`, `compute_position_size`, `refresh_universe`, `get_cache_status`, `get_upcoming_events`, `list_watchlist_with_scores`, `backtest_simple`. Update `_compute_4quadrant_score_impl` to populate `warnings`. Refactor `_compute_beta_impl` to use new `closes_for_with_dates` (resolves Part-2 TODO). |
| `psx-mcp/tests/test_server.py`, `test_alerts.py`, `test_cache.py`, `test_screener.py` | Tests for each new path. |
| `psx-mcp/README.md` | Tool table updates for all new tools. |
| `docs/investing-playbook.md` | Mark resolved Part-1 gaps. Add "Part-4 outlook" note. |

---

## Phase 1 — Risk metrics module

### Task 1.1: Build `risk.py` with pure-function primitives

**Files:**
- Create: `psx-mcp/src/psx_mcp/risk.py`
- Create: `psx-mcp/tests/test_risk.py`

- [ ] **Step 1: Failing pure-function tests**

```python
# psx-mcp/tests/test_risk.py
import pytest
import pandas as pd
import numpy as np
from psx_mcp.risk import (
    drawdown_current, drawdown_max,
    volatility_annualized, sharpe,
    relative_strength, correlation_matrix,
)


def test_drawdown_current_at_all_time_high_is_zero():
    closes = pd.Series([100.0, 101.0, 102.0, 105.0])
    dd = drawdown_current(closes)
    assert dd["drawdown_pct"] == pytest.approx(0.0)
    assert dd["peak"] == pytest.approx(105.0)


def test_drawdown_current_below_peak_is_negative():
    closes = pd.Series([100.0, 110.0, 105.0])  # peak 110, now 105 → -4.55%
    dd = drawdown_current(closes)
    assert dd["drawdown_pct"] == pytest.approx(-4.5454545, abs=1e-4)
    assert dd["peak"] == pytest.approx(110.0)


def test_drawdown_current_empty_returns_zero():
    """Defensive: empty series → safe defaults rather than crash."""
    dd = drawdown_current(pd.Series([], dtype=float))
    assert dd["drawdown_pct"] == 0.0
    assert dd["peak"] is None


def test_drawdown_max_known_trajectory():
    # 100 → 120 (peak) → 80 (max DD here = -33.33%) → 110
    closes = pd.Series([100.0, 120.0, 80.0, 110.0])
    out = drawdown_max(closes)
    assert out["max_drawdown_pct"] == pytest.approx(-33.3333, abs=1e-3)
    # Trough index = 2 (the 80), peak index = 1 (the 120)
    assert out["peak_index"] == 1
    assert out["trough_index"] == 2


def test_volatility_annualized_constant_series_is_zero():
    closes = pd.Series([100.0] * 30)
    assert volatility_annualized(closes) == pytest.approx(0.0)


def test_volatility_annualized_uses_252_factor():
    """Daily returns with stdev 0.01 should annualize to ~0.01*sqrt(252) ≈ 15.87%."""
    rng = np.random.default_rng(42)
    # Build series whose pct_change has stdev ≈ 0.01
    pcts = rng.normal(loc=0.0, scale=0.01, size=500)
    closes = pd.Series(np.exp(np.cumsum(pcts)))
    v = volatility_annualized(closes)
    assert 0.10 < v < 0.25  # loose band; deterministic with seed


def test_sharpe_zero_rf_on_positive_drift():
    """Series with positive drift and modest vol → positive Sharpe."""
    rng = np.random.default_rng(7)
    pcts = rng.normal(loc=0.001, scale=0.01, size=500)  # +25%/yr drift, 16% vol
    closes = pd.Series(np.exp(np.cumsum(pcts)))
    s = sharpe(closes, rf_annual=0.0)
    assert s > 0


def test_sharpe_returns_none_on_zero_vol():
    """Constant series → undefined Sharpe → None (not inf, not crash)."""
    closes = pd.Series([100.0] * 30)
    assert sharpe(closes, rf_annual=0.0) is None


def test_relative_strength_identical_to_index_is_zero():
    """If stock returns == index returns over the window, RS = 0%."""
    idx = pd.Series([100.0 + i for i in range(100)])
    stock = idx.copy()
    rs = relative_strength(stock, idx, window=60)
    assert rs == pytest.approx(0.0, abs=1e-6)


def test_relative_strength_stock_outperforms_returns_positive():
    """Stock returns 30% while index returns 10% → RS = +20%."""
    # Build constant-rate series
    idx = pd.Series([100.0 * (1.10 ** (i / 252)) for i in range(253)])  # 10% over 1yr
    stock = pd.Series([100.0 * (1.30 ** (i / 252)) for i in range(253)])  # 30% over 1yr
    rs = relative_strength(stock, idx, window=252)
    # Both grew at constant compounded rates from same start; over 252 trading days
    # the stock is up ~30% and index ~10% → RS ≈ +20%.
    assert 0.18 < rs < 0.22


def test_relative_strength_insufficient_history_returns_none():
    short = pd.Series([100.0, 101.0])
    assert relative_strength(short, short, window=60) is None


def test_correlation_matrix_identical_series_are_1():
    a = pd.Series([100.0 + i for i in range(50)])
    out = correlation_matrix({"A": a, "B": a.copy()})
    assert out["A"]["B"] == pytest.approx(1.0)
    assert out["B"]["A"] == pytest.approx(1.0)
    assert out["A"]["A"] == pytest.approx(1.0)


def test_correlation_matrix_handles_short_or_missing_series():
    """Symbols with < 2 returns yield None in the matrix, not a crash."""
    a = pd.Series([100.0 + i for i in range(50)])
    short = pd.Series([100.0])
    out = correlation_matrix({"A": a, "SHORT": short})
    assert out["A"]["SHORT"] is None
    assert out["SHORT"]["A"] is None
```

- [ ] **Step 2: Run, confirm ModuleNotFoundError**

Run: `uv run pytest tests/test_risk.py -v` with `timeout=60000`.

- [ ] **Step 3: Implement `psx-mcp/src/psx_mcp/risk.py`**

```python
"""Pure-function risk and relative-performance primitives.
Inputs are pandas Series of closes (oldest first). No I/O, no caching."""
from __future__ import annotations
from typing import Optional
import math
import pandas as pd
import numpy as np


TRADING_DAYS = 252


def drawdown_current(closes: pd.Series) -> dict:
    """Current drawdown from running peak.

    Returns:
      {drawdown_pct: float (≤ 0), peak: float|None, current: float|None}.
      drawdown_pct is 0.0 at all-time high.
    """
    if closes is None or len(closes) == 0:
        return {"drawdown_pct": 0.0, "peak": None, "current": None}
    peak = float(closes.max())
    current = float(closes.iloc[-1])
    if peak <= 0:
        return {"drawdown_pct": 0.0, "peak": peak, "current": current}
    return {
        "drawdown_pct": float((current / peak - 1.0) * 100.0),
        "peak": peak,
        "current": current,
    }


def drawdown_max(closes: pd.Series) -> dict:
    """Maximum drawdown over the entire series.

    Returns:
      {max_drawdown_pct: float (≤ 0), peak_index: int|None, trough_index: int|None}.
      max_drawdown_pct is 0.0 on a strictly non-decreasing series.
    """
    if closes is None or len(closes) < 2:
        return {"max_drawdown_pct": 0.0, "peak_index": None, "trough_index": None}
    values = closes.reset_index(drop=True)
    running_max = values.cummax()
    dd = (values / running_max - 1.0) * 100.0
    trough_pos = int(dd.idxmin())
    # Peak is the running_max value at the trough → find its first occurrence ≤ trough_pos
    peak_val = float(running_max.iloc[trough_pos])
    # Earliest index where the cumulative max reached peak_val
    peak_pos = int(values.iloc[:trough_pos + 1].idxmax())
    return {
        "max_drawdown_pct": float(dd.min()),
        "peak_index": peak_pos,
        "trough_index": trough_pos,
    }


def volatility_annualized(closes: pd.Series) -> float:
    """Annualized stdev of daily log returns (returns 0.0 if < 2 closes)."""
    if closes is None or len(closes) < 2:
        return 0.0
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    return float(rets.std(ddof=1) * math.sqrt(TRADING_DAYS))


def sharpe(closes: pd.Series, rf_annual: float = 0.0) -> Optional[float]:
    """Sharpe ratio over the available history.
    rf_annual is the annual risk-free rate (e.g., 0.22 for 22% in Pakistan).
    Returns None if volatility is zero or series too short."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    daily_rf = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    excess = rets - daily_rf
    sd = float(rets.std(ddof=1))
    if sd == 0:
        return None
    return float(excess.mean() / sd * math.sqrt(TRADING_DAYS))


def relative_strength(stock_closes: pd.Series, index_closes: pd.Series,
                       window: int = 252) -> Optional[float]:
    """Stock return − index return over the last `window` bars (as decimal).
    Both inputs must already be date-aligned; we align by tail position.
    Returns None if either series is shorter than `window + 1`."""
    if stock_closes is None or index_closes is None:
        return None
    if len(stock_closes) < window + 1 or len(index_closes) < window + 1:
        return None
    stock_start = float(stock_closes.iloc[-window - 1])
    stock_end = float(stock_closes.iloc[-1])
    idx_start = float(index_closes.iloc[-window - 1])
    idx_end = float(index_closes.iloc[-1])
    if stock_start <= 0 or idx_start <= 0:
        return None
    stock_ret = stock_end / stock_start - 1.0
    idx_ret = idx_end / idx_start - 1.0
    return float(stock_ret - idx_ret)


def correlation_matrix(closes_by_symbol: dict[str, pd.Series]) -> dict[str, dict[str, Optional[float]]]:
    """Pairwise Pearson correlation of daily returns across symbols.
    Symbols with < 2 returns produce None entries (not crashes).
    Returns nested dict: {sym_a: {sym_b: corr_or_None, ...}, ...}."""
    syms = list(closes_by_symbol.keys())
    returns: dict[str, pd.Series] = {}
    for s in syms:
        if closes_by_symbol[s] is None or len(closes_by_symbol[s]) < 2:
            returns[s] = pd.Series(dtype=float)
        else:
            returns[s] = closes_by_symbol[s].pct_change().dropna().reset_index(drop=True)
    out: dict[str, dict[str, Optional[float]]] = {}
    for a in syms:
        out[a] = {}
        for b in syms:
            if len(returns[a]) < 2 or len(returns[b]) < 2:
                out[a][b] = None
                continue
            n = min(len(returns[a]), len(returns[b]))
            ra = returns[a].iloc[-n:].values
            rb = returns[b].iloc[-n:].values
            if np.std(ra) == 0 or np.std(rb) == 0:
                out[a][b] = None
                continue
            out[a][b] = float(np.corrcoef(ra, rb)[0, 1])
    return out
```

- [ ] **Step 4: Run, confirm 12 passed**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/risk.py psx-mcp/tests/test_risk.py
git commit -m "feat(psx-mcp): risk.py — drawdown, vol, Sharpe, relative strength, correlation"
```

---

### Task 1.2: Add `Cache.closes_for_with_dates(symbol)` + refactor `_compute_beta_impl`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py` — add helper
- Modify: `psx-mcp/server.py` — refactor `_compute_beta_impl` to use it (resolves Part-2 TODO)
- Test: `psx-mcp/tests/test_cache.py`

- [ ] **Step 1: Failing test**

```python
def test_closes_for_with_dates_returns_ordered_pairs(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=4 - i),
                open=100.0, high=110.0, low=90.0, close=100.0 + i, volume=1000)
            for i in range(5)]
    cache.upsert_bars(bars)
    out = cache.closes_for_with_dates("XYZ")
    assert len(out) == 5
    # Oldest first by date
    dates = [d for d, _ in out]
    assert dates == sorted(dates)
    # Close values match the seed
    closes = [c for _, c in out]
    assert closes == [100.0, 101.0, 102.0, 103.0, 104.0]
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement in `cache.py`**

```python
def closes_for_with_dates(self, symbol: str) -> list[tuple[str, float]]:
    """Return [(iso_date, close), ...] for symbol, oldest first."""
    rows = self.conn.execute(
        "SELECT date, close FROM bars_daily WHERE symbol=? ORDER BY date ASC",
        (symbol.upper(),),
    ).fetchall()
    return [(r["date"], r["close"]) for r in rows]
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Refactor `_compute_beta_impl` in `server.py`**

Find the existing block that does `cache.conn.execute("SELECT date, close FROM bars_daily ...")`. Replace with `cache.closes_for_with_dates(symbol)`:

```python
def _compute_beta_impl(cache: Cache, symbol: str,
                       index_code: str = "KSE100",
                       window: int = 252) -> BetaResponse:
    stock_pairs = cache.closes_for_with_dates(symbol)
    stock_by_date = dict(stock_pairs)
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
    idx_closes = pd.Series([idx_by_date[d] for d in common_dates])
    result = beta(stock_closes=stock_closes, index_closes=idx_closes, window=window)
    return BetaResponse(
        symbol=symbol.upper(), index_code=index_code, window=window,
        beta=result["beta"], alpha=result["alpha"],
        r_squared=result["r_squared"], n=result["n"],
        note=None,
    )
```

(The TODO comment about raw SQL in `_compute_beta_impl` is now removed since the helper exists.)

- [ ] **Step 6: Run beta tests**

```
uv run pytest tests/test_beta.py tests/test_server.py -k beta -v
```
Use `timeout=120000`. Expected: all green (no regression).

- [ ] **Step 7: Commit**

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/server.py psx-mcp/tests/test_cache.py
git commit -m "refactor(psx-mcp): closes_for_with_dates helper; remove raw SQL from beta impl"
```

---

### Task 1.3: MCP tools `compute_drawdown`, `compute_risk_metrics`, `compute_relative_strength`, `compute_correlation`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — 4 new response models
- Modify: `psx-mcp/server.py` — 4 impls + 4 wrappers
- Test: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add models to `models.py`**

```python
class DrawdownResponse(Disclaimer):
    symbol: str
    drawdown_pct: float
    max_drawdown_pct: float
    peak: Optional[float] = None
    current: Optional[float] = None
    note: Optional[str] = None


class RiskMetricsResponse(Disclaimer):
    symbol: str
    volatility_annualized: float
    sharpe: Optional[float] = None
    max_drawdown_pct: float
    n_bars: int
    rf_annual: float = 0.0
    note: Optional[str] = None


class RelativeStrengthResponse(Disclaimer):
    symbol: str
    index_code: str
    window: int
    relative_strength_pct: Optional[float] = None
    stock_return_pct: Optional[float] = None
    index_return_pct: Optional[float] = None
    n_bars: int
    note: Optional[str] = None


class CorrelationMatrixResponse(Disclaimer):
    symbols: list[str]
    matrix: dict[str, dict[str, Optional[float]]]
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_compute_drawdown_with_seeded_bars(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    closes = [100.0, 120.0, 80.0, 110.0]  # peak 120, max DD -33.33%, current down from peak
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=3 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_drawdown_impl(cache, "XYZ")
    assert out.peak == 120.0
    assert out.current == 110.0
    assert out.drawdown_pct == pytest.approx(-8.3333, abs=1e-3)
    assert out.max_drawdown_pct == pytest.approx(-33.3333, abs=1e-3)


def test_compute_risk_metrics_seeded(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    import numpy as np
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    rng = np.random.default_rng(42)
    pcts = rng.normal(loc=0.0008, scale=0.012, size=300)
    closes = list(np.exp(np.cumsum(pcts)) * 100.0)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=299 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_risk_metrics_impl(cache, "XYZ", rf_annual=0.0)
    assert out.n_bars == 300
    assert 0.10 < out.volatility_annualized < 0.30
    assert out.sharpe is not None
    assert out.max_drawdown_pct <= 0


def test_compute_relative_strength_uses_index_history(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    # Stock up 30% over 252 bars; index up 10%.
    for i in range(253):
        d = today - timedelta(days=252 - i)
        stock_c = 100.0 * (1.30 ** (i / 252))
        idx_c = 100.0 * (1.10 ** (i / 252))
        cache.upsert_bars([Bar(symbol="XYZ", date=d, open=stock_c, high=stock_c,
                                low=stock_c, close=stock_c, volume=1)])
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=idx_c, volume=1e8)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_relative_strength_impl(cache, "XYZ", window=252)
    assert out.relative_strength_pct is not None
    assert 0.18 < out.relative_strength_pct < 0.22
    assert out.n_bars == 253


def test_compute_correlation_matrix_seeded(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    # AAA and BBB have identical close trajectories → corr 1.0
    for sym in ("AAA", "BBB"):
        bars = [Bar(symbol=sym, date=today - timedelta(days=49 - i),
                    open=100.0+i, high=100.0+i, low=100.0+i,
                    close=100.0+i, volume=1000)
                for i in range(50)]
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_correlation_impl(cache, ["AAA", "BBB"])
    assert out.matrix["AAA"]["BBB"] == pytest.approx(1.0)
    assert out.matrix["BBB"]["AAA"] == pytest.approx(1.0)
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement impls + tools in `server.py`**

```python
import math
from psx_mcp.risk import (
    drawdown_current, drawdown_max,
    volatility_annualized, sharpe,
    relative_strength, correlation_matrix,
)
from psx_mcp.models import (
    DrawdownResponse, RiskMetricsResponse,
    RelativeStrengthResponse, CorrelationMatrixResponse,
)


def _series_for(cache: Cache, symbol: str) -> pd.Series:
    return pd.Series(cache.closes_for(symbol))


def _compute_drawdown_impl(cache: Cache, symbol: str) -> DrawdownResponse:
    closes = _series_for(cache, symbol)
    if len(closes) == 0:
        return DrawdownResponse(symbol=symbol.upper(), drawdown_pct=0.0,
                                 max_drawdown_pct=0.0,
                                 note=f"No bars cached for {symbol}. "
                                      f"Call refresh_history({symbol!r}).")
    cur = drawdown_current(closes)
    mx = drawdown_max(closes)
    return DrawdownResponse(
        symbol=symbol.upper(),
        drawdown_pct=cur["drawdown_pct"],
        max_drawdown_pct=mx["max_drawdown_pct"],
        peak=cur["peak"],
        current=cur["current"],
        note=None,
    )


def _compute_risk_metrics_impl(cache: Cache, symbol: str,
                                rf_annual: float = 0.0) -> RiskMetricsResponse:
    closes = _series_for(cache, symbol)
    if len(closes) < 2:
        return RiskMetricsResponse(
            symbol=symbol.upper(),
            volatility_annualized=0.0, sharpe=None,
            max_drawdown_pct=0.0, n_bars=int(len(closes)), rf_annual=rf_annual,
            note=f"Need at least 2 bars; call refresh_history({symbol!r}).",
        )
    vol = volatility_annualized(closes)
    sh = sharpe(closes, rf_annual=rf_annual)
    mx = drawdown_max(closes)
    return RiskMetricsResponse(
        symbol=symbol.upper(),
        volatility_annualized=vol, sharpe=sh,
        max_drawdown_pct=mx["max_drawdown_pct"],
        n_bars=int(len(closes)), rf_annual=rf_annual,
        note=None,
    )


def _compute_relative_strength_impl(cache: Cache, symbol: str,
                                     index_code: str = "KSE100",
                                     window: int = 252) -> RelativeStrengthResponse:
    # Date-align: only consider bars where BOTH stock and index have data.
    stock_pairs = cache.closes_for_with_dates(symbol)
    stock_by_date = dict(stock_pairs)
    idx_rows = cache.get_index_history(index_code)
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
    common_dates = sorted(set(stock_by_date) & set(idx_by_date))
    if len(common_dates) < window + 1:
        return RelativeStrengthResponse(
            symbol=symbol.upper(), index_code=index_code, window=window,
            relative_strength_pct=None,
            stock_return_pct=None, index_return_pct=None,
            n_bars=len(common_dates),
            note=(f"Need at least window+1={window+1} aligned bars; have "
                  f"{len(common_dates)}. Call refresh_history(symbol) and "
                  f"refresh_market."),
        )
    stock_series = pd.Series([stock_by_date[d] for d in common_dates])
    idx_series = pd.Series([idx_by_date[d] for d in common_dates])
    rs = relative_strength(stock_series, idx_series, window=window)
    stock_ret = float(stock_series.iloc[-1] / stock_series.iloc[-window - 1] - 1.0)
    idx_ret = float(idx_series.iloc[-1] / idx_series.iloc[-window - 1] - 1.0)
    return RelativeStrengthResponse(
        symbol=symbol.upper(), index_code=index_code, window=window,
        relative_strength_pct=rs,
        stock_return_pct=stock_ret, index_return_pct=idx_ret,
        n_bars=len(common_dates), note=None,
    )


def _compute_correlation_impl(cache: Cache, symbols: list[str]) -> CorrelationMatrixResponse:
    syms_upper = [s.upper() for s in symbols]
    closes_by = {s: pd.Series(cache.closes_for(s)) for s in syms_upper}
    matrix = correlation_matrix(closes_by)
    note = None
    missing = [s for s, ser in closes_by.items() if len(ser) < 2]
    if missing:
        note = (f"Insufficient bars for: {missing}. "
                f"Call refresh_history(symbol) for each.")
    return CorrelationMatrixResponse(
        symbols=syms_upper, matrix=matrix, note=note,
    )


@mcp.tool()
async def compute_drawdown(symbol: str) -> DrawdownResponse:
    """Current drawdown from peak and max drawdown over all cached bars."""
    return _compute_drawdown_impl(_cache, symbol)


@mcp.tool()
async def compute_risk_metrics(symbol: str, rf_annual: float = 0.0) -> RiskMetricsResponse:
    """Annualized volatility (sqrt(252) scaling), Sharpe ratio, and max drawdown.
    rf_annual is the annual risk-free rate as a decimal (e.g., 0.22 for 22%
    Pakistan T-bill yield). Default 0.0 = excess return == raw return."""
    return _compute_risk_metrics_impl(_cache, symbol, rf_annual)


@mcp.tool()
async def compute_relative_strength(symbol: str, index_code: str = "KSE100",
                                     window: int = 252) -> RelativeStrengthResponse:
    """Stock return minus index return over the last `window` aligned trading days.
    Positive = stock outperformed; negative = lagged. Uses cached bars_daily +
    indices_history (call refresh_history and refresh_market first)."""
    return _compute_relative_strength_impl(_cache, symbol, index_code, window)


@mcp.tool()
async def compute_correlation(symbols: list[str]) -> CorrelationMatrixResponse:
    """Pairwise Pearson correlation of daily returns across the given symbols.
    Useful for diversification: highly-correlated names (>0.8) provide little
    diversification benefit; near-zero correlations diversify well."""
    return _compute_correlation_impl(_cache, symbols)
```

- [ ] **Step 5: Run all new tests**

```
uv run pytest tests/test_risk.py tests/test_server.py -k "drawdown or risk_metrics or relative_strength or correlation" -v
```
Use `timeout=180000`. Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_drawdown, compute_risk_metrics, compute_relative_strength, compute_correlation"
```

---

## Phase 2 — Cross-sectional ranking

### Task 2.1: `ranking.py` + `rank_sectors` MCP tool

**Files:**
- Create: `psx-mcp/src/psx_mcp/ranking.py`
- Modify: `psx-mcp/src/psx_mcp/models.py` — `SectorRankResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: `psx-mcp/tests/test_ranking.py`, `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Failing pure-function test**

```python
# psx-mcp/tests/test_ranking.py
import pytest
from datetime import datetime, date, timedelta
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.ranking import rank_sectors


@pytest.fixture
def seeded(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    universe = [
        ("AAA", "TECH", 100.0, +5.0),
        ("BBB", "TECH", 50.0, +2.0),
        ("CCC", "CEMENT", 200.0, -3.0),
        ("DDD", "CEMENT", 100.0, -2.0),
    ]
    for sym, sector, price, change in universe:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                            volume=10_000, day_high=price+1, day_low=price-1,
                            fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=10.0, pb=None,
                                   div_yield=None, payout=None, roe=None)
        # Seed enough bars for sector_summary's sma200 path
        # 260 bars so compute_momentum_score (needs >= 252) has data
        bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                     open=price * (0.8 + i / 260 * 0.4),
                     high=price * (0.81 + i / 260 * 0.4),
                     low=price * (0.79 + i / 260 * 0.4),
                     close=price * (0.8 + i / 260 * 0.4),
                     volume=10_000) for i in range(260)]
        cache.upsert_bars(bars)
    return cache


def test_rank_sectors_by_avg_change_pct(seeded):
    """TECH has +5,+2 avg = +3.5% pos; CEMENT has -3,-2 avg = -2.5% neg → TECH first."""
    out = rank_sectors(seeded, sectors=["TECH", "CEMENT"], by="avg_change_pct")
    assert out[0]["sector"] == "TECH"
    assert out[1]["sector"] == "CEMENT"
    assert out[0]["avg_change_pct"] > out[1]["avg_change_pct"]


def test_rank_sectors_by_breadth(seeded):
    """Both sectors should produce breadth values."""
    out = rank_sectors(seeded, sectors=["TECH", "CEMENT"], by="pct_above_sma200")
    assert all("pct_above_sma200" in r for r in out)


def test_rank_sectors_drops_empty_sectors(seeded):
    """A sector with no members is silently dropped, not a crash."""
    out = rank_sectors(seeded, sectors=["NOSUCH"], by="avg_change_pct")
    assert out == []
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `ranking.py`**

```python
"""Cross-sectional ranking helpers.
Pulls from cache through screener.sector_summary; does not query SQL directly."""
from __future__ import annotations
from typing import Literal
from psx_mcp.screener import sector_summary


SectorRankMetric = Literal[
    "avg_change_pct",
    "median_pe",
    "pct_above_sma200",
    "n",
]


def rank_sectors(cache, sectors: list[str],
                 by: str = "avg_change_pct",
                 desc: bool = True) -> list[dict]:
    """Score each sector via sector_summary, return rank list sorted by `by`.

    Empty sectors (n == 0) are dropped. None values sort to the end regardless
    of `desc`."""
    rows = []
    for s in sectors:
        summary = sector_summary(cache, s)
        if summary.get("n", 0) == 0:
            continue
        rows.append(summary)
    rows.sort(key=lambda r: (r.get(by) is None, r.get(by)), reverse=desc)
    return rows
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add server impl + tool**

In `models.py`:

```python
class SectorRankResponse(Disclaimer):
    metric: str
    desc: bool
    rows: list[dict]
    note: Optional[str] = None
```

In `server.py`:

```python
from psx_mcp.ranking import rank_sectors as _rank_sectors_pure
from psx_mcp.models import SectorRankResponse


# A small curated list of PSX sectors used as default when the caller doesn't supply one.
DEFAULT_SECTORS = [
    "TECHNOLOGY & COMMUNICATION", "CEMENT",
    "OIL & GAS EXPLORATION COMPANIES", "OIL & GAS MARKETING COMPANIES",
    "COMMERCIAL BANKS", "FERTILIZER",
    "POWER GENERATION & DISTRIBUTION",
    "AUTOMOBILE ASSEMBLER", "FOOD & PERSONAL CARE PRODUCTS",
    "PHARMACEUTICALS", "TEXTILE COMPOSITE",
    "CHEMICAL", "REFINERY",
]


def _rank_sectors_impl(cache: Cache, sectors: list[str] | None,
                       by: str = "avg_change_pct",
                       desc: bool = True) -> SectorRankResponse:
    sectors = sectors or DEFAULT_SECTORS
    rows = _rank_sectors_pure(cache, sectors, by=by, desc=desc)
    return SectorRankResponse(metric=by, desc=desc, rows=rows, note=None)


@mcp.tool()
async def rank_sectors(sectors: list[str] | None = None,
                       by: str = "avg_change_pct",
                       desc: bool = True) -> SectorRankResponse:
    """Rank PSX sectors by an aggregate metric. Default: 13 major sectors.
    Valid `by`: 'avg_change_pct' (today's mood), 'median_pe' (relative valuation),
    'pct_above_sma200' (breadth/trend strength), 'n' (member count)."""
    return _rank_sectors_impl(_cache, sectors, by, desc)
```

- [ ] **Step 6: Server test**

```python
def test_rank_sectors_tool_returns_sorted_rows(tmp_path):
    """Use the seeded universe from test_ranking to assert tool wiring."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    for sym, sector, price, change in [
        ("AAA", "TECH", 100.0, +5.0), ("BBB", "TECH", 50.0, +2.0),
        ("CCC", "CEMENT", 200.0, -3.0), ("DDD", "CEMENT", 100.0, -2.0),
    ]:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=10_000, day_high=price+1, day_low=price-1,
                           fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=10.0, pb=None,
                                  div_yield=None, payout=None, roe=None)
        bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                    open=price * (0.8 + i / 260 * 0.4),
                    high=price * (0.81 + i / 260 * 0.4),
                    low=price * (0.79 + i / 260 * 0.4),
                    close=price * (0.8 + i / 260 * 0.4),
                    volume=10_000) for i in range(260)]
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._rank_sectors_impl(cache, sectors=["TECH", "CEMENT"],
                                  by="avg_change_pct", desc=True)
    assert out.metric == "avg_change_pct"
    assert out.rows[0]["sector"] == "TECH"
```

- [ ] **Step 7: Run + commit**

```
uv run pytest tests/test_ranking.py tests/test_server.py -k rank_sectors -v
```
Use `timeout=180000`.

```bash
git add psx-mcp/src/psx_mcp/ranking.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_ranking.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): rank_sectors tool"
```

---

### Task 2.2: `rank_universe` MCP tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/ranking.py` — `rank_universe(cache, by, sector, limit)`
- Modify: `psx-mcp/src/psx_mcp/models.py` — `UniverseRankResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: extend `tests/test_ranking.py` and `tests/test_server.py`

- [ ] **Step 1: Failing test**

```python
def test_rank_universe_by_composite_returns_sorted(seeded):
    """Use the 4-quadrant composite (max 4) to rank."""
    from psx_mcp.ranking import rank_universe
    out = rank_universe(seeded, by="composite", sector=None, limit=10)
    assert len(out) >= 1
    # Total is in [0, 4]; sorted desc by composite
    totals = [r["composite"] for r in out]
    assert totals == sorted(totals, reverse=True)


def test_rank_universe_filters_to_sector(seeded):
    from psx_mcp.ranking import rank_universe
    out = rank_universe(seeded, by="composite", sector="TECH", limit=10)
    for r in out:
        assert r["sector"] == "TECH"


def test_rank_universe_change_pct_metric(seeded):
    from psx_mcp.ranking import rank_universe
    out = rank_universe(seeded, by="change_pct", sector=None, limit=10)
    # AAA (+5%) and BBB (+2%) lead CCC (-3%) and DDD (-2%)
    syms = [r["symbol"] for r in out]
    assert syms.index("AAA") < syms.index("CCC")
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement in `ranking.py`**

```python
from typing import Optional
import pandas as pd
from psx_mcp.quality import compute_4quadrant_score
from psx_mcp.df_utils import bars_df
from psx_mcp.indicators import rsi
from psx_mcp.screener import sector_summary


def rank_universe(cache, by: str = "composite",
                  sector: str | None = None,
                  limit: int = 20,
                  candidate_cap: int = 200) -> list[dict]:
    """Rank cached symbols by a metric. Always computes against the LATEST quote
    JOIN; only symbols with cached quotes are scored.

    `by`:
      "composite"   — 4-quadrant total (0..4), descending
      "change_pct"  — today's % change, descending
      "rsi14"       — RSI(14), descending (overbought first)
      "pe"          — P/E, ascending (cheapest first)

    `candidate_cap` limits how many symbols' indicators we compute (expensive)
    to avoid blowing up on the full ~1000-symbol universe. Default 200 keeps
    end-to-end < ~10s on a warm cache.
    """
    sql = "SELECT s.symbol, s.sector FROM symbols s JOIN quotes q ON q.symbol = s.symbol"
    params: list = []
    if sector:
        sql += " WHERE s.sector = ?"
        params.append(sector)
    sql += " LIMIT ?"
    params.append(candidate_cap)
    rows = cache.conn.execute(sql, params).fetchall()
    out = []
    # Memoize sector_summary for the lifetime of this call. With ~13 unique
    # sectors across 200 candidates, this cuts sector_summary calls from ~200
    # down to ~13.
    sector_med_cache: dict[str, Optional[float]] = {}

    for r in rows:
        sym = r["symbol"]
        df = bars_df(cache, sym, lookback_days=260)
        if df.empty:
            continue
        quote = cache.get_latest_quote(sym) or {}
        fund = cache.get_fundamentals(sym) or {}
        price = float(quote.get("price") or 0)
        change = float(quote.get("change") or 0)
        prev_close = price - change
        change_pct = (change / prev_close * 100) if prev_close > 0 else None

        record = {
            "symbol": sym, "sector": r["sector"],
            "price": price, "change_pct": change_pct,
            "pe": fund.get("pe"), "eps": fund.get("eps"),
        }

        if by == "composite":
            closes = pd.Series(cache.closes_for(sym))
            sector_med = None
            if r["sector"]:
                if r["sector"] not in sector_med_cache:
                    ss = sector_summary(cache, r["sector"])
                    sector_med_cache[r["sector"]] = ss.get("median_pe")
                sector_med = sector_med_cache[r["sector"]]
            hist = cache.get_fundamentals_history(sym) or []
            eps_history = list(reversed([h["eps"] for h in hist if h.get("eps") is not None]))
            snap = {
                "pe": fund.get("pe"), "eps": fund.get("eps"),
                "price": price, "roe": fund.get("roe"),
                "eps_history": eps_history, "closes": closes,
                "sector_median_pe": sector_med,
            }
            sc = compute_4quadrant_score(snap)
            record["composite"] = sc["total"]
            record["quadrants"] = {k: sc[k] for k in ("value", "quality", "momentum", "trend")}
        elif by == "rsi14":
            closes = pd.Series(cache.closes_for(sym))
            if len(closes) < 15:
                continue
            record["rsi14"] = float(rsi(closes, 14).iloc[-1])
        elif by == "change_pct":
            if change_pct is None:
                continue
        elif by == "pe":
            if record["pe"] is None:
                continue
        else:
            raise ValueError(f"unknown ranking metric: {by}")

        out.append(record)

    if by == "pe":
        # Cheapest first
        out.sort(key=lambda r: (r.get("pe") is None, r.get("pe")), reverse=False)
    else:
        out.sort(key=lambda r: (r.get(by) is None, r.get(by)), reverse=True)
    return out[:limit]
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add server impl + tool**

```python
# models.py
class UniverseRankResponse(Disclaimer):
    metric: str
    sector: Optional[str] = None
    limit: int
    rows: list[dict]
    note: Optional[str] = None
```

```python
# server.py
from psx_mcp.ranking import rank_universe as _rank_universe_pure
from psx_mcp.models import UniverseRankResponse


def _rank_universe_impl(cache: Cache, by: str = "composite",
                        sector: Optional[str] = None,
                        limit: int = 20) -> UniverseRankResponse:
    rows = _rank_universe_pure(cache, by=by, sector=sector, limit=limit)
    note = None
    if not rows:
        note = ("No symbols ranked. Possible causes: cache is empty (call "
                "refresh_market then refresh_history), or the selected sector "
                "has no scored members.")
    return UniverseRankResponse(metric=by, sector=sector, limit=limit,
                                 rows=rows, note=note)


@mcp.tool()
async def rank_universe(by: str = "composite",
                        sector: str | None = None,
                        limit: int = 20) -> UniverseRankResponse:
    """Rank cached PSX symbols by a metric. Default: 4-quadrant composite score.
    Valid metrics: 'composite' (Value+Quality+Momentum+Trend, max 4),
    'change_pct' (today's movers), 'rsi14' (technical overbought/oversold),
    'pe' (cheapest first). Limits to top-200 candidates by quote freshness;
    call refresh_history(symbol) for each candidate before this for full coverage."""
    return _rank_universe_impl(_cache, by, sector, limit)
```

- [ ] **Step 6: Run + commit**

```
uv run pytest tests/test_ranking.py tests/test_server.py -k rank_universe -v
```
Use `timeout=240000`. Expected: all green.

```bash
git add psx-mcp/src/psx_mcp/ranking.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_ranking.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): rank_universe MCP tool"
```

---

## Phase 3 — Unified dashboard

### Task 3.1: `get_full_analysis(symbol)` MCP tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `FullAnalysisResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: `psx-mcp/tests/test_dashboard.py`

- [ ] **Step 1: Add model**

Python disallows attributes starting with a digit, so use `week52` (not `52w`):

```python
class FullAnalysisResponse(Disclaimer):
    symbol: str
    quote: Optional[dict] = None
    fundamentals: Optional[dict] = None
    week52: Optional[dict] = None
    indicators: Optional[dict] = None
    drawdown: Optional[dict] = None
    risk: Optional[dict] = None
    beta: Optional[dict] = None
    relative_strength: Optional[dict] = None
    quadrant_score: Optional[dict] = None
    dividend_history_recent: list[dict] = []
    announcements_recent: list[dict] = []
    warnings: list[str] = []
```

- [ ] **Step 2: Failing test in `tests/test_dashboard.py`**

```python
import pytest
from datetime import datetime, date, timedelta
import server as srv
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.watchlist import WatchlistStore


def _seed_full(cache: Cache, sym: str, sector: str = "TECH"):
    """Seed a symbol with everything full_analysis touches."""
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    cache.upsert_symbol(sym, sym, sector, None)
    cache.upsert_quote(symbol=sym, ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    # Seed 260 bars with realistic high/low spread so ATR > 0 (the indicators
    # default bundle includes atr14 — fixes M4 from review).
    bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                open=100.0 + i, high=100.0 + i + 5, low=100.0 + i - 5,
                close=100.0 + i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    # Index for relative_strength + beta (date-aligned with stock bars)
    for i in range(260):
        d = today - timedelta(days=259 - i)
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=170_000.0 + i, volume=1e8)


def test_get_full_analysis_combines_all_sections(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    _seed_full(cache, "SYS")
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_full_analysis_impl(cache, "SYS")
    assert out.symbol == "SYS"
    assert out.quote is not None
    assert out.fundamentals is not None
    assert out.week52 is not None
    assert out.indicators is not None and "rsi14" in out.indicators
    assert out.drawdown is not None
    assert out.risk is not None
    assert out.beta is not None
    assert out.relative_strength is not None
    assert out.quadrant_score is not None
    assert isinstance(out.warnings, list)


def test_get_full_analysis_handles_missing_data(tmp_path):
    """Empty cache → response with warnings, no crash."""
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_full_analysis_impl(cache, "NOSUCH")
    assert out.symbol == "NOSUCH"
    assert len(out.warnings) > 0
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement in `server.py`**

```python
from psx_mcp.models import FullAnalysisResponse


def _get_full_analysis_impl(cache: Cache, symbol: str) -> FullAnalysisResponse:
    """One-shot dashboard. Composes existing impls. Each section is best-effort
    — missing data → that section is None and a warning is added."""
    sym = symbol.upper()
    warnings: list[str] = []

    # Quote
    quote = None
    try:
        q = _get_quote_impl(cache, sym)
        quote = q.model_dump(exclude={"disclaimer"})
        if q.stale:
            warnings.append("Quote is stale; call refresh_market.")
    except Exception as e:
        warnings.append(f"quote: {e!r}")

    # Fundamentals (current)
    fundamentals = None
    try:
        f = cache.get_fundamentals(sym)
        if f:
            fundamentals = dict(f)
        else:
            warnings.append("No fundamentals cached.")
    except Exception as e:
        warnings.append(f"fundamentals: {e!r}")

    # 52w high/low
    week52 = None
    try:
        hi, lo = cache.fifty_two_week(sym)
        week52 = {"high": hi, "low": lo}
    except Exception as e:
        warnings.append(f"52w: {e!r}")

    # Indicators (default bundle)
    indicators = None
    try:
        ind = _compute_indicators_impl(cache, sym, indicators=None)
        # Strip the embedded disclaimer key
        indicators = {k: v for k, v in ind.items() if k != "disclaimer"}
    except Exception as e:
        warnings.append(f"indicators: {e!r}")

    # Drawdown
    drawdown = None
    try:
        dd = _compute_drawdown_impl(cache, sym)
        drawdown = dd.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"drawdown: {e!r}")

    # Risk metrics
    risk = None
    try:
        rm = _compute_risk_metrics_impl(cache, sym, rf_annual=0.0)
        risk = rm.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"risk: {e!r}")

    # Beta
    beta_dict = None
    try:
        b = _compute_beta_impl(cache, sym)
        beta_dict = b.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"beta: {e!r}")

    # Relative strength
    rs = None
    try:
        rs_r = _compute_relative_strength_impl(cache, sym)
        rs = rs_r.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"relative_strength: {e!r}")

    # Quadrant score (also lift its per-quadrant warnings into the dashboard top-level)
    quadrant_score = None
    try:
        qs = _compute_4quadrant_score_impl(cache, sym)
        quadrant_score = qs.model_dump(exclude={"disclaimer"})
        for w in getattr(qs, "warnings", []) or []:
            warnings.append(f"quadrant: {w}")
    except Exception as e:
        warnings.append(f"quadrant_score: {e!r}")

    # Dividend history (last 5)
    divs = []
    try:
        ds = cache.get_dividend_history(sym)
        divs = [dict(d) for d in ds[:5]]
    except Exception as e:
        warnings.append(f"dividends: {e!r}")

    # Announcements (last 5 for this symbol)
    anns = []
    try:
        rows = cache.conn.execute(
            "SELECT title, posted_at, url FROM announcements "
            "WHERE symbol=? ORDER BY posted_at DESC LIMIT 5",
            (sym,),
        ).fetchall()
        anns = [dict(r) for r in rows]
    except Exception as e:
        warnings.append(f"announcements: {e!r}")

    return FullAnalysisResponse(
        symbol=sym, quote=quote, fundamentals=fundamentals,
        week52=week52, indicators=indicators,
        drawdown=drawdown, risk=risk, beta=beta_dict,
        relative_strength=rs, quadrant_score=quadrant_score,
        dividend_history_recent=divs,
        announcements_recent=anns,
        warnings=warnings,
    )


@mcp.tool()
async def get_full_analysis(symbol: str) -> FullAnalysisResponse:
    """One-shot research dashboard: quote, fundamentals, 52w range, indicators,
    drawdown, risk metrics, beta, relative strength, 4-quadrant score, recent
    dividends, recent announcements. Missing sections → null + warning."""
    return _get_full_analysis_impl(_cache, symbol)
```

- [ ] **Step 5: Run + commit**

```
uv run pytest tests/test_dashboard.py -v
```
Use `timeout=120000`.

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_dashboard.py
git commit -m "feat(psx-mcp): get_full_analysis dashboard tool"
```

---

## Phase 4 — Position sizing

### Task 4.1: `compute_position_size` tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `PositionSizeResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: `psx-mcp/tests/test_server.py`

ATR-based fixed-fractional sizing per the playbook Part-2 Section I.

- [ ] **Step 1: Failing test**

```python
def test_compute_position_size_atr_based(tmp_path):
    """100k portfolio, 2% risk, 2x ATR stop, ATR computed from seeded bars.
    With ATR=10 and 2x stop, risk per share = 20; risk budget = 2000;
    qty = 2000/20 = 100 shares."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    # Synthetic bars where ATR(14) ≈ 10 (high-low spread of ~10 daily)
    bars = []
    for i in range(30):
        d = today - timedelta(days=29 - i)
        close = 100.0 + i
        bars.append(Bar(symbol="XYZ", date=d, open=close,
                         high=close + 5, low=close - 5, close=close, volume=1000))
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_position_size_impl(cache, "XYZ",
                                           portfolio_value=100_000.0,
                                           risk_pct=2.0, stop_atr_mult=2.0)
    assert out.atr is not None
    assert 8 < out.atr < 12  # ATR ~10 for ±5 high-low spread
    assert out.qty is not None
    assert out.qty > 0
    # Risk per share ≈ 2 × ATR; qty ≈ risk_budget / risk_per_share
    expected_qty = int(2000.0 / (2 * out.atr))
    assert abs(out.qty - expected_qty) <= 1


def test_compute_position_size_insufficient_bars(tmp_path):
    """< 15 bars → ATR undefined → qty None + note."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_bars([Bar(symbol="XYZ", date=date(2026, 5, 23),
                            open=100.0, high=110.0, low=90.0, close=100.0, volume=1)])
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_position_size_impl(cache, "XYZ",
                                           portfolio_value=100_000.0,
                                           risk_pct=2.0, stop_atr_mult=2.0)
    assert out.qty is None
    assert out.note is not None
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add model + impl**

```python
# models.py
class PositionSizeResponse(Disclaimer):
    symbol: str
    portfolio_value: float
    risk_pct: float
    stop_atr_mult: float
    price: Optional[float] = None
    atr: Optional[float] = None
    risk_budget: float
    risk_per_share: Optional[float] = None
    qty: Optional[int] = None
    notional: Optional[float] = None
    note: Optional[str] = None
```

```python
# server.py
from psx_mcp.indicators import atr as _atr
from psx_mcp.models import PositionSizeResponse


def _compute_position_size_impl(cache: Cache, symbol: str,
                                 portfolio_value: float,
                                 risk_pct: float = 1.0,
                                 stop_atr_mult: float = 2.0) -> PositionSizeResponse:
    """ATR-based fixed-fractional sizing:
       risk_per_share = stop_atr_mult × ATR(14)
       qty = floor((portfolio_value × risk_pct/100) / risk_per_share)"""
    df = bars_df(cache, symbol, lookback_days=60)
    risk_budget = portfolio_value * (risk_pct / 100.0)
    if df.empty or len(df) < 15:
        return PositionSizeResponse(
            symbol=symbol.upper(), portfolio_value=portfolio_value,
            risk_pct=risk_pct, stop_atr_mult=stop_atr_mult,
            risk_budget=risk_budget,
            note=(f"Need at least 15 bars to compute ATR(14); have {len(df)}. "
                  f"Call refresh_history({symbol!r})."),
        )
    atr_val = float(_atr(df["high"], df["low"], df["close"], 14).iloc[-1])
    price = float(df["close"].iloc[-1])
    risk_per_share = stop_atr_mult * atr_val
    if risk_per_share <= 0:
        return PositionSizeResponse(
            symbol=symbol.upper(), portfolio_value=portfolio_value,
            risk_pct=risk_pct, stop_atr_mult=stop_atr_mult,
            price=price, atr=atr_val,
            risk_budget=risk_budget, risk_per_share=risk_per_share,
            note="ATR collapsed to ≤ 0; cannot size.",
        )
    qty = int(risk_budget // risk_per_share)
    return PositionSizeResponse(
        symbol=symbol.upper(), portfolio_value=portfolio_value,
        risk_pct=risk_pct, stop_atr_mult=stop_atr_mult,
        price=price, atr=atr_val,
        risk_budget=risk_budget, risk_per_share=risk_per_share,
        qty=qty, notional=qty * price,
        note=None,
    )


@mcp.tool()
async def compute_position_size(symbol: str, portfolio_value: float,
                                 risk_pct: float = 1.0,
                                 stop_atr_mult: float = 2.0) -> PositionSizeResponse:
    """ATR-based fixed-fractional position sizing.

    risk_pct: portfolio % to risk per trade (industry rule: 1–2%).
    stop_atr_mult: stop distance in ATR multiples (industry default: 2).

    Returns: ATR, suggested qty (floor), notional cost. None on insufficient bars."""
    return _compute_position_size_impl(_cache, symbol, portfolio_value,
                                        risk_pct, stop_atr_mult)
```

- [ ] **Step 4: Run + commit**

```
uv run pytest tests/test_server.py -k position_size -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_position_size — ATR-based fixed-fractional sizing"
```

---

## Phase 5 — Operational ergonomics

### Task 5.1: `refresh_universe` bulk tool + `get_cache_status`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/cache.py` — `cache_status()` helper
- Modify: `psx-mcp/src/psx_mcp/models.py` — `BulkRefreshResponse`, `CacheStatusResponse`
- Modify: `psx-mcp/server.py` — impls + tools
- Test: `psx-mcp/tests/test_server.py`, `tests/test_cache.py`

- [ ] **Step 1: Failing cache test**

```python
def test_cache_status_reports_table_counts_and_freshness(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from datetime import datetime, date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_symbol("XYZ", "X", "TECH", None)
    cache.upsert_quote(symbol="XYZ", ts=datetime(2026, 5, 23, 10, 0),
                       price=100.0, change=1.0, volume=1000,
                       day_high=101, day_low=99,
                       fetched_at=datetime(2026, 5, 23, 10, 0))
    cache.upsert_bars([Bar(symbol="XYZ", date=date(2026, 5, 23),
                            open=100.0, high=101.0, low=99.0, close=100.0, volume=1000)])
    status = cache.cache_status()
    assert status["symbols"]["count"] == 1
    assert status["quotes"]["count"] == 1
    assert status["bars_daily"]["count"] == 1
    # latest_refreshed_at is None for tables without that column, populated otherwise
    assert "latest_refreshed_at" in status["symbols"]
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `cache_status` in `cache.py`**

```python
def cache_status(self) -> dict:
    """Return per-table row count + max refreshed_at where available.

    Tables and their "freshness" column:
      symbols.refreshed_at, quotes.fetched_at, bars_daily.(latest date),
      announcements.posted_at, fundamentals.refreshed_at,
      fundamentals_history.refreshed_at, indices.refreshed_at,
      indices_history.(latest bar_date), dividends.(latest ex_date), news.posted_at."""
    spec = [
        ("symbols", "refreshed_at"),
        ("quotes", "fetched_at"),
        ("bars_daily", "date"),
        ("announcements", "posted_at"),
        ("fundamentals", "refreshed_at"),
        ("fundamentals_history", "refreshed_at"),
        ("indices", "refreshed_at"),
        ("indices_history", "bar_date"),
        ("dividends", "ex_date"),
        ("news", "posted_at"),
    ]
    out = {}
    for table, freshness_col in spec:
        try:
            count = self.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        latest = None
        if freshness_col and count:
            try:
                row = self.conn.execute(
                    f"SELECT MAX({freshness_col}) FROM {table}"
                ).fetchone()
                latest = row[0] if row else None
            except sqlite3.OperationalError:
                latest = None
        out[table] = {"count": count, "latest_refreshed_at": latest}
    return out
```

(Make sure `sqlite3` is imported at the top of `cache.py`.)

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add models**

```python
class CacheStatusResponse(Disclaimer):
    tables: dict[str, dict]
    note: Optional[str] = None


class BulkRefreshResponse(Disclaimer):
    requested: list[str]
    succeeded: list[str]
    failed: list[dict]  # [{symbol, error}, ...]
    elapsed_seconds: float
    note: Optional[str] = None
```

- [ ] **Step 6: Add server impls + tools**

```python
import time

from psx_mcp.models import CacheStatusResponse, BulkRefreshResponse


def _get_cache_status_impl(cache: Cache) -> CacheStatusResponse:
    tables = cache.cache_status()
    note = None
    if not any(t["count"] for t in tables.values()):
        note = "Cache is empty. Start with refresh_market then refresh_history(symbol)."
    return CacheStatusResponse(tables=tables, note=note)


async def _refresh_universe_impl(cache: Cache,
                                  client: Optional[PSXClient],
                                  symbols: Optional[list[str]] = None,
                                  sector: Optional[str] = None) -> BulkRefreshResponse:
    """Bulk refresh history for many symbols. Order of resolution for `symbols`:
       1. If `symbols` is given, use it.
       2. Else if `sector` is given, pull all symbols in that sector from cache.
       3. Else pull all symbols that have quotes cached (latest universe)."""
    if client is None:
        return BulkRefreshResponse(
            requested=[], succeeded=[], failed=[], elapsed_seconds=0.0,
            note=("No PSX client configured (server.set_dependencies(client=...) "
                  "was called with None). Cannot fetch."),
        )
    if symbols:
        targets = [s.upper() for s in symbols]
    elif sector:
        rows = cache.conn.execute(
            "SELECT symbol FROM symbols WHERE sector = ?", (sector,)
        ).fetchall()
        targets = [r["symbol"] for r in rows]
    else:
        rows = cache.conn.execute(
            "SELECT DISTINCT symbol FROM quotes"
        ).fetchall()
        targets = [r["symbol"] for r in rows]

    succeeded: list[str] = []
    failed: list[dict] = []
    start = time.time()
    for sym in targets:
        try:
            await _refresh_history_impl(cache, client, sym)
            succeeded.append(sym)
        except Exception as e:
            failed.append({"symbol": sym, "error": str(e)})
    elapsed = time.time() - start
    note = None
    if not targets:
        note = ("No symbols resolved. Either pass `symbols=[...]`, or call "
                "refresh_market first to populate the universe.")
    return BulkRefreshResponse(
        requested=targets, succeeded=succeeded, failed=failed,
        elapsed_seconds=elapsed, note=note,
    )


@mcp.tool()
async def get_cache_status() -> CacheStatusResponse:
    """Report row counts and latest-refresh timestamp for each cache table.
    Use this to know what's fresh before relying on screener/score outputs."""
    return _get_cache_status_impl(_cache)


@mcp.tool()
async def refresh_universe(symbols: list[str] | None = None,
                            sector: str | None = None) -> BulkRefreshResponse:
    """Bulk-refresh daily history for many symbols. Resolution order:
       1. `symbols` if given;
       2. else all symbols in `sector` if given;
       3. else all symbols with cached quotes.
    Slow on the full universe (1 HTTP call per symbol). Use sparingly or
    pre-filter via `sector`."""
    return await _refresh_universe_impl(_cache, _client, symbols, sector)
```

NOTE: This task assumes `_refresh_history_impl(cache, client, symbol)` exists. If the existing server has a `refresh_history` tool that's tightly coupled to MCP wrapper plumbing, refactor the body into a sync/async impl helper first as a minor in-task cleanup.

- [ ] **Step 7: Server test**

```python
def test_get_cache_status_empty_cache(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_cache_status_impl(cache)
    assert out.tables["symbols"]["count"] == 0
    assert "empty" in (out.note or "").lower()
```

- [ ] **Step 8: Run + commit**

```
uv run pytest tests/test_cache.py tests/test_server.py -k "cache_status or refresh_universe" -v
```

```bash
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_cache.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): get_cache_status + refresh_universe bulk tool"
```

---

### Task 5.2: `get_upcoming_events`

Find announcements with title containing "Board Meeting" (or similar earnings-cycle markers) and surface them as "upcoming" — interpreted as: announcement was posted recently AND title implies a future-dated event.

This is heuristic — without parsing the announcement PDF body, we can't reliably extract the meeting date. The tool returns announcements posted in the last `lookback_days` whose title matches relevant patterns.

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `UpcomingEventsResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Failing test**

```python
def test_get_upcoming_events_filters_by_title_keywords(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    now = datetime.now()
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=now - timedelta(days=2),
        title="Notice of Board Meeting on 30 May 2026",
        category=None, url=None, body=None,
    ))
    cache.upsert_announcement(Announcement(
        id="A2", symbol="SYS", posted_at=now - timedelta(days=2),
        title="Disclosure of Interest by Director",
        category=None, url=None, body=None,
    ))
    cache.upsert_announcement(Announcement(
        id="A3", symbol="LUCK", posted_at=now - timedelta(days=10),
        title="Board Meeting Other Than Financial Results",
        category=None, url=None, body=None,
    ))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_upcoming_events_impl(cache, lookback_days=7)
    titles = [e["title"] for e in out.events]
    assert any("Board Meeting on 30 May" in t for t in titles)
    assert all("Disclosure of Interest" not in t for t in titles)
    # A3 is older than 7 days → excluded
    assert all("Other Than Financial" not in t for t in titles)
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add model + impl**

```python
# models.py
class UpcomingEventsResponse(Disclaimer):
    lookback_days: int
    events: list[dict]
    note: Optional[str] = None
```

```python
# server.py
import re as _re

UPCOMING_EVENT_PATTERNS = [
    r"\bboard\s+meeting\b",
    r"\bagm\b", r"\bextraordinary\s+general\s+meeting\b", r"\begm\b",
    r"\bfinancial\s+results?\b",
    r"\bcorporate\s+briefing\b", r"\bcbs\b",
    r"\bex[- ]?date\b", r"\bbook\s+closure\b",
]
_UPCOMING_RE = _re.compile("|".join(UPCOMING_EVENT_PATTERNS), _re.I)


def _get_upcoming_events_impl(cache: Cache, lookback_days: int = 14) -> UpcomingEventsResponse:
    """Heuristic 'upcoming events' tool: returns announcements posted in the last
    `lookback_days` whose title matches a curated set of corporate-action
    patterns (Board Meeting, AGM, EGM, Financial Results, Corporate Briefing,
    Ex-Date, Book Closure). Without parsing announcement PDFs we cannot extract
    the actual scheduled date; the user must read the announcement for that."""
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=lookback_days)).isoformat()
    rows = cache.conn.execute(
        "SELECT symbol, title, posted_at, url FROM announcements "
        "WHERE posted_at >= ? ORDER BY posted_at DESC",
        (since,),
    ).fetchall()
    events = []
    for r in rows:
        title = r["title"] or ""
        if _UPCOMING_RE.search(title):
            events.append(dict(r))
    note = None
    if not events:
        note = (f"No matching announcements in the last {lookback_days} days. "
                f"Try a wider lookback or call refresh_announcements first.")
    return UpcomingEventsResponse(lookback_days=lookback_days, events=events,
                                   note=note)


@mcp.tool()
async def get_upcoming_events(lookback_days: int = 14) -> UpcomingEventsResponse:
    """Surface recently-posted announcements that imply upcoming corporate
    actions (Board Meeting, AGM/EGM, Financial Results, CBS, Ex-Date, Book
    Closure). Heuristic — title-pattern based; actual event dates require
    reading the announcement PDF via its url."""
    return _get_upcoming_events_impl(_cache, lookback_days)
```

- [ ] **Step 4: Run + commit**

```
uv run pytest tests/test_server.py -k upcoming_events -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): get_upcoming_events — surface board meetings + AGM/EGM titles"
```

---

### Task 5.3: `list_watchlist_with_scores`

Adds composite scores to the existing watchlist listing — additive, doesn't replace `list_watchlist`.

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — `WatchlistWithScoresResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Failing test**

```python
def test_list_watchlist_with_scores_attaches_composite(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    store = WatchlistStore(str(tmp_path / "w.json"))
    store.add_watch("SYS", notes="tech leader")
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    cache.upsert_symbol("SYS", "Systems", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    bars = [Bar(symbol="SYS", date=today - timedelta(days=259 - i),
                open=100.0 + i, high=100.0 + i, low=100.0 + i,
                close=100.0 + i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=store, client=None)
    out = srv._list_watchlist_with_scores_impl(cache, store)
    assert len(out.entries) == 1
    e = out.entries[0]
    assert e["symbol"] == "SYS"
    assert "composite" in e
    assert e["notes"] == "tech leader"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Add model + impl**

```python
# models.py
class WatchlistWithScoresResponse(Disclaimer):
    entries: list[dict]
    note: Optional[str] = None
```

```python
# server.py
from psx_mcp.models import WatchlistWithScoresResponse


def _list_watchlist_with_scores_impl(cache: Cache,
                                      store: WatchlistStore) -> WatchlistWithScoresResponse:
    entries = []
    for w in store.list_watch():
        try:
            qs = _compute_4quadrant_score_impl(cache, w.symbol)
            composite = qs.total
            quadrants = {k: getattr(qs, k) for k in ("value", "quality", "momentum", "trend")}
            warnings_for_entry = list(getattr(qs, "warnings", []) or [])
        except Exception as e:
            composite = None
            quadrants = {}
            warnings_for_entry = [f"score-failed: {e!r}"]
        quote = cache.get_latest_quote(w.symbol) or {}
        entries.append({
            "symbol": w.symbol,
            "notes": w.notes,
            "added_at": w.added_at.isoformat(),
            "price": quote.get("price"),
            "composite": composite,
            "quadrants": quadrants,
            "warnings": warnings_for_entry,
        })
    note = None
    if not entries:
        note = "Watchlist is empty. Use add_to_watchlist(symbol) first."
    return WatchlistWithScoresResponse(entries=entries, note=note)


@mcp.tool()
async def list_watchlist_with_scores() -> WatchlistWithScoresResponse:
    """Like list_watchlist but each entry includes its current 4-quadrant
    composite score (0..4) and price. Heavy: computes scores per entry."""
    return _list_watchlist_with_scores_impl(_cache, _store)
```

- [ ] **Step 4: Run + commit**

```
uv run pytest tests/test_server.py -k watchlist_with_scores -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): list_watchlist_with_scores tool"
```

---

## Phase 6 — Alerts & correctness

### Task 6.1: Fundamental alert rules

Extend `AlertRule.type` from `Literal["price", "indicator", "volume", "announcement"]` to also include `"fundamental"`. Add a dispatch branch in `evaluate_rule`. Reuses existing `cond.indicator` field to name the fundamental metric (`"pe"`, `"roe"`, `"div_yield"`).

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — extend `RuleType` Literal
- Modify: `psx-mcp/src/psx_mcp/alerts.py` — new branch in `evaluate_rule`
- Test: `psx-mcp/tests/test_alerts.py`

- [ ] **Step 1: Failing test**

```python
def test_evaluate_fundamental_rule_pe_below_triggers(tmp_path):
    """PE < threshold should fire."""
    from psx_mcp.cache import Cache
    from psx_mcp.models import AlertRule, AlertCondition
    from psx_mcp.alerts import evaluate_rule
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    rule = AlertRule(
        id="rid", symbol="SYS", type="fundamental",
        condition=AlertCondition(indicator="pe", op="<", value=10.0),
        active=True, created_at=date.today(),
    )
    hit = evaluate_rule(cache, rule)
    assert hit is not None
    assert "pe" in hit.message.lower()


def test_evaluate_fundamental_rule_pe_above_threshold_no_trigger(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import AlertRule, AlertCondition
    from psx_mcp.alerts import evaluate_rule
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=12.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    rule = AlertRule(
        id="rid", symbol="SYS", type="fundamental",
        condition=AlertCondition(indicator="pe", op="<", value=10.0),
        active=True, created_at=date.today(),
    )
    assert evaluate_rule(cache, rule) is None


def test_evaluate_fundamental_rule_missing_indicator_returns_none(tmp_path):
    """No fundamentals cached → silently None, no crash."""
    from psx_mcp.cache import Cache
    from psx_mcp.models import AlertRule, AlertCondition
    from psx_mcp.alerts import evaluate_rule
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    rule = AlertRule(
        id="rid", symbol="NOSUCH", type="fundamental",
        condition=AlertCondition(indicator="pe", op="<", value=10.0),
        active=True, created_at=date.today(),
    )
    assert evaluate_rule(cache, rule) is None
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Extend `RuleType` in `models.py`**

Change:

```python
RuleType = Literal["price", "indicator", "volume", "announcement"]
```

to:

```python
RuleType = Literal["price", "indicator", "volume", "announcement", "fundamental"]
```

- [ ] **Step 4: Add branch in `alerts.py::evaluate_rule`**

Add this case before the final `return None`:

```python
if rule.type == "fundamental":
    fund = cache.get_fundamentals(rule.symbol)
    if not fund:
        return None
    key = cond.indicator
    if not key or key not in fund:
        return None
    val = fund.get(key)
    if val is None:
        return None
    op = _OPS.get(cond.op)
    if op and op(val, cond.value):
        return AlertHit(
            rule_id=rule.id, symbol=rule.symbol, triggered_at=now,
            message=f"{rule.symbol} {key}={val:.2f} {cond.op} {cond.value}",
            snapshot={"indicator": key, "value": val, "threshold": cond.value},
        )
    return None
```

- [ ] **Step 5: Run + commit**

```
uv run pytest tests/test_alerts.py -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/src/psx_mcp/alerts.py psx-mcp/tests/test_alerts.py
git commit -m "feat(psx-mcp): fundamental alert rules (PE/ROE/div_yield thresholds)"
```

---

### Task 6.2: Silent-failure warnings

Add a `warnings: list[str]` field to:
- `QuadrantScoreResponse` — populated when sector_median_pe is None, when fundamentals_history is empty (quality score is incomplete), when closes < 200 bars (trend can't be computed).
- `ScreenResponse` — populated with a count of symbols skipped due to insufficient bars.

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py` — add `warnings` field to both models
- Modify: `psx-mcp/src/psx_mcp/screener.py` — track skipped count
- Modify: `psx-mcp/server.py` — `_compute_4quadrant_score_impl` populates warnings; `_screen_symbols_impl` populates from screen output

- [ ] **Step 1: Failing test (compute_4quadrant_score warnings)**

```python
def test_compute_4quadrant_score_warns_on_missing_data(tmp_path):
    """Empty cache → score returns zeros AND lists what's missing."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_4quadrant_score_impl(cache, "NOSUCH")
    assert out.total == 0
    assert len(out.warnings) > 0
    # Specific warnings about missing data
    joined = " ".join(out.warnings).lower()
    assert ("sector" in joined or "quote" in joined or "bars" in joined
            or "fundamentals" in joined)


def test_screen_symbols_reports_skipped_count(tmp_path):
    """Symbols missing bars when a technical filter is set should be reported."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    cache.upsert_symbol("SYS", "Sys", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    # No bars → screener with rsi_min should skip SYS
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._screen_symbols_impl(cache, rsi_min=40, rsi_max=70)
    assert out.count == 0
    assert out.warnings  # should mention skipped
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Extend models in `models.py`**

```python
class QuadrantScoreResponse(Disclaimer):
    symbol: str
    value: int
    quality: int
    momentum: int
    trend: int
    total: int
    raw: dict
    warnings: list[str] = []


class ScreenResponse(Disclaimer):
    results: list[dict]
    count: int
    warnings: list[str] = []
```

- [ ] **Step 4: Instrument `screener.screen()` to track skips (single SQL pass)**

Rather than re-running SQL and re-deriving the skipped count post-hoc (which would double the work AND over-count symbols dropped for non-bar SQL filters like `pe_max`), refactor `screen()` to call an internal `_screen()` that returns BOTH results and metadata. Public `screen()` keeps its current contract for backwards compatibility.

In `psx-mcp/src/psx_mcp/screener.py`, do this surgical refactor:

1. **Rename the current `screen(cache, spec)` body** to `def _screen(cache, spec: FilterSpec) -> tuple[list[dict], dict]:`.
2. **Initialize `skipped_no_bars = 0`** at the top, near `results = []`.
3. **In the per-candidate `< 50 bars` skip branch** (where it currently `continue`s when `any technical filter is active`), change to:
   ```python
   skipped_no_bars += 1
   continue
   ```
4. **Change the final return** from `return results[:spec.limit]` to:
   ```python
   return results[:spec.limit], {"skipped_no_bars": skipped_no_bars, "candidates": len(rows)}
   ```
5. **Add thin wrappers at the bottom** of `screener.py`:
   ```python
   def screen(cache, spec: FilterSpec) -> list[dict]:
       """Backwards-compatible: returns results only, drops meta."""
       results, _meta = _screen(cache, spec)
       return results


   def screen_with_meta(cache, spec: FilterSpec) -> tuple[list[dict], dict]:
       """For callers that need the skipped-bars count (e.g., _screen_symbols_impl)."""
       return _screen(cache, spec)
   ```

This keeps all existing callers (`sector_summary`, `rank_universe`, the test suite) untouched while exposing the metadata only to the caller that wants it. Single SQL pass.

- [ ] **Step 5: Update `_screen_symbols_impl` in `server.py`**

```python
def _screen_symbols_impl(cache, **kwargs) -> ScreenResponse:
    from psx_mcp.screener import screen_with_meta, FilterSpec
    spec_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    spec = FilterSpec(**spec_kwargs)
    rows, meta = screen_with_meta(cache, spec)
    warnings: list[str] = []
    if meta["skipped_no_bars"]:
        warnings.append(
            f"{meta['skipped_no_bars']} symbol(s) skipped due to insufficient bars "
            f"(needs >= 50 daily bars). Call refresh_history(symbol) for each."
        )
    return ScreenResponse(results=rows, count=len(rows), warnings=warnings)
```

- [ ] **Step 6: Update `_compute_4quadrant_score_impl`**

```python
def _compute_4quadrant_score_impl(cache: Cache, symbol: str) -> QuadrantScoreResponse:
    snap = _build_snapshot(cache, symbol)
    sc = _compute_4quadrant_score_pure(snap)
    warnings: list[str] = []
    if snap.get("price") is None or snap.get("pe") is None:
        warnings.append("No quote/fundamentals cached. Value/Quality scores are 0.")
    if snap.get("sector_median_pe") is None:
        warnings.append("No sector peers cached → value score = 0 even if PE is low. "
                        "Call refresh_market first.")
    if not snap.get("eps_history"):
        warnings.append("No fundamentals_history (Part-4 dependency) → quality score "
                        "only reflects current ROE, not EPS trend.")
    closes = snap.get("closes")
    if closes is None or len(closes) < 200:
        warnings.append(f"Need at least 200 daily bars for trend score; have "
                        f"{len(closes) if closes is not None else 0}. "
                        f"Call refresh_history({symbol!r}).")
    return QuadrantScoreResponse(
        symbol=symbol.upper(),
        value=sc["value"], quality=sc["quality"],
        momentum=sc["momentum"], trend=sc["trend"], total=sc["total"],
        raw=sc["raw"], warnings=warnings,
    )
```

- [ ] **Step 7: Run + commit**

```
uv run pytest tests/test_screener.py tests/test_server.py -v
```
Expected: existing tests still pass; new warning tests pass.

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/src/psx_mcp/screener.py psx-mcp/server.py psx-mcp/tests/test_screener.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): warnings for silent-failure cases in 4quadrant_score + screen"
```

---

### Task 6.3: Honest naming for `compute_quality_score`

The existing tool says "Piotroski-flavored" but only checks 2 of 9 signals. Don't rename (additive-only), but update the docstring to be precise.

**Files:**
- Modify: `psx-mcp/server.py` — update docstring
- Modify: `psx-mcp/README.md` — clarify description

- [ ] **Step 1: Update docstring**

In `server.py`, find the `@mcp.tool() async def compute_quality_score(symbol)` and replace its docstring with:

```
Simple 2-signal quality score (0..1). Signals:
  +0.5 if ROE ≥ 15%
  +0.5 if EPS is non-decreasing across the last 3 fiscal years

This is NOT a full Piotroski F-Score (which requires 9 signals including
balance-sheet items not yet populated; see Part-4 for headless-browser
sub-tab fetcher that will unlock ROIC, debt/equity, current ratio, etc.).
```

- [ ] **Step 2: Same fix in README tool table**

Replace the existing one-line description with the same precision.

- [ ] **Step 3: Commit**

```bash
git add psx-mcp/server.py psx-mcp/README.md
git commit -m "docs(psx-mcp): clarify compute_quality_score is 2-signal, not full Piotroski"
```

---

### Task 6.4: Verify or fix `get_news`

Per project memory `get_news` was returning `[]` despite cache having rows. Investigate and either:
- Document why it's empty (e.g., parser filter removes everything)
- Fix the bug

**Files:**
- Investigate: `psx-mcp/src/psx_mcp/news.py` and `server.py::_get_news_impl`
- Possibly modify: whatever fixes the bug

- [ ] **Step 1: Reproduce**

First inspect the actual signatures (they differ from project-memory notes):

```powershell
uv run python -c "from psx_mcp.cache import Cache; from psx_mcp.psx_client import PSXClient; from server import _refresh_news_impl, _get_news_impl; import asyncio; c=Cache('data/psx.db'); n=asyncio.run(_refresh_news_impl(c, PSXClient())); print('refreshed:', n); rows = _get_news_impl(c, symbol=None, since_days=30); print('returned rows:', len(rows))"
```

Adapt to the *actual* signature found in `server.py` — the kwargs above (`since_days`, `symbol`) match what's there now. If they've diverged, use what's there.

- [ ] **Step 2: Diagnose**

If `refreshed > 0` but `returned rows == 0`, inspect the SQL in `_get_news_impl` for filter bugs. If `refreshed == 0`, inspect feed-parser output. Either way, document the finding in a small commit:

```bash
git add psx-mcp/src/psx_mcp/news.py psx-mcp/server.py psx-mcp/tests/test_news.py
git commit -m "fix(psx-mcp): get_news <whatever the fix is>"
```

- [ ] **Step 3: If it's already working, just add a test guarding the path and commit**

If `_get_news_impl` returns the seeded rows correctly, the original "returns []" complaint may have already been silently fixed in analytics-v1/v2. Confirm with a test:

```python
def test_get_news_returns_cached_rows(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    cache.conn.execute(
        """INSERT INTO news(id, source, posted_at, title, url, symbols)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("n1", "dawn_business", datetime.now().isoformat(),
         "PSX hits new high", "https://dawn.com/...", "KSE100"),
    )
    cache.conn.commit()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_news_impl(cache, symbol=None, since_days=7)
    assert len(out) >= 1
    assert out[0].title == "PSX hits new high"
```

```bash
git add psx-mcp/tests/test_server.py
git commit -m "test(psx-mcp): regression test for get_news cache round-trip"
```

NOTE: this task may legitimately be a no-op (already works) — in that case the report should say so.

---

## Phase 7 — Backtest

### Task 7.1: `backtest_simple(filter_spec, hold_days=63, since='1y_ago')`

Buy any symbol that passes `filter_spec` at the close of each day, hold for `hold_days`, sell at close. Equal-weight position per signal. Aggregate return.

This is a **smoke-test-grade backtest**, not a production simulation. Documented caveats:
- No transaction costs / slippage / dividends.
- Raw prices (not bonus/split adjusted — see Phase-0 Q4 of analytics-v1).
- Per-signal independent positions (no portfolio constraint).
- Equal-weight at entry, no rebalance.

**Files:**
- Create: `psx-mcp/src/psx_mcp/backtest.py`
- Create: `psx-mcp/tests/test_backtest.py`
- Modify: `psx-mcp/src/psx_mcp/models.py` — `BacktestResponse`
- Modify: `psx-mcp/server.py` — impl + tool
- Test: extend `tests/test_server.py`

- [ ] **Step 1: Failing pure-function tests**

```python
# psx-mcp/tests/test_backtest.py
import pytest
from datetime import date, timedelta
from psx_mcp.backtest import backtest_simple


def test_backtest_simple_constant_uptrend_yields_positive_return():
    """One symbol, uptrending closes. Always pass the filter → consistent positive return."""
    today = date(2026, 5, 23)
    closes = {
        ("XYZ", today - timedelta(days=n)): 100.0 + (180 - n)
        for n in range(180)
    }
    # Filter: every day passes
    signals = {(today - timedelta(days=n)): ["XYZ"] for n in range(120)}
    out = backtest_simple(closes_by_sym_date=closes,
                          signals_by_date=signals,
                          hold_days=20)
    assert out["n_trades"] > 0
    # All trades profitable in monotone uptrend
    assert out["mean_return_pct"] > 0
    assert all(t["return_pct"] > 0 for t in out["trades"])


def test_backtest_simple_no_signals_returns_zero_trades():
    out = backtest_simple(closes_by_sym_date={}, signals_by_date={}, hold_days=20)
    assert out["n_trades"] == 0
    assert out["mean_return_pct"] is None


def test_backtest_simple_hold_past_data_end_drops_trade():
    """If signal date + hold_days > last available close, skip the trade."""
    today = date(2026, 5, 23)
    closes = {
        ("XYZ", today - timedelta(days=n)): 100.0 + (10 - n)
        for n in range(10)
    }
    signals = {today - timedelta(days=2): ["XYZ"]}  # need to hold 20 days from here
    out = backtest_simple(closes_by_sym_date=closes,
                          signals_by_date=signals,
                          hold_days=20)
    assert out["n_trades"] == 0
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement `backtest.py`**

```python
"""Smoke-test backtest. Equal-weight, fixed-hold, no costs."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional


def backtest_simple(closes_by_sym_date: dict[tuple[str, date], float],
                    signals_by_date: dict[date, list[str]],
                    hold_days: int = 63) -> dict:
    """Generate trades from signals; for each signal (date, [symbols]):
      For each symbol with a close on that date, buy at that close,
      sell at the close `hold_days` later (skip if no exit close exists).

    Returns:
      {n_trades, mean_return_pct, median_return_pct, total_return_pct,
       win_rate_pct, trades: [{symbol, entry_date, exit_date, entry, exit, return_pct}]}.
    All NULL safely if n_trades == 0.
    """
    trades = []
    for sig_date, symbols in sorted(signals_by_date.items()):
        exit_date = sig_date + timedelta(days=hold_days)
        for sym in symbols:
            entry = closes_by_sym_date.get((sym, sig_date))
            if entry is None or entry <= 0:
                continue
            exit_price = closes_by_sym_date.get((sym, exit_date))
            if exit_price is None:
                # Try nearest-trading-day forward up to 5 calendar days
                for delta in range(1, 6):
                    exit_price = closes_by_sym_date.get((sym, exit_date + timedelta(days=delta)))
                    if exit_price is not None:
                        exit_date_eff = exit_date + timedelta(days=delta)
                        break
                else:
                    continue
                exit_date_used = exit_date_eff
            else:
                exit_date_used = exit_date
            ret_pct = (exit_price / entry - 1.0) * 100.0
            trades.append({
                "symbol": sym, "entry_date": sig_date, "exit_date": exit_date_used,
                "entry": entry, "exit": exit_price, "return_pct": ret_pct,
            })
    if not trades:
        return {"n_trades": 0, "mean_return_pct": None,
                "median_return_pct": None, "total_return_pct": None,
                "win_rate_pct": None, "trades": []}
    rets = sorted(t["return_pct"] for t in trades)
    n = len(rets)
    mean_ret = sum(rets) / n
    median_ret = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    wins = sum(1 for r in rets if r > 0)
    win_rate = 100.0 * wins / n
    total_ret = mean_ret  # equal-weight basket of independent trades; not compounded
    return {"n_trades": n, "mean_return_pct": mean_ret,
            "median_return_pct": median_ret, "total_return_pct": total_ret,
            "win_rate_pct": win_rate, "trades": trades}
```

- [ ] **Step 4: Run, confirm pass**

- [ ] **Step 5: Add server impl + tool**

```python
# models.py
class BacktestResponse(Disclaimer):
    filter_spec: dict
    hold_days: int
    since: str
    n_trades: int
    mean_return_pct: Optional[float] = None
    median_return_pct: Optional[float] = None
    total_return_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    trades: list[dict] = []
    caveats: list[str]
    note: Optional[str] = None
```

```python
# server.py
from psx_mcp.backtest import backtest_simple as _backtest_simple_pure
from psx_mcp.models import BacktestResponse


BACKTEST_CAVEATS = [
    "No transaction costs / slippage / spread.",
    "No dividend reinvestment.",
    "Raw prices — bonus/split adjustment status indeterminate (see analytics-v1 Q4).",
    "Per-signal independent positions; no portfolio-level constraint.",
    "Equal-weight at entry; no rebalance.",
    "Smoke-test grade — directional sanity check, NOT a production simulation.",
]


def _backtest_simple_impl(cache: Cache,
                          filter_spec: dict,
                          hold_days: int = 63,
                          since: str = "2025-01-01") -> BacktestResponse:
    """Run a smoke-test backtest using bars_daily.

    Strategy: each trading day in [since, today], compute which symbols pass the
    `filter_spec` (currently supports `pe_max`, `min_volume` only — keep narrow
    to avoid leaking forward-looking data). Buy at that day's close, sell
    `hold_days` later."""
    from datetime import date as _d, datetime as _dt
    from psx_mcp.screener import FilterSpec, screen

    since_date = _d.fromisoformat(since)
    # Gather all bars for all cached symbols
    rows = cache.conn.execute(
        "SELECT symbol, date, close FROM bars_daily ORDER BY date ASC"
    ).fetchall()
    closes_by_sym_date: dict[tuple[str, _d], float] = {}
    for r in rows:
        closes_by_sym_date[(r["symbol"], _d.fromisoformat(r["date"]))] = r["close"]

    # Naive signal generation: evaluate today's filter against today's
    # current_state — NOTE: this leaks today's quote/fundamentals into past
    # signals. For a smoke test only. Real backtest needs as-of-date fundamentals.
    spec = FilterSpec(**{k: v for k, v in filter_spec.items() if v is not None})
    candidate_rows = screen(cache, spec)
    candidate_syms = [r["symbol"] for r in candidate_rows]

    # Build per-symbol date index ONCE so signal generation is O(total_bars
    # + candidates × candidate_bars) instead of O(symbols × all_bars × candidates).
    dates_by_sym: dict[str, list[_d]] = {}
    for (s, d) in closes_by_sym_date.keys():
        dates_by_sym.setdefault(s, []).append(d)

    signals_by_date: dict[_d, list[str]] = {}
    for sym in candidate_syms:
        for d in dates_by_sym.get(sym, []):
            if d < since_date:
                continue
            signals_by_date.setdefault(d, []).append(sym)

    result = _backtest_simple_pure(
        closes_by_sym_date=closes_by_sym_date,
        signals_by_date=signals_by_date,
        hold_days=hold_days,
    )
    return BacktestResponse(
        filter_spec=filter_spec, hold_days=hold_days, since=since,
        n_trades=result["n_trades"],
        mean_return_pct=result["mean_return_pct"],
        median_return_pct=result["median_return_pct"],
        total_return_pct=result["total_return_pct"],
        win_rate_pct=result["win_rate_pct"],
        trades=[{**t, "entry_date": t["entry_date"].isoformat(),
                 "exit_date": t["exit_date"].isoformat()} for t in result["trades"]],
        caveats=BACKTEST_CAVEATS,
        note=("This is a SMOKE-TEST backtest. Today's fundamentals are used to "
              "generate past signals, which leaks information forward. Treat "
              "results as directional sanity only — do not rely on Sharpe/winrate "
              "for live position sizing."),
    )


@mcp.tool()
async def backtest_simple(filter_spec: dict,
                          hold_days: int = 63,
                          since: str = "2025-01-01") -> BacktestResponse:
    """Smoke-test backtest of a simple buy-on-signal/sell-after-hold strategy.
    filter_spec keys correspond to FilterSpec fields (pe_max, min_volume, etc.).
    Reads caveats list carefully before relying on results."""
    return _backtest_simple_impl(_cache, filter_spec, hold_days, since)
```

- [ ] **Step 6: Run + commit**

```
uv run pytest tests/test_backtest.py tests/test_server.py -k backtest -v
```
Use `timeout=180000`.

```bash
git add psx-mcp/src/psx_mcp/backtest.py psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_backtest.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): backtest_simple — smoke-test backtest with explicit caveats"
```

---

## Phase 8 — Documentation & release

### Task 8.1: README + playbook updates

- [ ] **Step 1: Update `psx-mcp/README.md` tool table**

Add rows for every new tool from Phases 1–7:
- `compute_drawdown(symbol)` — current and max drawdown
- `compute_risk_metrics(symbol, rf_annual=0)` — vol + Sharpe + max DD
- `compute_relative_strength(symbol, index_code='KSE100', window=252)` — RS vs index
- `compute_correlation(symbols)` — pairwise return correlation matrix
- `rank_sectors(sectors?, by='avg_change_pct')` — sector rotation
- `rank_universe(by='composite', sector?, limit=20)` — cross-sectional top-N
- `get_full_analysis(symbol)` — one-shot research dashboard
- `compute_position_size(symbol, portfolio_value, risk_pct, stop_atr_mult)` — ATR-based sizing
- `get_cache_status()` — table-by-table freshness summary
- `refresh_universe(symbols?, sector?)` — bulk history refresh
- `get_upcoming_events(lookback_days=14)` — Board Meeting / AGM / EGM titles
- `list_watchlist_with_scores()` — watchlist + composite scores
- `backtest_simple(filter_spec, hold_days, since)` — smoke-test backtest

Annotate existing tools:
- `compute_quality_score` — clarify 2-signal vs full Piotroski
- `compute_4quadrant_score` — now returns `warnings`
- `screen_symbols` — now returns `warnings` (skipped-bars count)
- Alert rules — add note about new `fundamental` type

- [ ] **Step 2: Update `docs/investing-playbook.md`**

In Part 1 gap table mark resolved:
- `compute_beta` ✅ analytics-v2
- `compute_quality_score` ✅ (partial, 2-signal) analytics-v2
- `compute_4quadrant_score` ✅ analytics-v2
- Drawdown ✅ analytics-v3 (NEW)
- Volatility / Sharpe ✅ analytics-v3 (NEW)
- Relative strength ✅ analytics-v3 (NEW)
- Correlation matrix ✅ analytics-v3 (NEW)
- Sector rotation ✅ analytics-v3 (NEW)
- Cross-sectional ranking ✅ analytics-v3 (NEW)
- Position sizing ✅ analytics-v3 (NEW)
- Cache status surface ✅ analytics-v3 (NEW)
- Bulk refresh ✅ analytics-v3 (NEW)
- Upcoming events heuristic ✅ analytics-v3 (NEW, title-based — actual dates require PDF)
- Watchlist with scores ✅ analytics-v3 (NEW)
- Fundamental alert triggers ✅ analytics-v3 (NEW)
- Backtest smoke test ✅ analytics-v3 (NEW)

In Part 6 (roadmap), add at the end:
"**analytics-v3** completes the analytical-tool surface (risk, ranking, sizing, dashboard, backtest). **Part 4** will populate ROE/PB/payout via a headless-browser sub-tab fetcher, unlock the full 9-signal Piotroski F-Score, and add macro context (USD/PKR, policy rate)."

- [ ] **Step 3: Commit**

```bash
git add psx-mcp/README.md docs/investing-playbook.md
git commit -m "docs(psx-mcp): document Part-3 analytics tools (risk, ranking, dashboard, backtest)"
```

---

### Task 8.2: Full suite gate + `analytics-v3` tag

- [ ] **Step 1: Run the full suite**

```
uv run pytest -v
```
With `timeout=600000`.

Expected: all green (target ~180+ tests up from 143 in analytics-v2).

- [ ] **Step 2: Tag the release (annotated, no push)**

```bash
cd C:/Users/pc/work/stocks/psx
git tag -a analytics-v3 -m "PSX MCP Analytics Upgrade Part 3 — risk metrics, ranking, dashboard, position sizing, backtest"
```

- [ ] **Step 3: Verify and report**

```bash
git tag -l "analytics*"
git log --oneline analytics-v2..analytics-v3
```

Report final test count, tag SHA, list of commits.

---

## Self-Review

**1. Spec coverage** — Compared against the Part-3 gap list shared with the user:
- Tier 1 risk & dashboards (drawdown, risk, RS, correlation, dashboard, sector/universe rank, position size) ✅ Tasks 1.x, 2.x, 3.1, 4.1
- Tier 2 operational completeness (bulk refresh, cache status, upcoming events, watchlist scores) ✅ Tasks 5.x
- Tier 3 alerts & correctness (fundamental alerts, silent-failure warnings, naming, news fix) ✅ Tasks 6.x
- Tier 4 backtest ✅ Task 7.1
- Tier 4 deferred (ROE/PB/F-Score full, macro, sentiment) — explicitly out-of-scope, documented in plan front matter and Phase 8 roadmap note.

**2. Placeholder scan** — every code step contains real code or an explicit reference (e.g., "the existing `_refresh_history_impl`" with a note about refactoring it if missing).

**3. Type consistency** — verified:
- `Cache.closes_for_with_dates` returns `list[tuple[str, float]]` consistent in Tasks 1.2, 1.3, 4.1.
- `Cache.cache_status` returns `dict` consistent with `CacheStatusResponse.tables`.
- `backtest_simple` pure-function returns dict; server impl maps to `BacktestResponse`.
- All response models inherit `Disclaimer`.
- All new tools follow `@mcp.tool() async def name(...) -> ModelResponse: return _name_impl(_cache, ...)` shape.

**4. Constraint check** — re-read user's constraints:
- "Only PSX DPS endpoints already accessible" — no new endpoints used; risk/ranking/dashboard read existing cache only; `refresh_universe` calls existing `refresh_history`.
- "No paid feeds, no scraping" — none added.
- "No macro, no news/sentiment" — explicitly deferred to Part 4.
- Compliant.

**5. Reviewer-flagged carryovers from Part-2 final review:**
- `_compute_beta_impl` raw SQL — RESOLVED via `closes_for_with_dates` helper (Task 1.2).
- `screener.screen()` N+1 — already fixed in Part-2 Task 1.2.
- Silent failure warnings — RESOLVED in Task 6.2.
- `_get_market_summary_impl` None guard, UTC timestamps — already shipped in Part-2 Task 1.3.

---

## What this plan deliberately does NOT cover

These belong to a future Part-4 plan:

- **ROE / P/B / payout population** — Phase 0 of Part-2 found sub-tabs SPA-rendered; needs headless browser.
- **Real 9-signal Piotroski F-Score** — depends on balance-sheet fields above.
- **SBP macro feed** (policy rate, USD/PKR, CPI) — user constraint forbids scraping.
- **News headlines / sentiment beyond cached RSS feeds** — same constraint.
- **Portfolio P&L tracking / trade journal** — project non-goal.
- **Real backtest** (as-of-date fundamentals, transaction costs, dividends) — needs more data than free PSX provides.
- **Tax-aware sizing or after-tax returns** — out of scope.

When Part 4 starts, the priority order is:
1. Headless-browser sub-tab fetcher → unlocks ROE/PB/payout → unlocks full F-Score + populated quality/value filters.
2. PDF-body fetcher for announcements → unlocks accurate `get_upcoming_events` dates and earnings calendar.
3. SBP macro scraper (if constraint relaxed).
