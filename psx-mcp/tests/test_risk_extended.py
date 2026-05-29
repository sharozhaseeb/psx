import math
import pytest
import pandas as pd
import numpy as np
from psx_mcp.risk_extended import (
    cagr,
    rolling_returns,
    win_rate,
    sortino,
    calmar,
    information_ratio,
    omega_ratio,
    var_historical,
    cvar_historical,
    skewness,
    kurtosis_excess,
    tail_ratio,
    drawdown_details,
    ulcer_index,
    up_down_capture,
)


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


def test_sortino_positive_drift():
    """Series with positive drift and some downside should yield Sortino > 0.

    NOTE: seed sensitive — seed 7 produced negative sample drift despite
    positive loc. Seed 3 reliably produces sample mean > 0.001 over 500 draws.
    """
    rng = np.random.default_rng(3)
    # Daily returns: positive mean, modest vol — produces some negative days
    rets = rng.normal(loc=0.0008, scale=0.012, size=500)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    result = sortino(closes)
    assert result is not None
    assert result > 0.0


def test_sortino_no_downside_returns_none():
    """All-positive returns → no downside deviation → None."""
    closes = pd.Series([100.0 * (1.001 ** i) for i in range(100)])
    assert sortino(closes) is None


def test_calmar_known_trajectory():
    """A series that rallies, draws down ~20%, then recovers slightly.
    CAGR should be positive, max DD ~20% → Calmar > 0 and finite."""
    # 252 trading days, +50% peak by day 126, then -20% drop to day 200, slight recover
    closes = []
    for i in range(127):
        closes.append(100.0 * (1.5 ** (i / 126)))  # ramp up to 150
    peak = closes[-1]
    for i in range(1, 75):
        closes.append(peak * (1.0 - 0.2 * (i / 74)))  # drop 20% over 74 days
    trough = closes[-1]
    for i in range(1, 52):
        closes.append(trough * (1.0 + 0.05 * (i / 51)))  # modest recover
    series = pd.Series(closes)
    result = calmar(series)
    assert result is not None
    assert math.isfinite(result)
    assert result > 0.0


def test_calmar_no_drawdown_returns_none():
    """Strictly increasing series — no drawdown → None."""
    closes = pd.Series([100.0 + i for i in range(252)])
    assert calmar(closes) is None


def test_information_ratio_outperformer_positive():
    """Stock outperforms benchmark with independent noise → IR > 0."""
    rng = np.random.default_rng(29)
    n = 500
    bench_rets = rng.normal(loc=0.0004, scale=0.010, size=n)
    # Stock = benchmark drift + alpha + independent noise → tracking error > 0
    stock_rets = bench_rets + rng.normal(loc=0.0008, scale=0.006, size=n)
    bench = pd.Series(100.0 * np.cumprod(1.0 + bench_rets))
    stock = pd.Series(100.0 * np.cumprod(1.0 + stock_rets))
    result = information_ratio(stock, bench)
    assert result is not None
    assert result > 0.0


def test_information_ratio_identical_series_returns_none():
    """Identical series → zero tracking error → None."""
    closes = pd.Series([100.0 + i for i in range(100)])
    assert information_ratio(closes, closes) is None


def test_omega_threshold_zero_above_one():
    """Series with positive drift, threshold=0 → Omega > 1."""
    rng = np.random.default_rng(11)
    rets = rng.normal(loc=0.0006, scale=0.010, size=500)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    result = omega_ratio(closes, threshold=0.0)
    assert result is not None
    assert result > 1.0


def test_omega_threshold_very_high_below_one():
    """Threshold above almost all returns → most days are losses vs threshold → Omega < 1."""
    rng = np.random.default_rng(13)
    rets = rng.normal(loc=0.0006, scale=0.010, size=500)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    # Threshold = 5% daily — virtually no day clears that
    result = omega_ratio(closes, threshold=0.05)
    assert result is not None
    assert result < 1.0


def test_var_historical_5pct_is_negative():
    """5% historical VaR on a normal-ish return distribution is negative."""
    rng = np.random.default_rng(17)
    rets = rng.normal(loc=0.0, scale=0.01, size=500)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    result = var_historical(closes, confidence=0.05)
    assert result is not None
    assert result < 0.0


def test_cvar_worse_than_var():
    """CVaR (expected shortfall) should be more negative than VaR."""
    rng = np.random.default_rng(19)
    rets = rng.normal(loc=0.0, scale=0.012, size=500)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    v = var_historical(closes, confidence=0.05)
    c = cvar_historical(closes, confidence=0.05)
    assert v is not None and c is not None
    assert c <= v


