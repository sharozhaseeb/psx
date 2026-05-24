from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Literal


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_e = ema(series, fast)
    slow_e = ema(series, slow)
    macd_line = fast_e - slow_e
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=1).std().fillna(0)
    return pd.DataFrame({
        "middle": mid,
        "upper": mid + n_std * std,
        "lower": mid - n_std * std,
    })


def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    avg = volume.rolling(window=window, min_periods=1).mean()
    std = volume.rolling(window=window, min_periods=1).std().replace(0, np.nan)
    return (volume - avg) / std


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's Average True Range.

    True Range = max(high - low, |high - prev_close|, |low - prev_close|).
    ATR is Wilder-smoothed (equivalent to an EMA with alpha = 1/window).
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


Cross = Literal["crosses_above", "crosses_below"]


def last_crosses(a: pd.Series, b: pd.Series, op: Cross) -> bool:
    """True iff the cross happened on the LATEST bar (between iloc[-2] and iloc[-1])."""
    if len(a) < 2 or len(b) < 2:
        return False
    prev_a, prev_b = a.iloc[-2], b.iloc[-2]
    curr_a, curr_b = a.iloc[-1], b.iloc[-1]
    if op == "crosses_above":
        return bool(prev_a <= prev_b and curr_a > curr_b)
    return bool(prev_a >= prev_b and curr_a < curr_b)
