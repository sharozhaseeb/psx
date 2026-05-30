# PSX MCP Analytics Upgrade — Part 4: Extended Metrics

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the metric-coverage gap for serious stock and sector analysis. Add Sortino / Calmar / Information / Omega ratios, VaR / CVaR / skewness / kurtosis / tail ratio, drawdown duration & Ulcer Index, CAGR + rolling-return distributions + win rate, up/down capture, sector dispersion + sector relative strength, universe z-score / percentile primitives, and four missing technical indicators (ADX, Stochastic, OBV, Williams %R). Surface all of these via a single unified `get_extended_risk_metrics(symbol)` dashboard plus targeted MCP tools per family.

**Architecture:** Same pattern as Parts 1-3 — pure-function modules expose primitives, server impls compose them into Disclaimer-mixin response models, async `@mcp.tool()` wrappers expose the impls. Three new modules: `risk_extended.py` (return-distribution and drawdown deep-dive), `cross_section.py` (z-score / percentile / sector-relative primitives), and extension of existing `indicators.py` (ADX / Stochastic / OBV / Williams %R).

**Tech Stack:** Python 3.12, FastMCP, pandas/numpy, pytest, uv. No new dependencies.

**Constraints (carried forward from Parts 1-3):**
- Only `dps.psx.com.pk` endpoints already in use; no new external data sources.
- No paid feeds; no macro feed; no scraping outside the existing PSX endpoints.
- Additive only — no removed fields, no renamed tools.
- async wrapper → sync `_impl(cache, ...)` → optional Cache helper pattern.
- Pydantic v2: validators are `@field_validator(..., mode="before") + @classmethod`.
- SQLite + ISO TEXT timestamps; no Claude attribution in commits.

---

## What is deliberately deferred to Part 5

- ROE / P/B / payout / dividend-yield population — needs headless-browser sub-tab fetcher (Phase 0 of Part 2 found these are SPA-rendered).
- Treynor ratio — depends on a rolling-window beta computation that needs Part 4 sector_history accumulation first.
- Sector P/E percentile vs own history — requires us to accumulate sector_summary snapshots over time; add a `sector_history` table in Part 5.
- Bollinger band width, Keltner channels, Heikin-Ashi candles — not requested.
- News sentiment, macro feed, F-Score — explicit user constraints.

---

## File Structure

### Ordering conventions (carried from Part 3)

| Method | Order |
|---|---|
| `Cache.closes_for(symbol)` | oldest first |
| `Cache.closes_for_with_dates(symbol)` | oldest first |
| `Cache.get_index_history(code)` | oldest first |
| `Cache.get_fundamentals_history(symbol)` | newest year first |
| `Cache.get_dividend_history(symbol)` | newest ex-date first |

### New files

| Path | Responsibility |
|---|---|
| `psx-mcp/src/psx_mcp/risk_extended.py` | Pure functions: `sortino`, `calmar`, `information_ratio`, `omega_ratio`, `var_historical`, `cvar_historical`, `skewness`, `kurtosis`, `tail_ratio`, `drawdown_details`, `ulcer_index`, `cagr`, `rolling_returns`, `win_rate`, `up_down_capture`. No I/O. |
| `psx-mcp/src/psx_mcp/cross_section.py` | Pure-ish helpers (read from cache, compute, return): `z_score`, `percentile_rank`, `sector_dispersion`, `sector_relative_strength`. |
| `psx-mcp/tests/test_risk_extended.py` | Tests for `risk_extended.py` with synthetic series. |
| `psx-mcp/tests/test_cross_section.py` | Tests for `cross_section.py` with seeded caches. |
| `psx-mcp/tests/test_indicators_extended.py` | Tests for new indicators (ADX, Stochastic, OBV, Williams %R). |
| `psx-mcp/tests/test_dashboard_extended.py` | Integration tests for the new `get_extended_risk_metrics` dashboard. |

### Modified files

| Path | What changes |
|---|---|
| `psx-mcp/src/psx_mcp/indicators.py` | Add `adx`, `stochastic`, `obv`, `williams_r` pure functions (pandas-Series-based, matching existing style). |
| `psx-mcp/src/psx_mcp/models.py` | New response models: `ReturnStatsResponse`, `DistributionStatsResponse`, `DrawdownDetailsResponse`, `UpDownCaptureResponse`, `CrossSectionalRankResponse`, `SectorDispersionResponse`, `SectorRelativeStrengthResponse`, `ExtendedRiskMetricsResponse`. |
| `psx-mcp/server.py` | New impls + tools for each family + unified `get_extended_risk_metrics(symbol)` dashboard. Extend `compute_indicators` dispatch to accept new indicator names. |
| `psx-mcp/src/psx_mcp/screener.py` | Add `risk_metric` filters (`sortino_min`, `calmar_min`, `max_dd_max`) — additive on `FilterSpec`. |
| `psx-mcp/tests/test_screener.py` | Test the new screener filters. |
| `psx-mcp/README.md` | Tool-table updates. |
| `docs/investing-playbook.md` | Mark Tier-1 resolved gaps. Add Part-5 outlook. |

---

## Phase 1 — Return characterization (foundational — used by later phases)

### Task 1.1: Pure-function return primitives

**Files:**
- Create: `psx-mcp/src/psx_mcp/risk_extended.py`
- Create: `psx-mcp/tests/test_risk_extended.py`

- [ ] **Step 1: Write failing tests**

```python
# psx-mcp/tests/test_risk_extended.py
import pytest
import pandas as pd
import numpy as np
from psx_mcp.risk_extended import cagr, rolling_returns, win_rate


def test_cagr_doubling_in_one_year():
    """Stock that doubles over 252 trading days → CAGR = 100%."""
    closes = pd.Series([100.0 * (2 ** (i / 252)) for i in range(253)])
    result = cagr(closes, periods_per_year=252)
    assert result == pytest.approx(1.0, abs=0.01)


def test_cagr_flat_series_is_zero():
    closes = pd.Series([100.0] * 100)
    assert cagr(closes, periods_per_year=252) == pytest.approx(0.0)


def test_cagr_returns_none_on_short_series():
    closes = pd.Series([100.0])
    assert cagr(closes, periods_per_year=252) is None


def test_rolling_returns_yields_expected_count():
    """50 closes, window=20 → 30 rolling returns (50-20)."""
    closes = pd.Series([100.0 + i for i in range(50)])
    result = rolling_returns(closes, window=20)
    assert len(result) == 30
    # Each entry should be a percentage return (decimal)
    assert all(isinstance(r, float) for r in result)


def test_rolling_returns_short_series_returns_empty():
    closes = pd.Series([100.0, 101.0])
    assert rolling_returns(closes, window=20) == []


def test_win_rate_alternating_returns():
    """50 closes alternating up-down → win rate ≈ 50%."""
    closes = pd.Series([100.0 + (i % 2) for i in range(50)])
    rate = win_rate(closes)
    assert 40.0 <= rate <= 60.0


def test_win_rate_strict_uptrend_is_100():
    closes = pd.Series([100.0 + i for i in range(50)])
    rate = win_rate(closes)
    assert rate == pytest.approx(100.0)


def test_win_rate_empty_returns_none():
    closes = pd.Series([100.0])
    assert win_rate(closes) is None
```

- [ ] **Step 2: Run, confirm fail**

Run: `uv run pytest tests/test_risk_extended.py -v` with `timeout=60000`. Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `risk_extended.py`**

```python
"""Pure-function extensions to risk.py — return characterization, distribution,
drawdown details, downside metrics, capture ratios.

Each function takes pandas Series of closes (oldest first). No I/O, no caching."""
from __future__ import annotations
from typing import Optional
import math
import pandas as pd
import numpy as np


TRADING_DAYS = 252


def cagr(closes: pd.Series, periods_per_year: int = TRADING_DAYS) -> Optional[float]:
    """Compound annual growth rate. Returns decimal (0.10 = +10%/year).
    None if < 2 closes or start <= 0."""
    if closes is None or len(closes) < 2:
        return None
    start = float(closes.iloc[0])
    end = float(closes.iloc[-1])
    if start <= 0:
        return None
    years = (len(closes) - 1) / periods_per_year
    if years <= 0:
        return None
    return float((end / start) ** (1 / years) - 1)


def rolling_returns(closes: pd.Series, window: int) -> list[float]:
    """Return list of N-bar % returns. Each value is decimal (0.05 = +5%).
    Empty list if len(closes) <= window."""
    if closes is None or len(closes) <= window:
        return []
    out = []
    for i in range(len(closes) - window):
        start = float(closes.iloc[i])
        end = float(closes.iloc[i + window])
        if start > 0:
            out.append(end / start - 1.0)
    return out


def win_rate(closes: pd.Series) -> Optional[float]:
    """Percentage of bar-over-bar returns that are positive.
    Returns None if < 2 closes."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    return float((rets > 0).sum() / len(rets) * 100.0)
```

- [ ] **Step 4: Run, confirm pass**

Run: `uv run pytest tests/test_risk_extended.py -v`. Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/risk_extended.py psx-mcp/tests/test_risk_extended.py
git commit -m "feat(psx-mcp): CAGR, rolling_returns, win_rate primitives"
```

---

### Task 1.2: Wire `compute_return_stats` MCP tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add `ReturnStatsResponse` to `models.py`**

After the existing `RiskMetricsResponse`, add:

```python
class ReturnStatsResponse(Disclaimer):
    symbol: str
    cagr_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    rolling_return_window_days: int
    rolling_returns_best_pct: Optional[float] = None
    rolling_returns_worst_pct: Optional[float] = None
    rolling_returns_median_pct: Optional[float] = None
    n_bars: int
    note: Optional[str] = None
