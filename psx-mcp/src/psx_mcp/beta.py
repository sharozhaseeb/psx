"""Pure-function beta / alpha / R-squared over aligned close series."""
from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np


def beta(stock_closes: pd.Series, index_closes: pd.Series,
         window: Optional[int] = 252) -> dict:
    """Compute beta of stock_closes vs index_closes via OLS on returns.

    Args:
      stock_closes, index_closes: pandas Series of closes (need not be aligned by index;
        we align by position from the END of each).
      window: number of most-recent returns to use, or None for all available.

    Returns: {beta, alpha, r_squared, n}. beta/alpha/r_squared are None if n < 2.
    """
    stock_returns = stock_closes.pct_change().dropna().reset_index(drop=True)
    index_returns = index_closes.pct_change().dropna().reset_index(drop=True)
    n_overlap = min(len(stock_returns), len(index_returns))
    if window is not None:
        n_overlap = min(n_overlap, window)
    if n_overlap < 2:
        return {"beta": None, "alpha": None, "r_squared": None, "n": n_overlap}
    s = stock_returns.iloc[-n_overlap:].values
    x = index_returns.iloc[-n_overlap:].values
    cov_xy = np.cov(x, s, ddof=1)[0, 1]
    var_x = np.var(x, ddof=1)
    if var_x == 0:
        return {"beta": None, "alpha": None, "r_squared": None, "n": n_overlap}
    b = float(cov_xy / var_x)
    a = float(s.mean() - b * x.mean())
    ss_res = float(np.sum((s - (a + b * x)) ** 2))
    ss_tot = float(np.sum((s - s.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else None
    return {"beta": b, "alpha": a, "r_squared": r2, "n": int(n_overlap)}
