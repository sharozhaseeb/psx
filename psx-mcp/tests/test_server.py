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


def test_compute_indicators_supports_new_names(tmp_path):
    """Dispatch must accept adx14, stochastic, obv, williams_r."""
    import server as srv
    from psx_mcp.models import Bar
    cache = Cache(str(tmp_path / "t.db"))
    today = date.today()
    # Seed 60 trending bars so ADX/Stochastic have enough history.
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=59 - i),
                open=100.0 + i * 0.5, high=105.0 + i * 0.5,
                low=95.0 + i * 0.5, close=100.0 + i * 0.5, volume=1000)
            for i in range(60)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._compute_indicators_impl(
        cache, "XYZ",
        indicators=["adx14", "stochastic", "obv", "williams_r"],
        lookback_days=200,
    )
    assert isinstance(out["adx14"], float)
    assert isinstance(out["stochastic"], dict)
    assert {"%K", "%D"} <= set(out["stochastic"].keys())
    assert isinstance(out["obv"], float)
    assert isinstance(out["williams_r"], float)


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


def test_announcement_url_propagates_through_cache(tmp_path):
    """The HTML feed has no body text — only a URL to a PDF disclosure.
    Verify the URL is persisted via the cache and surfaced by
    `_get_announcements_impl`, so users can read announcements via the link."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.models import Announcement

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="X1",
        symbol="SYS",
        posted_at=datetime(2026, 5, 22, 16, 18),
        title="Board meeting adjourned",
        category=None,
        url="https://dps.psx.com.pk/download/document/277743.pdf",
        body=None,
    ))
    srv.set_dependencies(
        cache=cache,
        store=WatchlistStore(str(tmp_path / "w.json")),
        client=None,
    )
    out = srv._get_announcements_impl(cache, "SYS", since_days=30)
    assert len(out) == 1
    assert out[0].url == "https://dps.psx.com.pk/download/document/277743.pdf"
    # Body intentionally None — not in source feed; documented behavior.
    assert out[0].body is None
    assert out[0].title == "Board meeting adjourned"


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


def test_screen_symbols_tool_returns_results(tmp_path):
    """Test the screen_symbols impl returns sector-matched results."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta

    cache = Cache(str(tmp_path / "c.db"))
    # Seed minimal universe with 250 bars per symbol for indicators
    universe = [
        ("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", 600.0, 5.0, 100_000, 12.0, 5.46),
        ("HUBC", "Hub Power", "POWER GENERATION & DISTRIBUTION", 130.0, 1.0, 200_000, 5.0, 26.0),
    ]
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    for sym, name, sector, price, change, volume, pe, eps in universe:
        cache.upsert_symbol(sym, name, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=volume, day_high=price+1, day_low=price-1,
                           fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=eps, pe=pe, pb=None,
                                  div_yield=None, payout=None, roe=None)
        bars = []
        for i in range(250):
            d = today - timedelta(days=250 - i)
            close = price * (0.8 + i / 250 * 0.4)
            bars.append(Bar(symbol=sym, date=d, open=close, high=close*1.01,
                            low=close*0.99, close=close, volume=volume))
        cache.upsert_bars(bars)

    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._screen_symbols_impl(
        cache, sector="TECHNOLOGY & COMMUNICATION",
        pe_max=20, rsi_min=0, rsi_max=100, limit=10,
    )
    assert out.disclaimer is not None
    assert isinstance(out.results, list)
    assert out.count == len(out.results)
    for r in out.results:
        assert r["sector"] == "TECHNOLOGY & COMMUNICATION"


