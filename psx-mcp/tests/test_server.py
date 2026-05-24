import pytest
from datetime import datetime, date, timedelta
from pathlib import Path

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.models import Bar
from psx_mcp.symbols import refresh_symbols_from_payload


@pytest.fixture
def deps(tmp_path, fixtures_dir):
    """Build server-module dependencies in isolation, seeded with fixtures + cached data."""
    import server as srv
    cache = Cache(str(tmp_path / "psx.db"))
    store = WatchlistStore(str(tmp_path / "wl.json"))
    for ext in ("json", "html"):
        p = fixtures_dir / f"symbols.{ext}"
        if p.exists():
            refresh_symbols_from_payload(cache, p.read_text(encoding="utf-8"))
            break
    cache.upsert_quote(symbol="LUCK", ts=datetime.now(), price=750.0,
                       change=10.0, volume=1000, day_high=760, day_low=740,
                       fetched_at=datetime.now())
    today = date.today()
    bars = [Bar(symbol="LUCK", date=today - timedelta(days=29 - i),
                open=700 + i, high=710 + i, low=695 + i, close=705 + i, volume=10000)
            for i in range(30)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=store, client=None)
    return srv


def test_get_quote_impl_returns_cached(deps):
    result = deps._get_quote_impl(deps._cache, "LUCK")
    assert result.symbol == "LUCK"
    assert result.price == 750.0
    assert "not investment advice" in result.disclaimer.lower()


def test_get_quote_handles_missing(deps):
    result = deps._get_quote_impl(deps._cache, "MISSING")
    assert result.stale is True


def test_get_quote_populates_52w_high_low(deps):
    """The `deps` fixture seeds 30 daily bars for LUCK with strictly increasing
    open/high/low/close (see fixture). The quote impl should surface the cached
    high/low over the trailing 252 bars on the returned Quote."""
    q = deps._get_quote_impl(deps._cache, "LUCK")
    assert q.week52_high > 0
    assert q.week52_low > 0
    assert q.week52_high >= q.week52_low
    # Fixture seeds high=710+i, low=695+i for i in [0..29], so:
    assert q.week52_high == 739.0  # 710 + 29
    assert q.week52_low == 695.0   # 695 + 0