```

- [ ] **Step 2: Failing server-level test**

Add to `psx-mcp/tests/test_server.py`:

```python
def test_compute_return_stats_uptrend_cagr_positive(tmp_path):
    """260 strictly uptrending bars → positive CAGR + 100% win rate."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=259 - i),
                open=100.0+i, high=100.0+i, low=100.0+i,
                close=100.0+i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_return_stats_impl(cache, "XYZ", rolling_window_days=20)
    assert out.cagr_pct is not None and out.cagr_pct > 0
    assert out.win_rate_pct == pytest.approx(100.0)
    assert out.n_bars == 260
    assert out.rolling_returns_best_pct is not None
```

- [ ] **Step 3: Run, confirm fail**

Run: `uv run pytest tests/test_server.py -k return_stats -v`. Expected: AttributeError.

- [ ] **Step 4: Implement impl + tool in `server.py`**

Add imports near other `psx_mcp.risk` imports:

```python
from psx_mcp.risk_extended import (
    cagr, rolling_returns, win_rate,
)
from psx_mcp.models import ReturnStatsResponse
```

Add impl + wrapper:

```python
def _compute_return_stats_impl(cache: Cache, symbol: str,
                                rolling_window_days: int = 20) -> ReturnStatsResponse:
    closes = pd.Series(cache.closes_for(symbol))
    if len(closes) < 2:
        return ReturnStatsResponse(
            symbol=symbol.upper(),
            rolling_return_window_days=rolling_window_days,
            n_bars=int(len(closes)),
            note=f"Need >= 2 bars; have {len(closes)}. "
                 f"Call refresh_history({symbol!r}).",
        )
    cagr_val = cagr(closes)
    wr = win_rate(closes)
    rolls = rolling_returns(closes, window=rolling_window_days)
    rolls_sorted = sorted(rolls) if rolls else []
    return ReturnStatsResponse(
        symbol=symbol.upper(),
        cagr_pct=(cagr_val * 100.0) if cagr_val is not None else None,
        win_rate_pct=wr,
        rolling_return_window_days=rolling_window_days,
        rolling_returns_best_pct=(rolls_sorted[-1] * 100.0) if rolls_sorted else None,
        rolling_returns_worst_pct=(rolls_sorted[0] * 100.0) if rolls_sorted else None,
        rolling_returns_median_pct=(rolls_sorted[len(rolls_sorted) // 2] * 100.0)
                                    if rolls_sorted else None,
        n_bars=int(len(closes)),
        note=None,
    )


@mcp.tool()
async def compute_return_stats(symbol: str,
                                rolling_window_days: int = 20) -> ReturnStatsResponse:
    """Return-characterization stats: CAGR, win rate, rolling-N-day-return
    best/worst/median. CAGR is annualized compound return over the full cached
    series. Rolling window defaults to 20 trading days (~1 calendar month)."""
    return _compute_return_stats_impl(_cache, symbol, rolling_window_days)
```

- [ ] **Step 5: Run, confirm pass**

Run: `uv run pytest tests/test_server.py -k return_stats -v`. Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_return_stats MCP tool — CAGR + win rate + rolling returns"
```

---

## Phase 2 — Risk-adjusted ratio extensions

### Task 2.1: Sortino, Calmar, Information ratio, Omega

**Files:**
- Modify: `psx-mcp/src/psx_mcp/risk_extended.py`
- Modify: `psx-mcp/tests/test_risk_extended.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_risk_extended.py`:

```python
from psx_mcp.risk_extended import (
    sortino, calmar, information_ratio, omega_ratio,
)


def test_sortino_positive_drift_positive():
    """Positive-drift series with mostly small swings → positive Sortino."""
    rng = np.random.default_rng(11)
    rets = rng.normal(loc=0.0008, scale=0.012, size=500)
    closes = pd.Series(np.exp(np.cumsum(rets)) * 100.0)
    s = sortino(closes, rf_annual=0.0)
    assert s is not None and s > 0


def test_sortino_no_downside_returns_none():
    """Pure uptrend → no downside returns → Sortino undefined → None."""
    closes = pd.Series([100.0 + i for i in range(50)])
    assert sortino(closes, rf_annual=0.0) is None


def test_calmar_known_trajectory():
    """100→200 over 252 bars (CAGR=100%), trajectory dips to 80 once (MaxDD=-60% peak-relative).
    Calmar = CAGR / |MaxDD|."""
    # First half rises to 200, dips to 80 once, then back to 200
    n = 252
    closes = list(100.0 + i for i in range(n))
    # Replace mid-point with a dip
    closes[n // 2] = 80.0
    closes = pd.Series(closes)
    c = calmar(closes)
    assert c is not None
    # End at 351 from start 100 over 251 bars → CAGR ~250% over 1y; large positive Calmar
    assert c > 0


def test_calmar_no_drawdown_returns_none():
    """Pure uptrend has 0 max DD → Calmar undefined."""
    closes = pd.Series([100.0 + i for i in range(252)])
    assert calmar(closes) is None


def test_information_ratio_outperformer_is_positive():
    """Stock outpaces benchmark on average; both have noise so tracking error > 0.
    Fixes B1: degenerate constant-drift series produce te=0 and IR=None."""
    rng = np.random.default_rng(29)
    n = 500
    bench_rets = rng.normal(loc=0.0003, scale=0.01, size=n)
    # Stock has higher drift but its own noise (NOT a constant beta * bench)
    stock_rets = bench_rets + rng.normal(loc=0.0005, scale=0.005, size=n)
    bench = pd.Series(np.exp(np.cumsum(bench_rets)) * 100.0)
    stock = pd.Series(np.exp(np.cumsum(stock_rets)) * 100.0)
    ir = information_ratio(stock, bench)
    assert ir is not None and ir > 0


def test_information_ratio_identical_returns_none():
    """If stock == benchmark, tracking error is 0 → IR undefined."""
    s = pd.Series([100.0 + i for i in range(252)])
    assert information_ratio(s, s.copy()) is None


def test_omega_threshold_zero_above_one_on_positive_drift():
    """Threshold 0 means 'better than break-even'. Positive-drift series → omega > 1."""
    closes = pd.Series([100.0 + i * 0.5 for i in range(200)])
    o = omega_ratio(closes, threshold=0.0)
    assert o is not None and o > 1.0


def test_omega_threshold_very_high_below_one():
    """Threshold above any rolling return → omega < 1 (mostly losses vs threshold)."""
    closes = pd.Series([100.0 + i * 0.1 for i in range(100)])
    o = omega_ratio(closes, threshold=0.50)  # need 50% per-bar return to beat
    assert o is not None and o < 1.0
```

- [ ] **Step 2: Run, confirm fail**

Run: `uv run pytest tests/test_risk_extended.py -v -k "sortino or calmar or information_ratio or omega"`. Expected: ImportError on the new symbols.

- [ ] **Step 3: Implement in `risk_extended.py`**

Append:

```python
def sortino(closes: pd.Series, rf_annual: float = 0.0) -> Optional[float]:
    """Sortino ratio: excess-return / downside-deviation, annualized.

    Sortino punishes only NEGATIVE volatility (better than Sharpe for retail
    investors who only care about losses). Returns None if no downside returns
    exist or series too short.

    FORMULA NOTE (M1): This implementation uses the "downside-distribution stdev"
    variant — sqrt(mean of squared excess returns conditional on excess < 0).
    The classical Sortino-1991 paper uses target downside deviation:
    sqrt(sum(min(0, excess)^2) / N_total). Our variant divides by N_downside
    instead of N_total, which produces a smaller denominator and thus a LARGER
    Sortino value on series with infrequent drawdowns. Numerical magnitudes are
    NOT directly comparable to fund-industry-reported Sortino. Use for ordinal
    ranking across PSX names (which all use the same convention), not for
    absolute comparison vs published benchmarks."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    daily_rf = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    excess = rets - daily_rf
    downside = excess[excess < 0]
    if len(downside) == 0:
        return None
    dd_std = float(np.sqrt((downside ** 2).mean()))
    if dd_std == 0:
        return None
    return float(excess.mean() / dd_std * math.sqrt(TRADING_DAYS))


def calmar(closes: pd.Series) -> Optional[float]:
    """Calmar ratio: CAGR / |Max Drawdown|. Higher is better.

    Directly answers 'what return did I earn for the worst drawdown I'd have
    sat through?' Returns None if no drawdown (pure uptrend) or short series."""
    if closes is None or len(closes) < 2:
        return None
    cagr_val = cagr(closes)
    if cagr_val is None:
        return None
    # Max DD as negative percent (e.g., -33.33). Use abs.
    values = closes.reset_index(drop=True)
    running_max = values.cummax()
    dd = (values / running_max - 1.0)
    max_dd = float(dd.min())
    if max_dd >= 0:
        return None
    return float(cagr_val / abs(max_dd))


def information_ratio(stock_closes: pd.Series,
                      benchmark_closes: pd.Series) -> Optional[float]:
    """Information ratio: (excess return over benchmark) / tracking error.
    Annualized. Best measure of 'alpha per unit of benchmark-tracking risk'."""
    if stock_closes is None or benchmark_closes is None:
        return None
    if len(stock_closes) < 2 or len(benchmark_closes) < 2:
        return None
    s_rets = stock_closes.pct_change().dropna().reset_index(drop=True)
    b_rets = benchmark_closes.pct_change().dropna().reset_index(drop=True)
    n = min(len(s_rets), len(b_rets))
    if n < 2:
        return None
    active = s_rets.iloc[-n:].values - b_rets.iloc[-n:].values
    te = float(np.std(active, ddof=1))
    if te == 0:
        return None
    return float(np.mean(active) / te * math.sqrt(TRADING_DAYS))


