"""PSX MCP server — FastMCP entrypoint with sync impl helpers + async tool wrappers."""
from __future__ import annotations
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from mcp.server.fastmcp import FastMCP

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.psx_client import (
    PSXClient, parse_market_watch, parse_historical, parse_announcements,
    parse_profile, parse_financials, parse_financial_statements,
)
from psx_mcp.symbols import search_symbols
from psx_mcp.indicators import rsi, sma, ema, macd, bollinger, volume_zscore
from psx_mcp.df_utils import bars_df
from psx_mcp.alerts import run_alerts
from psx_mcp.news import FEEDS, parse_rss, find_symbol_mentions
from psx_mcp.models import (
    Quote, Bar, SymbolMatch, MarketSummary, Mover, CompanyInfo, Fundamentals,
    FinancialStatement, Announcement, NewsItem, WatchEntry, AlertRule,
    AlertCondition, AlertHit, VolumeSpike, ComparisonTable, ComparisonRow,
    DEFAULT_DISCLAIMER,
)
from psx_mcp.logging_config import configure_logging, get_logger

mcp = FastMCP(
    "psx-mcp",
    instructions=(
        "PSX (Pakistan Stock Exchange) research tools. "
        "Data is 15+ minutes delayed. Informational only — not investment advice. "
        "Call refresh_market before quote-based alerts; refresh_history for indicator/volume rules."
    ),
)
log = get_logger("server")

_cache: Optional[Cache] = None
_store: Optional[WatchlistStore] = None
_client: Optional[PSXClient] = None


def set_dependencies(*, cache: Cache, store: WatchlistStore,
                     client: Optional[PSXClient]) -> None:
    global _cache, _store, _client
    _cache, _store, _client = cache, store, client


# ============================================================================
# Impl helpers — sync, fully testable, no MCP / no asyncio dependencies
# ============================================================================

def _search_symbol_impl(cache: Cache, query: str, limit: int = 10) -> list[SymbolMatch]:
    rows = search_symbols(cache, query, limit=limit)
    return [SymbolMatch(**r) for r in rows]


def _get_quote_impl(cache: Cache, symbol: str) -> Quote:
    sym = symbol.upper()
    row = cache.get_latest_quote(sym)
    if not row:
        return Quote(
            symbol=sym, price=0, change=0, change_pct=0, volume=0,
            day_high=0, day_low=0, week52_high=0, week52_low=0,
            timestamp=datetime.now(), stale=True,
            summary=f"No data cached for {sym}. Try refresh_market first.",
        )
    fetched_at = datetime.fromisoformat(row["fetched_at"])
    stale = (datetime.now() - fetched_at).total_seconds() > 300
    prev_close = row["price"] - row["change"]
    change_pct = (row["change"] / prev_close * 100) if prev_close > 0 else 0.0
    return Quote(
        symbol=sym, price=row["price"], change=row["change"],
        change_pct=change_pct,
        volume=row["volume"], day_high=row["day_high"] or 0,
        day_low=row["day_low"] or 0, week52_high=0, week52_low=0,
        timestamp=datetime.fromisoformat(row["ts"]), stale=stale,
        summary=f"{sym} at {row['price']} ({row['change']:+.2f})",
    )


def _get_history_impl(cache: Cache, symbol: str, from_date: str, to_date: str,
                      interval: str = "1d") -> list[Bar]:
    if interval != "1d":
        raise ValueError("Only '1d' interval supported on free PSX data")
    rows = cache.get_bars(symbol, date.fromisoformat(from_date), date.fromisoformat(to_date))
    return [Bar(symbol=symbol, date=r["date"], open=r["open"], high=r["high"],
                low=r["low"], close=r["close"], volume=r["volume"]) for r in rows]


def _compute_indicators_impl(cache: Cache, symbol: str, indicators: list[str],
                              lookback_days: int = 200) -> dict:
    df = bars_df(cache, symbol, lookback_days)
    if df.empty:
        return {"error": f"No bars cached for {symbol}", "disclaimer": DEFAULT_DISCLAIMER}
    out: dict = {}
    for name in indicators:
        try:
            if name == "rsi14":
                out[name] = float(rsi(df["close"], 14).iloc[-1])
            elif name == "macd":
                m = macd(df["close"]).iloc[-1]
                out[name] = {"macd": float(m["macd"]), "signal": float(m["signal"]), "hist": float(m["hist"])}
            elif name.startswith("sma"):
                out[name] = float(sma(df["close"], int(name[3:])).iloc[-1])
            elif name.startswith("ema"):
                out[name] = float(ema(df["close"], int(name[3:])).iloc[-1])
            elif name == "bollinger":
                b = bollinger(df["close"]).iloc[-1]
                out[name] = {"upper": float(b["upper"]), "middle": float(b["middle"]), "lower": float(b["lower"])}
            elif name == "volume_z":
                out[name] = float(volume_zscore(df["volume"], 20).iloc[-1])
            else:
                out[name] = {"error": f"unknown indicator: {name}"}
        except (ValueError, IndexError, KeyError) as e:
            out[name] = {"error": str(e)}
    out["disclaimer"] = DEFAULT_DISCLAIMER
    return out


