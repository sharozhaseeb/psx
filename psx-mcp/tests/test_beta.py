import pytest
import pandas as pd
import numpy as np
from psx_mcp.beta import beta


def test_beta_of_identical_series_is_one():
    s = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    result = beta(stock_closes=s, index_closes=s, window=None)
    assert result["beta"] == pytest.approx(1.0)
    assert result["r_squared"] == pytest.approx(1.0)
    assert result["n"] == 9


def test_beta_of_double_series_is_two():
    idx = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0])
    stock_returns = idx.pct_change().dropna() * 2
    stock_vals = [100.0]
    for r in stock_returns:
        stock_vals.append(stock_vals[-1] * (1 + r))
    stock = pd.Series(stock_vals)
    result = beta(stock_closes=stock, index_closes=idx, window=None)
    assert result["beta"] == pytest.approx(2.0, abs=0.01)


def test_beta_returns_none_when_insufficient_overlap():
    s = pd.Series([100.0, 101.0])
    result = beta(stock_closes=s, index_closes=s, window=None)
    assert result["beta"] is None
    assert result["n"] == 1


def test_beta_window_limits_to_last_n_returns():
    idx = pd.Series([100.0 + i for i in range(100)])
    stock = idx.copy()
    result = beta(stock_closes=stock, index_closes=idx, window=20)
    assert result["n"] == 20