def omega_ratio(closes: pd.Series, threshold: float = 0.0) -> Optional[float]:
    """Omega ratio: ratio of gains-above-threshold to losses-below-threshold.

    Uses the FULL return distribution (better than Sharpe for fat-tailed series).
    threshold is per-bar return; default 0.0 means 'better than break-even'.
    Omega > 1 = more upside than downside; < 1 = the reverse."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    excess = rets - threshold
    gains = excess[excess > 0].sum()
    losses = -excess[excess < 0].sum()
    if losses == 0:
        return None  # undefined when no losses
    return float(gains / losses)
```

- [ ] **Step 4: Run, confirm 8 new tests pass**

```
uv run pytest tests/test_risk_extended.py -v
```

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/risk_extended.py psx-mcp/tests/test_risk_extended.py
git commit -m "feat(psx-mcp): Sortino, Calmar, Information ratio, Omega ratio primitives"
```

---

### Task 2.2: Tail risk — VaR, CVaR, skewness, kurtosis, tail ratio

**Files:**
- Modify: `psx-mcp/src/psx_mcp/risk_extended.py`
- Modify: `psx-mcp/tests/test_risk_extended.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_risk_extended.py`:

```python
from psx_mcp.risk_extended import (
    var_historical, cvar_historical, skewness, kurtosis_excess, tail_ratio,
)


def test_var_historical_5pct_lossy_series():
    """A series with known 5%-tail loss should give VaR matching that loss."""
    # 100 returns: 95 small gains, 5 of -10% each.
    rets = [0.001] * 95 + [-0.10] * 5
    closes = [100.0]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    s = pd.Series(closes)
    v = var_historical(s, confidence=0.05)
    # 5th-percentile return ≈ -0.10 (-10%)
    assert v is not None
    assert -0.11 <= v <= -0.09


def test_cvar_is_worse_than_var():
    """CVaR (average of worst 5%) is at least as negative as VaR (5th-pctile)."""
    rng = np.random.default_rng(13)
    rets = rng.normal(loc=0.0, scale=0.02, size=500)
    closes = pd.Series(np.exp(np.cumsum(rets)) * 100.0)
    v = var_historical(closes, confidence=0.05)
    cv = cvar_historical(closes, confidence=0.05)
    assert v is not None and cv is not None
    assert cv <= v


def test_skewness_normal_series_near_zero():
    rng = np.random.default_rng(17)
    rets = rng.normal(loc=0.0, scale=0.01, size=2000)
    closes = pd.Series(np.exp(np.cumsum(rets)) * 100.0)
    sk = skewness(closes)
    assert sk is not None and -0.3 < sk < 0.3


def test_kurtosis_excess_normal_series_near_zero():
    rng = np.random.default_rng(19)
    rets = rng.normal(loc=0.0, scale=0.01, size=2000)
    closes = pd.Series(np.exp(np.cumsum(rets)) * 100.0)
    k = kurtosis_excess(closes)
    assert k is not None
    # Excess kurtosis of normal ≈ 0; tolerate sampling noise
    assert -0.5 < k < 1.0


def test_tail_ratio_uptrend_above_one():
    """Strict uptrend → best returns dominate worst → tail ratio > 1."""
    closes = pd.Series([100.0 + i for i in range(100)])
    tr = tail_ratio(closes)
    assert tr is not None and tr > 1.0


def test_tail_ratio_no_returns_returns_none():
    closes = pd.Series([100.0])
    assert tail_ratio(closes) is None
```

- [ ] **Step 2: Run, confirm import-error fail**

- [ ] **Step 3: Implement in `risk_extended.py`**

Append:

```python
def var_historical(closes: pd.Series, confidence: float = 0.05) -> Optional[float]:
    """Historical Value-at-Risk at the given confidence level.

    Returns the `confidence`-percentile of historical per-bar returns as a
    decimal (e.g., -0.05 = -5% worst-case 5% of the time). Confidence 0.05 =
    95% confidence on the loss side."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    return float(np.percentile(rets, confidence * 100.0))


def cvar_historical(closes: pd.Series, confidence: float = 0.05) -> Optional[float]:
    """Conditional VaR (Expected Shortfall) at the given confidence level.

    Average return in the worst `confidence` fraction of bars. Always at least
    as negative as `var_historical`. Better measure than VaR because it captures
    tail magnitude, not just the threshold."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    threshold = np.percentile(rets, confidence * 100.0)
    tail = rets[rets <= threshold]
    if len(tail) == 0:
        return float(threshold)
    return float(tail.mean())


def skewness(closes: pd.Series) -> Optional[float]:
    """Skewness of per-bar returns. Negative = more big losses than big gains
    (bad for investors). None on series too short."""
    if closes is None or len(closes) < 3:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 3:
        return None
    sd = float(rets.std(ddof=1))
    if sd == 0:
        return None
    return float(((rets - rets.mean()) ** 3).mean() / sd ** 3)


def kurtosis_excess(closes: pd.Series) -> Optional[float]:
    """Excess kurtosis of per-bar returns (= kurtosis - 3).

    > 0 means fatter tails than normal distribution (= more frequent extreme moves).
    Normal distribution has excess kurtosis = 0."""
    if closes is None or len(closes) < 4:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 4:
        return None
    sd = float(rets.std(ddof=1))
    if sd == 0:
        return None
    return float(((rets - rets.mean()) ** 4).mean() / sd ** 4 - 3.0)


def tail_ratio(closes: pd.Series, quantile: float = 0.05) -> Optional[float]:
    """Ratio: magnitude of (top-quantile gain) / (bottom-quantile loss).

    > 1 = positive asymmetry; < 1 = negative asymmetry. Default 0.05 compares
    best 5% of returns vs worst 5%."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    upper = float(np.percentile(rets, (1 - quantile) * 100.0))
    lower = float(np.percentile(rets, quantile * 100.0))
    if lower >= 0 or upper <= 0:
        return None  # no clear positive/negative tail to compare
    return float(abs(upper) / abs(lower))
```

- [ ] **Step 4: Run, confirm 6 new tests pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/risk_extended.py psx-mcp/tests/test_risk_extended.py
git commit -m "feat(psx-mcp): tail-risk metrics (VaR, CVaR, skewness, kurtosis, tail ratio)"
```

---

### Task 2.3: Drawdown deep-dive (duration, recovery, Ulcer Index, top-3)

**Files:**
- Modify: `psx-mcp/src/psx_mcp/risk_extended.py`
- Modify: `psx-mcp/tests/test_risk_extended.py`

- [ ] **Step 1: Failing tests**

```python
from psx_mcp.risk_extended import drawdown_details, ulcer_index


def test_drawdown_details_returns_all_fields():
    """100 → 120 (peak day 1) → 80 (trough day 2) → recovered to 120 by day 5."""
    closes = pd.Series([100.0, 120.0, 80.0, 100.0, 110.0, 120.0, 130.0])
    out = drawdown_details(closes)
    assert out["max_drawdown_pct"] == pytest.approx(-33.3333, abs=1e-3)
    assert out["peak_index"] == 1   # the 120
    assert out["trough_index"] == 2  # the 80
    assert out["recovery_index"] == 5  # when price re-hit 120
    assert out["drawdown_duration_bars"] == 1  # peak→trough = 1 bar
    assert out["recovery_duration_bars"] == 3  # trough→recovery = 3 bars


def test_drawdown_details_no_recovery_yet():
    """100 → 80 (still down) → recovery_index is None."""
    closes = pd.Series([100.0, 90.0, 85.0, 80.0])
    out = drawdown_details(closes)
    assert out["recovery_index"] is None


def test_drawdown_details_top_drawdowns_sorted():
    """Sequence with two distinct drawdown events; top_drawdowns is sorted by
    depth descending."""
    closes = pd.Series([
        100, 120, 100,  # DD-1: -16.67%
        130, 140, 100,  # DD-2: -28.57%
        145, 150,        # recover and new high
    ])
    out = drawdown_details(closes)
    tops = out["top_drawdowns"]
    assert len(tops) >= 2
    # First entry should be the biggest
    assert tops[0]["depth_pct"] < tops[1]["depth_pct"]


def test_ulcer_index_constant_series_is_zero():
    closes = pd.Series([100.0] * 50)
    assert ulcer_index(closes) == pytest.approx(0.0)


def test_ulcer_index_drawdown_series_is_positive():
    closes = pd.Series([100.0, 110.0, 90.0, 80.0, 100.0, 110.0])
    u = ulcer_index(closes)
    assert u is not None and u > 0
```

- [ ] **Step 2: Run, confirm import-error**

- [ ] **Step 3: Implement in `risk_extended.py`**

Append:

```python
def drawdown_details(closes: pd.Series) -> dict:
    """Comprehensive drawdown analysis.

    Returns: {
      max_drawdown_pct,
      peak_index, trough_index, recovery_index,
      drawdown_duration_bars,   # peak → trough
      recovery_duration_bars,   # trough → recovery (None if not recovered)
      top_drawdowns: list of up to 3 distinct DD events sorted by depth (deepest first),
                     each {peak_index, trough_index, depth_pct, recovery_index?}
    }

    A "distinct" drawdown event ends when the running max is re-achieved.
    """
    if closes is None or len(closes) < 2:
        return {
            "max_drawdown_pct": 0.0, "peak_index": None, "trough_index": None,
            "recovery_index": None, "drawdown_duration_bars": None,
            "recovery_duration_bars": None, "top_drawdowns": [],
        }
    values = closes.reset_index(drop=True)
    running_max = values.cummax()
    dd_series = (values / running_max - 1.0) * 100.0

    # Find max DD
    trough = int(dd_series.idxmin())
    max_dd_pct = float(dd_series.min())
    peak_val = float(running_max.iloc[trough])
    peak = int(values.iloc[:trough + 1].idxmax())

    # Recovery: first index > trough where values >= peak_val
    recovery = None
    for i in range(trough + 1, len(values)):
        if values.iloc[i] >= peak_val:
            recovery = i
            break

    # Enumerate ALL distinct drawdown events
    events = []
    current_peak_idx = 0
    in_dd = False
    cur_event_peak = None
    cur_event_trough = None
    cur_event_trough_val = float("inf")
    for i in range(1, len(values)):
        if values.iloc[i] >= running_max.iloc[i - 1] and not in_dd:
            current_peak_idx = i
            continue
        if values.iloc[i] < running_max.iloc[i]:
            # We're in a drawdown
            if not in_dd:
                in_dd = True
                cur_event_peak = current_peak_idx
                cur_event_trough = i
                cur_event_trough_val = float(values.iloc[i])
            else:
                if float(values.iloc[i]) < cur_event_trough_val:
                    cur_event_trough = i
                    cur_event_trough_val = float(values.iloc[i])
            # Did we recover?
            if values.iloc[i] >= float(running_max.iloc[cur_event_peak]):
                depth = (cur_event_trough_val / float(running_max.iloc[cur_event_peak]) - 1.0) * 100.0
                events.append({
                    "peak_index": cur_event_peak,
                    "trough_index": cur_event_trough,
                    "depth_pct": float(depth),
                    "recovery_index": i,
                })
                in_dd = False
                current_peak_idx = i
        elif values.iloc[i] >= running_max.iloc[i]:
            if in_dd:
                depth = (cur_event_trough_val / float(running_max.iloc[cur_event_peak]) - 1.0) * 100.0
                events.append({
                    "peak_index": cur_event_peak,
                    "trough_index": cur_event_trough,
                    "depth_pct": float(depth),
                    "recovery_index": i,
                })
                in_dd = False
            current_peak_idx = i

    # Trailing unrecovered drawdown
    if in_dd:
        depth = (cur_event_trough_val / float(running_max.iloc[cur_event_peak]) - 1.0) * 100.0
        events.append({
            "peak_index": cur_event_peak,
            "trough_index": cur_event_trough,
            "depth_pct": float(depth),
            "recovery_index": None,
        })

    top_drawdowns = sorted(events, key=lambda e: e["depth_pct"])[:3]

    return {
        "max_drawdown_pct": max_dd_pct,
        "peak_index": peak,
        "trough_index": trough,
        "recovery_index": recovery,
        "drawdown_duration_bars": trough - peak if trough > peak else None,
        "recovery_duration_bars": (recovery - trough) if recovery is not None else None,
        "top_drawdowns": top_drawdowns,
    }


def ulcer_index(closes: pd.Series) -> Optional[float]:
    """Ulcer Index: root-mean-square of drawdowns. Captures both depth and
    duration of drawdowns. 0 on a strictly non-decreasing series. Higher = more
    painful to hold."""
    if closes is None or len(closes) < 2:
        return None
    values = closes.reset_index(drop=True)
    running_max = values.cummax()
    dd_pct = (values / running_max - 1.0) * 100.0
    return float(np.sqrt((dd_pct ** 2).mean()))
```

