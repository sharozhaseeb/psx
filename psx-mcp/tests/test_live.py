import os
import pytest
from psx_mcp.cache import Cache
from psx_mcp.psx_client import PSXClient, parse_market_watch

LIVE = os.environ.get("PSX_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="set PSX_LIVE=1 to run")


@pytest.mark.asyncio
async def test_market_watch_live():
    c = PSXClient()
    try:
        html = await c.fetch_market_watch()
        rows = parse_market_watch(html)
        assert len(rows) > 100
    finally:
        await c.close()


async def test_live_market_summary_returns_indices(tmp_path):
    """Smoke: after refreshing the market, get_market_summary returns real index values."""
    import server as srv

    cache = Cache(str(tmp_path / "live.db"))
    client = PSXClient()
    try:
        await srv._refresh_market_impl(cache, client)
        summary = srv._get_market_summary_impl(cache)

        assert summary.kse100 > 0, "KSE-100 should have a real value after refresh"
        assert summary.stale is False, "Should be fresh immediately after refresh"
    finally:
        await client.close()
        cache.close()


async def test_live_screen_tech_sector(tmp_path):
    """Smoke: after refresh, screening by TECHNOLOGY & COMMUNICATION sector
    runs end-to-end and any returned rows have the correct sector."""
    import server as srv

    cache = Cache(str(tmp_path / "live.db"))
    client = PSXClient()
    try:
        await srv._refresh_market_impl(cache, client)

        # Note: refresh_market only populates quotes + indices; symbols+sectors
        # come from a separate sync. Without bars/fundamentals, sector-only
        # filters may return 0 rows — that's a real finding, not a failure.
        # The smoke test asserts the call path is wired correctly and any
        # returned rows are sector-correct.
        out = srv._screen_symbols_impl(
            cache, sector="TECHNOLOGY & COMMUNICATION", limit=10,
        )
        assert isinstance(out.count, int)
        assert out.count == len(out.results)
        for r in out.results:
            assert r["sector"] == "TECHNOLOGY & COMMUNICATION"
    finally:
        await client.close()
        cache.close()
