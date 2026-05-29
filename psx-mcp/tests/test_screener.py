import pytest
from datetime import datetime, date, timedelta
from psx_mcp.cache import Cache
from psx_mcp.models import Bar
from psx_mcp.screener import screen, FilterSpec, sector_summary


@pytest.fixture
def seeded_cache(tmp_path):
    """Cache with symbols, quotes, fundamentals, and ~250 bars per symbol."""
    cache = Cache(str(tmp_path / "c.db"))
    universe = [
        ("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", 600.0, 5.0, 100_000, 27.5, 5.46),
        ("NETSOL", "NetSol Technologies", "TECHNOLOGY & COMMUNICATION", 120.0, -2.0, 50_000, 12.0, 10.0),
        ("LUCK", "Lucky Cement", "CEMENT", 750.0, 10.0, 30_000, 8.5, 88.0),
        ("HUBC", "Hub Power", "POWER GENERATION & DISTRIBUTION", 130.0, 1.0, 200_000, 5.0, 26.0),
        ("CHEAP", "Cheap Co", "TECHNOLOGY & COMMUNICATION", 5.0, 0.05, 5_000_000, 6.0, 0.83),
    ]
    ts = datetime(2026, 5, 23, 10, 0)
    for sym, name, sector, price, change, volume, pe, eps in universe:
        cache.upsert_symbol(sym, name, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                           volume=volume, day_high=price + 1, day_low=price - 1,
                           fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=eps, pe=pe, pb=None,
                                  div_yield=None, payout=None, roe=None)
        # Seed ~250 daily bars with mild uptrend so indicators have data.
        # A small sine oscillation introduces both up and down bars so risk
        # metrics (Sortino, Calmar, max-DD) are computable.
        import math
        today = date(2026, 5, 23)
        bars = []
        for i in range(250):
            d = today - timedelta(days=250 - i)
            trend = 0.8 + i / 250 * 0.4  # 80%..120% drift
            osc = 0.02 * math.sin(i / 5.0)  # +/- 2% oscillation
            close = price * (trend + osc)
            bars.append(Bar(symbol=sym, date=d, open=close, high=close * 1.01,
                            low=close * 0.99, close=close, volume=volume))
        cache.upsert_bars(bars)
    return cache


def test_screen_filters_by_pe_max(seeded_cache):
    out = screen(seeded_cache, FilterSpec(pe_max=10))
    for r in out:
        assert r["pe"] is not None and r["pe"] <= 10


def test_screen_filters_by_sector(seeded_cache):
    out = screen(seeded_cache, FilterSpec(sector="TECHNOLOGY & COMMUNICATION"))
    for r in out:
        assert r["sector"] == "TECHNOLOGY & COMMUNICATION"


def test_screen_combines_filters_AND(seeded_cache):
    spec = FilterSpec(sector="TECHNOLOGY & COMMUNICATION", pe_max=15)
    out = screen(seeded_cache, spec)
    for r in out:
        assert r["sector"] == "TECHNOLOGY & COMMUNICATION"
        assert r["pe"] is not None and r["pe"] <= 15


def test_screen_min_turnover(seeded_cache):
    out = screen(seeded_cache, FilterSpec(min_turnover_pkr=50_000_000))
    for r in out:
        assert r["price"] * r["volume"] >= 50_000_000


def test_screen_sort_and_limit(seeded_cache):
    out = screen(seeded_cache, FilterSpec(sort_by="change_pct", desc=True, limit=3))
    assert len(out) <= 3
    pcts = [r["change_pct"] for r in out if r["change_pct"] is not None]
    assert pcts == sorted(pcts, reverse=True)


def test_screen_rsi_range(seeded_cache):
    out = screen(seeded_cache, FilterSpec(rsi_min=0, rsi_max=100))
    # All seeded symbols should pass since RSI between 0..100 always
    syms = {r["symbol"] for r in out}
    assert "SYS" in syms


def test_screen_above_sma200(seeded_cache):
    """Symbols where current price > sma200 of their seeded series."""
    out = screen(seeded_cache, FilterSpec(above_sma200=True))
    # The latest bar close (~1.198 * price) is above the average of 250 bars
    # (centered around ~1.0 * price), so all seeded symbols should pass.
    for r in out:
        assert r["sma200"] is not None and r["price"] > r["sma200"]


def test_screen_filters_by_roe_min(seeded_cache):
    """Seeded cache: upsert ROE values then assert screen filters correctly."""
    seeded_cache.upsert_fundamentals(symbol="SYS", eps=5.46, pe=27.5, pb=None,
                                      div_yield=None, payout=None, roe=18.0)
    seeded_cache.upsert_fundamentals(symbol="NETSOL", eps=10.0, pe=12.0, pb=None,
                                      div_yield=None, payout=None, roe=5.0)
    from psx_mcp.screener import screen, FilterSpec
    out = screen(seeded_cache, FilterSpec(roe_min=10.0))
    syms = {r["symbol"] for r in out}
    assert "SYS" in syms
    assert "NETSOL" not in syms


def test_screen_results_include_roe_and_pb(seeded_cache):
    """Regression: screen() must propagate ROE/P/B/div_yield/payout into result dicts."""
    seeded_cache.upsert_fundamentals(symbol="SYS", eps=5.46, pe=27.5, pb=4.0,
                                      div_yield=2.5, payout=40.0, roe=22.0)
    from psx_mcp.screener import screen, FilterSpec
    out = screen(seeded_cache, FilterSpec(sector="TECHNOLOGY & COMMUNICATION"))
    sys_row = next((r for r in out if r["symbol"] == "SYS"), None)
    assert sys_row is not None
    assert sys_row["roe"] == 22.0
    assert sys_row["pb"] == 4.0
    assert sys_row["div_yield"] == 2.5
    assert sys_row["payout"] == 40.0


def test_screen_filters_by_sortino_min(seeded_cache):
    """Symbols whose Sortino is below the threshold are excluded."""
    from psx_mcp.screener import screen, FilterSpec
    out = screen(seeded_cache, FilterSpec(sortino_min=-99.0))
    assert len(out) >= 1
    out_strict = screen(seeded_cache, FilterSpec(sortino_min=999.0))
    assert len(out_strict) == 0


def test_sector_summary_returns_breadth_and_leaders(seeded_cache):
    """Uses the existing seeded_cache fixture from test_screener.py."""
    out = sector_summary(seeded_cache, "TECHNOLOGY & COMMUNICATION")
    assert "n" in out and out["n"] >= 1
    assert "median_pe" in out
    assert "avg_change_pct" in out
    assert "pct_above_sma200" in out  # 0..100
    assert "top_5_by_change" in out and len(out["top_5_by_change"]) <= 5
    assert "bottom_5_by_change" in out and len(out["bottom_5_by_change"]) <= 5
