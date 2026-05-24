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
from psx_mcp.indicators import rsi, sma, ema, macd, bollinger, volume_zscore, atr
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
    host="127.0.0.1",
    port=8765,
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
    hi52, lo52 = cache.fifty_two_week(sym)
    if not row:
        return Quote(
            symbol=sym, price=0, change=0, change_pct=0, volume=0,
            day_high=0, day_low=0, week52_high=hi52, week52_low=lo52,
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
        day_low=row["day_low"] or 0, week52_high=hi52, week52_low=lo52,
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


DEFAULT_INDICATOR_BUNDLE = ["sma20", "sma50", "sma200", "rsi14", "atr14"]


def _compute_indicators_impl(cache: Cache, symbol: str, indicators: list[str] | None = None,
                              lookback_days: int = 200) -> dict:
    if not indicators:
        indicators = DEFAULT_INDICATOR_BUNDLE
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
            elif name.startswith("atr"):
                window = int(name[3:]) if len(name) > 3 else 14
                out[name] = float(atr(df["high"], df["low"], df["close"], window).iloc[-1])
            else:
                out[name] = {"error": f"unknown indicator: {name}"}
        except (ValueError, IndexError, KeyError, ZeroDivisionError) as e:
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
async def compute_indicators(symbol: str, indicators: list[str] | None = None,
                              lookback_days: int = 200) -> dict:
    """Compute one or more indicators from cached daily bars.

    If `indicators` is omitted, returns the default bundle:
    sma20, sma50, sma200, rsi14, atr14.
    """
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
    # Best-effort: also refresh the index snapshot. Don't fail the whole refresh
    # if the indices endpoint hiccups — individual indices already get skipped.
    try:
        indices = await client.fetch_indices()
        for idx in indices:
            cache.upsert_index(
                idx["code"], idx["value"], idx["change"],
                idx["change_pct"], idx["refreshed_at"],
            )
        log.info("indices_refresh", count=len(indices))
    except Exception as e:
        log.warning("indices_refresh_failed", error=str(e))
    log.info("market_refresh", count=len(rows))
    return len(rows)


def _get_market_summary_impl(cache: Cache) -> MarketSummary:
    snap = cache.index_snapshot()
    kse100 = snap.get("KSE100", {})
    kse30 = snap.get("KSE30", {})
    allshr = snap.get("ALLSHR", {})

    # Staleness: oldest refreshed_at across cached indices > 5 min ⇒ stale.
    # No indices cached at all ⇒ stale.
    if not snap:
        stale = True
    else:
        oldest = min(v["refreshed_at"] for v in snap.values())
        try:
            stale = (datetime.now() - datetime.fromisoformat(oldest)).total_seconds() > 300
        except (ValueError, TypeError):
            stale = True

    summary = (
        f"KSE-100 at {kse100.get('value'):.2f} ({kse100.get('change_pct'):+.2f}%)"
        if (not stale and kse100)
        else "KSE-100 snapshot — call refresh_market() first if stale."
    )

    return MarketSummary(
        kse100=kse100.get("value") or 0.0,
        kse100_change=kse100.get("change_pct") or 0.0,
        kse30=kse30.get("value"),
        kse30_change=kse30.get("change_pct"),
        allshr=allshr.get("value"),
        allshr_change=allshr.get("change_pct"),
        sectors=[],
        timestamp=datetime.now(),
        stale=stale,
        summary=summary,
    )


def _get_top_movers_impl(cache: Cache, kind: str = "gainers", limit: int = 10) -> list[Mover]:
    if kind not in {"gainers", "losers", "volume"}:
        raise ValueError(f"unknown kind: {kind}")
    movers = cache.top_movers(n=limit)
    key = "by_volume" if kind == "volume" else kind
    return [Mover(**m) for m in movers[key]]


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


async def _get_company_info_impl(cache: Cache, client: Optional[PSXClient], symbol: str) -> CompanyInfo:
    sym = symbol.upper()
    cached = cache.get_symbol(sym)
    age = cache.symbols_master_age_seconds()
    if cached and age is not None and age < 7 * 86400 and cached.get("name"):
        return CompanyInfo(
            symbol=sym, name=cached["name"], sector=cached.get("sector"),
            listed_shares=cached.get("listed_shares"),
        )
    if not client:
        return CompanyInfo(symbol=sym, name=(cached or {}).get("name") or sym)
    html = await client.fetch_profile(sym)
    info = parse_profile(sym, html)
    cache.upsert_symbol(sym, info.name, info.sector, info.listed_shares)
    return info


async def _get_fundamentals_impl(cache: Cache, client: Optional[PSXClient], symbol: str) -> Fundamentals:
    sym = symbol.upper()
    age = cache.fundamentals_age_seconds(sym)
    if age is not None and age < 86400:
        row = cache.get_fundamentals(sym)
        return Fundamentals(
            symbol=sym, eps=row["eps"], pe=row["pe"], pb=row["pb"],
            div_yield=row["div_yield"], payout=row["payout"], roe=row["roe"],
            refreshed_at=datetime.fromisoformat(row["refreshed_at"]),
        )
    if not client:
        row = cache.get_fundamentals(sym)
        if not row:
            return Fundamentals(symbol=sym)
        return Fundamentals(
            symbol=sym, eps=row["eps"], pe=row["pe"], pb=row["pb"],
            div_yield=row["div_yield"], payout=row["payout"], roe=row["roe"],
        )
    html = await client.fetch_financials(sym)
    f = parse_financials(sym, html)
    cache.upsert_fundamentals(symbol=sym, eps=f.eps, pe=f.pe, pb=f.pb,
                              div_yield=f.div_yield, payout=f.payout, roe=f.roe)
    return f


async def _get_financials_impl(cache: Cache, client: Optional[PSXClient],
                                symbol: str, period: str = "annual") -> list[FinancialStatement]:
    if period not in ("annual", "quarterly"):
        raise ValueError("period must be 'annual' or 'quarterly'")
    if not client:
        return []
    html = await client.fetch_financials(symbol)
    return parse_financial_statements(symbol, period, html)


async def _refresh_history_impl(cache: Cache, client: Optional[PSXClient], symbol: str) -> int:
    if not client:
        return 0
    payload = await client.fetch_historical(symbol)
    bars = parse_historical(symbol, payload)
    cache.upsert_bars(bars)
    return len(bars)


async def _refresh_announcements_impl(cache: Cache, client: Optional[PSXClient]) -> int:
    if not client:
        return 0
    payload = await client.fetch_announcements()
    items = parse_announcements(payload)
    for a in items:
        cache.upsert_announcement(a)
    log.info("announcements_refresh", count=len(items))
    return len(items)


def _get_announcements_impl(cache: Cache, symbol: Optional[str], since_days: int) -> list[Announcement]:
    since = datetime.now() - timedelta(days=since_days)
    rows = cache.get_announcements(symbol=symbol, since=since)
    return [Announcement(
        id=r["id"], symbol=r.get("symbol"), posted_at=r["posted_at"],
        title=r["title"], category=r.get("category"), url=r.get("url"), body=r.get("body"),
    ) for r in rows]


async def _refresh_news_impl(cache: Cache, client: Optional[PSXClient]) -> int:
    if not client:
        return 0
    universe = {s["symbol"] for s in cache.all_symbols()}
    total = 0
    for source, url in FEEDS.items():
        try:
            xml = await client._get(url)
        except Exception as e:
            log.warning("news_fetch_failed", source=source, error=str(e))
            continue
        items = parse_rss(source, xml)
        for it in items:
            mentions = find_symbol_mentions(it.title, "", universe)
            cache.upsert_news(id=it.id, source=it.source, posted_at=it.posted_at,
                              title=it.title, url=it.url, symbols=mentions)
            total += 1
    return total


def _get_news_impl(cache: Cache, symbol: Optional[str], since_days: int) -> list[NewsItem]:
    since = datetime.now() - timedelta(days=since_days)
    rows = cache.get_news(symbol=symbol, since=since)
    return [NewsItem(id=r["id"], source=r["source"], posted_at=r["posted_at"],
                     title=r["title"], url=r["url"], symbols=r["symbols"]) for r in rows]


@mcp.tool()
async def get_company_info(symbol: str) -> CompanyInfo:
    """Profile, sector, listed shares. Fetches & caches on first call."""
    return await _get_company_info_impl(_cache, _client, symbol)


@mcp.tool()
async def get_fundamentals(symbol: str) -> Fundamentals:
    """EPS, P/E, P/B, dividend yield. Cached for 1 day."""
    return await _get_fundamentals_impl(_cache, _client, symbol)


@mcp.tool()
async def get_financials(symbol: str, period: str = "annual") -> list[FinancialStatement]:
    """Best-effort annual/quarterly financial statements from PSX filings."""
    return await _get_financials_impl(_cache, _client, symbol, period)


@mcp.tool()
async def refresh_history(symbol: str) -> int:
    """Pull daily bars for a symbol from PSX and append to cache."""
    return await _refresh_history_impl(_cache, _client, symbol)


@mcp.tool()
async def refresh_announcements() -> int:
    """Pull recent corporate announcements and cache them."""
    return await _refresh_announcements_impl(_cache, _client)


@mcp.tool()
async def get_announcements(symbol: Optional[str] = None, since_days: int = 7) -> list[Announcement]:
    """Cached corporate announcements; symbol=None returns all."""
    return _get_announcements_impl(_cache, symbol, since_days)


@mcp.tool()
async def refresh_news() -> int:
    """Pull all configured RSS feeds, tag symbol mentions, cache items."""
    return await _refresh_news_impl(_cache, _client)


@mcp.tool()
async def get_news(symbol: Optional[str] = None, since_days: int = 3) -> list[NewsItem]:
    """Cached news items; filter by symbol mention if provided."""
    return _get_news_impl(_cache, symbol, since_days)


# ---- watchlist & alerts ----

def _list_watchlist_impl(store: WatchlistStore) -> list[WatchEntry]:
    return store.list_watch()


def _add_to_watchlist_impl(store: WatchlistStore, symbol: str,
                            notes: Optional[str] = None) -> WatchEntry:
    return store.add_watch(symbol, notes)


def _remove_from_watchlist_impl(store: WatchlistStore, symbol: str) -> bool:
    return store.remove_watch(symbol)


def _set_alert_rule_impl(store: WatchlistStore, *, symbol: str, type: str,
                          condition: dict) -> AlertRule:
    cond = AlertCondition(**condition)
    return store.set_alert_rule(symbol=symbol, type=type, condition=cond)


def _list_alert_rules_impl(store: WatchlistStore, symbol: Optional[str] = None) -> list[AlertRule]:
    return store.list_alert_rules(symbol)


def _remove_alert_rule_impl(store: WatchlistStore, rule_id: str) -> bool:
    return store.remove_alert_rule(rule_id)


def _check_alerts_impl(cache: Cache, store: WatchlistStore,
                        symbols: Optional[list[str]] = None) -> list[AlertHit]:
    return run_alerts(cache, store, symbols=symbols)


def _scan_volume_spikes_impl(cache: Cache, symbols: Optional[list[str]],
                              multiplier: float, lookback_days: int) -> list[VolumeSpike]:
    if not symbols:
        symbols = [s["symbol"] for s in cache.all_symbols()]
    out: list[VolumeSpike] = []
    for sym in symbols:
        df = bars_df(cache, sym, lookback_days)
        if len(df) < 5:
            continue
        today_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else 0.0
        mult = today_vol / avg_vol if avg_vol else 0.0
        if mult >= multiplier:
            out.append(VolumeSpike(symbol=sym, today_volume=int(today_vol),
                                    avg_volume=avg_vol, multiplier=mult))
    out.sort(key=lambda v: v.multiplier, reverse=True)
    return out


def _compare_symbols_impl(cache: Cache, symbols: list[str], metrics: list[str]) -> ComparisonTable:
    rows: list[ComparisonRow] = []
    for sym in symbols:
        m: dict = {}
        q = cache.get_latest_quote(sym)
        f = cache.get_fundamentals(sym)
        df = bars_df(cache, sym, lookback_days=400)
        for name in metrics:
            if name == "price":
                m[name] = q["price"] if q else None
            elif name == "volume":
                m[name] = q["volume"] if q else None
            elif name == "change_pct":
                if q:
                    prev_close = q["price"] - q["change"]
                    m[name] = (q["change"] / prev_close * 100) if prev_close > 0 else 0.0
                else:
                    m[name] = None
            elif name == "rsi14" and not df.empty and len(df) >= 14:
                m[name] = float(rsi(df["close"], 14).iloc[-1])
            elif name.startswith("sma") and not df.empty:
                window = int(name[3:])
                m[name] = float(sma(df["close"], window).iloc[-1]) if len(df) >= window else None
            elif name in ("pe", "eps", "pb", "div_yield", "payout", "roe"):
                m[name] = (f or {}).get(name)
            else:
                m[name] = None
        rows.append(ComparisonRow(symbol=sym, metrics=m))
    return ComparisonTable(metrics=metrics, rows=rows)


@mcp.tool()
async def list_watchlist() -> list[WatchEntry]:
    return _list_watchlist_impl(_store)


@mcp.tool()
async def add_to_watchlist(symbol: str, notes: Optional[str] = None) -> WatchEntry:
    return _add_to_watchlist_impl(_store, symbol, notes)


@mcp.tool()
async def remove_from_watchlist(symbol: str) -> bool:
    return _remove_from_watchlist_impl(_store, symbol)


@mcp.tool()
async def set_alert_rule(symbol: str, type: str, condition: dict) -> AlertRule:
    """Create or replace an alert rule.

    type: 'price' | 'indicator' | 'volume' | 'announcement'
    condition: {indicator?, op, value, lookback_days?}
    """
    return _set_alert_rule_impl(_store, symbol=symbol, type=type, condition=condition)


@mcp.tool()
async def list_alert_rules(symbol: Optional[str] = None) -> list[AlertRule]:
    return _list_alert_rules_impl(_store, symbol)


@mcp.tool()
async def remove_alert_rule(rule_id: str) -> bool:
    return _remove_alert_rule_impl(_store, rule_id)


@mcp.tool()
async def check_alerts(symbols: Optional[list[str]] = None) -> list[AlertHit]:
    """Evaluate all (or selected) alert rules against latest cached data."""
    return _check_alerts_impl(_cache, _store, symbols)


@mcp.tool()
async def scan_volume_spikes(symbols: Optional[list[str]] = None,
                              multiplier: float = 2.0,
                              lookback_days: int = 20) -> list[VolumeSpike]:
    """Find symbols whose latest volume is >= multiplier * recent average."""
    return _scan_volume_spikes_impl(_cache, symbols, multiplier, lookback_days)


@mcp.tool()
async def compare_symbols(symbols: list[str], metrics: list[str]) -> ComparisonTable:
    """Side-by-side metric table. metrics: price | rsi14 | sma50 | sma200 | pe | eps | div_yield | …"""
    return _compare_symbols_impl(_cache, symbols, metrics)


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
