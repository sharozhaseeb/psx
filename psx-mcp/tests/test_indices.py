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
