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


def sortino(closes: pd.Series, rf_annual: float = 0.0) -> Optional[float]:
    """Annualized Sortino ratio.

    FORMULA CONVENTION NOTE (M1):
    This implementation uses the "downside-distribution stdev" variant:
        sortino = (mean_excess_return * periods_per_year) /
                  (std(downside_returns) * sqrt(periods_per_year))

    where `downside_returns` are the subset of excess returns strictly below
    zero (vs. the per-period risk-free rate). The stdev is taken of THAT
    subset's distribution, not the canonical Sortino (1991) "target
    semi-deviation" which divides sum-of-squared-shortfalls by the full
    sample size N (including non-downside periods).

    Consequence: this number is NOT directly comparable to industry-reported
    Sortino figures (e.g., Morningstar, PortfolioVisualizer) that use the
    target semi-deviation convention. It will generally read HIGHER than
    those because we divide by a smaller-denominator stdev.

    Returns None if:
      - < 2 closes
      - no returns
      - no downside returns (stdev would be undefined)
      - downside stdev is zero
    """
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    rf_per_period = rf_annual / TRADING_DAYS
    excess = rets - rf_per_period
    downside = excess[excess < 0]
    if len(downside) == 0:
        return None
    dd_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    if dd_std == 0.0 or not math.isfinite(dd_std):
        return None
    mean_excess = float(excess.mean())
    annualized_excess = mean_excess * TRADING_DAYS
    annualized_dd = dd_std * math.sqrt(TRADING_DAYS)
    return float(annualized_excess / annualized_dd)


def calmar(closes: pd.Series) -> Optional[float]:
    """Calmar ratio = CAGR / |Max Drawdown|.

    Returns None if:
      - CAGR cannot be computed
      - No drawdown (max DD is 0 or undefined)
    """
    if closes is None or len(closes) < 2:
        return None
    c = cagr(closes)
    if c is None:
        return None
    running_max = closes.cummax()
    drawdowns = (closes / running_max) - 1.0  # ≤ 0
    max_dd = float(drawdowns.min())  # most negative
    if not math.isfinite(max_dd) or max_dd >= 0.0:
        return None
    return float(c / abs(max_dd))


def information_ratio(
    stock_closes: pd.Series, benchmark_closes: pd.Series
) -> Optional[float]:
    """Annualized Information Ratio = (mean active return) / (tracking error).

    Active return = stock return - benchmark return, per period.
    Tracking error = stdev of active returns.
    Both are tail-aligned: if series differ in length, the LAST
    min(len(stock), len(bench)) closes of each are used.

    Returns None if:
      - either series has < 2 closes after alignment
      - tracking error is zero or non-finite
    """
    if stock_closes is None or benchmark_closes is None:
        return None
    n = min(len(stock_closes), len(benchmark_closes))
    if n < 2:
        return None
    s = stock_closes.iloc[-n:].reset_index(drop=True)
    b = benchmark_closes.iloc[-n:].reset_index(drop=True)
    s_rets = s.pct_change().dropna()
    b_rets = b.pct_change().dropna()
    # Both should yield n-1 returns after tail-alignment
    m = min(len(s_rets), len(b_rets))
    if m < 2:
        return None
    s_rets = s_rets.iloc[-m:].reset_index(drop=True)
    b_rets = b_rets.iloc[-m:].reset_index(drop=True)
    active = s_rets - b_rets
    te = float(active.std(ddof=1))
    if te == 0.0 or not math.isfinite(te):
        return None
    mean_active = float(active.mean())
    annualized_active = mean_active * TRADING_DAYS
    annualized_te = te * math.sqrt(TRADING_DAYS)
    return float(annualized_active / annualized_te)


