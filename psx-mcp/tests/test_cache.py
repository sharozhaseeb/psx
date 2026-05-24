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


def test_fifty_two_week_returns_max_min_of_last_252_closes(tmp_path):
    db = tmp_path / "c.db"
    cache = Cache(str(db))
    # Seed 300 days of synthetic history for "XYZ"
    import datetime as dt
    base = dt.date(2025, 1, 1)
    rows = []
    for i in range(300):
        d = base + dt.timedelta(days=i)
        close = 100 + (i % 50)
        rows.append((d.isoformat(), "XYZ", 100.0, close + 5, close - 5, float(close), 1000))
    # No bulk-insert helper exists for raw history tuples; use raw INSERT via conn.
    cache.conn.executemany(
        """INSERT INTO bars_daily(date, symbol, open, high, low, close, volume)
           VALUES(?,?,?,?,?,?,?)""",
        rows,
    )
    cache.conn.commit()

    hi, lo = cache.fifty_two_week("XYZ")
    # Last 252 rows -> i in [48..299]. close = 100 + (i % 50).
    # max close in window is 149, so high = 149 + 5 = 154.
    # min close in window is 100, so low = 100 - 5 = 95.
    assert hi == 154.0
    assert lo == 95.0


def test_fifty_two_week_returns_zero_when_no_history(cache):
    hi, lo = cache.fifty_two_week("NOPE")
    assert hi == 0.0
    assert lo == 0.0


def test_top_movers_returns_sorted_gainers_and_losers(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    quotes = [
        ("AAA", 100.0, 5.0, 1000),
        ("BBB", 100.0, 3.0, 2000),
        ("CCC", 100.0, 1.0, 3000),
        ("DDD", 100.0, -2.0, 4000),
        ("EEE", 100.0, -4.0, 5000),
    ]
    ts = datetime(2026, 5, 23, 10, 0)
    for sym, price, change, volume in quotes:
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=volume, day_high=price + 1, day_low=price - 1,
                           fetched_at=ts)
    movers = cache.top_movers(n=2)
    # gainers: descending change_pct order
    assert [m["symbol"] for m in movers["gainers"]] == ["AAA", "BBB"]
    # losers: ascending change_pct order (most negative first)
    assert [m["symbol"] for m in movers["losers"]] == ["EEE", "DDD"]


def test_top_movers_skips_invalid_prev_close(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    # change == price -> prev_close == 0, should be skipped
    cache.upsert_quote(symbol="ZERO", ts=ts, price=10.0, change=10.0,
                       volume=100, day_high=11, day_low=9, fetched_at=ts)
    # price 0 -> filtered by WHERE clause
    cache.upsert_quote(symbol="DEAD", ts=ts, price=0.0, change=0.0,
                       volume=0, day_high=0, day_low=0, fetched_at=ts)
    cache.upsert_quote(symbol="GOOD", ts=ts, price=50.0, change=2.0,
                       volume=500, day_high=51, day_low=49, fetched_at=ts)
    movers = cache.top_movers(n=5)
    # ZERO and DEAD are excluded; only GOOD remains
    assert [m["symbol"] for m in movers["gainers"]] == ["GOOD"]
    assert [m["symbol"] for m in movers["losers"]] == ["GOOD"]
    assert [m["symbol"] for m in movers["by_volume"]] == ["GOOD"]


def test_closes_for_returns_all_bars_ascending(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    # Seed so that oldest date has lowest close, newest has highest; date-ascending
    # then implies value-ascending, letting `closes == sorted(closes)` verify order.
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=9 - i),
                open=100.0, high=110.0, low=90.0, close=100.0 + i, volume=1000)
            for i in range(10)]
    cache.upsert_bars(bars)
    closes = cache.closes_for("XYZ")
    assert len(closes) == 10
    assert closes == sorted(closes)  # ascending by date -> oldest first


def test_screen_candidates_filters_via_parameterized_sql(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    cache.upsert_symbol("SYS", "Systems", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_symbol("HUBC", "Hub Power", "POWER GENERATION & DISTRIBUTION", None)
    for sym, price, change, vol, pe in [
        ("SYS", 600.0, 5.0, 100_000, 12.0),
        ("HUBC", 200.0, 1.0, 200_000, 8.0),
    ]:
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change, volume=vol,
                           day_high=price+1, day_low=price-1, fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=pe, pb=None,
                                  div_yield=None, payout=None, roe=None)
    out = cache.screen_candidates("s.sector = ? AND f.pe <= ?",
                                  ["TECHNOLOGY & COMMUNICATION", 15.0])
    assert len(out) == 1
    assert out[0]["symbol"] == "SYS"


def test_fifty_two_week_handles_partial_history(cache):
    import datetime as dt
    base = dt.date(2025, 1, 1)
    # Only 10 days of bars — less than 252.
    rows = []
    for i in range(10):
        d = base + dt.timedelta(days=i)
        rows.append((d.isoformat(), "ABC", 100.0, 110.0 + i, 90.0 - i, 100.0, 100))
    cache.conn.executemany(
        """INSERT INTO bars_daily(date, symbol, open, high, low, close, volume)
           VALUES(?,?,?,?,?,?,?)""",
        rows,
    )
    cache.conn.commit()
    hi, lo = cache.fifty_two_week("ABC")
    assert hi == 119.0  # 110 + 9
    assert lo == 81.0   # 90 - 9
