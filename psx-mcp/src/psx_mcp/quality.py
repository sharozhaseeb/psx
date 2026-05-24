"""Composite scoring primitives. Each returns either a 0/1 quadrant pass or a
continuous score; compute_4quadrant_score aggregates them into a 0-4 total."""
from __future__ import annotations
from typing import Optional
import pandas as pd
from psx_mcp.indicators import sma, rsi


def compute_value_score(snapshot: dict, sector_median: dict) -> float:
    """1.0 if P/E is below sector median and positive; 0.0 otherwise.
    Continuous: scaled by how far below median."""
    pe = snapshot.get("pe")
    med = sector_median.get("pe")
    if pe is None or med is None or pe <= 0:
        return 0.0
    if pe >= med:
        return 0.0
    return min(1.0, (med - pe) / med)


def compute_quality_score(snapshot: dict) -> float:
    """1.0 if ROE >= 15 AND EPS history is non-decreasing across last 3 years.
    Continuous: half-credit for either.
    eps_history must be in chronological order, oldest first."""
    score = 0.0
    roe = snapshot.get("roe")
    if roe is not None and roe >= 15:
        score += 0.5
    eps_hist = snapshot.get("eps_history") or []
    if len(eps_hist) >= 3:
        recent = eps_hist[-3:]
        if all(a <= b for a, b in zip(recent, recent[1:])):
            score += 0.5
    return score


def compute_momentum_score(closes: pd.Series) -> Optional[float]:
    """12-1 momentum: return from t-252 to t-21. None if insufficient data.
    Returns the float return (e.g., 0.30 = +30%)."""
    if len(closes) < 252:
        return None
    past = closes.iloc[-252]
    skip = closes.iloc[-21]
    if past <= 0:
        return None
    return float(skip / past - 1.0)


def compute_trend_score(closes: pd.Series) -> float:
    """1.0 if price > SMA200 AND SMA20 > SMA50. 0.5 if only one. 0.0 if neither.
    Returns 0.0 if insufficient data for SMA200."""
    if len(closes) < 200:
        return 0.0
    price = closes.iloc[-1]
    s200 = float(sma(closes, 200).iloc[-1])
    s50  = float(sma(closes, 50).iloc[-1])
    s20  = float(sma(closes, 20).iloc[-1])
    score = 0.0
    if price > s200:
        score += 0.5
    if s20 > s50:
        score += 0.5
    return score


def compute_4quadrant_score(snapshot: dict) -> dict:
    """Synthesize Value/Quality/Momentum/Trend scores into one 0-4 total.

    Required keys in snapshot:
      pe, eps, price, roe, eps_history, closes (pd.Series), sector_median_pe.
    Missing keys -> that quadrant scores 0.

    Each quadrant is binarized at threshold 0.5 -> 0 or 1, so total in {0,1,2,3,4}.
    """
    v = compute_value_score(snapshot, {"pe": snapshot.get("sector_median_pe")})
    q = compute_quality_score(snapshot)
    m_raw = compute_momentum_score(snapshot.get("closes", pd.Series(dtype=float)))
    m = 1.0 if (m_raw is not None and m_raw > 0) else 0.0
    t = compute_trend_score(snapshot.get("closes", pd.Series(dtype=float)))
    bin_v = 1 if v >= 0.5 else 0
    bin_q = 1 if q >= 0.5 else 0
    bin_m = 1 if m >= 0.5 else 0
    bin_t = 1 if t >= 0.5 else 0
    return {
        "value": bin_v, "quality": bin_q, "momentum": bin_m, "trend": bin_t,
        "total": bin_v + bin_q + bin_m + bin_t,
        "raw": {"value": v, "quality": q, "momentum_return": m_raw, "trend": t},
    }
