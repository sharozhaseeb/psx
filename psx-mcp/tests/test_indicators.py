import numpy as np
import pandas as pd
import pytest
from psx_mcp.indicators import (
    rsi, sma, ema, macd, bollinger, volume_zscore, last_crosses,
)


@pytest.fixture
def closes_15():
    return pd.Series(
        [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
         45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    )


def test_sma_last_value():
    s = pd.Series([1, 2, 3, 4, 5])
    assert sma(s, 3).iloc[-1] == pytest.approx(4.0)


def test_ema_last_value():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ema(s, 3).iloc[-1]
    assert out > 0


def test_rsi_in_bounds(closes_15):
    out = rsi(closes_15, 14).iloc[-1]
    assert 0.0 <= out <= 100.0


def test_rsi_oversold_detected():
    s = pd.Series([float(x) for x in range(100, 85, -1)] + [86.0])
    out = rsi(s, 14).iloc[-1]
    assert out < 50.0


def test_macd_shape():
    s = pd.Series(np.linspace(100, 200, 60))
    m = macd(s)
    assert {"macd", "signal", "hist"} <= set(m.columns)
    assert len(m) == 60


def test_bollinger_bands_ordering():
    s = pd.Series(np.random.RandomState(0).randn(40).cumsum() + 100)
    b = bollinger(s, 20, 2.0)
    assert (b["upper"] >= b["middle"]).all()
    assert (b["middle"] >= b["lower"]).all()


def test_volume_zscore_positive_spike():
    v = pd.Series([100.0] * 19 + [500.0])
    z = volume_zscore(v, 20)
    assert z.iloc[-1] > 2.0


def test_crosses_above_on_latest_bar():
    # Cross happens between iloc[-2]=2.5 and iloc[-1]=4.0 over threshold 3.0
    a = pd.Series([1.0, 1.5, 2.0, 2.5, 4.0])
    b = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0])
    assert last_crosses(a, b, "crosses_above") is True


def test_crosses_below_on_latest_bar():
    a = pd.Series([5.0, 4.5, 4.0, 3.5, 2.0])
    b = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0])
    assert last_crosses(a, b, "crosses_below") is True


def test_no_cross_when_already_above():
    # a was already above b in prev bar — not a fresh cross
    a = pd.Series([1.0, 2.0, 3.5, 4.0, 5.0])
    b = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0])
    assert last_crosses(a, b, "crosses_above") is False


def test_no_cross_when_flat():
    a = pd.Series([1.0, 1.0, 1.0, 1.0])
    b = pd.Series([2.0, 2.0, 2.0, 2.0])
    assert last_crosses(a, b, "crosses_above") is False
