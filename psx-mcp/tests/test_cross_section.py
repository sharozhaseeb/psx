import pytest
from datetime import datetime
from psx_mcp.cache import Cache
from psx_mcp.cross_section import (
    z_score, percentile_rank, sector_dispersion,
    sector_relative_strength,
)


@pytest.fixture
def seeded(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    ts = datetime(2026, 5, 29, 10, 0)
    rows = [
        ("AAA", "TECH",     100.0, +1.0),
        ("BBB", "TECH",     200.0, +2.0),
        ("CCC", "TECH",     300.0, -1.0),
        ("DDD", "CEMENT",   400.0, -2.0),
        ("EEE", "CEMENT",   500.0, +0.5),
    ]
    for sym, sector, price, change in rows:
        cache.upsert_symbol(sym, sym, sector, None)
        cache.upsert_quote(symbol=sym, ts=ts, price=price, change=change,
                            volume=10_000, day_high=price+1, day_low=price-1,
                            fetched_at=ts)
        cache.upsert_fundamentals(symbol=sym, eps=10.0, pe=10.0 + (price / 100),
                                   pb=None, div_yield=None, payout=None, roe=None)
    return cache


def test_z_score_centers_to_zero():
    """Z-score of the median element of a sorted set is ~0."""
    values = [10.0, 11.0, 12.0, 13.0, 14.0]
    out = z_score(12.0, values)
    assert out is not None and abs(out) < 0.01


def test_z_score_outlier_is_high():
    out = z_score(100.0, [10.0, 11.0, 12.0, 13.0, 14.0])
    assert out > 10  # very far out


def test_z_score_empty_returns_none():
    assert z_score(10.0, []) is None


def test_z_score_zero_stdev_returns_none():
    assert z_score(10.0, [10.0, 10.0, 10.0]) is None


def test_percentile_rank_of_min_is_zero():
    """Min element is at the 0th percentile."""
    assert percentile_rank(10.0, [10.0, 20.0, 30.0]) == pytest.approx(0.0)


def test_percentile_rank_of_max_is_one_hundred():
    assert percentile_rank(30.0, [10.0, 20.0, 30.0]) == pytest.approx(100.0)


def test_percentile_rank_empty_returns_none():
    assert percentile_rank(10.0, []) is None


def test_percentile_rank_clamps_outside_range():
    """Value above max → 100; value below min → 0. Fixes M2."""
    assert percentile_rank(1000.0, [10.0, 20.0, 30.0]) == 100.0
    assert percentile_rank(-1000.0, [10.0, 20.0, 30.0]) == 0.0


def test_sector_dispersion_returns_stats(seeded):
    """Pulls PE values for sector TECH and reports dispersion."""
    out = sector_dispersion(seeded, "TECH", metric="pe")
    assert out["n"] == 3
    assert out["stdev"] is not None and out["stdev"] > 0
    assert out["range_pct"] is not None


def test_sector_dispersion_unknown_sector(seeded):
    out = sector_dispersion(seeded, "NOSUCH", metric="pe")
    assert out["n"] == 0
