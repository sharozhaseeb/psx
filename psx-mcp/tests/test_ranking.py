import pytest
from datetime import datetime, date, timedelta
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.ranking import rank_sectors


@pytest.fixture
def seeded(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    universe = [
        ("AAA", "TECH", 100.0, +5.0),
        ("BBB", "TECH", 50.0, +2.0),
        ("CCC", "CEMENT", 200.0, -3.0),
        ("DDD", "CEMENT", 100.0, -2.0),
    ]
    for sym, sector, price, change in universe:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                            volume=10_000, day_high=price+1, day_low=price-1,
                            fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=10.0, pb=None,
                                   div_yield=None, payout=None, roe=None)
        # 260 bars so compute_momentum_score (needs >= 252) has data
        bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                     open=price * (0.8 + i / 260 * 0.4),
                     high=price * (0.81 + i / 260 * 0.4),
                     low=price * (0.79 + i / 260 * 0.4),
                     close=price * (0.8 + i / 260 * 0.4),
                     volume=10_000) for i in range(260)]
        cache.upsert_bars(bars)
    return cache


def test_rank_sectors_by_avg_change_pct(seeded):
    out = rank_sectors(seeded, sectors=["TECH", "CEMENT"], by="avg_change_pct")
    assert out[0]["sector"] == "TECH"
    assert out[1]["sector"] == "CEMENT"
    assert out[0]["avg_change_pct"] > out[1]["avg_change_pct"]


def test_rank_sectors_by_breadth(seeded):
    out = rank_sectors(seeded, sectors=["TECH", "CEMENT"], by="pct_above_sma200")
    assert all("pct_above_sma200" in r for r in out)


def test_rank_sectors_drops_empty_sectors(seeded):
    out = rank_sectors(seeded, sectors=["NOSUCH"], by="avg_change_pct")
    assert out == []
