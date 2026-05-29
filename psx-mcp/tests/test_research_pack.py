import pytest
from datetime import date, datetime, timedelta
import server as srv
from psx_mcp.cache import Cache
from psx_mcp.models import Announcement
from psx_mcp.watchlist import WatchlistStore


def _seed_minimal(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    today = date.today()
    cache.upsert_symbol("SYS", "Systems Limited", "TECHNOLOGY & COMMUNICATION", None)
    cache.upsert_quote(symbol="SYS", ts=datetime.now(),
                        price=600.0, change=5.0, volume=100_000,
                        day_high=605, day_low=595, fetched_at=datetime.now())
    cache.upsert_fundamentals(symbol="SYS", eps=10.0, pe=8.0, pb=None,
                                div_yield=None, payout=None, roe=20.0)
    cache.upsert_announcement(Announcement(
        id="A1", symbol="SYS", posted_at=datetime.now() - timedelta(days=5),
        title="Financial Results for the Quarter Ended 31 March 2026",
        category=None,
        url="https://dps.psx.com.pk/download/document/1.pdf",
        body="The company reported EPS of Rs 5.46 for the quarter ended 31 March 2026, "
             "vs Rs 4.91 in the comparable prior period. Revenue grew 12%.",
    ))
    cache.upsert_insider_trade(
        announcement_id="A2", symbol="SYS",
        insider_name="Mr. Asif Peer", insider_role="Director",
        action="buy", qty=15_000, pct_holding=None,
        trade_date=today - timedelta(days=10),
        posted_at=datetime.now() - timedelta(days=9),
    )
    cache.upsert_board_meeting(
        announcement_id="A3", symbol="SYS",
        meeting_date=today + timedelta(days=20),
        agenda="financial_results",
        posted_at=datetime.now(),
    )
    return cache


def test_research_pack_returns_all_sections(tmp_path):
    cache = _seed_minimal(tmp_path)
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_company_research_pack_impl(cache, "SYS", lookback_days=30)
    assert out.symbol == "SYS"
    assert out.quote is not None
    assert out.fundamentals is not None
    assert len(out.announcements) == 1
    assert "Financial Results" in out.announcements[0]["title"]
    assert len(out.insider_trades) == 1
    assert len(out.upcoming_meetings) == 1
    assert "SYS" in out.llm_briefing_text
    assert "Financial Results" in out.llm_briefing_text
    assert "Mr. Asif Peer" in out.llm_briefing_text


def test_research_pack_empty_cache_returns_warnings(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(cache=cache,
                         store=WatchlistStore(str(tmp_path / "w.json")),
                         client=None)
    out = srv._get_company_research_pack_impl(cache, "NOSUCH", lookback_days=30)
    assert out.symbol == "NOSUCH"
    assert len(out.warnings) > 0
    assert "NOSUCH" in out.llm_briefing_text
