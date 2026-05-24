from datetime import datetime
import pytest
from psx_mcp.cache import Cache


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


def _full_kwargs(**overrides):
    """Helper to fill in the long required-kwarg list with Nones."""
    base = dict(
        symbol="X", fiscal_year=2024, eps=None, pe=None, pb=None,
        div_yield=None, payout=None, roe=None, gross_margin=None,
        net_income=None, cfo=None, revenue=None,
        total_assets=None, long_term_debt=None, current_liab=None,
        current_assets=None, shares_outstanding=None,
        source_url=None, refreshed_at=datetime.now(),
    )
    base.update(overrides)
    return base


def test_upsert_and_get_fundamentals_history_round_trip(cache):
    """Multiple years per symbol, retrieved newest-first."""
    cache.upsert_fundamentals_history(**_full_kwargs(
        symbol="LUCK", fiscal_year=2024, eps=29.41, roe=15.2,
        net_income=14500.0, cfo=18000.0, revenue=80000.0,
        source_url="https://dps.psx.com.pk/company/LUCK",
        refreshed_at=datetime(2026, 5, 24, 10, 0),
    ))
    cache.upsert_fundamentals_history(**_full_kwargs(
        symbol="LUCK", fiscal_year=2025, eps=4.19, roe=2.1,
        net_income=2100.0, cfo=2500.0, revenue=76000.0,
        source_url="https://dps.psx.com.pk/company/LUCK",
        refreshed_at=datetime(2026, 5, 24, 10, 0),
    ))
    rows = cache.get_fundamentals_history("LUCK")
    assert [r["fiscal_year"] for r in rows] == [2025, 2024]
    assert rows[0]["eps"] == 4.19
    assert rows[1]["roe"] == 15.2
    assert rows[1]["net_income"] == 14500.0


def test_upsert_replaces_same_year(cache):
    """Re-upserting the same (symbol, fiscal_year) replaces values."""
    for eps in [10.0, 11.5]:
        cache.upsert_fundamentals_history(**_full_kwargs(
            symbol="SYS", fiscal_year=2024, eps=eps,
        ))
    rows = cache.get_fundamentals_history("SYS")
    assert len(rows) == 1
    assert rows[0]["eps"] == 11.5


def test_get_fundamentals_history_empty_returns_empty_list(cache):
    assert cache.get_fundamentals_history("NOSUCH") == []
