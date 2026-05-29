import numpy as np
import pandas as pd
import pytest

from psx_mcp.indicators import adx, stochastic, obv, williams_r


# ---------- ADX ----------

def _build_trend_ohlc(n: int, slope: float, noise: float = 0.0,
                      seed: int = 0) -> pd.DataFrame:
    """Synthesize an OHLC frame that trends with given slope per bar.

    high = close + 1, low = close - 1; noise (if any) is added to close.
    """
    rng = np.random.RandomState(seed)
    base = np.arange(n) * slope + 100.0
    if noise:
        base = base + rng.randn(n) * noise
    close = pd.Series(base)
    high = close + 1.0
    low = close - 1.0
    return pd.DataFrame({"high": high, "low": low, "close": close})


def test_adx_strong_uptrend_above_25():
    df = _build_trend_ohlc(n=60, slope=1.0)
    val = float(adx(df["high"], df["low"], df["close"], 14).iloc[-1])
    assert val > 25.0, f"clean uptrend ADX should exceed 25, got {val}"


def test_adx_choppy_is_lower_than_clean_trend():
    """Comparative: a choppy series should show weaker ADX than a clean trend."""
    trend = _build_trend_ohlc(n=80, slope=1.0)
    # Choppy: zero net slope, large noise.
    choppy = _build_trend_ohlc(n=80, slope=0.0, noise=3.0, seed=7)
    trend_adx = float(adx(trend["high"], trend["low"], trend["close"], 14).iloc[-1])
    choppy_adx = float(adx(choppy["high"], choppy["low"], choppy["close"], 14).iloc[-1])
    assert trend_adx > choppy_adx, (
        f"clean trend ADX ({trend_adx}) should exceed choppy ADX ({choppy_adx})"
    )


# ---------- Stochastic ----------

def test_stochastic_at_high_range_near_100():
    n = 30
    # Range 100..110 over the window; final close pinned at the top.
    high = pd.Series([110.0] * n)
    low = pd.Series([100.0] * n)
    close = pd.Series([105.0] * (n - 1) + [110.0])
    out = stochastic(high, low, close, k_window=14, d_window=3)
    k_last = float(out["%K"].iloc[-1])
    assert k_last >= 95.0, f"%K at top of range should approach 100, got {k_last}"


def test_stochastic_at_low_range_near_zero():
    n = 30
    high = pd.Series([110.0] * n)
    low = pd.Series([100.0] * n)
    close = pd.Series([105.0] * (n - 1) + [100.0])
    out = stochastic(high, low, close, k_window=14, d_window=3)
    k_last = float(out["%K"].iloc[-1])
    assert k_last <= 5.0, f"%K at bottom of range should approach 0, got {k_last}"


# ---------- OBV ----------

def test_obv_uptrend_with_volume_is_monotonic_up():
    # Strictly rising closes with constant positive volume -> OBV strictly increasing.
    close = pd.Series([float(x) for x in range(100, 120)])
    volume = pd.Series([1000.0] * len(close))
    out = obv(close, volume)
    diffs = out.diff().dropna()
    assert (diffs > 0).all(), f"OBV should be monotonically increasing, diffs={diffs.tolist()}"


# ---------- Williams %R ----------

def test_williams_r_at_high_close_near_zero():
    n = 30
    high = pd.Series([110.0] * n)
    low = pd.Series([100.0] * n)
    close = pd.Series([105.0] * (n - 1) + [110.0])
    val = float(williams_r(high, low, close, window=14).iloc[-1])
    # %R = -100 * (highestHigh - close) / (highestHigh - lowestLow)
    # close at top -> %R ~ 0
    assert -5.0 <= val <= 0.0, f"Williams %R at top of range should be near 0, got {val}"