def omega_ratio(closes: pd.Series, threshold: float = 0.0) -> Optional[float]:
    """Omega ratio = sum(gains above threshold) / sum(losses below threshold).

    `threshold` is a per-period return threshold (decimal). Default 0
    means: gains/losses partitioned at zero return.

    Returns None if:
      - < 2 closes
      - no returns
      - denominator (losses) is zero (would be infinite)
    """
    if closes is None or len(closes) < 2:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    excess = rets - threshold
    gains = float(excess[excess > 0].sum())
    losses = float(-excess[excess < 0].sum())  # positive magnitude
    if losses == 0.0 or not math.isfinite(losses):
        return None
    return float(gains / losses)


def var_historical(closes: pd.Series, confidence: float = 0.05) -> Optional[float]:
    """Historical Value-at-Risk: the `confidence`-quantile of bar-over-bar returns.

    With `confidence=0.05`, returns the 5th-percentile return (typically
    negative) — the threshold such that returns below it occur 5% of the time.

    Returns None if:
      - < 2 closes
      - no returns
      - confidence is not in (0, 1)
    """
    if closes is None or len(closes) < 2:
        return None
    if not (0.0 < confidence < 1.0):
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    return float(np.quantile(rets.values, confidence))


def cvar_historical(closes: pd.Series, confidence: float = 0.05) -> Optional[float]:
    """Historical Conditional Value-at-Risk (Expected Shortfall):
    mean of returns at or below the `confidence`-quantile.

    More negative than `var_historical` for the same confidence level.

    Returns None if:
      - < 2 closes
      - no returns
      - confidence is not in (0, 1)
      - tail subset is empty
    """
    if closes is None or len(closes) < 2:
        return None
    if not (0.0 < confidence < 1.0):
        return None
    rets = closes.pct_change().dropna()
    if len(rets) == 0:
        return None
    threshold = float(np.quantile(rets.values, confidence))
    tail = rets[rets <= threshold]
    if len(tail) == 0:
        return None
    return float(tail.mean())


def skewness(closes: pd.Series) -> Optional[float]:
    """Sample skewness of bar-over-bar returns (third standardized moment).

    Uses the population (biased) estimator: E[((X - mu)/sigma)^3].
    Positive → right-skewed (longer right tail); negative → left-skewed.

    Returns None if:
      - < 3 closes
      - stdev is zero or non-finite
    """
    if closes is None or len(closes) < 3:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    arr = rets.values.astype(float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=0))
    if std == 0.0 or not math.isfinite(std):
        return None
    return float(((arr - mean) ** 3).mean() / (std ** 3))


def kurtosis_excess(closes: pd.Series) -> Optional[float]:
    """Excess kurtosis of bar-over-bar returns: fourth standardized moment - 3.

    Uses the population (biased) estimator. Zero for a normal distribution;
    positive → fatter tails / more peaked than normal (leptokurtic).

    Returns None if:
      - < 3 closes
      - stdev is zero or non-finite
    """
    if closes is None or len(closes) < 3:
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    arr = rets.values.astype(float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=0))
    if std == 0.0 or not math.isfinite(std):
        return None
    return float(((arr - mean) ** 4).mean() / (std ** 4) - 3.0)


def tail_ratio(closes: pd.Series, quantile: float = 0.05) -> Optional[float]:
    """Tail ratio = |upper-tail quantile| / |lower-tail quantile| of returns.

    With `quantile=0.05`, compares the 95th-percentile return to the
    5th-percentile return (in magnitude). >1 means right tail dominates
    (good); <1 means left tail dominates (bad).

    Returns None if:
      - < 2 closes
      - quantile not in (0, 0.5)
      - no returns
      - lower-tail magnitude is zero or non-finite
    """
    if closes is None or len(closes) < 2:
        return None
    if not (0.0 < quantile < 0.5):
        return None
    rets = closes.pct_change().dropna()
    if len(rets) < 2:
        return None
    upper = float(np.quantile(rets.values, 1.0 - quantile))
    lower = float(np.quantile(rets.values, quantile))
    denom = abs(lower)
    if denom == 0.0 or not math.isfinite(denom):
        return None
    return float(abs(upper) / denom)
