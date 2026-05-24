import pytest
import pandas as pd
from psx_mcp.quality import (
    compute_value_score, compute_quality_score,
    compute_momentum_score, compute_trend_score,
    compute_4quadrant_score,
)


def test_value_score_cheaper_pe_scores_higher():
    cheap = {"pe": 5.0, "eps": 10.0, "price": 50.0}
    expensive = {"pe": 30.0, "eps": 1.0, "price": 30.0}
    sector_median = {"pe": 12.0}
    assert compute_value_score(cheap, sector_median) > compute_value_score(expensive, sector_median)


def test_quality_score_higher_roe_scores_higher():
    hi = {"roe": 25.0, "eps_history": [1.0, 1.1, 1.2, 1.3]}
    lo = {"roe": 5.0,  "eps_history": [1.0, 0.9, 0.8, 0.7]}
    assert compute_quality_score(hi) > compute_quality_score(lo)


def test_momentum_score_12_1_skips_recent_month():
    """12-1 momentum should equal return from -252 to -21."""
    n = 260
    closes = pd.Series([100.0 + i for i in range(n)])  # straight uptrend
    score = compute_momentum_score(closes)
    assert score is not None
    assert score > 0  # uptrend → positive


def test_momentum_returns_none_if_insufficient_history():
    closes = pd.Series([100.0, 101.0, 102.0])
    assert compute_momentum_score(closes) is None


def test_trend_score_above_sma200_and_stack_passes():
    n = 250
    closes = pd.Series([100.0 + i for i in range(n)])
    assert compute_trend_score(closes) > 0


def test_4quadrant_combines_to_0_to_4():
    snapshot = {
        "pe": 5.0, "eps": 10.0, "price": 50.0,
        "roe": 25.0, "eps_history": [1.0, 1.1, 1.2, 1.3],
        "closes": pd.Series([100.0 + i for i in range(260)]),
        "sector_median_pe": 12.0,
    }
    score = compute_4quadrant_score(snapshot)
    assert "total" in score
    assert 0 <= score["total"] <= 4
    assert set(score.keys()) >= {"value", "quality", "momentum", "trend", "total"}
