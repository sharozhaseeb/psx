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


Cross = Literal["crosses_above", "crosses_below"]


def last_crosses(a: pd.Series, b: pd.Series, op: Cross) -> bool:
    if len(a) < 2 or len(b) < 2:
        return False
    # Iterate backwards from the end to find the most recent crossing
    for i in range(len(a) - 1, 0, -1):
        prev_a, prev_b = a.iloc[i-1], b.iloc[i-1]
        curr_a, curr_b = a.iloc[i], b.iloc[i]
        if op == "crosses_above":
            if bool(prev_a <= prev_b and curr_a > curr_b):
                return True
        else:  # crosses_below
            if bool(prev_a >= prev_b and curr_a < curr_b):
                return True
    return False