def test_get_sector_summary_returns_response(tmp_path):
    """Server-level wrapper for sector_summary."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta

    cache = Cache(str(tmp_path / "c.db"))
    universe = [
        ("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", 600.0, 5.0, 100_000, 27.5, 5.46),
        ("NETSOL", "NetSol Technologies", "TECHNOLOGY & COMMUNICATION", 120.0, -2.0, 50_000, 12.0, 10.0),
    ]
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    for sym, name, sector, price, change, volume, pe, eps in universe:
        cache.upsert_symbol(sym, name, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=volume, day_high=price+1, day_low=price-1,
                           fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=eps, pe=pe, pb=None,
                                  div_yield=None, payout=None, roe=None)
        bars = []
        for i in range(250):
            d = today - timedelta(days=250 - i)
            close = price * (0.8 + i / 250 * 0.4)
            bars.append(Bar(symbol=sym, date=d, open=close, high=close*1.01,
                            low=close*0.99, close=close, volume=volume))
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    out = srv._get_sector_summary_impl(cache, "TECHNOLOGY & COMMUNICATION")
    assert out.sector == "TECHNOLOGY & COMMUNICATION"
    assert out.n == 2
    assert out.disclaimer  # non-empty


def test_get_fundamentals_history_returns_cached(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_fundamentals_history(
        symbol="LUCK", fiscal_year=2025, eps=4.19, pe=None, pb=None,
        div_yield=None, payout=None, roe=2.1, gross_margin=None,
        net_income=None, cfo=None, revenue=None,
        total_assets=None, long_term_debt=None, current_liab=None,
        current_assets=None, shares_outstanding=None,
        source_url=None, refreshed_at=datetime(2026, 5, 24),
    )
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_fundamentals_history_impl(cache, "LUCK")
    assert len(out) == 1
    assert out[0].eps == 4.19


def test_get_fundamentals_history_empty(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_fundamentals_history_impl(cache, "NOSUCH")
    assert out == []


def test_compute_beta_with_seeded_series(tmp_path):
    """Beta of a symbol whose returns equal index returns should be ~1."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    bars = []
    for i in range(100):
        d = today - timedelta(days=99 - i)
        close = 100.0 * (1 + i * 0.01)
        bars.append(Bar(symbol="XYZ", date=d, open=close, high=close*1.01,
                        low=close*0.99, close=close, volume=1000))
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                               close=close, volume=1e8)
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_beta_impl(cache, "XYZ")
    assert out.beta == pytest.approx(1.0, abs=0.01)
    assert out.r_squared == pytest.approx(1.0, abs=0.01)


def test_compute_beta_insufficient_overlap_returns_none_with_note(tmp_path):
    """If bar dates and index dates don't overlap, beta is None and note explains."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_bars([Bar(symbol="XYZ", date=date(2024, 1, 1) + timedelta(days=i),
                            open=100.0, high=101.0, low=99.0, close=100.0 + i, volume=1)
                       for i in range(50)])
    for i in range(50):
        cache.upsert_index_bar(index_code="KSE100",
                                bar_date=date(2026, 5, 1) + timedelta(days=i),
                                close=170000.0 + i, volume=1e8)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_beta_impl(cache, "XYZ")
    assert out.beta is None
    assert out.n == 0
    assert out.note and "overlap" in out.note.lower()


def test_compute_4quadrant_score_returns_total_0_to_4(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    cache.upsert_symbol("SYS", "Systems", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=ts, price=600.0, change=5.0, volume=100_000,
                       day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    cache.upsert_fundamentals_history(symbol="SYS", fiscal_year=2023, eps=8.0,
                                       pe=None, pb=None, div_yield=None, payout=None, roe=None,
                                       gross_margin=None, net_income=None, cfo=None, revenue=None,
                                       total_assets=None, long_term_debt=None, current_liab=None,
                                       current_assets=None, shares_outstanding=None,
                                       source_url=None, refreshed_at=ts)
    cache.upsert_fundamentals_history(symbol="SYS", fiscal_year=2024, eps=9.0,
                                       pe=None, pb=None, div_yield=None, payout=None, roe=None,
                                       gross_margin=None, net_income=None, cfo=None, revenue=None,
                                       total_assets=None, long_term_debt=None, current_liab=None,
                                       current_assets=None, shares_outstanding=None,
                                       source_url=None, refreshed_at=ts)
    cache.upsert_fundamentals_history(symbol="SYS", fiscal_year=2025, eps=10.0,
                                       pe=None, pb=None, div_yield=None, payout=None, roe=None,
                                       gross_margin=None, net_income=None, cfo=None, revenue=None,
                                       total_assets=None, long_term_debt=None, current_liab=None,
                                       current_assets=None, shares_outstanding=None,
                                       source_url=None, refreshed_at=ts)
    today = date(2026, 5, 23)
    bars = [Bar(symbol="SYS", date=today - timedelta(days=259 - i),
                open=100.0 + i, high=100.0 + i, low=100.0 + i,
                close=100.0 + i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_4quadrant_score_impl(cache, "SYS")
    assert 0 <= out.total <= 4
    assert out.value + out.quality + out.momentum + out.trend == out.total


def test_get_dividend_history_returns_cached(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_dividend(symbol="FFC", ex_date=date(2025, 9, 1),
                          announcement_date=date(2025, 8, 15),
                          payout_type="cash", per_share=8.0, bonus_pct=None,
                          announcement_id="FFC-2025-09")
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    events = srv._get_dividend_history_impl(cache, "FFC")
    assert len(events) == 1
    assert events[0].per_share == 8.0


def test_compute_drawdown_with_seeded_bars(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    closes = [100.0, 120.0, 80.0, 110.0]  # peak 120, max DD -33.33%, current down from peak
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=3 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_drawdown_impl(cache, "XYZ")
    assert out.peak == 120.0
    assert out.current == 110.0
    assert out.drawdown_pct == pytest.approx(-8.3333, abs=1e-3)
    assert out.max_drawdown_pct == pytest.approx(-33.3333, abs=1e-3)


def test_compute_risk_metrics_seeded(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    import numpy as np
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    rng = np.random.default_rng(42)
    pcts = rng.normal(loc=0.0008, scale=0.012, size=300)
    closes = list(np.exp(np.cumsum(pcts)) * 100.0)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=299 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_risk_metrics_impl(cache, "XYZ", rf_annual=0.0)
    assert out.n_bars == 300
    assert 0.10 < out.volatility_annualized < 0.30
    assert out.sharpe is not None
    assert out.max_drawdown_pct <= 0


def test_compute_return_stats_uptrend_cagr_positive(tmp_path):
    """260 strictly uptrending bars → positive CAGR + 100% win rate."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=259 - i),
                open=100.0+i, high=100.0+i, low=100.0+i,
                close=100.0+i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_return_stats_impl(cache, "XYZ", rolling_window_days=20)
    assert out.cagr_pct is not None and out.cagr_pct > 0
    assert out.win_rate_pct == pytest.approx(100.0)
    assert out.n_bars == 260
    assert out.rolling_returns_best_pct is not None