# ============================================================================
# Async MCP tool wrappers
# ============================================================================

@mcp.tool()
async def search_symbol(query: str, limit: int = 10) -> list[SymbolMatch]:
    """Fuzzy-match a PSX ticker or company name."""
    return _search_symbol_impl(_cache, query, limit)


@mcp.tool()
async def get_quote(symbol: str) -> Quote:
    """Latest cached quote for a PSX symbol (15-min delayed)."""
    return _get_quote_impl(_cache, symbol)


@mcp.tool()
async def get_history(symbol: str, from_date: str, to_date: str, interval: str = "1d") -> list[Bar]:
    """Historical OHLCV. Free PSX data is daily only."""
    return _get_history_impl(_cache, symbol, from_date, to_date, interval)


@mcp.tool()
async def compute_indicators(symbol: str, indicators: list[str], lookback_days: int = 200) -> dict:
    """Compute one or more indicators from cached daily bars."""
    return _compute_indicators_impl(_cache, symbol, indicators, lookback_days)


async def _refresh_market_impl(cache: Cache, client: Optional[PSXClient]) -> int:
    if not client:
        return 0
    html = await client.fetch_market_watch()
    rows = parse_market_watch(html)
    now = datetime.now()
    for r in rows:
        cache.upsert_quote(
            symbol=r["symbol"], ts=now, price=r["price"] or 0,
            change=r["change"] or 0, volume=r["volume"] or 0,
            day_high=r["day_high"] or 0, day_low=r["day_low"] or 0,
            fetched_at=now,
        )
    log.info("market_refresh", count=len(rows))
    return len(rows)


def _get_market_summary_impl(cache: Cache) -> MarketSummary:
    kse100_row = cache.get_latest_quote("KSE100")
    return MarketSummary(
        kse100=(kse100_row or {}).get("price") or 0.0,
        kse100_change=(kse100_row or {}).get("change") or 0.0,
        sectors=[],
        timestamp=datetime.now(),
        stale=kse100_row is None,
        summary="KSE-100 snapshot — call refresh_market() first if stale.",
    )


def _get_top_movers_impl(cache: Cache, kind: str = "gainers", limit: int = 10) -> list[Mover]:
    rows = cache.conn.execute(
        """SELECT q.symbol, q.price, q.change, q.volume, s.name
           FROM quotes q LEFT JOIN symbols s ON s.symbol=q.symbol
           WHERE q.ts = (SELECT MAX(ts) FROM quotes q2 WHERE q2.symbol=q.symbol)
           AND q.price > 0"""
    ).fetchall()
    movers = []
    for r in rows:
        d = dict(r)
        prev_close = d["price"] - d["change"]
        change_pct = (d["change"] / prev_close * 100) if prev_close > 0 else 0.0
        movers.append(Mover(symbol=d["symbol"], name=d.get("name"),
                            price=d["price"], change_pct=change_pct, volume=d["volume"]))
    if kind == "gainers":
        movers.sort(key=lambda m: m.change_pct, reverse=True)
    elif kind == "losers":
        movers.sort(key=lambda m: m.change_pct)
    elif kind == "volume":
        movers.sort(key=lambda m: m.volume, reverse=True)
    else:
        raise ValueError(f"unknown kind: {kind}")
    return movers[:limit]


@mcp.tool()
async def refresh_market() -> int:
    """Force a refresh of the market-watch snapshot. Returns quotes upserted."""
    return await _refresh_market_impl(_cache, _client)


@mcp.tool()
async def get_market_summary() -> MarketSummary:
    """Index levels + sector aggregates. Best-effort from cached snapshot."""
    return _get_market_summary_impl(_cache)


@mcp.tool()
async def get_top_movers(kind: str = "gainers", limit: int = 10) -> list[Mover]:
    """kind: 'gainers' | 'losers' | 'volume'."""
    return _get_top_movers_impl(_cache, kind, limit)


if __name__ == "__main__":
    configure_logging()
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    set_dependencies(
        cache=Cache(str(data_dir / "psx.db")),
        store=WatchlistStore(str(data_dir / "watchlist.json")),
        client=PSXClient(),
    )
    log.info("psx-mcp server starting on http://127.0.0.1:8765/sse")
    mcp.run(transport="sse")
