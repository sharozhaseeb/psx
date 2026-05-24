"""Pure-function risk and relative-performance primitives.
Inputs are pandas Series of closes (oldest first). No I/O, no caching."""
from __future__ import annotations
from typing import Optional
import math
import pandas as pd
import numpy as np


TRADING_DAYS = 252


def drawdown_current(closes: pd.Series) -> dict:
    """Current drawdown from running peak.

    Returns:
      {drawdown_pct: float (<= 0), peak: float|None, current: float|None}.
      drawdown_pct is 0.0 at all-time high.
    """
    if closes is None or len(closes) == 0:
        return {"drawdown_pct": 0.0, "peak": None, "current": None}
    peak = float(closes.max())
    current = float(closes.iloc[-1])
    if peak <= 0:
        return {"drawdown_pct": 0.0, "peak": peak, "current": current}
    return {
        "drawdown_pct": float((current / peak - 1.0) * 100.0),
        "peak": peak,
        "current": current,
    }


def drawdown_max(closes: pd.Series) -> dict:
    """Maximum drawdown over the entire series.

    Returns:
      {max_drawdown_pct: float (<= 0), peak_index: int|None, trough_index: int|None}.
      max_drawdown_pct is 0.0 on a strictly non-decreasing series.
    """
    if closes is None or len(closes) < 2:
        return {"max_drawdown_pct": 0.0, "peak_index": None, "trough_index": None}
    values = closes.reset_index(drop=True)
    running_max = values.cummax()
    dd = (values / running_max - 1.0) * 100.0
    trough_pos = int(dd.idxmin())
    # Peak is the running_max value at the trough -> find its first occurrence <= trough_pos
    peak_val = float(running_max.iloc[trough_pos])
    # Earliest index where the cumulative max reached peak_val
    peak_pos = int(values.iloc[:trough_pos + 1].idxmax())
    return {
        "max_drawdown_pct": float(dd.min()),
        "peak_index": peak_pos,
        "trough_index": trough_pos,
    }


def volatility_annualized(closes: pd.Series) -> float:
    """Annualized stdev of daily log returns (returns 0.0 if < 2 closes)."""
    if closes is None or len(closes) < 2:
        return 0.0
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    return float(rets.std(ddof=1) * math.sqrt(TRADING_DAYS))


def sharpe(closes: pd.Series, rf_annual: float = 0.0) -> Optional[float]:
    """Sharpe ratio over the available history.
    rf_annual is the annual risk-free rate (e.g., 0.22 for 22% in Pakistan).
    Returns None if volatility is zero or series too short."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    daily_rf = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    excess = rets - daily_rf
    sd = float(rets.std(ddof=1))
    if sd == 0:
        return None
    return float(excess.mean() / sd * math.sqrt(TRADING_DAYS))


def relative_strength(stock_closes: pd.Series, index_closes: pd.Series,
                      window: int = 252) -> Optional[float]:
    """Stock return minus index return over the last `window` bars (as decimal).
    Both inputs must already be date-aligned; we align by tail position.
    Returns None if either series is shorter than `window + 1`."""
    if stock_closes is None or index_closes is None:
        return None
    if len(stock_closes) < window + 1 or len(index_closes) < window + 1:
        return None
    stock_start = float(stock_closes.iloc[-window - 1])
    stock_end = float(stock_closes.iloc[-1])
    idx_start = float(index_closes.iloc[-window - 1])
    idx_end = float(index_closes.iloc[-1])
    if stock_start <= 0 or idx_start <= 0:
        return None
    stock_ret = stock_end / stock_start - 1.0
    idx_ret = idx_end / idx_start - 1.0
    return float(stock_ret - idx_ret)


def correlation_matrix(closes_by_symbol: dict[str, pd.Series]) -> dict[str, dict[str, Optional[float]]]:
    """Pairwise Pearson correlation of daily returns across symbols.
    Symbols with < 2 returns produce None entries (not crashes).
    Returns nested dict: {sym_a: {sym_b: corr_or_None, ...}, ...}."""
    syms = list(closes_by_symbol.keys())
    returns: dict[str, pd.Series] = {}
    for s in syms:
        if closes_by_symbol[s] is None or len(closes_by_symbol[s]) < 2:
            returns[s] = pd.Series(dtype=float)
        else:
            returns[s] = closes_by_symbol[s].pct_change().dropna().reset_index(drop=True)
    out: dict[str, dict[str, Optional[float]]] = {}
    for a in syms:
        out[a] = {}
        for b in syms:
            if len(returns[a]) < 2 or len(returns[b]) < 2:
                out[a][b] = None
                continue
            n = min(len(returns[a]), len(returns[b]))
            ra = returns[a].iloc[-n:].values
            rb = returns[b].iloc[-n:].values
            if np.std(ra) == 0 or np.std(rb) == 0:
                out[a][b] = None
                continue
            out[a][b] = float(np.corrcoef(ra, rb)[0, 1])
    return out
