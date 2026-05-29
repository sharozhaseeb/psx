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
