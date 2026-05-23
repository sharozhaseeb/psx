from datetime import datetime, date, timedelta
import pytest
from psx_mcp.cache import Cache
from psx_mcp.models import Bar, Announcement


@pytest.fixture
def cache(tmp_path):
    db = tmp_path / "t.db"
    return Cache(str(db))


def test_schema_created(cache):
    tables = cache.list_tables()
    for t in ["symbols", "quotes", "bars_daily", "announcements", "fundamentals", "news"]:
        assert t in tables


def test_upsert_quote_and_fetch(cache):
    cache.upsert_quote(
        symbol="LUCK", ts=datetime(2026, 5, 23, 10, 0),
        price=750.0, change=10.0, volume=1000, day_high=760, day_low=740,
        fetched_at=datetime(2026, 5, 23, 10, 1),
    )
    q = cache.get_latest_quote("LUCK")
    assert q is not None
    assert q["price"] == 750.0


def test_quote_freshness(cache):
    cache.upsert_quote(
        symbol="LUCK", ts=datetime.now(),
        price=1, change=0, volume=0, day_high=0, day_low=0,
        fetched_at=datetime.now() - timedelta(minutes=2),
    )
    assert cache.is_quote_fresh("LUCK", ttl_seconds=300)
    assert not cache.is_quote_fresh("LUCK", ttl_seconds=30)


def test_append_bars_idempotent(cache):
    today = date.today()
    bars = [
        Bar(symbol="LUCK", date=today - timedelta(days=2), open=700, high=710, low=695, close=705, volume=10),
        Bar(symbol="LUCK", date=today - timedelta(days=1), open=705, high=720, low=702, close=718, volume=12),
    ]
    cache.upsert_bars(bars)
    cache.upsert_bars(bars)
    rows = cache.get_bars("LUCK", today - timedelta(days=10), today)
    assert len(rows) == 2


def test_get_bars_date_range(cache):
    today = date.today()
    bars = [
        Bar(symbol="LUCK", date=today - timedelta(days=d), open=1, high=1, low=1, close=1, volume=1)
        for d in (4, 3, 2, 1, 0)
    ]
    cache.upsert_bars(bars)
    got = cache.get_bars("LUCK", today - timedelta(days=2), today - timedelta(days=1))
    assert len(got) == 2


def test_announcements_upsert(cache):
    a = Announcement(
        id="a1", symbol="LUCK", posted_at=datetime(2026, 5, 23, 9),
        title="Board Meeting", category="board", url="http://x", body=None,
    )
    cache.upsert_announcement(a)
    cache.upsert_announcement(a)
    rows = cache.get_announcements(symbol="LUCK", since=datetime(2026, 1, 1))
    assert len(rows) == 1


def test_symbol_master_refresh(cache):
    cache.upsert_symbol("LUCK", "Lucky Cement Limited", "Cement", 323_375_503)
    s = cache.get_symbol("LUCK")
    assert s["name"] == "Lucky Cement Limited"