def test_skewness_near_zero_on_normal():
    """Symmetric normal returns → skewness near zero."""
    rng = np.random.default_rng(23)
    rets = rng.normal(loc=0.0, scale=0.01, size=2000)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    result = skewness(closes)
    assert result is not None
    assert abs(result) < 0.3


def test_kurtosis_excess_near_zero_on_normal():
    """Normal returns → excess kurtosis near zero."""
    rng = np.random.default_rng(31)
    rets = rng.normal(loc=0.0, scale=0.01, size=2000)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    result = kurtosis_excess(closes)
    assert result is not None
    assert abs(result) < 0.5


def test_tail_ratio_uptrend_greater_than_one():
    """Uptrend with positive drift → best tail magnitude > worst tail magnitude → ratio > 1."""
    rng = np.random.default_rng(37)
    rets = rng.normal(loc=0.002, scale=0.01, size=500)
    closes = pd.Series(100.0 * np.cumprod(1.0 + rets))
    result = tail_ratio(closes, quantile=0.05)
    assert result is not None
    assert result > 1.0


def test_tail_ratio_short_series_returns_none():
    closes = pd.Series([100.0, 101.0])
    assert tail_ratio(closes, quantile=0.05) is None


def test_drawdown_details_returns_all_fields():
    """[100, 120, 80, 100, 110, 120, 130] — single DD event recovered.
    Peak at index 1 (120), trough at index 2 (80), recovery at index 5 (120).
    Drawdown duration = trough - peak = 1 bar. Recovery duration = recovery - trough = 3 bars.
    Max DD = (80 - 120) / 120 = -33.33%."""
    closes = pd.Series([100.0, 120.0, 80.0, 100.0, 110.0, 120.0, 130.0])
    result = drawdown_details(closes)
    assert result is not None
    assert result["peak_index"] == 1
    assert result["trough_index"] == 2
    assert result["recovery_index"] == 5
    assert result["drawdown_duration_bars"] == 1
    assert result["recovery_duration_bars"] == 3
    assert result["max_drawdown_pct"] == pytest.approx(-33.333333, abs=0.01)


def test_drawdown_details_no_recovery_yet():
    """[100, 90, 85, 80] — DD ongoing; no recovery → recovery_index is None."""
    closes = pd.Series([100.0, 90.0, 85.0, 80.0])
    result = drawdown_details(closes)
    assert result is not None
    assert result["recovery_index"] is None


def test_drawdown_details_top_drawdowns_sorted():
    """Two distinct DD events. The deeper one should appear first
    (depth_pct ascending = most negative first)."""
    # First DD: 100 → 70 (-30%) → 100 (recover)
    # Second DD: 100 → 90 (-10%) → 100 (recover)
    closes = pd.Series([
        100.0, 70.0, 100.0,   # event 1: -30% then recover
        90.0, 100.0,          # event 2: -10% then recover
    ])
    result = drawdown_details(closes)
    assert result is not None
    tops = result["top_drawdowns"]
    assert len(tops) >= 2
    # Sorted by depth ascending → most negative first
    assert tops[0]["depth_pct"] < tops[1]["depth_pct"]


def test_ulcer_index_constant_series_is_zero():
    closes = pd.Series([100.0] * 50)
    result = ulcer_index(closes)
    assert result is not None
    assert result == pytest.approx(0.0, abs=1e-9)


def test_ulcer_index_drawdown_series_is_positive():
    """Series with a clear dip → ulcer index > 0."""
    closes = pd.Series([100.0, 90.0, 80.0, 85.0, 95.0, 100.0])
    result = ulcer_index(closes)
    assert result is not None
    assert result > 0.0


def test_up_capture_high_beta_above_100():
    """If stock returns are 2x benchmark in up periods, up-capture = ~200%."""
    bench_rets = [0.01, 0.02, 0.015, -0.005, 0.01]
    stock_rets = [0.02, 0.04, 0.03, -0.005, 0.02]
    bench_vals = [100.0]
    stock_vals = [100.0]
    for r in bench_rets:
        bench_vals.append(bench_vals[-1] * (1 + r))
    for r in stock_rets:
        stock_vals.append(stock_vals[-1] * (1 + r))
    out = up_down_capture(pd.Series(stock_vals), pd.Series(bench_vals))
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
