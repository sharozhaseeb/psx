"""Tests for index snapshot fetching, caching, and market-summary surfacing."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from psx_mcp.cache import Cache
from psx_mcp.psx_client import PSXClient
from psx_mcp.watchlist import WatchlistStore


# ---------- fetch_indices payload parsing ----------

def test_fetch_indices_parses_payload(monkeypatch):
    """fetch_indices computes change_pct from rows[0] (latest) vs rows[1] (prev).
    Real PSX EOD payload is newest-first, so rows[0] = today."""
    import json as _json
    # rows[0] is the latest snapshot, rows[1] is the previous EOD.
    fake_payload = _json.dumps({
        "status": 1,
        "message": "",
        "data": [
            [1779447600, 170000.0, 110_000_000, 169000.0],  # latest
            [1779361200, 167000.0, 100_000_000, 167500.0],  # prev
        ],
    })

    async def fake_get(self, url):
        return fake_payload

    monkeypatch.setattr(PSXClient, "_get", fake_get)
    client = PSXClient()
    try:
        out = asyncio.run(client.fetch_indices(codes=["KSE100"]))
    finally:
        asyncio.run(client.close())

    assert len(out) == 1
    row = out[0]
    assert row["code"] == "KSE100"
    assert row["value"] == 170000.0
    assert row["volume"] == 110_000_000
    # change = 3000, change_pct ~= 3000/167000 * 100 = 1.7964...
    assert abs(row["change"] - 3000.0) < 1e-6
    assert abs(row["change_pct"] - (3000.0 / 167000.0 * 100)) < 1e-6
    assert row["refreshed_at"]


def test_fetch_indices_handles_single_row(monkeypatch):
    """With only one EOD row, change_pct degrades to 0 (no prev to diff against)."""
    import json as _json
    payload = _json.dumps({"status": 1, "data": [[1779447600, 170000.0, 110_000_000]]})

    async def fake_get(self, url):
        return payload

    monkeypatch.setattr(PSXClient, "_get", fake_get)
    client = PSXClient()
    try:
        out = asyncio.run(client.fetch_indices(codes=["KSE100"]))
    finally:
        asyncio.run(client.close())

    assert len(out) == 1
    assert out[0]["value"] == 170000.0
    assert out[0]["change"] == 0.0
    assert out[0]["change_pct"] == 0.0


def test_fetch_indices_skips_failing_index(monkeypatch):
    """If one index 500s, the others still come back."""
    import json as _json
    import httpx

    good = _json.dumps({"status": 1, "data": [
        [1779447600, 170000.0, 110_000_000, 169000.0],
        [1779361200, 167000.0, 100_000_000, 167500.0],
    ]})

    async def fake_get(self, url):
        if "KSE30" in url:
            raise httpx.HTTPError("boom")
        return good

    monkeypatch.setattr(PSXClient, "_get", fake_get)
    client = PSXClient()
    try:
        out = asyncio.run(client.fetch_indices(codes=["KSE100", "KSE30", "ALLSHR"]))
    finally:
        asyncio.run(client.close())

    codes = {r["code"] for r in out}
    assert codes == {"KSE100", "ALLSHR"}


def test_fetch_indices_refreshed_at_is_utc_iso(monkeypatch):
    """refreshed_at should be a UTC ISO string ending in '+00:00'."""
    import asyncio
    from psx_mcp.psx_client import PSXClient
    fake = {"data": [[1779360000, 167000.0, 100_000_000, 167000.0]]}
    async def fake_get(self, url):
        import json as _j
        return _j.dumps(fake)
    monkeypatch.setattr(PSXClient, "_get", fake_get)
    out = asyncio.run(PSXClient().fetch_indices(codes=["KSE100"]))
    assert len(out) == 1
    assert out[0]["refreshed_at"].endswith("+00:00")


def test_fetch_indices_skips_empty_data(monkeypatch):
    """Empty data array → index dropped, no exception."""
    import json as _json
    payload = _json.dumps({"status": 1, "data": []})

    async def fake_get(self, url):
        return payload

    monkeypatch.setattr(PSXClient, "_get", fake_get)
    client = PSXClient()
    try:
        out = asyncio.run(client.fetch_indices(codes=["KSE100"]))
    finally:
        asyncio.run(client.close())

    assert out == []


# ---------- cache upsert / read ----------

def test_cache_upsert_and_snapshot_roundtrip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    now_iso = datetime.now().isoformat()
    cache.upsert_index("KSE100", 170000.0, 1200.0, 0.71, now_iso)
    cache.upsert_index("KSE30", 50000.0, -100.0, -0.2, now_iso)
    snap = cache.index_snapshot()
    assert set(snap.keys()) == {"KSE100", "KSE30"}
    assert snap["KSE100"]["value"] == 170000.0
    assert snap["KSE100"]["change_pct"] == 0.71
    assert snap["KSE30"]["change"] == -100.0


def test_cache_upsert_replaces_existing(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_index("KSE100", 100.0, 1.0, 1.0, datetime.now().isoformat())
    cache.upsert_index("KSE100", 200.0, 2.0, 2.0, datetime.now().isoformat())
    snap = cache.index_snapshot()
    assert snap["KSE100"]["value"] == 200.0
    assert snap["KSE100"]["change_pct"] == 2.0


# ---------- market_summary impl reads from cache ----------

def test_get_market_summary_reads_cached_indices(tmp_path):
    import server as srv
    cache = Cache(str(tmp_path / "c.db"))
    now_iso = datetime.now().isoformat()
    cache.upsert_index("KSE100", 170000.0, 1200.0, 0.71, now_iso)
    cache.upsert_index("KSE30", 50000.0, -100.0, -0.2, now_iso)
    cache.upsert_index("ALLSHR", 110000.0, 50.0, 0.05, now_iso)
    srv.set_dependencies(
        cache=cache,
        store=WatchlistStore(str(tmp_path / "w.json")),
        client=None,
    )
    out = srv._get_market_summary_impl(cache)
    assert out.kse100 == 170000.0
    assert abs(out.kse100_change - 0.71) < 1e-6
    assert out.kse30 == 50000.0
    assert abs(out.kse30_change - (-0.2)) < 1e-6
    assert out.allshr == 110000.0
    assert out.stale is False
    assert "170000" in out.summary


def test_get_market_summary_stale_when_old(tmp_path):
    import server as srv
    cache = Cache(str(tmp_path / "c.db"))
    old_iso = (datetime.now() - timedelta(hours=2)).isoformat()
    cache.upsert_index("KSE100", 170000.0, 1200.0, 0.71, old_iso)
    srv.set_dependencies(
        cache=cache,
        store=WatchlistStore(str(tmp_path / "w.json")),
        client=None,
    )
    out = srv._get_market_summary_impl(cache)
    assert out.stale is True
    assert out.kse100 == 170000.0  # value still surfaced even if stale


def test_get_market_summary_empty_cache_is_stale(tmp_path):
    import server as srv
    cache = Cache(str(tmp_path / "c.db"))
    srv.set_dependencies(
        cache=cache,
        store=WatchlistStore(str(tmp_path / "w.json")),
        client=None,
    )
    out = srv._get_market_summary_impl(cache)
    assert out.stale is True
    assert out.kse100 == 0.0
    assert out.kse30 is None
    assert out.allshr is None


# ---------- indices_history (EOD bars per index) ----------

def test_index_history_eod_round_trip(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    cache.upsert_index_bar(index_code="KSE100", bar_date=date(2026, 5, 22),
                           close=170000.0, volume=110_000_000)
    cache.upsert_index_bar(index_code="KSE100", bar_date=date(2026, 5, 21),
                           close=168500.0, volume=100_000_000)
    rows = cache.get_index_history("KSE100")
    assert len(rows) == 2
    # Oldest first
    assert rows[0]["close"] == 168500.0
    assert rows[1]["close"] == 170000.0


def test_index_history_upsert_replaces_same_date(tmp_path):
    from psx_mcp.cache import Cache
    from datetime import date
    cache = Cache(str(tmp_path / "c.db"))
    for close in (170000.0, 170500.0):
        cache.upsert_index_bar(index_code="KSE100", bar_date=date(2026, 5, 22),
                               close=close, volume=110_000_000)
    rows = cache.get_index_history("KSE100")
    assert len(rows) == 1
    assert rows[0]["close"] == 170500.0


def test_fetch_index_eod_history_parses_full_payload(monkeypatch):
    """Full EOD timeseries -> list of dated bars, oldest first."""
    import asyncio
    from psx_mcp.psx_client import PSXClient
    fake = {"data": [
        [1779447600, 167844.24, 170376043, 169539.16],  # newer
        [1779361200, 168514.44, 165000000, 168000.00],
        [1779274800, 164831.42, 160000000, 164000.00],  # older
    ]}
    async def fake_get(self, url):
        import json as _j
        return _j.dumps(fake)
    monkeypatch.setattr(PSXClient, "_get", fake_get)
    bars = asyncio.run(PSXClient().fetch_index_eod_history("KSE100"))
    assert len(bars) == 3
    assert bars[0]["close"] == 164831.42  # oldest first after reversal
    assert bars[-1]["close"] == 167844.24
    assert bars[0]["bar_date"] < bars[-1]["bar_date"]


def test_get_index_history_after_refresh(tmp_path, monkeypatch):
    """End-to-end: fake fetch_index_eod_history, refresh_market, then get_index_history."""
    import asyncio
    import server as srv
    from psx_mcp.cache import Cache
    from psx_mcp.psx_client import PSXClient
    from psx_mcp.watchlist import WatchlistStore
    cache = Cache(str(tmp_path / "c.db"))

    async def fake_market(self):
        return "<table></table>"  # empty market-watch HTML; parse returns 0 rows
    async def fake_indices(self, codes=None):
        return []  # no snapshot - just exercise the history branch
    async def fake_eod(self, code):
        from datetime import date as _d
        return [
            {"bar_date": _d(2026, 5, 20), "close": 168000.0, "volume": 1e8},
            {"bar_date": _d(2026, 5, 21), "close": 168500.0, "volume": 1e8},
            {"bar_date": _d(2026, 5, 22), "close": 170000.0, "volume": 1.1e8},
        ]
    monkeypatch.setattr(PSXClient, "fetch_market_watch", fake_market)
    monkeypatch.setattr(PSXClient, "fetch_indices", fake_indices)
    monkeypatch.setattr(PSXClient, "fetch_index_eod_history", fake_eod)

    client = PSXClient()
    srv.set_dependencies(cache=cache, store=WatchlistStore(str(tmp_path / "w.json")),
                         client=client)
    asyncio.run(srv._refresh_market_impl(cache, client))
    rows = srv._get_index_history_impl(cache, "KSE100")
    assert len(rows) == 3
    assert rows[0].close == 168000.0
    assert rows[-1].close == 170000.0
