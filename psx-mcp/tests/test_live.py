import os
import pytest
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
