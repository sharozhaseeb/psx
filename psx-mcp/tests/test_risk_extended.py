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
