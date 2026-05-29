import pytest
from datetime import datetime, date, timedelta
import server as srv
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.watchlist import WatchlistStore


def _seed_uptrend(cache: Cache, sym: str, sector: str = "TECH"):
    """Seed a symbol with 260 bars (uptrend) + 260 KSE100 index bars on same dates."""
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    cache.upsert_symbol(sym, sym, sector, None)
    cache.upsert_quote(symbol=sym, ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    # 260 bars with high=close+1, low=close-1 (per plan)
    bars = []
    for i in range(260):
        d = today - timedelta(days=259 - i)
        c = 100.0 + i
        bars.append(Bar(symbol=sym, date=d, open=c, high=c + 1, low=c - 1,
                        close=c, volume=1000))
    cache.upsert_bars(bars)
    # 260 KSE100 index bars on the SAME dates (date-aligned for IR / capture)
    for i in range(260):
        d = today - timedelta(days=259 - i)
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=170_000.0 + i * 10, volume=1e8)


def test_get_extended_risk_metrics_seeded_uptrend(tmp_path):
    """260 seeded bars + 260 aligned index bars → all 6 sections non-None."""
    cache = Cache(str(tmp_path / "c.db"))
    _seed_uptrend(cache, "SYS")
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_extended_risk_metrics_impl(cache, "SYS")
    assert out.symbol == "SYS"
    assert out.return_stats is not None
    assert out.risk_adjusted is not None
    assert out.distribution is not None
    assert out.drawdown is not None
    assert out.capture is not None
    assert out.technical is not None
    assert isinstance(out.warnings, list)


def test_get_extended_risk_metrics_empty_cache(tmp_path):
    """Empty cache → warnings populated, no crash."""
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_extended_risk_metrics_impl(cache, "NOSUCH")
    assert out.symbol == "NOSUCH"
    assert len(out.warnings) > 0
