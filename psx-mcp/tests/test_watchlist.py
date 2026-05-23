from datetime import date
import pytest
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.models import AlertCondition


@pytest.fixture
def store(tmp_path):
    return WatchlistStore(str(tmp_path / "wl.json"))


def test_add_and_list_watch(store):
    store.add_watch("LUCK", "favorite cement")
    entries = store.list_watch()
    assert len(entries) == 1
    assert entries[0].symbol == "LUCK"


def test_add_is_idempotent(store):
    store.add_watch("LUCK")
    store.add_watch("luck")
    assert len(store.list_watch()) == 1


def test_remove_watch(store):
    store.add_watch("LUCK")
    assert store.remove_watch("LUCK") is True
    assert store.list_watch() == []


def test_set_alert_rule_generates_id(store):
    cond = AlertCondition(indicator="rsi14", op="<", value=30)
    rule = store.set_alert_rule(symbol="LUCK", type="indicator", condition=cond)
    assert rule.id
    assert rule.symbol == "LUCK"


def test_list_and_remove_rule(store):
    cond = AlertCondition(op=">", value=800)
    rule = store.set_alert_rule(symbol="LUCK", type="price", condition=cond)
    rules = store.list_alert_rules(symbol="LUCK")
    assert any(r.id == rule.id for r in rules)
    assert store.remove_alert_rule(rule.id) is True
    assert store.list_alert_rules() == []


def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "wl.json")
    s1 = WatchlistStore(p)
    s1.add_watch("LUCK")
    s2 = WatchlistStore(p)
    assert s2.list_watch()[0].symbol == "LUCK"