- [ ] **Step 4: Run, confirm 5 new tests pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/risk_extended.py psx-mcp/tests/test_risk_extended.py
git commit -m "feat(psx-mcp): drawdown_details + ulcer_index — duration, recovery, top-3 DDs"
```

---

### Task 2.4: Up/down capture ratio

**Files:**
- Modify: `psx-mcp/src/psx_mcp/risk_extended.py`
- Modify: `psx-mcp/tests/test_risk_extended.py`

- [ ] **Step 1: Failing test**

```python
from psx_mcp.risk_extended import up_down_capture


def test_up_capture_high_beta_above_100():
    """If stock returns are 2x benchmark in up periods, up-capture = ~200%."""
    bench_rets = [0.01, 0.02, 0.015, -0.005, 0.01]
    stock_rets = [0.02, 0.04, 0.03, -0.005, 0.02]
    # Convert to price series
    bench = pd.Series([100.0])
    stock = pd.Series([100.0])
    for r in bench_rets:
        bench = pd.concat([bench, pd.Series([bench.iloc[-1] * (1 + r)])], ignore_index=True)
    for r in stock_rets:
        stock = pd.concat([stock, pd.Series([stock.iloc[-1] * (1 + r)])], ignore_index=True)
    # Use lists, not concat in production tests — this is small
    out = up_down_capture(stock, bench)
    assert out["up_capture_pct"] is not None
    assert out["up_capture_pct"] > 150.0  # stock outpaces bench in up periods


def test_down_capture_defensive_below_100():
    """Stock that drops half as fast as benchmark in down periods."""
    bench_rets = [0.01, -0.04, -0.02, 0.005, -0.03]
    stock_rets = [0.01, -0.02, -0.01, 0.005, -0.015]
    bench_vals = [100.0]
    stock_vals = [100.0]
    for r in bench_rets:
        bench_vals.append(bench_vals[-1] * (1 + r))
    for r in stock_rets:
        stock_vals.append(stock_vals[-1] * (1 + r))
    out = up_down_capture(pd.Series(stock_vals), pd.Series(bench_vals))
    assert out["down_capture_pct"] is not None
    assert out["down_capture_pct"] < 75.0  # defensive: caught less than half the downside


def test_up_down_capture_short_series_returns_none():
    s = pd.Series([100.0, 101.0])
    b = pd.Series([100.0, 101.0])
    out = up_down_capture(s, b)
    assert out["up_capture_pct"] is None
    assert out["down_capture_pct"] is None
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

```python
def up_down_capture(stock_closes: pd.Series,
                    benchmark_closes: pd.Series) -> dict:
    """Up/down capture ratios.

    For each period where benchmark return > 0, computes stock_return /
    benchmark_return; averages over all such periods → up_capture (as %).
    Same logic for benchmark return < 0 → down_capture.

    100% = matches the benchmark. > 100% on up-capture = aggressive/high-beta.
    < 100% on down-capture = defensive. Best profile: high up-capture + low
    down-capture.

    Both series are aligned by tail position (no date check)."""
    if stock_closes is None or benchmark_closes is None:
        return {"up_capture_pct": None, "down_capture_pct": None,
                "n_up_periods": 0, "n_down_periods": 0}
    if len(stock_closes) < 3 or len(benchmark_closes) < 3:
        return {"up_capture_pct": None, "down_capture_pct": None,
                "n_up_periods": 0, "n_down_periods": 0}
    s_rets = stock_closes.pct_change().dropna().reset_index(drop=True)
    b_rets = benchmark_closes.pct_change().dropna().reset_index(drop=True)
    n = min(len(s_rets), len(b_rets))
    s_rets = s_rets.iloc[-n:].values
    b_rets = b_rets.iloc[-n:].values
    up_mask = b_rets > 0
    down_mask = b_rets < 0
    up_cap = None
    down_cap = None
    if up_mask.sum() >= 1:
        b_up = b_rets[up_mask].mean()
        s_up = s_rets[up_mask].mean()
        if b_up != 0:
            up_cap = float(s_up / b_up * 100.0)
    if down_mask.sum() >= 1:
        b_dn = b_rets[down_mask].mean()
        s_dn = s_rets[down_mask].mean()
        if b_dn != 0:
            down_cap = float(s_dn / b_dn * 100.0)
    return {
        "up_capture_pct": up_cap,
        "down_capture_pct": down_cap,
        "n_up_periods": int(up_mask.sum()),
        "n_down_periods": int(down_mask.sum()),
    }
```

