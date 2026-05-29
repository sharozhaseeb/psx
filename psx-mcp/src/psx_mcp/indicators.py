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


def donchian(closes: pd.Series, window: int) -> tuple[float | None, float | None]:
    """Returns (highest, lowest) over the last `window` closes; (None, None) if insufficient data."""
    if len(closes) < window:
        return (None, None)
    tail = closes.iloc[-window:]
    return (float(tail.max()), float(tail.min()))


def returns_window(closes: pd.Series, lookback: int) -> float | None:
    """Pct change between latest close and the close `lookback` bars ago. None if too short."""
    if len(closes) <= lookback:
        return None
    return float(closes.iloc[-1] / closes.iloc[-1 - lookback] - 1.0)


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


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        window: int = 14) -> pd.Series:
    """Wilder's Average Directional Index (ADX).

    Steps:
      1. True Range (TR) and directional moves (+DM, -DM).
      2. Wilder-smooth TR, +DM, -DM (EMA with alpha = 1/window).
      3. +DI = 100 * smoothed(+DM) / smoothed(TR); same for -DI.
      4. DX = 100 * |+DI - -DI| / (+DI + -DI).
      5. ADX = Wilder-smoothed DX.
    Returns a Series of ADX values aligned to the inputs.
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    alpha = 1.0 / window
    tr_s = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_dm_s = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    minus_dm_s = minus_dm.ewm(alpha=alpha, adjust=False).mean()

    plus_di = 100.0 * plus_dm_s / tr_s.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_s / tr_s.replace(0, np.nan)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    return dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0)


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_window: int = 14, d_window: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator (%K, %D).

      %K = 100 * (close - lowest_low) / (highest_high - lowest_low)
      %D = SMA(%K, d_window)
    Both windows look back `k_window` / `d_window` bars respectively.
    Returns a DataFrame with columns "%K" and "%D".
    """
    lowest_low = low.rolling(window=k_window, min_periods=1).min()
    highest_high = high.rolling(window=k_window, min_periods=1).max()
    rng = (highest_high - lowest_low).replace(0, np.nan)
    k = 100.0 * (close - lowest_low) / rng
    k = k.fillna(50.0)
    d = k.rolling(window=d_window, min_periods=1).mean()
    return pd.DataFrame({"%K": k, "%D": d})


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume.

      OBV_t = OBV_{t-1} + sign(close_t - close_{t-1}) * volume_t
    First bar has OBV = 0. Sign is +1 on up days, -1 on down days, 0 on flat.
    """
    direction = np.sign(close.diff().fillna(0.0))
    signed_volume = direction * volume
    return signed_volume.cumsum()


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series,
               window: int = 14) -> pd.Series:
    """Williams %R.

      %R = -100 * (highest_high - close) / (highest_high - lowest_low)
    Values range from -100 (very oversold) to 0 (very overbought).
    """
    highest_high = high.rolling(window=window, min_periods=1).max()
    lowest_low = low.rolling(window=window, min_periods=1).min()
    rng = (highest_high - lowest_low).replace(0, np.nan)
    out = -100.0 * (highest_high - close) / rng
    return out.fillna(-50.0)