def test_compute_distribution_stats_seeded(tmp_path):
    """300 seeded random bars → var/cvar non-None and cvar <= var."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    import numpy as np
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    rng = np.random.default_rng(42)
    pcts = rng.normal(loc=0.0008, scale=0.012, size=300)
    closes = list(np.exp(np.cumsum(pcts)) * 100.0)
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=299 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(closes)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_distribution_stats_impl(cache, "XYZ")
    assert out.n_bars == 300
    assert out.var_5pct_pct is not None
    assert out.cvar_5pct_pct is not None
    # CVaR (tail mean) should be at least as negative as VaR (tail threshold)
    assert out.cvar_5pct_pct <= out.var_5pct_pct
    assert out.skewness is not None
    assert out.excess_kurtosis is not None
    assert out.tail_ratio_5pct is not None


def test_compute_drawdown_details_seven_bar_series(tmp_path):
    """7-bar series [100,120,80,100,110,120,130]:
    peak at idx 1 (120), trough at idx 2 (80, -33.33%), recovery at idx 5 (120).
    DD duration = 1 bar (2-1), recovery duration = 3 bars (5-2)."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    prices = [100.0, 120.0, 80.0, 100.0, 110.0, 120.0, 130.0]
    bars = [Bar(symbol="XYZ", date=today - timedelta(days=len(prices) - 1 - i),
                open=c, high=c, low=c, close=c, volume=1000)
            for i, c in enumerate(prices)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_drawdown_details_impl(cache, "XYZ")
    assert out.n_bars == 7
    assert out.max_drawdown_pct == pytest.approx(-33.333333, abs=1e-4)
    assert out.peak_index == 1
    assert out.trough_index == 2
    assert out.recovery_index == 5
    assert out.drawdown_duration_bars == 1
    assert out.recovery_duration_bars == 3
    assert out.ulcer_index is not None and out.ulcer_index > 0
    assert len(out.top_drawdowns) >= 1
    assert out.top_drawdowns[0]["peak_index"] == 1
    assert out.top_drawdowns[0]["trough_index"] == 2
    assert out.top_drawdowns[0]["recovery_index"] == 5
    assert out.note is None


def test_compute_drawdown_details_insufficient_bars(tmp_path):
    """< 2 bars → note set, default zeros returned."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    bars = [Bar(symbol="XYZ", date=date(2026, 5, 29),
                open=100, high=100, low=100, close=100, volume=1)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_drawdown_details_impl(cache, "XYZ")
    assert out.n_bars == 1
    assert out.max_drawdown_pct == 0.0
    assert out.note is not None and "Need" in out.note
    assert out.peak_index is None
    assert out.trough_index is None


def test_compute_relative_strength_uses_index_history(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    # Stock up 30% over 252 bars; index up 10%.
    for i in range(253):
        d = today - timedelta(days=252 - i)
        stock_c = 100.0 * (1.30 ** (i / 252))
        idx_c = 100.0 * (1.10 ** (i / 252))
        cache.upsert_bars([Bar(symbol="XYZ", date=d, open=stock_c, high=stock_c,
                                low=stock_c, close=stock_c, volume=1)])
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=idx_c, volume=1e8)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_relative_strength_impl(cache, "XYZ", window=252)
    assert out.relative_strength_pct is not None
    assert 0.18 < out.relative_strength_pct < 0.22
    assert out.n_bars == 253


def test_compute_correlation_matrix_seeded(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    # AAA and BBB have identical close trajectories → corr 1.0
    for sym in ("AAA", "BBB"):
        bars = [Bar(symbol=sym, date=today - timedelta(days=49 - i),
                    open=100.0+i, high=100.0+i, low=100.0+i,
                    close=100.0+i, volume=1000)
                for i in range(50)]
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_correlation_impl(cache, ["AAA", "BBB"])
    assert out.matrix["AAA"]["BBB"] == pytest.approx(1.0)
    assert out.matrix["BBB"]["AAA"] == pytest.approx(1.0)


def test_rank_sectors_tool_returns_sorted_rows(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    for sym, sector, price, change in [
        ("AAA", "TECH", 100.0, +5.0), ("BBB", "TECH", 50.0, +2.0),
        ("CCC", "CEMENT", 200.0, -3.0), ("DDD", "CEMENT", 100.0, -2.0),
    ]:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=10_000, day_high=price+1, day_low=price-1,
                           fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=10.0, pb=None,
                                  div_yield=None, payout=None, roe=None)
        bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                    open=price * (0.8 + i / 260 * 0.4),
                    high=price * (0.81 + i / 260 * 0.4),
                    low=price * (0.79 + i / 260 * 0.4),
                    close=price * (0.8 + i / 260 * 0.4),
                    volume=10_000) for i in range(260)]
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._rank_sectors_impl(cache, sectors=["TECH", "CEMENT"],
                                  by="avg_change_pct", desc=True)
    assert out.metric == "avg_change_pct"
    assert out.rows[0]["sector"] == "TECH"


def test_rank_universe_tool_returns_composite_rows(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    for sym, sector, price, change in [
        ("AAA", "TECH", 100.0, +5.0), ("BBB", "TECH", 50.0, +2.0),
        ("CCC", "CEMENT", 200.0, -3.0), ("DDD", "CEMENT", 100.0, -2.0),
    ]:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=10_000, day_high=price+1, day_low=price-1,
                           fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=5.0, pe=10.0, pb=None,
                                  div_yield=None, payout=None, roe=None)
        bars = [Bar(symbol=sym, date=today - timedelta(days=259 - i),
                    open=price * (0.8 + i / 260 * 0.4),
                    high=price * (0.81 + i / 260 * 0.4),
                    low=price * (0.79 + i / 260 * 0.4),
                    close=price * (0.8 + i / 260 * 0.4),
                    volume=10_000) for i in range(260)]
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._rank_universe_impl(cache, by="composite", sector=None, limit=10)
    assert out.metric == "composite"
    assert out.limit == 10
    assert len(out.rows) >= 1
    totals = [r["composite"] for r in out.rows]
    assert totals == sorted(totals, reverse=True)


def test_rank_universe_tool_empty_cache_has_note(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._rank_universe_impl(cache, by="composite", sector=None, limit=10)
    assert out.rows == []
    assert out.note is not None
    assert "cache is empty" in out.note


def test_compute_position_size_atr_based(tmp_path):
    """100k portfolio, 2% risk, 2x ATR stop, ATR computed from seeded bars."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 23)
    bars = []
    for i in range(30):
        d = today - timedelta(days=29 - i)
        close = 100.0 + i
        bars.append(Bar(symbol="XYZ", date=d, open=close,
                         high=close + 5, low=close - 5, close=close, volume=1000))
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_position_size_impl(cache, "XYZ",
                                           portfolio_value=100_000.0,
                                           risk_pct=2.0, stop_atr_mult=2.0)
    assert out.atr is not None
    assert 8 < out.atr < 12  # ATR ~10 for ±5 high-low spread
    assert out.qty is not None
    assert out.qty > 0
    expected_qty = int(2000.0 / (2 * out.atr))
    assert abs(out.qty - expected_qty) <= 1


def test_compute_position_size_insufficient_bars(tmp_path):
    """< 15 bars → ATR undefined → qty None + note."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_bars([Bar(symbol="XYZ", date=date(2026, 5, 23),
                            open=100.0, high=110.0, low=90.0, close=100.0, volume=1)])
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_position_size_impl(cache, "XYZ",
                                           portfolio_value=100_000.0,
                                           risk_pct=2.0, stop_atr_mult=2.0)
    assert out.qty is None
    assert out.note is not None


def test_get_cache_status_empty_cache(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_cache_status_impl(cache)
    assert out.tables["symbols"]["count"] == 0
    assert "empty" in (out.note or "").lower()


def test_refresh_universe_no_client_returns_note(tmp_path):
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = asyncio.run(srv._refresh_universe_impl(cache, None))
    assert out.requested == []
    assert out.succeeded == []
    assert out.failed == []
    assert out.note is not None
    assert "no psx client" in out.note.lower()


def test_get_upcoming_events_filters_by_title_keywords(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    now = datetime.now()
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=now - timedelta(days=2),
        title="Notice of Board Meeting on 30 May 2026",
        category=None, url=None, body=None,
    ))
    cache.upsert_announcement(Announcement(
        id="A2", symbol="SYS", posted_at=now - timedelta(days=2),
        title="Disclosure of Interest by Director",
        category=None, url=None, body=None,
    ))
    cache.upsert_announcement(Announcement(
        id="A3", symbol="LUCK", posted_at=now - timedelta(days=10),
        title="Board Meeting Other Than Financial Results",
        category=None, url=None, body=None,
    ))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_upcoming_events_impl(cache, lookback_days=7)
    titles = [e["title"] for e in out.events]
    assert any("Board Meeting on 30 May" in t for t in titles)
    assert all("Disclosure of Interest" not in t for t in titles)
    # A3 is older than 7 days → excluded
    assert all("Other Than Financial" not in t for t in titles)


def test_list_watchlist_with_scores_attaches_composite(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    store = WatchlistStore(str(tmp_path / "w.json"))
    store.add_watch("SYS", notes="tech leader")
    ts = datetime(2026, 5, 23, 10, 0)
    today = date(2026, 5, 23)
    cache.upsert_symbol("SYS", "Systems", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    bars = [Bar(symbol="SYS", date=today - timedelta(days=259 - i),
                open=100.0 + i, high=100.0 + i, low=100.0 + i,
                close=100.0 + i, volume=1000) for i in range(260)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=store, client=None)
    out = srv._list_watchlist_with_scores_impl(cache, store)
    assert len(out.entries) == 1
    e = out.entries[0]
    assert e["symbol"] == "SYS"
    assert "composite" in e
    assert e["notes"] == "tech leader"


def test_compute_4quadrant_score_warns_on_missing_data(tmp_path):
    """Empty cache -> score returns zeros AND lists what's missing."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_4quadrant_score_impl(cache, "NOSUCH")
    assert out.total == 0
    assert len(out.warnings) > 0
    joined = " ".join(out.warnings).lower()
    assert ("sector" in joined or "quote" in joined or "bars" in joined
            or "fundamentals" in joined)


def test_screen_symbols_reports_skipped_count(tmp_path):
    """Symbols missing bars when a technical filter is set should be reported."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 23, 10, 0)
    cache.upsert_symbol("SYS", "Sys", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=ts, price=600.0, change=5.0,
                       volume=100_000, day_high=605, day_low=595, fetched_at=ts)
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                              div_yield=None, payout=None, roe=20.0)
    # No bars -> screener with rsi_min should skip SYS
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._screen_symbols_impl(cache, rsi_min=40, rsi_max=70)
    assert out.count == 0
    assert out.warnings  # should mention skipped


def test_get_news_returns_cached_rows(tmp_path):
    """Regression test (Phase 6.4): news cache round-trip should not return []
    when rows exist. The symbols column is comma-separated TEXT (not JSON);
    `_get_news_impl(cache, symbol, since_days)` must round-trip it correctly
    for both unfiltered and symbol-filtered reads, and exclude rows whose
    symbols don't include the requested ticker."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    now = datetime.now()
    # Row 1: tagged with KSE100 + LUCK
    cache.conn.execute(
        """INSERT INTO news(id, source, posted_at, title, url, symbols)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("n1", "dawn_business", now.isoformat(),
         "PSX hits new high", "https://dawn.com/a", "KSE100,LUCK"),
    )
    # Row 2: no symbols
    cache.conn.execute(
        """INSERT INTO news(id, source, posted_at, title, url, symbols)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("n2", "profit_pakistan", (now - timedelta(days=1)).isoformat(),
         "General market commentary", "https://profit.pk/b", ""),
    )
    # Row 3: older than the since_days window
    cache.conn.execute(
        """INSERT INTO news(id, source, posted_at, title, url, symbols)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("n3", "dawn_business", (now - timedelta(days=30)).isoformat(),
         "Stale story", "https://dawn.com/c", "LUCK"),
    )
    cache.conn.commit()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)

    # symbol=None within window -> both recent rows, newest first
    out_all = srv._get_news_impl(cache, None, 7)
    assert len(out_all) == 2
    assert out_all[0].title == "PSX hits new high"
    assert out_all[0].symbols == ["KSE100", "LUCK"]
    assert out_all[1].symbols == []  # empty symbols column round-trips to []

    # symbol filter -> only rows whose symbols include the ticker
    out_luck = srv._get_news_impl(cache, "LUCK", 7)
    assert len(out_luck) == 1
    assert out_luck[0].id == "n1"

    # symbol filter is case-insensitive on the query side
    out_lower = srv._get_news_impl(cache, "luck", 7)
    assert len(out_lower) == 1
    assert out_lower[0].id == "n1"

    # since_days excludes the 30-day-old story even when filtered by symbol
    out_window = srv._get_news_impl(cache, "LUCK", 7)
    assert all(it.id != "n3" for it in out_window)

    # widening the window pulls the older LUCK story back in
    out_wide = srv._get_news_impl(cache, "LUCK", 60)
    assert {it.id for it in out_wide} == {"n1", "n3"}

    # filter miss -> empty list (not an error)
    out_miss = srv._get_news_impl(cache, "NOTAREALSYM", 7)
    assert out_miss == []


def test_compute_up_down_capture_aggressive_2x_stock(tmp_path):
    """Stock moves 2x the index on each aligned bar.
    Expect up_capture_pct ~= 200 and down_capture_pct ~= 200."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    # Index returns over 5 bars: [+1%, -2%, +3%, -1%, +2%] (after the initial bar).
    idx_rets = [0.01, -0.02, 0.03, -0.01, 0.02]
    idx_closes = [100.0]
    stock_closes = [50.0]
    for r in idx_rets:
        idx_closes.append(idx_closes[-1] * (1.0 + r))
        # Stock = 2x the index return on the same bar.
        stock_closes.append(stock_closes[-1] * (1.0 + 2.0 * r))
    dates = [today - timedelta(days=len(idx_closes) - 1 - i)
             for i in range(len(idx_closes))]
    for d, sc in zip(dates, stock_closes):
        cache.upsert_bars([Bar(symbol="XYZ", date=d, open=sc, high=sc,
                                low=sc, close=sc, volume=1)])
    for d, ic in zip(dates, idx_closes):
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=ic, volume=1e8)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_up_down_capture_impl(cache, "XYZ", "KSE100")
    assert out.symbol == "XYZ"
    assert out.index_code == "KSE100"
    assert out.n_aligned_bars == 6
    assert out.n_up_periods == 3
    assert out.n_down_periods == 2
    assert out.up_capture_pct is not None
    assert out.down_capture_pct is not None
    assert out.up_capture_pct == pytest.approx(200.0, rel=1e-2)
    assert out.down_capture_pct == pytest.approx(200.0, rel=1e-2)
    assert out.note is None


def test_compute_up_down_capture_insufficient_overlap(tmp_path):
    """< 3 aligned bars → note set, captures stay None."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    cache.upsert_bars([Bar(symbol="XYZ", date=today, open=100, high=100,
                            low=100, close=100, volume=1)])
    cache.upsert_index_bar(index_code="KSE100", bar_date=today,
                            close=10000.0, volume=1e8)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_up_down_capture_impl(cache, "XYZ", "KSE100")
    assert out.n_aligned_bars == 1
    assert out.up_capture_pct is None
    assert out.down_capture_pct is None
    assert out.note is not None and "Need at least 3" in out.note


# ============================================================================
# Phase 5.2 — cross-sectional MCP tools
# ============================================================================

def _seed_cross_section_cache(tmp_path):
    """Seed a cache with a TECH sector (3 syms) + CEMENT sector (2 syms) with
    distinct PE values for cross-sectional ranking."""
    from psx_mcp.cache import Cache
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 29, 10, 0)
    rows = [
        ("AAA", "TECH",     100.0, +1.0, 11.0),
        ("BBB", "TECH",     200.0, +2.0, 12.0),
        ("CCC", "TECH",     300.0, -1.0, 13.0),
        ("DDD", "CEMENT",   400.0, -2.0, 14.0),
        ("EEE", "CEMENT",   500.0, +0.5, 15.0),
    ]
    for sym, sector, price, change, pe in rows:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                            volume=10_000, day_high=price+1, day_low=price-1,
                            fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=pe,
                                   pb=None, div_yield=None, payout=None, roe=None)
    return cache


def test_compute_cross_sectional_rank_pe_in_sector(tmp_path):
    """Median-PE symbol in TECH sector → z near zero, percentile near 50."""
    import server as srv
    from psx_mcp.watchlist import WatchlistStore
    cache = _seed_cross_section_cache(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_cross_sectional_rank_impl(
        cache, symbol="BBB", metric="pe", universe="sector",
    )
    assert out.symbol == "BBB"
    assert out.metric == "pe"
    assert out.universe == "sector"
    assert out.sector == "TECH"
    assert out.value == pytest.approx(12.0)
    assert out.n_in_universe == 3
    # BBB is the median of {11, 12, 13}
    assert out.z_score is not None and abs(out.z_score) < 0.01
    assert out.percentile_pct is not None and 40 <= out.percentile_pct <= 60


def test_compute_cross_sectional_rank_unknown_symbol(tmp_path):
    """Symbol not in cache → note set, value None."""
    import server as srv
    from psx_mcp.watchlist import WatchlistStore
    cache = _seed_cross_section_cache(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_cross_sectional_rank_impl(
        cache, symbol="ZZZ", metric="pe", universe="sector",
    )
    assert out.symbol == "ZZZ"
    assert out.value is None
    assert out.note is not None


def test_compute_cross_sectional_rank_market_universe(tmp_path):
    """universe='market' compares vs all symbols across sectors."""
    import server as srv
    from psx_mcp.watchlist import WatchlistStore
    cache = _seed_cross_section_cache(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._compute_cross_sectional_rank_impl(
        cache, symbol="CCC", metric="pe", universe="market",
    )
    assert out.universe == "market"
    assert out.n_in_universe == 5
    assert out.value == pytest.approx(13.0)


def test_sector_dispersion_tool(tmp_path):
    """TECH sector dispersion on PE returns stats."""
    import server as srv
    from psx_mcp.watchlist import WatchlistStore
    cache = _seed_cross_section_cache(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_sector_dispersion_impl(cache, "TECH", metric="pe")
    assert out.sector == "TECH"
    assert out.metric == "pe"
    assert out.n == 3
    assert out.stdev is not None and out.stdev > 0
    assert out.range_pct is not None
    assert out.mean == pytest.approx(12.0)


def test_sector_dispersion_unknown_sector(tmp_path):
    """Sector with no members → n=0, note set."""
    import server as srv
    from psx_mcp.watchlist import WatchlistStore
    cache = _seed_cross_section_cache(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_sector_dispersion_impl(cache, "NOSUCH", metric="pe")
    assert out.n == 0
    assert out.note is not None


def test_rank_sector_relative_strength_returns_rows(tmp_path):
    """KSE100 down over window; TECH closes up → TECH RS positive."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Bar
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date(2026, 5, 29)
    window = 60
    # Seed index with declining closes (down 10% over the window).
    for i in range(window + 5):
        d = today - timedelta(days=(window + 4) - i)
        # i=0: oldest; i=last: newest
        close = 10000.0 * (1.0 - i * (0.10 / (window + 4)))
        cache.upsert_index_bar(index_code="KSE100", bar_date=d,
                                close=close, volume=1e8)
    # Seed TECH symbols with rising bars; CEMENT with flat bars.
    for sym, sector, slope in [
        ("AAA", "TECH",    +0.20),
        ("BBB", "TECH",    +0.20),
        ("CCC", "CEMENT",  +0.00),
        ("DDD", "CEMENT",  +0.00),
    ]:
        cache.upsert_symbol(sym, sym, sector, None)
        ts = datetime(2026, 5, 29, 10, 0)
        cache.upsert_quote(symbol=sym, ts=ts,
                            price=100.0, change=0.0, volume=10_000,
                            day_high=101, day_low=99,
                            fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=10.0,
                                   pb=None, div_yield=None, payout=None, roe=None)
        bars = []
        for i in range(window + 5):
            d = today - timedelta(days=(window + 4) - i)
            close = 100.0 * (1.0 + i * (slope / (window + 4)))
            bars.append(Bar(symbol=sym, date=d, open=close, high=close + 1,
                             low=close - 1, close=close, volume=1000))
        cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._rank_sector_relative_strength_impl(
        cache, sectors=["TECH", "CEMENT"], window_days=window,
    )
    assert out.window_days == window
    assert len(out.rows) == 2
    # TECH up vs index down → positive RS; CEMENT flat vs index down → also positive
    # but smaller than TECH. Result is sorted desc by RS.
    assert out.rows[0]["sector"] == "TECH"
    assert out.rows[0]["rs_pct"] > out.rows[1]["rs_pct"]


def test_rank_sector_relative_strength_uses_defaults(tmp_path):
    """sectors=None → falls back to DEFAULT_SECTORS, returns rows for each."""
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._rank_sector_relative_strength_impl(cache, sectors=None,
                                                    window_days=60)
    # Empty index history → each row has a note flagging insufficient history.
    assert len(out.rows) == len(srv.DEFAULT_SECTORS)


def test_fetch_announcement_body_caches_pdf_bytes(tmp_path, monkeypatch):
    """Mock the PDF fetcher; verify body is cached + fetch_status='ok'."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient
    from datetime import datetime

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime.now(),
        title="Board Meeting", category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf", body=None,
    ))

    async def fake_fetch(self, url, timeout=30.0):
        return b"%PDF-fake-bytes"
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)
    monkeypatch.setattr("server.extract_text_or_empty",
                         lambda b: "Board meeting on 15-June-2026 to consider results.")

    client = PSXClient()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=client)

    out = asyncio.run(srv._fetch_announcement_body_impl(cache, client, "A1"))
    assert out.fetch_status == "ok"
    assert "Board meeting" in out.body
    assert out.body_chars > 10

    row = cache.conn.execute(
        "SELECT body, fetch_status FROM announcements WHERE id='A1'"
    ).fetchone()
    assert row["fetch_status"] == "ok"
    assert "Board meeting" in row["body"]


def test_fetch_announcement_body_no_url_returns_no_url_status(tmp_path):
    """Announcement with no URL → fetch_status='no_url', no fetch attempted."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from datetime import datetime
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A2", symbol="SYS", posted_at=datetime.now(),
        title="No URL", category=None, url=None, body=None,
    ))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = asyncio.run(srv._fetch_announcement_body_impl(cache, None, "A2"))
    assert out.fetch_status == "no_url"
    assert out.body is None