- [ ] **Step 4: Run, confirm 3 new tests pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/risk_extended.py psx-mcp/tests/test_risk_extended.py
git commit -m "feat(psx-mcp): up_down_capture ratios — aggressive vs defensive profile"
```

---

## Phase 3 — Wire the new metrics through MCP

### Task 3.1: `compute_distribution_stats` MCP tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add `DistributionStatsResponse` to `models.py`**

After `ReturnStatsResponse`:

```python
class DistributionStatsResponse(Disclaimer):
    symbol: str
    skewness: Optional[float] = None
    excess_kurtosis: Optional[float] = None
    var_5pct_pct: Optional[float] = None     # 5% VaR as percent
    cvar_5pct_pct: Optional[float] = None    # 5% Conditional VaR as percent
    tail_ratio_5pct: Optional[float] = None
    n_bars: int
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_compute_distribution_stats_seeded(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    import numpy as np
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    rng = np.random.default_rng(23)
    pcts = rng.normal(loc=0.0005, scale=0.015, size=300)
    closes = list(np.exp(np.cumsum(pcts)) * 100.0)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=299 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_distribution_stats_impl(cache, "XYZ")
    assert out.n_bars == 300
    assert out.var_5pct_pct is not None and out.var_5pct_pct < 0
    assert out.cvar_5pct_pct is not None and out.cvar_5pct_pct <= out.var_5pct_pct
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement impl + tool**

In `server.py`, extend imports:

```python
from psx_mcp.risk_extended import (
    cagr, rolling_returns, win_rate,
    sortino, calmar, information_ratio, omega_ratio,
    var_historical, cvar_historical, skewness, kurtosis_excess, tail_ratio,
    drawdown_details, ulcer_index, up_down_capture,
)
from psx_mcp.models import (
    ReturnStatsResponse, DistributionStatsResponse,
)
```

Add impl:

```python
def _compute_distribution_stats_impl(cache: Cache, symbol: str) -> DistributionStatsResponse:
    closes = pd.Series(cache.closes_for(symbol))
    if len(closes) < 4:
        return DistributionStatsResponse(
            symbol=symbol.upper(),
            n_bars=int(len(closes)),
            note=f"Need >= 4 bars; have {len(closes)}.",
        )
    var5 = var_historical(closes, confidence=0.05)
    cvar5 = cvar_historical(closes, confidence=0.05)
    return DistributionStatsResponse(
        symbol=symbol.upper(),
        skewness=skewness(closes),
        excess_kurtosis=kurtosis_excess(closes),
        var_5pct_pct=(var5 * 100.0) if var5 is not None else None,
        cvar_5pct_pct=(cvar5 * 100.0) if cvar5 is not None else None,
        tail_ratio_5pct=tail_ratio(closes, quantile=0.05),
        n_bars=int(len(closes)),
        note=None,
    )


@mcp.tool()
async def compute_distribution_stats(symbol: str) -> DistributionStatsResponse:
    """Return-distribution stats: skewness, excess kurtosis, 5% VaR/CVaR,
    tail ratio. Use to spot fat tails or asymmetric loss patterns that Sharpe
    misses."""
    return _compute_distribution_stats_impl(_cache, symbol)
```

- [ ] **Step 5: Run, commit**

```
uv run pytest tests/test_server.py -k distribution_stats -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_distribution_stats MCP tool"
```

---

### Task 3.2: `compute_drawdown_details` MCP tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add `DrawdownDetailsResponse` to `models.py`**

```python
class DrawdownDetailsResponse(Disclaimer):
    symbol: str
    max_drawdown_pct: float
    peak_index: Optional[int] = None
    trough_index: Optional[int] = None
    recovery_index: Optional[int] = None
    drawdown_duration_bars: Optional[int] = None
    recovery_duration_bars: Optional[int] = None
    ulcer_index: Optional[float] = None
    top_drawdowns: list[dict] = []
    n_bars: int
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_compute_drawdown_details_seeded(tmp_path):
    """A series that dips and recovers exposes the recovery_index field."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    closes = [100.0, 120.0, 80.0, 100.0, 110.0, 120.0, 130.0]
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=len(closes) - 1 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_drawdown_details_impl(cache, "XYZ")
    assert out.n_bars == 7
    assert out.max_drawdown_pct < -30  # the 120→80 dip
    assert out.recovery_index == 5
    assert out.ulcer_index is not None and out.ulcer_index > 0
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement impl + tool**

```python
def _compute_drawdown_details_impl(cache: Cache, symbol: str) -> DrawdownDetailsResponse:
    closes = pd.Series(cache.closes_for(symbol))
    if len(closes) < 2:
        return DrawdownDetailsResponse(
            symbol=symbol.upper(), max_drawdown_pct=0.0,
            n_bars=int(len(closes)),
            note=f"Need >= 2 bars; have {len(closes)}.",
        )
    dd = drawdown_details(closes)
    ulc = ulcer_index(closes)
    return DrawdownDetailsResponse(
        symbol=symbol.upper(),
        max_drawdown_pct=dd["max_drawdown_pct"],
        peak_index=dd["peak_index"],
        trough_index=dd["trough_index"],
        recovery_index=dd["recovery_index"],
        drawdown_duration_bars=dd["drawdown_duration_bars"],
        recovery_duration_bars=dd["recovery_duration_bars"],
        ulcer_index=ulc,
        top_drawdowns=dd["top_drawdowns"],
        n_bars=int(len(closes)),
        note=None,
    )


@mcp.tool()
async def compute_drawdown_details(symbol: str) -> DrawdownDetailsResponse:
    """Drawdown deep-dive: max DD, time-to-trough, time-to-recovery,
    Ulcer Index, top-3 distinct drawdown events. Critical for understanding
    holding-period pain."""
    return _compute_drawdown_details_impl(_cache, symbol)
```

- [ ] **Step 5: Run, commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_drawdown_details MCP tool"
```

---

### Task 3.3: `compute_up_down_capture` MCP tool

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Add `UpDownCaptureResponse`**

```python
class UpDownCaptureResponse(Disclaimer):
    symbol: str
    index_code: str
    up_capture_pct: Optional[float] = None
    down_capture_pct: Optional[float] = None
    n_up_periods: int = 0
    n_down_periods: int = 0
    n_aligned_bars: int = 0
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test**

```python
def test_compute_up_down_capture_aligned_series(tmp_path):
    """Aggressive stock — captures more upside and more downside than KSE-100."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    # Seed stock with 2x volatility vs index; both 100 → 110 → 95 → 105 trajectory
    bench_path = [100.0, 105.0, 95.0, 100.0, 110.0]
    stock_path = [100.0, 110.0, 85.0, 95.0, 120.0]
    for i, (b, s) in enumerate(zip(bench_path, stock_path)):
        d = today - timedelta(days=len(bench_path) - 1 - i)
        cache.upsert_bars([Bar(symbol="XYZ", date=d, open=s, high=s, low=s,
                                close=s, volume=1)])
        cache.upsert_index_bar(index_code="KSE100", bar_date=d, close=b, volume=1e8)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_up_down_capture_impl(cache, "XYZ", index_code="KSE100")
    assert out.up_capture_pct is not None and out.up_capture_pct > 100
    assert out.down_capture_pct is not None and out.down_capture_pct > 100
    assert out.n_aligned_bars == 5
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement**

```python
def _compute_up_down_capture_impl(cache: Cache, symbol: str,
                                    index_code: str = "KSE100") -> UpDownCaptureResponse:
    stock_pairs = cache.closes_for_with_dates(symbol)
    stock_by_date = dict(stock_pairs)
    idx_rows = cache.get_index_history(index_code)
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
    common = sorted(set(stock_by_date) & set(idx_by_date))
    if len(common) < 3:
        return UpDownCaptureResponse(
            symbol=symbol.upper(), index_code=index_code,
            n_aligned_bars=len(common),
            note=(f"Need at least 3 aligned bars; have {len(common)}. "
                  f"Call refresh_history({symbol!r}) and refresh_market."),
        )
    s = pd.Series([stock_by_date[d] for d in common])
    b = pd.Series([idx_by_date[d] for d in common])
    out = up_down_capture(s, b)
    return UpDownCaptureResponse(
        symbol=symbol.upper(), index_code=index_code,
        up_capture_pct=out["up_capture_pct"],
        down_capture_pct=out["down_capture_pct"],
        n_up_periods=out["n_up_periods"],
        n_down_periods=out["n_down_periods"],
        n_aligned_bars=len(common),
        note=None,
    )


@mcp.tool()
async def compute_up_down_capture(symbol: str,
                                   index_code: str = "KSE100") -> UpDownCaptureResponse:
    """Up/down capture vs an index. > 100% up-capture = aggressive; < 100%
    down-capture = defensive. Best profile: high up + low down."""
    return _compute_up_down_capture_impl(_cache, symbol, index_code)
```

- [ ] **Step 5: Run, commit**

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): compute_up_down_capture MCP tool"
```

---

## Phase 4 — Extended indicators (ADX, Stochastic, OBV, Williams %R)

### Task 4.1: Add four indicators to `indicators.py`

**Files:**
- Modify: `psx-mcp/src/psx_mcp/indicators.py`
- Create: `psx-mcp/tests/test_indicators_extended.py`

- [ ] **Step 1: Failing tests**

```python
# psx-mcp/tests/test_indicators_extended.py
import pytest
import pandas as pd
import numpy as np
from psx_mcp.indicators import adx, stochastic, obv, williams_r


def test_adx_strong_uptrend_above_25():
    """A clean uptrend should produce ADX > 25 (industry rule: 25 = trending)."""
    n = 60
    high = pd.Series([100.0 + i + 1 for i in range(n)])
    low = pd.Series([100.0 + i - 1 for i in range(n)])
    close = pd.Series([100.0 + i for i in range(n)])
    result = adx(high, low, close, window=14)
    assert result is not None and not pd.isna(result.iloc[-1])
    assert result.iloc[-1] > 25


def test_adx_choppy_is_lower_than_clean_trend():
    """Pure-noise series should produce a LOWER terminal ADX than the clean uptrend
    series from the prior test. Comparative assertion (fixes M3 — original
    'below 20' assertion was loose at < 50)."""
    rng = np.random.default_rng(31)
    n = 200
    base = 100.0
    closes = [base]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + rng.normal(0, 0.005)))
    high = pd.Series([c + 0.5 for c in closes])
    low = pd.Series([c - 0.5 for c in closes])
    close = pd.Series(closes)
    choppy_adx = adx(high, low, close, window=14).iloc[-1]

    # Clean uptrend reference
    n2 = 60
    h2 = pd.Series([100.0 + i + 1 for i in range(n2)])
    l2 = pd.Series([100.0 + i - 1 for i in range(n2)])
    c2 = pd.Series([100.0 + i for i in range(n2)])
    clean_adx = adx(h2, l2, c2, window=14).iloc[-1]

    assert choppy_adx < clean_adx


def test_stochastic_at_high_range_near_100():
    """Latest close at recent high → %K near 100."""
    high = pd.Series([100.0 + i for i in range(30)])
    low = pd.Series([95.0 + i for i in range(30)])
    close = pd.Series([99.5 + i for i in range(30)])
    result = stochastic(high, low, close, window=14)
    assert result is not None
    assert result["%K"].iloc[-1] > 80.0


def test_stochastic_at_low_range_near_zero():
    """Latest close at recent low → %K near 0."""
    high = pd.Series([105.0 - i * 0.1 for i in range(30)])
    low = pd.Series([100.0 - i * 0.1 for i in range(30)])
    close = pd.Series([100.5 - i * 0.1 for i in range(30)])
    result = stochastic(high, low, close, window=14)
    assert result["%K"].iloc[-1] < 30.0


def test_obv_uptrend_with_volume_is_monotonic_up():
    """If closes only go up, OBV is monotonically non-decreasing."""
    close = pd.Series([100.0 + i for i in range(20)])
    volume = pd.Series([1000] * 20)
    result = obv(close, volume)
    assert all(result.iloc[i] >= result.iloc[i - 1] for i in range(1, len(result)))


def test_williams_r_at_high_close_near_zero():
    """Williams %R is 0 to -100. Near 0 = at recent high."""
    high = pd.Series([100.0 + i for i in range(30)])
    low = pd.Series([95.0 + i for i in range(30)])
    close = pd.Series([99.5 + i for i in range(30)])
    result = williams_r(high, low, close, window=14)
    assert result.iloc[-1] > -25  # near top of range
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement in `src/psx_mcp/indicators.py`**

Append to the existing `indicators.py`:

```python
def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        window: int = 14) -> pd.Series:
    """Average Directional Index (ADX) — trend strength (0..100).
    > 25 = trending; < 20 = choppy/range-bound. Pure-function pandas implementation."""
    high = high.reset_index(drop=True)
    low = low.reset_index(drop=True)
    close = close.reset_index(drop=True)
    plus_dm = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # If +DM > -DM, keep +DM; else 0 (and reverse for -DM)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)
    # True range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_val = tr.ewm(alpha=1 / window, adjust=False).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=1 / window, adjust=False).mean() / atr_val.replace(0, np.nan))
    minus_di = 100.0 * (minus_dm.ewm(alpha=1 / window, adjust=False).mean() / atr_val.replace(0, np.nan))
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / window, adjust=False).mean().fillna(0.0)


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                window: int = 14, smooth_d: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator — momentum (0..100).
    %K = (close - low_min) / (high_max - low_min) * 100
    %D = SMA(%K, smooth_d)
    > 80 = overbought; < 20 = oversold."""
    low_min = low.rolling(window=window, min_periods=1).min()
    high_max = high.rolling(window=window, min_periods=1).max()
    denom = (high_max - low_min).replace(0, np.nan)
    k = ((close - low_min) / denom * 100.0).fillna(50.0)
    d = k.rolling(window=smooth_d, min_periods=1).mean()
    return pd.DataFrame({"%K": k, "%D": d})


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume — accumulation/distribution proxy.
    Adds volume on up-days, subtracts on down-days. Rising OBV = accumulation."""
    direction = close.diff().fillna(0)
    sign = direction.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (sign * volume).cumsum()


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series,
                window: int = 14) -> pd.Series:
    """Williams %R — momentum oscillator (0 to -100).
    0 = at recent high; -100 = at recent low. -20 to 0 = overbought; -100 to -80 = oversold."""
    low_min = low.rolling(window=window, min_periods=1).min()
    high_max = high.rolling(window=window, min_periods=1).max()
    denom = (high_max - low_min).replace(0, np.nan)
    return ((high_max - close) / denom * -100.0).fillna(-50.0)
```

- [ ] **Step 4: Run, confirm 6 new tests pass**

- [ ] **Step 5: Wire into the `_compute_indicators_impl` dispatch in `server.py`**

Find the existing if/elif chain in `_compute_indicators_impl`. Add before the `else: unknown` branch:

```python
elif name.startswith("adx"):
    window = int(name[3:]) if len(name) > 3 else 14
    df = bars_df(cache, symbol, lookback_days)  # already in scope
    out[name] = float(adx(df["high"], df["low"], df["close"], window).iloc[-1])
elif name.startswith("stoch"):
    s = stochastic(df["high"], df["low"], df["close"])
    out[name] = {"%K": float(s["%K"].iloc[-1]), "%D": float(s["%D"].iloc[-1])}
elif name == "obv":
    out[name] = float(obv(df["close"], df["volume"]).iloc[-1])
elif name.startswith("wr"):
    window = int(name[2:]) if len(name) > 2 else 14
    out[name] = float(williams_r(df["high"], df["low"], df["close"], window).iloc[-1])
```

Add `adx, stochastic, obv, williams_r` to the existing `from psx_mcp.indicators import ...` line.

- [ ] **Step 6: Server-level test for the new indicators**

In `tests/test_server.py`:

```python
def test_compute_indicators_supports_new_names(tmp_path):
    """Verify dispatch handles adx, stoch, obv, wr14."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=59 - i),
                open=100.0+i, high=100.0+i+1, low=100.0+i-1,
                close=100.0+i, volume=1000) for i in range(60)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_indicators_impl(cache, "XYZ",
                                        indicators=["adx14", "stoch", "obv", "wr14"])
    for k in ("adx14", "stoch", "obv", "wr14"):
        assert k in out
