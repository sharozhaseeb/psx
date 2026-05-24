from datetime import datetime, date, timedelta
import pytest

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.alerts import evaluate_rule, run_alerts
from psx_mcp.models import AlertRule, AlertCondition, Bar, Announcement


def _seed_bars(cache: Cache, symbol: str, closes: list[float],
               volumes: list[int] | None = None) -> None:
    volumes = volumes or [1000] * len(closes)
    bars = []
    end = date.today()
    n = len(closes)
    for i, (c, v) in enumerate(zip(closes, volumes)):
        bars.append(Bar(symbol=symbol, date=end - timedelta(days=(n - 1 - i)),
                        open=c, high=c, low=c, close=c, volume=v))
    cache.upsert_bars(bars)


def test_price_rule_triggers(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_quote(symbol="LUCK", ts=datetime.now(), price=850.0, change=10,
                   volume=1000, day_high=860, day_low=840, fetched_at=datetime.now())
    rule = AlertRule(id="r1", symbol="LUCK", type="price",
                     condition=AlertCondition(op=">", value=800),
                     active=True, created_at=date.today())
    hit = evaluate_rule(c, rule)
    assert hit is not None
    assert "850" in hit.message


def test_price_rule_does_not_trigger(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_quote(symbol="LUCK", ts=datetime.now(), price=750.0, change=0,
                   volume=0, day_high=0, day_low=0, fetched_at=datetime.now())
    rule = AlertRule(id="r1", symbol="LUCK", type="price",
                     condition=AlertCondition(op=">", value=800),
                     active=True, created_at=date.today())
    assert evaluate_rule(c, rule) is None


def test_indicator_rsi_oversold(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    _seed_bars(c, "LUCK", [float(x) for x in range(120, 80, -1)])
    rule = AlertRule(id="r2", symbol="LUCK", type="indicator",
                     condition=AlertCondition(indicator="rsi14", op="<", value=40),
                     active=True, created_at=date.today())
    hit = evaluate_rule(c, rule)
    assert hit is not None


def test_volume_rule_triggers_on_spike(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    volumes = [1000] * 19 + [5000]
    _seed_bars(c, "LUCK", [100.0] * 20, volumes)
    rule = AlertRule(id="r3", symbol="LUCK", type="volume",
                     condition=AlertCondition(op=">", value=2.0, lookback_days=20),
                     active=True, created_at=date.today())
    hit = evaluate_rule(c, rule)
    assert hit is not None


def test_announcement_rule_triggers_for_new_filing(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_announcement(Announcement(
        id="a1", symbol="LUCK", posted_at=datetime.now() - timedelta(hours=1),
        title="Board Meeting", category=None, url=None, body=None,
    ))
    rule = AlertRule(id="r4", symbol="LUCK", type="announcement",
                     condition=AlertCondition(op=">", value=0),
                     active=True, created_at=date.today(),
                     last_checked=datetime.now() - timedelta(hours=2))
    hit = evaluate_rule(c, rule)
    assert hit is not None
    assert "Board Meeting" in hit.message


def test_announcement_rule_no_trigger_when_already_checked(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_announcement(Announcement(
        id="a1", symbol="LUCK", posted_at=datetime.now() - timedelta(hours=3),
        title="Board Meeting", category=None, url=None, body=None,
    ))
    rule = AlertRule(id="r4", symbol="LUCK", type="announcement",
                     condition=AlertCondition(op=">", value=0),
                     active=True, created_at=date.today(),
                     last_checked=datetime.now() - timedelta(hours=1))
    assert evaluate_rule(c, rule) is None


def test_run_alerts_iterates_active_rules(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    store = WatchlistStore(str(tmp_path / "wl.json"))
    c.upsert_quote(symbol="LUCK", ts=datetime.now(), price=900.0, change=0,
                   volume=0, day_high=0, day_low=0, fetched_at=datetime.now())
    store.set_alert_rule(symbol="LUCK", type="price",
                         condition=AlertCondition(op=">", value=800))
    hits = run_alerts(c, store)
    assert len(hits) == 1


def test_evaluate_fundamental_rule_pe_below_triggers(tmp_path):
    """PE < threshold should fire."""
    from psx_mcp.cache import Cache
    from psx_mcp.models import AlertRule, AlertCondition
    from psx_mcp.alerts import evaluate_rule
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    rule = AlertRule(
        id="rid", symbol="SYS", type="fundamental",
        condition=AlertCondition(indicator="pe", op="<", value=10.0),
        active=True, created_at=date.today(),
    )
    hit = evaluate_rule(cache, rule)
    assert hit is not None
    assert "pe" in hit.message.lower()


def test_evaluate_fundamental_rule_pe_above_threshold_no_trigger(tmp_path):
    from psx_mcp.cache import Cache
    from psx_mcp.models import AlertRule, AlertCondition
    from psx_mcp.alerts import evaluate_rule
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=12.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    rule = AlertRule(
        id="rid", symbol="SYS", type="fundamental",
        condition=AlertCondition(indicator="pe", op="<", value=10.0),
        active=True, created_at=date.today(),
    )
    assert evaluate_rule(cache, rule) is None


def test_evaluate_fundamental_rule_missing_indicator_returns_none(tmp_path):
    """No fundamentals cached -> silently None, no crash."""
    from psx_mcp.cache import Cache
    from psx_mcp.models import AlertRule, AlertCondition
    from psx_mcp.alerts import evaluate_rule
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    rule = AlertRule(
        id="rid", symbol="NOSUCH", type="fundamental",
        condition=AlertCondition(indicator="pe", op="<", value=10.0),
        active=True, created_at=date.today(),
    )
    assert evaluate_rule(cache, rule) is None
