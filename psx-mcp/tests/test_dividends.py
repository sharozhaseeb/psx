import pytest
from datetime import date
from psx_mcp.cache import Cache


@pytest.fixture
def cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


def test_upsert_and_get_dividend_history(cache):
    cache.upsert_dividend(symbol="LUCK", ex_date=date(2025, 9, 15),
                          announcement_date=date(2025, 8, 30),
                          payout_type="cash", per_share=14.0, bonus_pct=None,
                          announcement_id="LUCK-2025-09")
    cache.upsert_dividend(symbol="LUCK", ex_date=date(2024, 9, 12),
                          announcement_date=date(2024, 8, 28),
                          payout_type="cash", per_share=10.0, bonus_pct=None,
                          announcement_id="LUCK-2024-09")
    rows = cache.get_dividend_history("LUCK")
    assert [r["per_share"] for r in rows] == [14.0, 10.0]  # newest first


def test_upsert_replaces_same_announcement_id(cache):
    for ps in (10.0, 12.0):
        cache.upsert_dividend(symbol="X", ex_date=date(2025, 1, 1),
                              announcement_date=date(2025, 1, 1),
                              payout_type="cash", per_share=ps, bonus_pct=None,
                              announcement_id="X-A1")
    rows = cache.get_dividend_history("X")
    assert len(rows) == 1
    assert rows[0]["per_share"] == 12.0