```

- [ ] **Step 7: Run + commit**

```
uv run pytest tests/test_indicators_extended.py tests/test_server.py -k "indicators_supports_new" -v
```

```bash
git add psx-mcp/src/psx_mcp/indicators.py psx-mcp/server.py psx-mcp/tests/test_indicators_extended.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): ADX, Stochastic, OBV, Williams %R indicators"
```

---

## Phase 5 — Cross-sectional & sector analytics

### Task 5.1: `cross_section.py` primitives

**Files:**
- Create: `psx-mcp/src/psx_mcp/cross_section.py`
- Create: `psx-mcp/tests/test_cross_section.py`

- [ ] **Step 1: Failing tests**

```python
# psx-mcp/tests/test_cross_section.py
import pytest
from datetime import datetime
from psx_mcp.cache import Cache
from psx_mcp.cross_section import (
    z_score, percentile_rank, sector_dispersion,
    sector_relative_strength,
)


@pytest.fixture
def seeded(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 29, 10, 0)
    rows = [
        ("AAA", "TECH",     100.0, +1.0),
        ("BBB", "TECH",     200.0, +2.0),
        ("CCC", "TECH",     300.0, -1.0),
        ("DDD", "CEMENT",   400.0, -2.0),
        ("EEE", "CEMENT",   500.0, +0.5),
    ]
    for sym, sector, price, change in rows:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                            volume=10_000, day_high=price+1, day_low=price-1,
                            fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=10.0 + (price / 100),
                                   pb=None, div_yield=None, payout=None, roe=None)
    return cache


def test_z_score_centers_to_zero():
    """Z-score of the median element of a sorted set is ~0."""
    values = [10.0, 11.0, 12.0, 13.0, 14.0]
    out = z_score(12.0, values)
    assert out is not None and abs(out) < 0.01


def test_z_score_outlier_is_high():
    out = z_score(100.0, [10.0, 11.0, 12.0, 13.0, 14.0])
    assert out > 10  # very far out


def test_z_score_empty_returns_none():
    assert z_score(10.0, []) is None


def test_z_score_zero_stdev_returns_none():
    assert z_score(10.0, [10.0, 10.0, 10.0]) is None


def test_percentile_rank_of_min_is_zero():
    """Min element is at the 0th percentile."""
    assert percentile_rank(10.0, [10.0, 20.0, 30.0]) == pytest.approx(0.0)


def test_percentile_rank_of_max_is_one_hundred():
    assert percentile_rank(30.0, [10.0, 20.0, 30.0]) == pytest.approx(100.0)


def test_percentile_rank_empty_returns_none():
    assert percentile_rank(10.0, []) is None


def test_percentile_rank_clamps_outside_range():
    """Value above max → 100; value below min → 0. Fixes M2."""
    assert percentile_rank(1000.0, [10.0, 20.0, 30.0]) == 100.0
    assert percentile_rank(-1000.0, [10.0, 20.0, 30.0]) == 0.0


def test_sector_dispersion_returns_stats(seeded):
    """Pulls PE values for sector TECH and reports dispersion."""
    out = sector_dispersion(seeded, "TECH", metric="pe")
    assert out["n"] == 3
    assert out["stdev"] is not None and out["stdev"] > 0
    assert out["range_pct"] is not None


def test_sector_dispersion_unknown_sector(seeded):
    out = sector_dispersion(seeded, "NOSUCH", metric="pe")
    assert out["n"] == 0
```

- [ ] **Step 2: Run, confirm import error**

- [ ] **Step 3: Implement `cross_section.py`**

```python
"""Cross-sectional / sector analytics helpers."""
from __future__ import annotations
from typing import Optional
import math
import numpy as np
from psx_mcp.screener import sector_summary


def z_score(value: float, universe: list[float]) -> Optional[float]:
    """Z-score of `value` within `universe`. None if universe < 2 or stdev = 0."""
    if value is None or not universe or len(universe) < 2:
        return None
    arr = np.array([v for v in universe if v is not None], dtype=float)
    if len(arr) < 2:
        return None
    sd = float(arr.std(ddof=1))
    if sd == 0:
        return None
    return float((value - arr.mean()) / sd)


def percentile_rank(value: float, universe: list[float]) -> Optional[float]:
    """Percent of universe strictly less than `value`. 0 = at-or-below min;
    100 = at-or-above max. Result is clamped to [0, 100] even if `value` lies
    outside the universe range.

    For n=1 (degenerate universe of single element), returns 50.0 by convention."""
    if value is None or not universe:
        return None
    arr = [v for v in universe if v is not None]
    if not arr:
        return None
    n = len(arr)
    if n == 1:
        return 50.0
    less = sum(1 for v in arr if v < value)
    raw = less / (n - 1) * 100.0
    return float(max(0.0, min(100.0, raw)))


def sector_dispersion(cache, sector: str, metric: str = "pe") -> dict:
    """Dispersion of `metric` across symbols in `sector`. metric ∈ {pe, eps, change_pct}.

    Returns {n, mean, median, stdev, min, max, range_pct, top_z_scores}.
    Useful for spotting high-dispersion sectors (alpha opportunity) vs
    low-dispersion (passive better)."""
    # Pull all symbols in this sector via screener.sector_summary
    summary = sector_summary(cache, sector)
    if summary.get("n", 0) == 0:
        return {"sector": sector, "metric": metric, "n": 0, "mean": None,
                "median": None, "stdev": None, "min": None, "max": None,
                "range_pct": None, "top_z_scores": []}

    # We re-pull the raw rows: sector_summary's top_5/bottom_5 are limited views.
    # Use the screener directly to enumerate sector members.
    from psx_mcp.screener import screen, FilterSpec
    rows = screen(cache, FilterSpec(sector=sector, limit=500))
    values = [r.get(metric) for r in rows if r.get(metric) is not None]
    if not values:
        return {"sector": sector, "metric": metric, "n": 0, "mean": None,
                "median": None, "stdev": None, "min": None, "max": None,
                "range_pct": None, "top_z_scores": []}
    arr = np.array(values, dtype=float)
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1)) if len(arr) > 1 else None
    mn = float(arr.min())
    mx = float(arr.max())
    range_pct = (mx / mn - 1.0) * 100.0 if mn > 0 else None
    # Top-z entries (highest |z|, signed) — symbol + value
    top_z = []
    if sd and sd > 0:
        for r in rows:
            v = r.get(metric)
            if v is None:
                continue
            z = (v - mean) / sd
            top_z.append({"symbol": r["symbol"], "value": v, "z_score": float(z)})
        top_z.sort(key=lambda e: abs(e["z_score"]), reverse=True)
        top_z = top_z[:5]
    return {"sector": sector, "metric": metric, "n": len(values),
            "mean": mean, "median": float(np.median(arr)), "stdev": sd,
            "min": mn, "max": mx, "range_pct": range_pct,
            "top_z_scores": top_z}


def sector_relative_strength(cache, sectors: list[str],
                              window_days: int = 60) -> list[dict]:
    """Per sector, compute (sector avg return) − (KSE-100 return) over the
    given window. Returns sector-by-sector RS sorted descending.

    Sector avg return = mean of `closes_for(sym).iloc[-1] / closes_for(sym).iloc[-window-1] - 1`
    for each symbol whose sector matches.
    """
    import pandas as pd
    idx_rows = cache.get_index_history("KSE100")
    if not idx_rows or len(idx_rows) < window_days + 1:
        return [{"sector": s, "rs_pct": None, "n": 0,
                  "note": "Insufficient index history"} for s in sectors]
    idx_closes = pd.Series([r["close"] for r in idx_rows])
    idx_ret = float(idx_closes.iloc[-1] / idx_closes.iloc[-window_days - 1] - 1.0)

    out = []
    for sector in sectors:
        from psx_mcp.screener import screen, FilterSpec
        members = screen(cache, FilterSpec(sector=sector, limit=500))
        rets = []
        for m in members:
            sym = m["symbol"]
            closes = cache.closes_for(sym)
            if len(closes) <= window_days:
                continue
            try:
                rets.append(closes[-1] / closes[-window_days - 1] - 1.0)
            except (IndexError, ZeroDivisionError):
                continue
        if not rets:
            out.append({"sector": sector, "rs_pct": None, "n": 0,
                         "index_return_pct": idx_ret * 100.0})
            continue
        sector_avg = sum(rets) / len(rets)
        out.append({
            "sector": sector,
            "rs_pct": float((sector_avg - idx_ret) * 100.0),
            "sector_return_pct": float(sector_avg * 100.0),
            "index_return_pct": float(idx_ret * 100.0),
            "n": len(rets),
        })
    out.sort(key=lambda r: (r["rs_pct"] is None, -(r["rs_pct"] or 0)))
    return out
```


- [ ] **Step 4: Run, confirm tests pass**

- [ ] **Step 5: Commit**

```bash
git add psx-mcp/src/psx_mcp/cross_section.py psx-mcp/tests/test_cross_section.py
git commit -m "feat(psx-mcp): cross_section.py — z_score, percentile, dispersion, sector RS"
```

---

### Task 5.2: MCP tools for cross-section

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Models**

```python
class CrossSectionalRankResponse(Disclaimer):
    symbol: str
    metric: str
    universe: str  # 'sector' or 'all'
    sector: Optional[str] = None
    value: Optional[float] = None
    z_score: Optional[float] = None
    percentile_pct: Optional[float] = None
    n_in_universe: int
    note: Optional[str] = None


