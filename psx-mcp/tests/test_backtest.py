import pytest
from datetime import date, timedelta
from psx_mcp.backtest import backtest_simple


def test_backtest_simple_constant_uptrend_yields_positive_return():
    """One symbol, uptrending closes. Always pass the filter → consistent positive return."""
    today = date(2026, 5, 23)
    closes = {
        ("XYZ", today - timedelta(days=n)): 100.0 + (180 - n)
        for n in range(180)
    }
    signals = {(today - timedelta(days=n)): ["XYZ"] for n in range(120)}
    out = backtest_simple(closes_by_sym_date=closes,
                          signals_by_date=signals,
                          hold_days=20)
    assert out["n_trades"] > 0
    assert out["mean_return_pct"] > 0
    assert all(t["return_pct"] > 0 for t in out["trades"])


def test_backtest_simple_no_signals_returns_zero_trades():
    out = backtest_simple(closes_by_sym_date={}, signals_by_date={}, hold_days=20)
    assert out["n_trades"] == 0
    assert out["mean_return_pct"] is None


def test_backtest_simple_hold_past_data_end_drops_trade():
    """If signal date + hold_days > last available close, skip the trade."""
    today = date(2026, 5, 23)
    closes = {
        ("XYZ", today - timedelta(days=n)): 100.0 + (10 - n)
        for n in range(10)
    }
    signals = {today - timedelta(days=2): ["XYZ"]}
    out = backtest_simple(closes_by_sym_date=closes,
                          signals_by_date=signals,
                          hold_days=20)
    assert out["n_trades"] == 0
