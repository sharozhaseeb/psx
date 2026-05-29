"""Pure-function extensions to risk.py — return characterization, distribution,
drawdown details, downside metrics, capture ratios.

Each function takes pandas Series of closes (oldest first). No I/O, no caching."""
from __future__ import annotations
from typing import Optional
import math
import pandas as pd
import numpy as np


TRADING_DAYS = 252


def cagr(closes: pd.Series, periods_per_year: int = TRADING_DAYS) -> Optional[float]:
    """Compound annual growth rate. Returns decimal (0.10 = +10%/year).
    None if < 2 closes or start <= 0."""
    if closes is None or len(closes) < 2:
        return None
    start = float(closes.iloc[0])
    end = float(closes.iloc[-1])
    if start <= 0:
        return None
    years = (len(closes) - 1) / periods_per_year
    if years <= 0:
        return None
    return float((end / start) ** (1 / years) - 1)


def rolling_returns(closes: pd.Series, window: int) -> list[float]:
    """Return list of N-bar % returns. Each value is decimal (0.05 = +5%).
    Empty list if len(closes) <= window."""
    if closes is None or len(closes) <= window:
        return []
    out = []
    for i in range(len(closes) - window):
        start = float(closes.iloc[i])
        end = float(closes.iloc[i + window])
        if start > 0:
            out.append(end / start - 1.0)
    return out


def win_rate(closes: pd.Series) -> Optional[float]:
    """Percentage of bar-over-bar returns that are positive.
    Returns None if < 2 closes."""
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    return float((rets > 0).sum() / len(rets) * 100.0)