class SectorDispersionResponse(Disclaimer):
    sector: str
    metric: str
    n: int
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    range_pct: Optional[float] = None
    top_z_scores: list[dict] = []
    note: Optional[str] = None


class SectorRelativeStrengthResponse(Disclaimer):
    window_days: int
    rows: list[dict]
    note: Optional[str] = None
```

- [ ] **Step 2: Failing tests**

```python
def test_compute_cross_sectional_rank_pe_in_sector(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 29, 10, 0)
    for sym, sector, price, pe in [
        ("AAA", "TECH", 100.0, 10.0),
        ("BBB", "TECH", 200.0, 20.0),
        ("CCC", "TECH", 300.0, 30.0),
    ]:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=0,
                           volume=1, day_high=price, day_low=price, fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=pe, pb=None,
                                   div_yield=None, payout=None, roe=None)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_cross_sectional_rank_impl(cache, "AAA",
                                                  metric="pe", scope="sector")
    assert out.value == 10.0
    assert out.z_score < 0  # AAA's PE is lower than the sector mean → negative z
    assert out.n_in_universe == 3


def test_sector_dispersion_tool(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 29, 10, 0)
    for sym, pe in [("X", 5.0), ("Y", 10.0), ("Z", 20.0)]:
        cache.upsert_symbol(sym, sym, "TECH", None)
        cache.upsert_quote(symbol=sym, ts=ts, price=100, change=0, volume=1,
                           day_high=101, day_low=99, fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=pe, pb=None,
                                   div_yield=None, payout=None, roe=None)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._sector_dispersion_impl(cache, "TECH", metric="pe")
    assert out.n == 3
    assert out.stdev is not None
    assert len(out.top_z_scores) >= 1
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement impls + tools**

```python
# server.py
from psx_mcp.cross_section import (
    z_score, percentile_rank, sector_dispersion, sector_relative_strength,
)
from psx_mcp.models import (
    CrossSectionalRankResponse, SectorDispersionResponse,
    SectorRelativeStrengthResponse,
)


def _compute_cross_sectional_rank_impl(cache: Cache, symbol: str,
                                         metric: str = "pe",
                                         scope: str = "sector") -> CrossSectionalRankResponse:
    sym = symbol.upper()
    sym_row = cache.get_symbol(sym) or {}
    sector = sym_row.get("sector")
    target = None
    universe_vals: list[float] = []

    # Identify universe
    from psx_mcp.screener import screen, FilterSpec
    if scope == "sector" and sector:
        rows = screen(cache, FilterSpec(sector=sector, limit=500))
    else:
        rows = screen(cache, FilterSpec(limit=500))

    for r in rows:
        v = r.get(metric)
        if v is None:
            continue
        universe_vals.append(float(v))
        if r["symbol"] == sym:
            target = float(v)

    if target is None:
        return CrossSectionalRankResponse(
            symbol=sym, metric=metric, universe=scope, sector=sector,
            n_in_universe=len(universe_vals),
            note=f"Metric {metric!r} not cached for {sym}.",
        )

    return CrossSectionalRankResponse(
        symbol=sym, metric=metric, universe=scope, sector=sector,
        value=target,
        z_score=z_score(target, universe_vals),
        percentile_pct=percentile_rank(target, universe_vals),
        n_in_universe=len(universe_vals),
        note=None,
    )


def _sector_dispersion_impl(cache: Cache, sector: str,
                              metric: str = "pe") -> SectorDispersionResponse:
    out = sector_dispersion(cache, sector, metric)
    return SectorDispersionResponse(**out)


def _sector_relative_strength_impl(cache: Cache,
                                     sectors: list[str] | None,
                                     window_days: int = 60) -> SectorRelativeStrengthResponse:
    sectors = sectors or DEFAULT_SECTORS  # carried over from analytics-v3
    rows = sector_relative_strength(cache, sectors, window_days=window_days)
    return SectorRelativeStrengthResponse(window_days=window_days, rows=rows,
                                            note=None)


@mcp.tool()
async def compute_cross_sectional_rank(symbol: str, metric: str = "pe",
                                        scope: str = "sector") -> CrossSectionalRankResponse:
    """Z-score and percentile rank of a metric within a peer universe.
    metric: 'pe', 'eps', 'change_pct'. scope: 'sector' or 'all'.
    Answers 'is this stock cheap/expensive relative to its peers?'"""
    return _compute_cross_sectional_rank_impl(_cache, symbol, metric, scope)


@mcp.tool()
async def get_sector_dispersion(sector: str, metric: str = "pe") -> SectorDispersionResponse:
    """Dispersion of a metric across a sector. High dispersion = stock-picking
    opportunity; low dispersion = passive better. Top-z entries surface
    outliers."""
    return _sector_dispersion_impl(_cache, sector, metric)


@mcp.tool()
async def rank_sector_relative_strength(sectors: list[str] | None = None,
                                          window_days: int = 60) -> SectorRelativeStrengthResponse:
    """Per-sector relative strength vs KSE-100 over the last N days.
    Default window: 60 trading days (~3 months). Sectors with rs_pct > 0
    are leading the market."""
    return _sector_relative_strength_impl(_cache, sectors, window_days)
```

- [ ] **Step 5: Run + commit**

```
uv run pytest tests/test_server.py -k "cross_sectional or sector_dispersion or sector_relative" -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): cross_sectional_rank + sector_dispersion + sector_relative_strength MCP tools"
```

---

## Phase 6 — Extend the screener with risk-adjusted filters

### Task 6.1: Add `sortino_min`, `calmar_min`, `max_dd_max` filters

**Files:**
- Modify: `psx-mcp/src/psx_mcp/screener.py`
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_screener.py`

- [ ] **Step 1: Failing test**

```python
def test_screen_filters_by_sortino_min(seeded_cache):
    """Symbols whose Sortino is below the threshold are excluded.
    Uses the same seeded_cache fixture as other screener tests."""
    from psx_mcp.screener import screen, FilterSpec
    # Use a strict Sortino threshold that only the cleanest series pass
    out = screen(seeded_cache, FilterSpec(sortino_min=-99.0))  # nearly all pass
    assert len(out) >= 1
    # Now a high threshold that excludes everything
    out_strict = screen(seeded_cache, FilterSpec(sortino_min=999.0))
    assert len(out_strict) == 0
```

- [ ] **Step 2: Run, confirm fail (FilterSpec lacks sortino_min)**

- [ ] **Step 3: Extend `FilterSpec` in `screener.py`**

In the dataclass:

```python
sortino_min: Optional[float] = None
calmar_min: Optional[float] = None
max_dd_max_pct: Optional[float] = None   # e.g., -30.0 = exclude if max DD worse than -30%
```

At the **top of `screener.py`** (with other imports — outside the per-symbol loop):

```python
from psx_mcp.risk_extended import (
    sortino as _sortino,
    calmar as _calmar,
    drawdown_details as _dd_details,
)
```

In the `_screen()` per-symbol loop (the Python-side filtering block), add — using existing `closes_list`:

```python
if any(f is not None for f in (spec.sortino_min, spec.calmar_min,
                                  spec.max_dd_max_pct)):
    if len(closes_list) < 50:
        skipped_no_bars += 1
        continue
    closes_s = pd.Series(closes_list)  # pandas already imported at module top
    if spec.sortino_min is not None:
        srt = _sortino(closes_s, rf_annual=0.0)
        if srt is None or srt < spec.sortino_min:
            continue
    if spec.calmar_min is not None:
        clm = _calmar(closes_s)
        if clm is None or clm < spec.calmar_min:
            continue
    if spec.max_dd_max_pct is not None:
        ddx = _dd_details(closes_s)["max_drawdown_pct"]
        # ddx is negative (e.g. -33.3). max_dd_max_pct is the WORST allowed
        # (e.g. -30 means "no worse than -30%"). Exclude if ddx is more
        # negative than the threshold.
        if ddx < spec.max_dd_max_pct:
            continue
```

- [ ] **Step 4: Extend `screen_symbols` wrapper in `server.py`** — add three new kwargs and pass through.

- [ ] **Step 5: Run all screener tests**

```
uv run pytest tests/test_screener.py tests/test_server.py -v
```

- [ ] **Step 6: Commit**

```bash
git add psx-mcp/src/psx_mcp/screener.py psx-mcp/server.py psx-mcp/tests/test_screener.py
git commit -m "feat(psx-mcp): screener filters by Sortino / Calmar / max-DD"
```

---

## Phase 7 — Unified dashboard: `get_extended_risk_metrics(symbol)`

### Task 7.1: One-shot tool combining everything

**Files:**
- Modify: `psx-mcp/src/psx_mcp/models.py`
- Modify: `psx-mcp/server.py`
- Create: `psx-mcp/tests/test_dashboard_extended.py`

- [ ] **Step 1: Add `ExtendedRiskMetricsResponse` to `models.py`**

```python
class ExtendedRiskMetricsResponse(Disclaimer):
    symbol: str
    n_bars: int
    return_stats: Optional[dict] = None      # CAGR, win rate, rolling
    risk_adjusted: Optional[dict] = None     # Sortino, Calmar, Information, Omega
    distribution: Optional[dict] = None      # skew, kurtosis, VaR, CVaR, tail ratio
    drawdown: Optional[dict] = None          # max DD, duration, recovery, Ulcer, top 3
    capture: Optional[dict] = None           # up/down capture vs KSE-100
    technical: Optional[dict] = None         # ADX, Stochastic, OBV, Williams %R
    warnings: list[str] = []
    note: Optional[str] = None
```

- [ ] **Step 2: Failing test in `tests/test_dashboard_extended.py`**

```python
import pytest
from datetime import date, timedelta
import server as srv
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.watchlist import WatchlistStore


def test_get_extended_risk_metrics_seeded_uptrend(tmp_path):
    """Seeded 260-bar uptrend should produce all sections non-empty."""
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=259 - i),
                open=100.0+i, high=100.0+i+1, low=100.0+i-1,
                close=100.0+i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    # Index for capture ratio
    for i in range(260):
        d = today - timedelta(days=259 - i)
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=170000.0 + i, volume=1e8)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_extended_risk_metrics_impl(cache, "XYZ")
    assert out.n_bars == 260
    assert out.return_stats is not None and "cagr_pct" in out.return_stats
    assert out.risk_adjusted is not None
    assert out.distribution is not None
    assert out.drawdown is not None
    assert out.capture is not None
    assert out.technical is not None


