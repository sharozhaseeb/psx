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
    closes = pd.Series([100.0, 110.0, 105.0])  # peak 110, now 105 -> -4.55%
    dd = drawdown_current(closes)
    assert dd["drawdown_pct"] == pytest.approx(-4.5454545, abs=1e-4)
    assert dd["peak"] == pytest.approx(110.0)


def test_drawdown_current_empty_returns_zero():
    """Defensive: empty series -> safe defaults rather than crash."""
    dd = drawdown_current(pd.Series([], dtype=float))
    assert dd["drawdown_pct"] == 0.0
    assert dd["peak"] is None


def test_drawdown_max_known_trajectory():
    # 100 -> 120 (peak) -> 80 (max DD here = -33.33%) -> 110
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
    """Daily returns with stdev 0.01 should annualize to ~0.01*sqrt(252) ~= 15.87%."""
    rng = np.random.default_rng(42)
    # Build series whose pct_change has stdev ~= 0.01
    pcts = rng.normal(loc=0.0, scale=0.01, size=500)
    closes = pd.Series(np.exp(np.cumsum(pcts)))
    v = volatility_annualized(closes)
    assert 0.10 < v < 0.25  # loose band; deterministic with seed


def test_sharpe_zero_rf_on_positive_drift():
    """Series with positive drift and modest vol -> positive Sharpe."""
    rng = np.random.default_rng(7)
    # Note: deviates from plan's size=500. With seed(7), 500 samples of
    # N(0.001, 0.01) happens to produce a sample mean of -0.00028 (unlucky
    # draw), causing the assertion to fail. size=1000 keeps the spirit of
    # the test (positive drift -> positive Sharpe) while honoring the
    # required seed(7).
    pcts = rng.normal(loc=0.001, scale=0.01, size=1000)  # +25%/yr drift, 16% vol
    closes = pd.Series(np.exp(np.cumsum(pcts)))
    s = sharpe(closes, rf_annual=0.0)
    assert s > 0


def test_sharpe_returns_none_on_zero_vol():
    """Constant series -> undefined Sharpe -> None (not inf, not crash)."""
    closes = pd.Series([100.0] * 30)
    assert sharpe(closes, rf_annual=0.0) is None


def test_relative_strength_identical_to_index_is_zero():
    """If stock returns == index returns over the window, RS = 0%."""
    idx = pd.Series([100.0 + i for i in range(100)])
    stock = idx.copy()
    rs = relative_strength(stock, idx, window=60)
    assert rs == pytest.approx(0.0, abs=1e-6)


def test_relative_strength_stock_outperforms_returns_positive():
    """Stock returns 30% while index returns 10% -> RS = +20%."""
    # Build constant-rate series
    idx = pd.Series([100.0 * (1.10 ** (i / 252)) for i in range(253)])  # 10% over 1yr
    stock = pd.Series([100.0 * (1.30 ** (i / 252)) for i in range(253)])  # 30% over 1yr
    rs = relative_strength(stock, idx, window=252)
    # Both grew at constant compounded rates from same start; over 252 trading days
    # the stock is up ~30% and index ~10% -> RS ~= +20%.
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
