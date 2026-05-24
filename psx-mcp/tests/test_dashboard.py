import pytest
from datetime import datetime, date, timedelta
import server as srv
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.watchlist import WatchlistStore


def _seed_full(cache: Cache, sym: str, sector: str = "TECH"):
    """Seed a symbol with everything full_analysis touches."""
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    cache.upsert_symbol(sym, sym, sector, None)
    cache.upsert_quote(symbol=sym, ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    # Seed 260 bars with realistic high/low spread so ATR > 0 (the indicators
    # default bundle includes atr14 — fixes M4 from review).
    bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                open=100.0 + i, high=100.0 + i + 5, low=100.0 + i - 5,
                close=100.0 + i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    # Index for relative_strength + beta (date-aligned with stock bars)
    for i in range(260):
        d = today - timedelta(days=259 - i)
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=170_000.0 + i, volume=1e8)


def test_get_full_analysis_combines_all_sections(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    _seed_full(cache, "SYS")
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_full_analysis_impl(cache, "SYS")
    assert out.symbol == "SYS"
    assert out.quote is not None
    assert out.fundamentals is not None
    assert out.week52 is not None
    assert out.indicators is not None and "rsi14" in out.indicators
    assert out.drawdown is not None
    assert out.risk is not None
    assert out.beta is not None
    assert out.relative_strength is not None
    assert out.quadrant_score is not None
    assert isinstance(out.warnings, list)


def test_get_full_analysis_handles_missing_data(tmp_path):
    """Empty cache → response with warnings, no crash."""
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_full_analysis_impl(cache, "NOSUCH")
    assert out.symbol == "NOSUCH"
    assert len(out.warnings) > 0