def test_get_extended_risk_metrics_empty_cache(tmp_path):
    """No bars → warnings populated; no crash."""
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_extended_risk_metrics_impl(cache, "NOSUCH")
    assert len(out.warnings) > 0
```

- [ ] **Step 3: Run, confirm fail**

- [ ] **Step 4: Implement impl + wrapper**

```python
def _get_extended_risk_metrics_impl(cache: Cache, symbol: str) -> ExtendedRiskMetricsResponse:
    sym = symbol.upper()
    warnings: list[str] = []
    closes = cache.closes_for(sym)
    n = len(closes)

    if n < 2:
        return ExtendedRiskMetricsResponse(
            symbol=sym, n_bars=n,
            warnings=[f"No bars cached. Call refresh_history({sym!r}) first."],
        )

    closes_s = pd.Series(closes)

    # Return stats
    return_stats = None
    try:
        rs = _compute_return_stats_impl(cache, sym, rolling_window_days=20)
        return_stats = rs.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"return_stats: {e!r}")

    # Risk-adjusted ratios
    risk_adjusted = None
    try:
        sr = sortino(closes_s, rf_annual=0.0)
        cl = calmar(closes_s)
        om = omega_ratio(closes_s, threshold=0.0)
        # Information ratio vs KSE-100 — DATE-ALIGN like _compute_beta_impl and
        # _compute_relative_strength_impl (fixes M4). Otherwise tail-position
        # alignment can pair calendar-mismatched bars when stock history is
        # much shorter than index history.
        stock_pairs = cache.closes_for_with_dates(sym)
        stock_by_date = dict(stock_pairs)
        idx_rows = cache.get_index_history("KSE100")
        idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
        common = sorted(set(stock_by_date) & set(idx_by_date))
        ir = None
        if len(common) >= 2:
            s_aligned = pd.Series([stock_by_date[d] for d in common])
            i_aligned = pd.Series([idx_by_date[d] for d in common])
            ir = information_ratio(s_aligned, i_aligned)
        risk_adjusted = {
            "sortino": sr, "calmar": cl, "omega": om,
            "information_ratio_vs_kse100": ir,
            "n_aligned_for_ir": len(common),
        }
    except Exception as e:
        warnings.append(f"risk_adjusted: {e!r}")

    # Distribution
    distribution = None
    try:
        ds = _compute_distribution_stats_impl(cache, sym)
        distribution = ds.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"distribution: {e!r}")

    # Drawdown
    drawdown = None
    try:
        dd_resp = _compute_drawdown_details_impl(cache, sym)
        drawdown = dd_resp.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"drawdown: {e!r}")

    # Capture
    capture = None
    try:
        cap = _compute_up_down_capture_impl(cache, sym, index_code="KSE100")
        capture = cap.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"capture: {e!r}")

    # Technical (latest values only)
    technical = None
    try:
        ind = _compute_indicators_impl(cache, sym,
                                         indicators=["adx14", "stoch", "obv", "wr14",
                                                      "rsi14", "atr14"],
                                         lookback_days=260)
        technical = {k: v for k, v in ind.items() if k != "disclaimer"}
    except Exception as e:
        warnings.append(f"technical: {e!r}")

    return ExtendedRiskMetricsResponse(
        symbol=sym, n_bars=n,
        return_stats=return_stats,
        risk_adjusted=risk_adjusted,
        distribution=distribution,
        drawdown=drawdown,
        capture=capture,
        technical=technical,
        warnings=warnings,
    )


@mcp.tool()
async def get_extended_risk_metrics(symbol: str) -> ExtendedRiskMetricsResponse:
    """One-shot extended-metric dashboard: return stats (CAGR, win rate, rolling
    returns), risk-adjusted ratios (Sortino, Calmar, Omega, Information),
    distribution (skew, kurtosis, VaR, CVaR, tail ratio), drawdown deep-dive
    (Ulcer Index, top-3 DDs), up/down capture vs KSE-100, and key technicals
    (ADX, Stochastic, OBV, Williams %R, RSI, ATR). Composes existing impls;
    missing data populates `warnings`."""
    return _get_extended_risk_metrics_impl(_cache, symbol)
```

- [ ] **Step 5: Run + commit**

```
uv run pytest tests/test_dashboard_extended.py -v
```

```bash
git add psx-mcp/src/psx_mcp/models.py psx-mcp/server.py psx-mcp/tests/test_dashboard_extended.py
git commit -m "feat(psx-mcp): get_extended_risk_metrics — unified Part-4 dashboard"
```

---

## Phase 8 — Docs & release

### Task 8.1: README + playbook updates

- [ ] **Step 1: Update `psx-mcp/README.md` tool table**

Add rows:
- `compute_return_stats(symbol, rolling_window_days=20)`
- `compute_distribution_stats(symbol)`
- `compute_drawdown_details(symbol)`
- `compute_up_down_capture(symbol, index_code="KSE100")`
- `compute_cross_sectional_rank(symbol, metric="pe", scope="sector")`
- `get_sector_dispersion(sector, metric="pe")`
- `rank_sector_relative_strength(sectors=None, window_days=60)`
- `get_extended_risk_metrics(symbol)` ← **mark as the recommended one-shot dashboard**

Update existing entries:
- `compute_indicators` — note new accepted names: `adx14`, `stoch`, `obv`, `wr14`
- `screen_symbols` — note new filters: `sortino_min`, `calmar_min`, `max_dd_max_pct`

- [ ] **Step 2: Update `docs/investing-playbook.md`**

In Part 1 gap table, mark resolved:
- CAGR / rolling returns ✅
- Sortino, Calmar, Omega, Information ratios ✅
- VaR / CVaR / skewness / kurtosis / tail ratio ✅
- Drawdown duration / Ulcer Index / top-3 DDs ✅
- Up/down capture ✅
- Z-score / percentile rank within universe ✅
- Sector dispersion ✅
- Sector relative strength ✅
- ADX, Stochastic, OBV, Williams %R indicators ✅
- Risk-adjusted screener filters ✅

In Part 6 roadmap, append:
"**analytics-v4** completes the metric-coverage layer (return characterization, risk-adjusted ratios beyond Sharpe, tail/distribution stats, drawdown deep-dive, cross-sectional/sector analytics, four more indicators). **Part 5** focus: headless-browser sub-tab fetcher to populate ROE/PB/payout (unblocks full F-Score), `sector_history` table to track sector P/E percentile vs own history over time, and Treynor ratio (depends on rolling beta from accumulated index history)."

- [ ] **Step 3: Commit**

```bash
git add psx-mcp/README.md docs/investing-playbook.md
git commit -m "docs(psx-mcp): document Part-4 metric tools (Sortino, Calmar, VaR/CVaR, drawdown, capture, ADX/Stoch/OBV)"
```

### Task 8.2: Full-suite gate + `analytics-v4` tag

- [ ] **Step 1: Run full suite**

```
uv run pytest -v
```
With `timeout=600000`. Expected: all green (target ~220+ tests from 188 in analytics-v3).

- [ ] **Step 2: Tag (annotated, no push)**

```bash
cd C:/Users/pc/work/stocks/psx
git tag -a analytics-v4 -m "PSX MCP Analytics Upgrade Part 4 — extended risk metrics: Sortino/Calmar/Omega, VaR/CVaR, drawdown deep-dive, up/down capture, ADX/Stochastic/OBV/Williams%R, cross-sectional ranking, sector dispersion"
```

- [ ] **Step 3: Report final test count, tag SHA, commit list**

---

## Self-Review

**1. Spec coverage:**
- Sortino, Calmar, Information, Omega ✅ Task 2.1
- VaR, CVaR, skewness, kurtosis, tail ratio ✅ Task 2.2
- Drawdown duration, recovery, Ulcer Index, top-3 DDs ✅ Task 2.3
- Up/down capture ✅ Task 2.4
- CAGR, rolling returns, win rate ✅ Task 1.1 + 1.2
- ADX, Stochastic, OBV, Williams %R ✅ Task 4.1
- Cross-sectional z-score / percentile / dispersion / sector RS ✅ Tasks 5.1 + 5.2
- Risk-adjusted screener filters ✅ Task 6.1
- Unified dashboard ✅ Task 7.1
- Treynor — explicitly deferred (depends on rolling beta — needs Part 5 sector_history)
- Sector P/E percentile vs own history — deferred (needs sector_history table)

**2. Placeholder scan:** every code step has real code or precise references. Conditional skip clauses (e.g., "if missing data → that section is None") are documented.

**3. Type consistency:**
- `cagr`, `sortino`, `calmar`, `omega_ratio` all return `Optional[float]` — consistent.
- `drawdown_details` returns a dict with keys consumed in the same shape by Task 3.2 and the dashboard.
- `up_down_capture` returns dict consumed identically in Task 2.4 test, Task 3.3, and the dashboard.
- `_compute_*_impl` follow the established `(cache, symbol, ...) → ResponseModel` shape.
- All new response models inherit `Disclaimer`.

**4. Constraint check:**
- No new external endpoints. All reads from cache.
- No paid feeds. No scraping outside existing PSX endpoints.
- All new tools are async wrappers over sync impls — pattern preserved.
- Backwards-compatible — no removed fields, no renamed tools.

**5. Carryover from Part-3 review:**
- Part-2 TODO about `closes_for_with_dates` in beta impl — already resolved in Part 3.
- Part-3 reviewer noted: "consider Sortino/Calmar additions" — fulfilled here.
- Phase 6.4 from Part 3 verified `get_news` already works — no carryover needed.

---

## What this plan deliberately does NOT cover

Belongs to Part 5:

- **ROE / P/B / payout / dividend yield population** — still needs headless-browser sub-tab fetcher.
- **Real Piotroski F-Score** — depends on balance-sheet items above.
- **Treynor ratio** — depends on a rolling beta computation; deferred to keep this plan tight.
- **Sector P/E percentile vs own history** — needs `sector_history` table to accumulate snapshots over time.
- **Bollinger Band Width, Keltner Channels** — not requested by user.
- **News sentiment, macro feed** — explicit constraint exclusions.
- **Portfolio-level metrics** (Modern Portfolio Theory optimization, efficient frontier) — out of project scope (no portfolio tracking, per analytics-v1 non-goal).
- **Multi-factor regression** (Fama-French 3/5-factor on PSX) — needs longer history and macro factor proxies.

When Part 5 starts, prioritize the headless-browser sub-tab fetcher — it unblocks the most downstream features.