def test_fetch_announcement_body_populates_insider_trade_table(tmp_path, monkeypatch):
    """When body parses as a director disclosure, insider_trades is populated."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient
    from datetime import datetime

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime(2026, 4, 16),
        title="Disclosure of Interest by a Director CEO, or Executive",
        category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf", body=None,
    ))

    async def fake_fetch(self, url, timeout=30.0):
        return b"%PDF-fake"
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)
    monkeypatch.setattr(
        "server.extract_text_or_empty",
        lambda b: ("Disclosure of Interest by a Director CEO, or Executive "
                   "Mr. Asif Peer Director purchased 10,000 shares on 15-April-2026."),
    )

    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=PSXClient())

    asyncio.run(srv._fetch_announcement_body_impl(cache, PSXClient(), "A1"))

    trades = cache.get_insider_trades("SYS")
    assert len(trades) == 1
    t = trades[0]
    assert t["action"] == "buy"
    assert t["qty"] == 10000


def test_fetch_announcement_body_populates_board_meeting_table(tmp_path, monkeypatch):
    """When body parses as a board-meeting notice with a date, board_meetings is populated."""
    import asyncio
    from datetime import date, datetime
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.models import Announcement
    from psx_mcp.watchlist import WatchlistStore
    from psx_mcp.psx_client import PSXClient

    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_announcement(Announcement(
        id="B1", symbol="SYS", posted_at=datetime(2026, 5, 28),
        title="Notice of Board Meeting",
        category=None,
        url="https://dps.psx.com.pk/download/document/2.pdf", body=None,
    ))

    async def fake_fetch(self, url, timeout=30.0):
        return b"%PDF-fake"
    monkeypatch.setattr(PSXClient, "fetch_url_bytes", fake_fetch)
    monkeypatch.setattr(
        "server.extract_text_or_empty",
        lambda b: ("Notice of Board Meeting. The Board will meet on "
                   "30-June-2026 to consider the quarterly financial results."),
    )

    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=PSXClient())

    asyncio.run(srv._fetch_announcement_body_impl(cache, PSXClient(), "B1"))

    rows = cache.get_board_meetings("SYS", since=date(2026, 6, 1), until=date(2026, 7, 1))
    assert len(rows) == 1
    assert rows[0]["agenda"] == "financial_results"


def test_get_insider_trades_summary_and_net_qty(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_insider_trade(
        announcement_id="A1", symbol="SYS",
        insider_name="X", insider_role="Director",
        action="buy", qty=10_000, pct_holding=None,
        trade_date=date(2026, 4, 15), posted_at=date(2026, 4, 16),
    )
    cache.upsert_insider_trade(
        announcement_id="A2", symbol="SYS",
        insider_name="Y", insider_role="Executive",
        action="sell", qty=3_000, pct_holding=None,
        trade_date=date(2026, 5, 1), posted_at=date(2026, 5, 2),
    )
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_insider_trades_impl(cache, "SYS", since_days=365)
    assert len(out.trades) == 2
    assert out.net_qty == 10_000 - 3_000


def test_get_earnings_calendar_returns_window_and_next_meeting(tmp_path):
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.watchlist import WatchlistStore
    from datetime import date, datetime, timedelta
    cache = Cache(str(tmp_path / "c.db"))
    today = date.today()
    cache.upsert_board_meeting(
        announcement_id="B1", symbol="SYS",
        meeting_date=today - timedelta(days=10),
        agenda="financial_results",
        posted_at=datetime.now() - timedelta(days=15),
    )
    cache.upsert_board_meeting(
        announcement_id="B2", symbol="SYS",
        meeting_date=today + timedelta(days=5),
        agenda="financial_results",
        posted_at=datetime.now(),
    )
    cache.upsert_board_meeting(
        announcement_id="B3", symbol="SYS",
        meeting_date=today + timedelta(days=120),
        agenda="other",
        posted_at=datetime.now(),
    )
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_earnings_calendar_impl(cache, "SYS",
                                           lookback_days=30, forward_days=60)
    assert len(out.meetings) == 2
    assert out.next_meeting is not None
    assert out.next_meeting.announcement_id == "B2"