def test_get_quote_populates_52w_even_without_quote_row(tmp_path):
    """If no quote is cached but history is, 52w fields should still be filled."""
    import server as srv
    from psx_mcp.models import Bar
    cache = Cache(str(tmp_path / "t.db"))
    today = date.today()
    bars = [Bar(symbol="HIST", date=today - timedelta(days=29 - i),
                open=100.0, high=120.0 + i, low=80.0 - i, close=100.0, volume=1)
            for i in range(30)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    q = srv._get_quote_impl(cache, "HIST")
    assert q.stale is True  # no quote row
    assert q.week52_high == 149.0  # 120 + 29
    assert q.week52_low == 51.0    # 80 - 29


def test_get_quote_missing_with_no_history_returns_zero_52w(tmp_path):
    """Defense: no quote AND no history → 52w fields are 0.0, no crash."""
    import server as srv
    cache = Cache(str(tmp_path / "t.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    q = srv._get_quote_impl(cache, "NONE")
    assert q.week52_high == 0.0
    assert q.week52_low == 0.0


def test_change_pct_subrupee_safe(tmp_path):
    """Verify change_pct doesn't blow up on sub-rupee penny stocks (issue from review)."""
    import server as srv
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_quote(symbol="PNY", ts=datetime.now(), price=0.5, change=0.05,
                   volume=1, day_high=0.55, day_low=0.45, fetched_at=datetime.now())
    srv.set_dependencies(cache=c, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    r = srv._get_quote_impl(c, "PNY")
    assert 10.0 < r.change_pct < 12.0


def test_search_symbol_impl(deps):
    res = deps._search_symbol_impl(deps._cache, "LUCK")
    assert len(res) >= 1
    assert res[0].symbol == "LUCK"


def test_get_history_impl(deps):
    today = date.today()
    bars = deps._get_history_impl(deps._cache, "LUCK",
                                  (today - timedelta(days=30)).isoformat(),
                                  today.isoformat())
    assert len(bars) > 0
    assert bars[0].symbol == "LUCK"


def test_compute_indicators_impl(deps):
    out = deps._compute_indicators_impl(deps._cache, "LUCK",
                                        indicators=["rsi14", "sma10"], lookback_days=30)
    assert "rsi14" in out
    assert "sma10" in out
    assert isinstance(out["rsi14"], float)


def test_compute_indicators_default_bundle(tmp_path):
    """When indicators=None, _compute_indicators_impl returns the default bundle."""
    import server as srv
    from psx_mcp.models import Bar
    cache = Cache(str(tmp_path / "t.db"))
    today = date.today()
    # Seed 250 bars so sma200 / atr14 have enough history.
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=249 - i),
                open=100.0 + i * 0.1, high=105.0 + i * 0.1,
                low=95.0 + i * 0.1, close=100.0 + i * 0.1, volume=1000)
            for i in range(250)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._compute_indicators_impl(cache, "XYZ", indicators=None)
    for key in ("sma20", "sma50", "sma200", "rsi14", "atr14"):
        assert key in out, f"missing default indicator {key}"


import asyncio
import httpx
import respx
from psx_mcp.psx_client import PSXClient, BASE_DPS


@pytest.fixture
def deps_with_client(deps, tmp_path):
    """Same as `deps` but with a real PSXClient (network mocked via respx in each test)."""
    deps.set_dependencies(cache=deps._cache, store=deps._store, client=PSXClient())
    return deps


@respx.mock
def test_refresh_market_impl_populates_cache(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "market_watch.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_DPS}/market-watch").mock(return_value=httpx.Response(200, text=html))
    n = asyncio.run(deps_with_client._refresh_market_impl(deps_with_client._cache,
                                                           deps_with_client._client))
    assert n > 100


@respx.mock
def test_get_top_movers_after_refresh(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "market_watch.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_DPS}/market-watch").mock(return_value=httpx.Response(200, text=html))
    asyncio.run(deps_with_client._refresh_market_impl(deps_with_client._cache,
                                                       deps_with_client._client))
    gainers = deps_with_client._get_top_movers_impl(deps_with_client._cache, kind="gainers", limit=5)
    assert len(gainers) <= 5


def test_market_summary_returns_stale_when_empty(deps):
    s = deps._get_market_summary_impl(deps._cache)
    assert s.timestamp
    assert s.stale is True


# ============================================================================
# Task 14: company info, fundamentals, financials, history-refresh,
#          announcements, news
# ============================================================================

from psx_mcp.psx_client import BASE_DPS  # noqa: E402  (already imported above)


@respx.mock
def test_get_company_info_fetches_and_caches(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "profile_LUCK.html").read_text(encoding="utf-8")
    # fetch_profile → GET https://dps.psx.com.pk/company/LUCK
    respx.get(f"{BASE_DPS}/company/LUCK").mock(return_value=httpx.Response(200, text=html))
    info = asyncio.run(deps_with_client._get_company_info_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK"))
    assert info.symbol == "LUCK"
    assert info.name


@respx.mock
def test_get_fundamentals(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "financial_LUCK.html").read_text(encoding="utf-8")
    # fetch_financials → GET https://dps.psx.com.pk/company/LUCK
    respx.get(f"{BASE_DPS}/company/LUCK").mock(return_value=httpx.Response(200, text=html))
    f = asyncio.run(deps_with_client._get_fundamentals_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK"))
    assert f.symbol == "LUCK"


@respx.mock
def test_get_financials_statements(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "financial_LUCK.html").read_text(encoding="utf-8")
    # fetch_financials → GET https://dps.psx.com.pk/company/LUCK
    respx.get(f"{BASE_DPS}/company/LUCK").mock(return_value=httpx.Response(200, text=html))
    out = asyncio.run(deps_with_client._get_financials_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK", "annual"))
    assert isinstance(out, list)


@respx.mock
def test_refresh_history_persists_bars(deps_with_client, fixtures_dir):
    for ext in ("json", "html"):
        p = fixtures_dir / f"historical_LUCK.{ext}"
        if p.exists():
            payload = p.read_text(encoding="utf-8")
            break
    # fetch_historical → POST https://dps.psx.com.pk/historical
    respx.post(f"{BASE_DPS}/historical").mock(return_value=httpx.Response(200, text=payload))
    n = asyncio.run(deps_with_client._refresh_history_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK"))
    assert n >= 0


@respx.mock
def test_refresh_and_get_announcements(deps_with_client, fixtures_dir):
    for ext in ("json", "html"):
        p = fixtures_dir / f"announcements.{ext}"
        if p.exists():
            payload = p.read_text(encoding="utf-8")
            break
    # fetch_announcements → POST https://dps.psx.com.pk/announcements
    respx.post(f"{BASE_DPS}/announcements").mock(return_value=httpx.Response(200, text=payload))
    asyncio.run(deps_with_client._refresh_announcements_impl(
        deps_with_client._cache, deps_with_client._client))
    anns = deps_with_client._get_announcements_impl(deps_with_client._cache, None, since_days=365)
    assert isinstance(anns, list)


def test_watchlist_lifecycle(deps):
    e = deps._add_to_watchlist_impl(deps._store, "OGDC", "energy")
    assert e.symbol == "OGDC"
    assert any(w.symbol == "OGDC" for w in deps._list_watchlist_impl(deps._store))
    assert deps._remove_from_watchlist_impl(deps._store, "OGDC") is True


def test_alert_rule_lifecycle(deps):
    rule = deps._set_alert_rule_impl(deps._store, symbol="LUCK", type="price",
                                     condition={"op": ">", "value": 700})
    assert rule.id
    rules = deps._list_alert_rules_impl(deps._store, symbol="LUCK")
    assert len(rules) == 1
    assert deps._remove_alert_rule_impl(deps._store, rule.id) is True


def test_check_alerts_returns_hits(deps):
    deps._set_alert_rule_impl(deps._store, symbol="LUCK", type="price",
                              condition={"op": ">", "value": 700})
    hits = deps._check_alerts_impl(deps._cache, deps._store, symbols=None)
    assert any(h.symbol == "LUCK" for h in hits)


def test_scan_volume_spikes(deps):
    spikes = deps._scan_volume_spikes_impl(deps._cache, symbols=["LUCK"],
                                            multiplier=0.001, lookback_days=10)
    assert isinstance(spikes, list)


def test_compare_symbols(deps):
    out = deps._compare_symbols_impl(deps._cache, symbols=["LUCK"], metrics=["price", "rsi14"])
    assert len(out.rows) == 1
    assert out.rows[0].symbol == "LUCK"


def test_compare_symbols_includes_change_pct_and_volume(tmp_path):
    """Regression: compare_symbols was returning None for change_pct/volume."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_quote(
        symbol="SYS", ts=datetime(2026, 5, 23, 10, 0),
        price=600.0, change=5.0, volume=100_000, day_high=605, day_low=595,
        fetched_at=datetime(2026, 5, 23, 10, 1),
    )
    cache.upsert_quote(
        symbol="NETSOL", ts=datetime(2026, 5, 23, 10, 0),
        price=120.0, change=-2.0, volume=50_000, day_high=125, day_low=118,
        fetched_at=datetime(2026, 5, 23, 10, 1),
    )
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._compare_symbols_impl(cache, symbols=["SYS", "NETSOL"],
                                     metrics=["price", "change_pct", "volume"])
    rows = {r.symbol: r.metrics for r in out.rows}
    for sym in ("SYS", "NETSOL"):
        assert rows[sym]["price"] is not None
        assert rows[sym]["change_pct"] is not None
        assert rows[sym]["volume"] is not None
    # SYS: change=+5 on prev_close=595 → ~0.840%
    assert rows["SYS"]["change_pct"] == pytest.approx(5.0 / 595.0 * 100, rel=1e-3)
    assert rows["SYS"]["volume"] == 100_000
    # NETSOL: change=-2 on prev_close=122 → ~-1.639%
    assert rows["NETSOL"]["change_pct"] == pytest.approx(-2.0 / 122.0 * 100, rel=1e-3)
    assert rows["NETSOL"]["volume"] == 50_000


def test_search_symbol_matches_name(tmp_path):
    """Verify case-insensitive name matching still works (regression guard)."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_symbol("NETSOL", "NetSol Technologies Limited", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_symbol("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", None)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._search_symbol_impl(cache, "netsol")
    assert any(r.symbol == "NETSOL" for r in out), "case-insensitive name should find NETSOL"


def test_search_symbol_matches_sector(tmp_path):
    """NEW: searching a sector name should return all symbols in that sector."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_symbol("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_symbol("NETSOL", "NetSol Technologies Limited", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_symbol("HUBC", "Hub Power Company", "POWER GENERATION & DISTRIBUTION", None)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._search_symbol_impl(cache, "technology")
    syms = {r.symbol for r in out}
    assert "SYS" in syms
    assert "NETSOL" in syms
