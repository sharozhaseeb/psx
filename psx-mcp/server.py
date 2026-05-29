"""PSX MCP server — FastMCP entrypoint with sync impl helpers + async tool wrappers."""
from __future__ import annotations
import asyncio
import re as _re
import time
import time as _time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from mcp.server.fastmcp import FastMCP

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.psx_client import (
    PSXClient, parse_market_watch, parse_historical, parse_announcements,
    parse_profile, parse_financials, parse_financial_statements, parse_payouts,
)
from psx_mcp.symbols import search_symbols
from psx_mcp.indicators import (
    rsi, sma, ema, macd, bollinger, volume_zscore, atr,
    adx, stochastic, obv, williams_r,
)
from psx_mcp.df_utils import bars_df
from psx_mcp.alerts import run_alerts
from psx_mcp.news import FEEDS, parse_rss, find_symbol_mentions
from psx_mcp.models import (
    Quote, Bar, SymbolMatch, MarketSummary, Mover, CompanyInfo, Fundamentals,
    FundamentalsHistoryPoint, IndexHistoryPoint, FinancialStatement,
    Announcement, NewsItem, WatchEntry, AlertRule, AlertCondition, AlertHit,
    VolumeSpike, ComparisonTable, ComparisonRow, ScreenResponse,
    SectorSummaryResponse, BetaResponse, QualityScoreResponse,
    QuadrantScoreResponse, DividendEvent, DEFAULT_DISCLAIMER,
    DrawdownResponse, RiskMetricsResponse,
    RelativeStrengthResponse, CorrelationMatrixResponse,
    SectorRankResponse, UniverseRankResponse,
    FullAnalysisResponse, PositionSizeResponse,
    CacheStatusResponse, BulkRefreshResponse,
    UpcomingEventsResponse, WatchlistWithScoresResponse,
    BacktestResponse,
)
from psx_mcp.backtest import backtest_simple as _backtest_simple_pure
from psx_mcp.screener import screen, FilterSpec, sector_summary
from psx_mcp.ranking import (
    rank_sectors as _rank_sectors_pure,
    rank_universe as _rank_universe_pure,
)
from psx_mcp.beta import beta
from psx_mcp.risk import (
    drawdown_current, drawdown_max,
    volatility_annualized, sharpe,
    relative_strength, correlation_matrix,
)
from psx_mcp.risk_extended import (
    cagr, rolling_returns, win_rate,
    sortino, calmar, information_ratio, omega_ratio,
    var_historical, cvar_historical, skewness, kurtosis_excess, tail_ratio,
    drawdown_details, ulcer_index, up_down_capture,
)
from psx_mcp.models import (
    ReturnStatsResponse, DistributionStatsResponse,
    DrawdownDetailsResponse, UpDownCaptureResponse,
    ExtendedRiskMetricsResponse,
)
from psx_mcp.cross_section import (
    z_score, percentile_rank, sector_dispersion, sector_relative_strength,
)
from psx_mcp.pdf_extractor import (
    extract_text_or_empty, is_probably_scan_only,
)
from psx_mcp.models import (
    AnnouncementBodyResponse, BulkBodyFetchResponse,
)
from psx_mcp.models import (
    CrossSectionalRankResponse, SectorDispersionResponse,
    SectorRelativeStrengthResponse,
)
from psx_mcp.quality import (
    compute_quality_score as _compute_quality_score_pure,
    compute_4quadrant_score as _compute_4quadrant_score_pure,
)
from psx_mcp.events import (
    classify_announcement, parse_insider_trade, parse_board_meeting,
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
            elif name.startswith("adx"):
                window = int(name[3:]) if len(name) > 3 else 14
                out[name] = float(adx(df["high"], df["low"], df["close"], window).iloc[-1])
            elif name == "stochastic":
                s = stochastic(df["high"], df["low"], df["close"]).iloc[-1]
                out[name] = {"%K": float(s["%K"]), "%D": float(s["%D"])}
            elif name == "obv":
                out[name] = float(obv(df["close"], df["volume"]).iloc[-1])
            elif name.startswith("williams_r"):
                window = int(name[len("williams_r"):]) if len(name) > len("williams_r") else 14
                out[name] = float(williams_r(df["high"], df["low"], df["close"], window).iloc[-1])
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
        # Also populate per-index EOD history (one row per trading day).
        for code in ("KSE100", "KSE30", "ALLSHR"):
            try:
                bars = await client.fetch_index_eod_history(code)
                if bars:
                    cache.upsert_index_bars_bulk(code, bars)
            except Exception:
                continue  # one failed index doesn't kill the rest
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

    kse100_val = kse100.get('value') if kse100 else None
    kse100_chg = kse100.get('change_pct') if kse100 else None
    if not stale and kse100_val is not None:
        chg = kse100_chg if kse100_chg is not None else 0.0
        summary = f"KSE-100 at {kse100_val:.2f} ({chg:+.2f}%)"
    else:
        summary = "KSE-100 snapshot — call refresh_market() first if stale."

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


def _get_index_history_impl(cache: Cache, index_code: str,
                            since: Optional[str] = None) -> list[IndexHistoryPoint]:
    rows = cache.get_index_history(index_code, since=since)
    return [IndexHistoryPoint(**r) for r in rows]


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


@mcp.tool()
async def get_index_history(index_code: str = "KSE100",
                            since: Optional[str] = None) -> list[IndexHistoryPoint]:
    """Cached EOD index history (one row per trading day).
    `since` is a YYYY-MM-DD string; omit for full history.
    Populated from /timeseries/eod/<INDEX> on every refresh_market."""
    return _get_index_history_impl(_cache, index_code, since)


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


def _get_fundamentals_history_impl(cache: Cache, symbol: str) -> list[FundamentalsHistoryPoint]:
    rows = cache.get_fundamentals_history(symbol)
    return [FundamentalsHistoryPoint(**r) for r in rows]


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
async def get_fundamentals_history(symbol: str) -> list[FundamentalsHistoryPoint]:
    """Cached per-fiscal-year fundamentals for a symbol, newest year first.
    Populated by refresh_fundamentals(symbol) (deferred to Part 3 — requires
    sub-tab fetcher). Empty list if never refreshed."""
    return _get_fundamentals_history_impl(_cache, symbol)


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


def _list_watchlist_with_scores_impl(cache: Cache,
                                      store: WatchlistStore) -> WatchlistWithScoresResponse:
    entries = []
    for w in store.list_watch():
        try:
            qs = _compute_4quadrant_score_impl(cache, w.symbol)
            composite = qs.total
            quadrants = {k: getattr(qs, k) for k in ("value", "quality", "momentum", "trend")}
            warnings_for_entry = list(getattr(qs, "warnings", []) or [])
        except Exception as e:
            composite = None
            quadrants = {}
            warnings_for_entry = [f"score-failed: {e!r}"]
        quote = cache.get_latest_quote(w.symbol) or {}
        entries.append({
            "symbol": w.symbol,
            "notes": w.notes,
            "added_at": w.added_at.isoformat(),
            "price": quote.get("price"),
            "composite": composite,
            "quadrants": quadrants,
            "warnings": warnings_for_entry,
        })
    note = None
    if not entries:
        note = "Watchlist is empty. Use add_to_watchlist(symbol) first."
    return WatchlistWithScoresResponse(entries=entries, note=note)


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
async def list_watchlist_with_scores() -> WatchlistWithScoresResponse:
    """Like list_watchlist but each entry includes its current 4-quadrant
    composite score (0..4) and price. Heavy: computes scores per entry."""
    return _list_watchlist_with_scores_impl(_cache, _store)


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


def _screen_symbols_impl(cache, **kwargs) -> ScreenResponse:
    from psx_mcp.screener import screen_with_meta, FilterSpec
    spec_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    spec = FilterSpec(**spec_kwargs)
    rows, meta = screen_with_meta(cache, spec)
    warnings: list[str] = []
    if meta["skipped_no_bars"]:
        warnings.append(
            f"{meta['skipped_no_bars']} symbol(s) skipped due to insufficient bars "
            f"(needs >= 50 daily bars). Call refresh_history(symbol) for each."
        )
    return ScreenResponse(results=rows, count=len(rows), warnings=warnings)


@mcp.tool()
async def screen_symbols(
    sector: str | None = None,
    sectors: list[str] | None = None,
    pe_min: float | None = None,
    pe_max: float | None = None,
    eps_min: float | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    above_sma200: bool | None = None,
    sma20_gt_sma50: bool | None = None,
    min_volume: int | None = None,
    min_turnover_pkr: float | None = None,
    roe_min: float | None = None,
    pb_max: float | None = None,
    div_yield_min: float | None = None,
    sortino_min: float | None = None,
    calmar_min: float | None = None,
    max_dd_max_pct: float | None = None,
    sort_by: str = "symbol",
    desc: bool = False,
    limit: int = 50,
) -> ScreenResponse:
    """Multi-criteria screener. Returns symbols matching ALL filters.

    Common workflows:
    - Value: pe_max=10, eps_min=5, sort_by="pe"
    - Tech leaders: sector="TECHNOLOGY & COMMUNICATION", above_sma200=True
    - Liquid movers: min_turnover_pkr=50_000_000, sort_by="change_pct", desc=True
    - Risk-adjusted: sortino_min=1.0, max_dd_max_pct=-30 (no worse than -30% DD)
    """
    return _screen_symbols_impl(
        _cache,
        sector=sector, sectors=sectors,
        pe_min=pe_min, pe_max=pe_max, eps_min=eps_min,
        price_min=price_min, price_max=price_max,
        rsi_min=rsi_min, rsi_max=rsi_max,
        above_sma200=above_sma200, sma20_gt_sma50=sma20_gt_sma50,
        min_volume=min_volume, min_turnover_pkr=min_turnover_pkr,
        roe_min=roe_min, pb_max=pb_max, div_yield_min=div_yield_min,
        sortino_min=sortino_min, calmar_min=calmar_min,
        max_dd_max_pct=max_dd_max_pct,
        sort_by=sort_by, desc=desc, limit=limit,
    )


def _get_sector_summary_impl(cache, sector: str) -> SectorSummaryResponse:
    data = sector_summary(cache, sector)
    return SectorSummaryResponse(**data)


@mcp.tool()
async def get_sector_summary(sector: str) -> SectorSummaryResponse:
    """Sector-level breadth, median PE, top/bottom 5 by change_pct.

    Useful for: market-rotation check, finding under-performing sectors,
    quick triage before drilling into individual names.
    """
    return _get_sector_summary_impl(_cache, sector)


DEFAULT_SECTORS = [
    "TECHNOLOGY & COMMUNICATION", "CEMENT",
    "OIL & GAS EXPLORATION COMPANIES", "OIL & GAS MARKETING COMPANIES",
    "COMMERCIAL BANKS", "FERTILIZER",
    "POWER GENERATION & DISTRIBUTION",
    "AUTOMOBILE ASSEMBLER", "FOOD & PERSONAL CARE PRODUCTS",
    "PHARMACEUTICALS", "TEXTILE COMPOSITE",
    "CHEMICAL", "REFINERY",
]


def _rank_sectors_impl(cache: Cache, sectors: list[str] | None,
                       by: str = "avg_change_pct",
                       desc: bool = True) -> SectorRankResponse:
    sectors = sectors or DEFAULT_SECTORS
    rows = _rank_sectors_pure(cache, sectors, by=by, desc=desc)
    return SectorRankResponse(metric=by, desc=desc, rows=rows, note=None)


@mcp.tool()
async def rank_sectors(sectors: list[str] | None = None,
                       by: str = "avg_change_pct",
                       desc: bool = True) -> SectorRankResponse:
    """Rank PSX sectors by an aggregate metric. Default: 13 major sectors.
    Valid `by`: 'avg_change_pct' (today's mood), 'median_pe' (relative valuation),
    'pct_above_sma200' (breadth/trend strength), 'n' (member count)."""
    return _rank_sectors_impl(_cache, sectors, by, desc)


def _rank_universe_impl(cache: Cache, by: str = "composite",
                        sector: Optional[str] = None,
                        limit: int = 20) -> UniverseRankResponse:
    rows = _rank_universe_pure(cache, by=by, sector=sector, limit=limit)
    note = None
    if not rows:
        note = ("No symbols ranked. Possible causes: cache is empty (call "
                "refresh_market then refresh_history), or the selected sector "
                "has no scored members.")
    return UniverseRankResponse(metric=by, sector=sector, limit=limit,
                                 rows=rows, note=note)


@mcp.tool()
async def rank_universe(by: str = "composite",
                        sector: str | None = None,
                        limit: int = 20) -> UniverseRankResponse:
    """Rank cached PSX symbols by a metric. Default: 4-quadrant composite score.
    Valid metrics: 'composite' (Value+Quality+Momentum+Trend, max 4),
    'change_pct' (today's movers), 'rsi14' (technical overbought/oversold),
    'pe' (cheapest first). Limits to top-200 candidates by quote freshness;
    call refresh_history(symbol) for each candidate before this for full coverage."""
    return _rank_universe_impl(_cache, by, sector, limit)


# ============================================================================
# Phase 5.2 — Cross-sectional / sector dispersion / sector relative strength
# ============================================================================

def _compute_cross_sectional_rank_impl(
    cache: Cache, symbol: str, metric: str = "pe",
    universe: str = "sector",
) -> CrossSectionalRankResponse:
    """Rank a symbol's metric within its sector (or the market) using z-score
    and percentile. universe: 'sector' | 'market'."""
    sym_u = symbol.strip().upper()
    sym_row = cache.get_symbol(sym_u)
    if not sym_row:
        return CrossSectionalRankResponse(
            symbol=sym_u, metric=metric, universe=universe, sector=None,
            value=None, z_score=None, percentile_pct=None, n_in_universe=0,
            note=f"Symbol {sym_u!r} not found in cache. "
                 f"Call refresh_market first.",
        )
    sector = sym_row.get("sector")
    if universe == "sector":
        if not sector:
            return CrossSectionalRankResponse(
                symbol=sym_u, metric=metric, universe=universe, sector=None,
                value=None, z_score=None, percentile_pct=None, n_in_universe=0,
                note=f"Symbol {sym_u!r} has no sector recorded.",
            )
        rows = screen(cache, FilterSpec(sector=sector, limit=500))
    elif universe == "market":
        rows = screen(cache, FilterSpec(limit=2000))
    else:
        return CrossSectionalRankResponse(
            symbol=sym_u, metric=metric, universe=universe, sector=sector,
            value=None, z_score=None, percentile_pct=None, n_in_universe=0,
            note=f"Unknown universe {universe!r}; expected 'sector' or 'market'.",
        )
    values = [r.get(metric) for r in rows if r.get(metric) is not None]
    target_row = next((r for r in rows if r["symbol"] == sym_u), None)
    value = target_row.get(metric) if target_row else None
    if value is None:
        return CrossSectionalRankResponse(
            symbol=sym_u, metric=metric, universe=universe, sector=sector,
            value=None, z_score=None, percentile_pct=None,
            n_in_universe=len(values),
            note=(f"Metric {metric!r} not available for {sym_u!r}. "
                  f"Valid metrics: pe, eps, change_pct, pb, roe, div_yield, "
                  f"rsi14, price, volume."),
        )
    z = z_score(value, values)
    pct = percentile_rank(value, values)
    return CrossSectionalRankResponse(
        symbol=sym_u, metric=metric, universe=universe, sector=sector,
        value=float(value), z_score=z, percentile_pct=pct,
        n_in_universe=len(values), note=None,
    )


@mcp.tool()
async def compute_cross_sectional_rank(
    symbol: str, metric: str = "pe", universe: str = "sector",
) -> CrossSectionalRankResponse:
    """Z-score + percentile of `symbol`'s `metric` vs its `universe`.
    universe in {'sector','market'}. Use to spot relative cheap/expensive,
    over/underperformance vs peers. Valid metrics include
    pe, eps, change_pct, pb, roe, div_yield, rsi14, price, volume.
    Call refresh_market + refresh_history first for accurate ranks."""
    return _compute_cross_sectional_rank_impl(_cache, symbol, metric, universe)


def _get_sector_dispersion_impl(
    cache: Cache, sector: str, metric: str = "pe",
) -> SectorDispersionResponse:
    """Cross-member dispersion of `metric` within `sector`."""
    data = sector_dispersion(cache, sector, metric=metric)
    note = None
    if data.get("n", 0) == 0:
        note = (f"No members found for sector {sector!r} with metric {metric!r}. "
                f"Check sector name and call refresh_market.")
    return SectorDispersionResponse(
        sector=data["sector"], metric=data["metric"], n=data["n"],
        mean=data["mean"], median=data["median"], stdev=data["stdev"],
        min=data["min"], max=data["max"], range_pct=data["range_pct"],
        top_z_scores=data["top_z_scores"], note=note,
    )


@mcp.tool()
async def get_sector_dispersion(
    sector: str, metric: str = "pe",
) -> SectorDispersionResponse:
    """Dispersion stats for `metric` across members of `sector`.
    metric in {pe, eps, change_pct, pb, roe, div_yield, rsi14, price, volume}.
    High dispersion = stock-picking opportunity; low dispersion = passive
    likely better. Also returns the 5 highest |z-score| members."""
    return _get_sector_dispersion_impl(_cache, sector, metric)


def _rank_sector_relative_strength_impl(
    cache: Cache, sectors: list[str] | None = None,
    window_days: int = 60,
) -> SectorRelativeStrengthResponse:
    """Per sector, compute (sector avg return) - (KSE100 return) over
    `window_days`. Sectors default to DEFAULT_SECTORS."""
    sectors = sectors or DEFAULT_SECTORS
    rows = sector_relative_strength(cache, sectors, window_days=window_days)
    note = None
    if rows and all(r.get("rs_pct") is None for r in rows):
        note = ("All sectors lack sufficient KSE100 / member history. "
                "Call refresh_market and refresh_history for members first.")
    return SectorRelativeStrengthResponse(
        window_days=window_days, rows=rows, note=note,
    )


@mcp.tool()
async def rank_sector_relative_strength(
    sectors: list[str] | None = None, window_days: int = 60,
) -> SectorRelativeStrengthResponse:
    """Rank sectors by relative strength = sector avg return − KSE100 return
    over the past `window_days` trading bars. Positive = sector outperforming
    the index. Sorted descending. Defaults to 13 major PSX sectors when
    `sectors` is None. Requires KSE100 history and member bars in cache."""
    return _rank_sector_relative_strength_impl(_cache, sectors, window_days)


def _compute_beta_impl(cache: Cache, symbol: str,
                       index_code: str = "KSE100",
                       window: int = 252) -> BetaResponse:
    """Date-align stock bars and index EOD history, then OLS on returns.

    Both `closes_for_with_dates` and `get_index_history` return oldest-first.
    We intersect on date to compute aligned returns — required because stock
    and index may have different trading-day coverage in the cache.
    """
    stock_pairs = cache.closes_for_with_dates(symbol)
    stock_by_date = dict(stock_pairs)
    idx_rows = cache.get_index_history(index_code)
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
    common_dates = sorted(set(stock_by_date) & set(idx_by_date))
    if len(common_dates) < 2:
        return BetaResponse(
            symbol=symbol.upper(), index_code=index_code, window=window,
            beta=None, alpha=None, r_squared=None, n=0,
            note=(f"Insufficient overlap: stock has {len(stock_by_date)} bars, "
                  f"index has {len(idx_by_date)} bars, common dates {len(common_dates)}. "
                  f"Call refresh_history({symbol!r}) and refresh_market first."),
        )
    stock_closes = pd.Series([stock_by_date[d] for d in common_dates])
    idx_closes = pd.Series([idx_by_date[d] for d in common_dates])
    result = beta(stock_closes=stock_closes, index_closes=idx_closes, window=window)
    return BetaResponse(
        symbol=symbol.upper(), index_code=index_code, window=window,
        beta=result["beta"], alpha=result["alpha"],
        r_squared=result["r_squared"], n=result["n"],
        note=None,
    )


@mcp.tool()
async def compute_beta(symbol: str, index_code: str = "KSE100",
                       window: int = 252) -> BetaResponse:
    """Beta of symbol vs index, computed on date-aligned EOD returns.
    window=252 ~ 1 trading year.
    Both series are sourced from cached daily data (bars_daily for the stock,
    indices_history for the index — populated from /timeseries/eod on each
    refresh_market call). Call refresh_history(symbol) and refresh_market once
    before this for full coverage."""
    return _compute_beta_impl(_cache, symbol, index_code, window)


def _series_for(cache: Cache, symbol: str) -> pd.Series:
    return pd.Series(cache.closes_for(symbol))


def _compute_drawdown_impl(cache: Cache, symbol: str) -> DrawdownResponse:
    closes = _series_for(cache, symbol)
    if len(closes) == 0:
        return DrawdownResponse(symbol=symbol.upper(), drawdown_pct=0.0,
                                 max_drawdown_pct=0.0,
                                 note=f"No bars cached for {symbol}. "
                                      f"Call refresh_history({symbol!r}).")
    cur = drawdown_current(closes)
    mx = drawdown_max(closes)
    return DrawdownResponse(
        symbol=symbol.upper(),
        drawdown_pct=cur["drawdown_pct"],
        max_drawdown_pct=mx["max_drawdown_pct"],
        peak=cur["peak"],
        current=cur["current"],
        note=None,
    )


def _compute_risk_metrics_impl(cache: Cache, symbol: str,
                                rf_annual: float = 0.0) -> RiskMetricsResponse:
    closes = _series_for(cache, symbol)
    if len(closes) < 2:
        return RiskMetricsResponse(
            symbol=symbol.upper(),
            volatility_annualized=0.0, sharpe=None,
            max_drawdown_pct=0.0, n_bars=int(len(closes)), rf_annual=rf_annual,
            note=f"Need at least 2 bars; call refresh_history({symbol!r}).",
        )
    vol = volatility_annualized(closes)
    sh = sharpe(closes, rf_annual=rf_annual)
    mx = drawdown_max(closes)
    return RiskMetricsResponse(
        symbol=symbol.upper(),
        volatility_annualized=vol, sharpe=sh,
        max_drawdown_pct=mx["max_drawdown_pct"],
        n_bars=int(len(closes)), rf_annual=rf_annual,
        note=None,
    )


def _compute_return_stats_impl(cache: Cache, symbol: str,
                                rolling_window_days: int = 20) -> ReturnStatsResponse:
    closes = pd.Series(cache.closes_for(symbol))
    if len(closes) < 2:
        return ReturnStatsResponse(
            symbol=symbol.upper(),
            rolling_return_window_days=rolling_window_days,
            n_bars=int(len(closes)),
            note=f"Need >= 2 bars; have {len(closes)}. "
                 f"Call refresh_history({symbol!r}).",
        )
    cagr_val = cagr(closes)
    wr = win_rate(closes)
    rolls = rolling_returns(closes, window=rolling_window_days)
    rolls_sorted = sorted(rolls) if rolls else []
    return ReturnStatsResponse(
        symbol=symbol.upper(),
        cagr_pct=(cagr_val * 100.0) if cagr_val is not None else None,
        win_rate_pct=wr,
        rolling_return_window_days=rolling_window_days,
        rolling_returns_best_pct=(rolls_sorted[-1] * 100.0) if rolls_sorted else None,
        rolling_returns_worst_pct=(rolls_sorted[0] * 100.0) if rolls_sorted else None,
        rolling_returns_median_pct=(rolls_sorted[len(rolls_sorted) // 2] * 100.0)
                                    if rolls_sorted else None,
        n_bars=int(len(closes)),
        note=None,
    )


def _compute_distribution_stats_impl(cache: Cache, symbol: str) -> DistributionStatsResponse:
    closes = pd.Series(cache.closes_for(symbol))
    if len(closes) < 3:
        return DistributionStatsResponse(
            symbol=symbol.upper(),
            n_bars=int(len(closes)),
            note=f"Need >= 3 bars; have {len(closes)}. "
                 f"Call refresh_history({symbol!r}).",
        )
    sk = skewness(closes)
    ek = kurtosis_excess(closes)
    var5 = var_historical(closes, confidence=0.05)
    cvar5 = cvar_historical(closes, confidence=0.05)
    tr5 = tail_ratio(closes, quantile=0.05)
    return DistributionStatsResponse(
        symbol=symbol.upper(),
        skewness=sk,
        excess_kurtosis=ek,
        var_5pct_pct=(var5 * 100.0) if var5 is not None else None,
        cvar_5pct_pct=(cvar5 * 100.0) if cvar5 is not None else None,
        tail_ratio_5pct=tr5,
        n_bars=int(len(closes)),
        note=None,
    )


def _compute_drawdown_details_impl(cache: Cache, symbol: str) -> DrawdownDetailsResponse:
    closes = pd.Series(cache.closes_for(symbol))
    if len(closes) < 2:
        return DrawdownDetailsResponse(
            symbol=symbol.upper(), max_drawdown_pct=0.0,
            n_bars=int(len(closes)),
            note=f"Need >= 2 bars; have {len(closes)}.",
        )
    dd = drawdown_details(closes)
    ulc = ulcer_index(closes)
    return DrawdownDetailsResponse(
        symbol=symbol.upper(),
        max_drawdown_pct=dd["max_drawdown_pct"],
        peak_index=dd["peak_index"],
        trough_index=dd["trough_index"],
        recovery_index=dd["recovery_index"],
        drawdown_duration_bars=dd["drawdown_duration_bars"],
        recovery_duration_bars=dd["recovery_duration_bars"],
        ulcer_index=ulc,
        top_drawdowns=dd["top_drawdowns"],
        n_bars=int(len(closes)),
        note=None,
    )


def _compute_relative_strength_impl(cache: Cache, symbol: str,
                                     index_code: str = "KSE100",
                                     window: int = 252) -> RelativeStrengthResponse:
    # Date-align: only consider bars where BOTH stock and index have data.
    stock_pairs = cache.closes_for_with_dates(symbol)
    stock_by_date = dict(stock_pairs)
    idx_rows = cache.get_index_history(index_code)
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
    common_dates = sorted(set(stock_by_date) & set(idx_by_date))
    if len(common_dates) < window + 1:
        return RelativeStrengthResponse(
            symbol=symbol.upper(), index_code=index_code, window=window,
            relative_strength_pct=None,
            stock_return_pct=None, index_return_pct=None,
            n_bars=len(common_dates),
            note=(f"Need at least window+1={window+1} aligned bars; have "
                  f"{len(common_dates)}. Call refresh_history(symbol) and "
                  f"refresh_market."),
        )
    stock_series = pd.Series([stock_by_date[d] for d in common_dates])
    idx_series = pd.Series([idx_by_date[d] for d in common_dates])
    rs = relative_strength(stock_series, idx_series, window=window)
    stock_ret = float(stock_series.iloc[-1] / stock_series.iloc[-window - 1] - 1.0)
    idx_ret = float(idx_series.iloc[-1] / idx_series.iloc[-window - 1] - 1.0)
    return RelativeStrengthResponse(
        symbol=symbol.upper(), index_code=index_code, window=window,
        relative_strength_pct=rs,
        stock_return_pct=stock_ret, index_return_pct=idx_ret,
        n_bars=len(common_dates), note=None,
    )


def _compute_up_down_capture_impl(cache: Cache, symbol: str,
                                    index_code: str = "KSE100") -> UpDownCaptureResponse:
    stock_pairs = cache.closes_for_with_dates(symbol)
    stock_by_date = dict(stock_pairs)
    idx_rows = cache.get_index_history(index_code)
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
    common = sorted(set(stock_by_date) & set(idx_by_date))
    if len(common) < 3:
        return UpDownCaptureResponse(
            symbol=symbol.upper(), index_code=index_code,
            n_aligned_bars=len(common),
            note=(f"Need at least 3 aligned bars; have {len(common)}. "
                  f"Call refresh_history({symbol!r}) and refresh_market."),
        )
    s = pd.Series([stock_by_date[d] for d in common])
    b = pd.Series([idx_by_date[d] for d in common])
    out = up_down_capture(s, b)
    return UpDownCaptureResponse(
        symbol=symbol.upper(), index_code=index_code,
        up_capture_pct=out["up_capture_pct"],
        down_capture_pct=out["down_capture_pct"],
        n_up_periods=out["n_up_periods"],
        n_down_periods=out["n_down_periods"],
        n_aligned_bars=len(common),
        note=None,
    )


def _compute_correlation_impl(cache: Cache, symbols: list[str]) -> CorrelationMatrixResponse:
    syms_upper = [s.upper() for s in symbols]
    closes_by = {s: pd.Series(cache.closes_for(s)) for s in syms_upper}
    matrix = correlation_matrix(closes_by)
    note = None
    missing = [s for s, ser in closes_by.items() if len(ser) < 2]
    if missing:
        note = (f"Insufficient bars for: {missing}. "
                f"Call refresh_history(symbol) for each.")
    return CorrelationMatrixResponse(
        symbols=syms_upper, matrix=matrix, note=note,
    )


@mcp.tool()
async def compute_drawdown(symbol: str) -> DrawdownResponse:
    """Current drawdown from peak and max drawdown over all cached bars."""
    return _compute_drawdown_impl(_cache, symbol)


@mcp.tool()
async def compute_risk_metrics(symbol: str, rf_annual: float = 0.0) -> RiskMetricsResponse:
    """Annualized volatility (sqrt(252) scaling), Sharpe ratio, and max drawdown.
    rf_annual is the annual risk-free rate as a decimal (e.g., 0.22 for 22%
    Pakistan T-bill yield). Default 0.0 = excess return == raw return."""
    return _compute_risk_metrics_impl(_cache, symbol, rf_annual)


@mcp.tool()
async def compute_return_stats(symbol: str,
                                rolling_window_days: int = 20) -> ReturnStatsResponse:
    """Return-characterization stats: CAGR, win rate, rolling-N-day-return
    best/worst/median. CAGR is annualized compound return over the full cached
    series. Rolling window defaults to 20 trading days (~1 calendar month)."""
    return _compute_return_stats_impl(_cache, symbol, rolling_window_days)


@mcp.tool()
async def compute_distribution_stats(symbol: str) -> DistributionStatsResponse:
    """Return-distribution shape: skewness, excess kurtosis, historical 5%
    VaR/CVaR (in percent), and 5% tail ratio. Heuristics for tail risk:
    excess_kurtosis > 0 = fatter tails than normal; var_5pct_pct = the daily
    return such that 5% of historical days were worse; cvar_5pct_pct = the
    mean of those tail days (always <= VaR). tail_ratio_5pct > 1 = right
    tail dominates (favorable)."""
    return _compute_distribution_stats_impl(_cache, symbol)


@mcp.tool()
async def compute_drawdown_details(symbol: str) -> DrawdownDetailsResponse:
    """Drawdown deep-dive: max DD, time-to-trough, time-to-recovery,
    Ulcer Index, top-3 distinct drawdown events. Critical for understanding
    holding-period pain."""
    return _compute_drawdown_details_impl(_cache, symbol)


@mcp.tool()
async def compute_relative_strength(symbol: str, index_code: str = "KSE100",
                                     window: int = 252) -> RelativeStrengthResponse:
    """Stock return minus index return over the last `window` aligned trading days.
    Positive = stock outperformed; negative = lagged. Uses cached bars_daily +
    indices_history (call refresh_history and refresh_market first)."""
    return _compute_relative_strength_impl(_cache, symbol, index_code, window)


@mcp.tool()
async def compute_up_down_capture(symbol: str,
                                   index_code: str = "KSE100") -> UpDownCaptureResponse:
    """Up/down capture vs an index. > 100% up-capture = aggressive; < 100%
    down-capture = defensive. Best profile: high up + low down."""
    return _compute_up_down_capture_impl(_cache, symbol, index_code)


@mcp.tool()
async def compute_correlation(symbols: list[str]) -> CorrelationMatrixResponse:
    """Pairwise Pearson correlation of daily returns across the given symbols.
    Useful for diversification: highly-correlated names (>0.8) provide little
    diversification benefit; near-zero correlations diversify well."""
    return _compute_correlation_impl(_cache, symbols)


def _compute_position_size_impl(cache: Cache, symbol: str,
                                 portfolio_value: float,
                                 risk_pct: float = 1.0,
                                 stop_atr_mult: float = 2.0) -> PositionSizeResponse:
    """ATR-based fixed-fractional sizing:
       risk_per_share = stop_atr_mult x ATR(14)
       qty = floor((portfolio_value x risk_pct/100) / risk_per_share)"""
    df = bars_df(cache, symbol, lookback_days=60)
    risk_budget = portfolio_value * (risk_pct / 100.0)
    if df.empty or len(df) < 15:
        return PositionSizeResponse(
            symbol=symbol.upper(), portfolio_value=portfolio_value,
            risk_pct=risk_pct, stop_atr_mult=stop_atr_mult,
            risk_budget=risk_budget,
            note=(f"Need at least 15 bars to compute ATR(14); have {len(df)}. "
                  f"Call refresh_history({symbol!r})."),
        )
    atr_val = float(atr(df["high"], df["low"], df["close"], 14).iloc[-1])
    price = float(df["close"].iloc[-1])
    risk_per_share = stop_atr_mult * atr_val
    if risk_per_share <= 0:
        return PositionSizeResponse(
            symbol=symbol.upper(), portfolio_value=portfolio_value,
            risk_pct=risk_pct, stop_atr_mult=stop_atr_mult,
            price=price, atr=atr_val,
            risk_budget=risk_budget, risk_per_share=risk_per_share,
            note="ATR collapsed to <= 0; cannot size.",
        )
    qty = int(risk_budget // risk_per_share)
    return PositionSizeResponse(
        symbol=symbol.upper(), portfolio_value=portfolio_value,
        risk_pct=risk_pct, stop_atr_mult=stop_atr_mult,
        price=price, atr=atr_val,
        risk_budget=risk_budget, risk_per_share=risk_per_share,
        qty=qty, notional=qty * price,
        note=None,
    )


@mcp.tool()
async def compute_position_size(symbol: str, portfolio_value: float,
                                 risk_pct: float = 1.0,
                                 stop_atr_mult: float = 2.0) -> PositionSizeResponse:
    """ATR-based fixed-fractional position sizing.

    risk_pct: portfolio % to risk per trade (industry rule: 1-2%).
    stop_atr_mult: stop distance in ATR multiples (industry default: 2).

    Returns: ATR, suggested qty (floor), notional cost. None on insufficient bars."""
    return _compute_position_size_impl(_cache, symbol, portfolio_value,
                                        risk_pct, stop_atr_mult)


def _build_snapshot(cache: Cache, symbol: str) -> dict:
    """Assemble the dict snapshot expected by quality.py primitives."""
    sym = symbol.upper()
    quote = cache.get_latest_quote(sym) or {}
    fund = cache.get_fundamentals(sym) or {}
    hist = cache.get_fundamentals_history(sym) or []
    # newest-first → reverse to oldest-first for compute_quality_score
    eps_history = list(reversed([h["eps"] for h in hist if h.get("eps") is not None]))
    sym_row = cache.get_symbol(sym) or {}
    sector = sym_row.get("sector")
    sector_med = None
    if sector:
        ss = sector_summary(cache, sector)
        sector_med = ss.get("median_pe")
    closes = pd.Series(cache.closes_for(sym))
    return {
        "pe": fund.get("pe"),
        "eps": fund.get("eps"),
        "price": quote.get("price"),
        "roe": fund.get("roe"),
        "eps_history": eps_history,
        "closes": closes,
        "sector_median_pe": sector_med,
    }


def _snap_for_response(snap: dict) -> dict:
    """Strip non-JSON-serializable parts of the snapshot for response model."""
    return {k: v for k, v in snap.items() if k != "closes"}


def _compute_quality_score_impl(cache: Cache, symbol: str) -> QualityScoreResponse:
    snap = _build_snapshot(cache, symbol)
    score = _compute_quality_score_pure(snap)
    return QualityScoreResponse(symbol=symbol.upper(), score=score,
                                 snapshot=_snap_for_response(snap))


def _compute_4quadrant_score_impl(cache: Cache, symbol: str) -> QuadrantScoreResponse:
    snap = _build_snapshot(cache, symbol)
    sc = _compute_4quadrant_score_pure(snap)
    warnings: list[str] = []
    if snap.get("price") is None or snap.get("pe") is None:
        warnings.append("No quote/fundamentals cached. Value/Quality scores are 0.")
    if snap.get("sector_median_pe") is None:
        warnings.append("No sector peers cached → value score = 0 even if PE is low. "
                        "Call refresh_market first.")
    if not snap.get("eps_history"):
        warnings.append("No fundamentals_history (Part-4 dependency) → quality score "
                        "only reflects current ROE, not EPS trend.")
    closes = snap.get("closes")
    if closes is None or len(closes) < 200:
        warnings.append(f"Need at least 200 daily bars for trend score; have "
                        f"{len(closes) if closes is not None else 0}. "
                        f"Call refresh_history({symbol!r}).")
    return QuadrantScoreResponse(
        symbol=symbol.upper(),
        value=sc["value"], quality=sc["quality"],
        momentum=sc["momentum"], trend=sc["trend"], total=sc["total"],
        raw=sc["raw"], warnings=warnings,
    )


@mcp.tool()
async def compute_quality_score(symbol: str) -> QualityScoreResponse:
    """Simple 2-signal quality score (0..1). Signals:
      +0.5 if ROE >= 15%
      +0.5 if EPS is non-decreasing across the last 3 fiscal years

    This is NOT a full Piotroski F-Score (which requires 9 signals including
    balance-sheet items not yet populated; see Part-4 for headless-browser
    sub-tab fetcher that will unlock ROIC, debt/equity, current ratio, etc.).
    """
    return _compute_quality_score_impl(_cache, symbol)


@mcp.tool()
async def compute_4quadrant_score(symbol: str) -> QuadrantScoreResponse:
    """Composite Value/Quality/Momentum/Trend score (0..4). 3+ = high-conviction."""
    return _compute_4quadrant_score_impl(_cache, symbol)


# ---- unified dashboard ----

def _get_full_analysis_impl(cache: Cache, symbol: str) -> FullAnalysisResponse:
    """One-shot dashboard. Composes existing impls. Each section is best-effort
    — missing data → that section is None and a warning is added."""
    sym = symbol.upper()
    warnings: list[str] = []

    # Quote
    quote = None
    try:
        q = _get_quote_impl(cache, sym)
        quote = q.model_dump(exclude={"disclaimer"})
        if q.stale:
            warnings.append("Quote is stale; call refresh_market.")
    except Exception as e:
        warnings.append(f"quote: {e!r}")

    # Fundamentals (current)
    fundamentals = None
    try:
        f = cache.get_fundamentals(sym)
        if f:
            fundamentals = dict(f)
        else:
            warnings.append("No fundamentals cached.")
    except Exception as e:
        warnings.append(f"fundamentals: {e!r}")

    # 52w high/low
    week52 = None
    try:
        hi, lo = cache.fifty_two_week(sym)
        week52 = {"high": hi, "low": lo}
    except Exception as e:
        warnings.append(f"52w: {e!r}")

    # Indicators (default bundle)
    indicators = None
    try:
        ind = _compute_indicators_impl(cache, sym, indicators=None)
        # Strip the embedded disclaimer key
        indicators = {k: v for k, v in ind.items() if k != "disclaimer"}
    except Exception as e:
        warnings.append(f"indicators: {e!r}")

    # Drawdown
    drawdown = None
    try:
        dd = _compute_drawdown_impl(cache, sym)
        drawdown = dd.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"drawdown: {e!r}")

    # Risk metrics
    risk = None
    try:
        rm = _compute_risk_metrics_impl(cache, sym, rf_annual=0.0)
        risk = rm.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"risk: {e!r}")

    # Beta
    beta_dict = None
    try:
        b = _compute_beta_impl(cache, sym)
        beta_dict = b.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"beta: {e!r}")

    # Relative strength
    rs = None
    try:
        rs_r = _compute_relative_strength_impl(cache, sym)
        rs = rs_r.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"relative_strength: {e!r}")

    # Quadrant score (also lift its per-quadrant warnings into the dashboard top-level)
    quadrant_score = None
    try:
        qs = _compute_4quadrant_score_impl(cache, sym)
        quadrant_score = qs.model_dump(exclude={"disclaimer"})
        for w in getattr(qs, "warnings", []) or []:
            warnings.append(f"quadrant: {w}")
    except Exception as e:
        warnings.append(f"quadrant_score: {e!r}")

    # Dividend history (last 5)
    divs: list[dict] = []
    try:
        ds = cache.get_dividend_history(sym)
        divs = [dict(d) for d in ds[:5]]
    except Exception as e:
        warnings.append(f"dividends: {e!r}")

    # Announcements (last 5 for this symbol)
    anns: list[dict] = []
    try:
        rows = cache.conn.execute(
            "SELECT title, posted_at, url FROM announcements "
            "WHERE symbol=? ORDER BY posted_at DESC LIMIT 5",
            (sym,),
        ).fetchall()
        anns = [dict(r) for r in rows]
    except Exception as e:
        warnings.append(f"announcements: {e!r}")

    return FullAnalysisResponse(
        symbol=sym, quote=quote, fundamentals=fundamentals,
        week52=week52, indicators=indicators,
        drawdown=drawdown, risk=risk, beta=beta_dict,
        relative_strength=rs, quadrant_score=quadrant_score,
        dividend_history_recent=divs,
        announcements_recent=anns,
        warnings=warnings,
    )


@mcp.tool()
async def get_full_analysis(symbol: str) -> FullAnalysisResponse:
    """One-shot research dashboard: quote, fundamentals, 52w range, indicators,
    drawdown, risk metrics, beta, relative strength, 4-quadrant score, recent
    dividends, recent announcements. Missing sections → null + warning."""
    return _get_full_analysis_impl(_cache, symbol)


def _get_extended_risk_metrics_impl(cache: Cache, symbol: str) -> ExtendedRiskMetricsResponse:
    """Part-4 unified risk dashboard. Composes return/risk-adjusted/distribution/
    drawdown/capture/technical sections. Each sub-call wrapped in try/except so
    missing data appends a warning rather than crashing the whole dashboard."""
    sym = symbol.upper()
    warnings: list[str] = []

    # 1. Return stats
    return_stats = None
    try:
        rs = _compute_return_stats_impl(cache, sym)
        return_stats = rs.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"return_stats: {e!r}")

    # 2. Risk-adjusted: Sortino, Calmar, Omega, Information Ratio (date-aligned)
    risk_adjusted = None
    try:
        closes = pd.Series(cache.closes_for(sym))
        if len(closes) < 3:
            warnings.append(f"risk_adjusted: need >= 3 bars; have {len(closes)}.")
        else:
            sortino_val = sortino(closes)
            calmar_val = calmar(closes)
            omega_val = omega_ratio(closes, threshold=0.0)
            # Information Ratio — REQUIRES date-aligned series (per M4 fix)
            stock_pairs = cache.closes_for_with_dates(sym)
            stock_by_date = dict(stock_pairs)
            idx_rows = cache.get_index_history("KSE100")
            idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
            common = sorted(set(stock_by_date) & set(idx_by_date))
            ir = None
            if len(common) >= 2:
                s_aligned = pd.Series([stock_by_date[d] for d in common])
                i_aligned = pd.Series([idx_by_date[d] for d in common])
                ir = information_ratio(s_aligned, i_aligned)
            else:
                warnings.append(
                    f"risk_adjusted.information_ratio: only {len(common)} "
                    f"date-aligned bars vs KSE100."
                )
            risk_adjusted = {
                "sortino": sortino_val,
                "calmar": calmar_val,
                "omega_ratio_threshold_0": omega_val,
                "information_ratio_vs_kse100": ir,
                "n_bars": int(len(closes)),
                "n_aligned_bars_kse100": len(common),
            }
    except Exception as e:
        warnings.append(f"risk_adjusted: {e!r}")

    # 3. Distribution
    distribution = None
    try:
        ds = _compute_distribution_stats_impl(cache, sym)
        distribution = ds.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"distribution: {e!r}")

    # 4. Drawdown details
    drawdown = None
    try:
        dd = _compute_drawdown_details_impl(cache, sym)
        drawdown = dd.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"drawdown: {e!r}")

    # 5. Up/Down capture
    capture = None
    try:
        cap = _compute_up_down_capture_impl(cache, sym)
        capture = cap.model_dump(exclude={"disclaimer"})
    except Exception as e:
        warnings.append(f"capture: {e!r}")

    # 6. Technical bundle (extended indicators)
    technical = None
    try:
        ind = _compute_indicators_impl(
            cache, sym,
            indicators=["adx14", "stochastic", "obv", "williams_r14",
                        "rsi14", "atr14"],
            lookback_days=260,
        )
        technical = {k: v for k, v in ind.items() if k != "disclaimer"}
    except Exception as e:
        warnings.append(f"technical: {e!r}")

    note = None
    if all(s is None for s in (return_stats, risk_adjusted, distribution,
                                drawdown, capture, technical)):
        note = (f"No data could be computed for {sym}. "
                f"Call refresh_history({sym!r}) and refresh_market first.")

    return ExtendedRiskMetricsResponse(
        symbol=sym,
        return_stats=return_stats,
        risk_adjusted=risk_adjusted,
        distribution=distribution,
        drawdown=drawdown,
        capture=capture,
        technical=technical,
        warnings=warnings,
        note=note,
    )


@mcp.tool()
async def get_extended_risk_metrics(symbol: str) -> ExtendedRiskMetricsResponse:
    """One-shot extended risk & technical dashboard (Part-4).

    Sections:
      - return_stats: CAGR, win rate, rolling N-day best/worst/median
      - risk_adjusted: Sortino, Calmar, Omega, Information Ratio (vs KSE100,
        date-aligned)
      - distribution: skewness, excess kurtosis, 5% VaR/CVaR, tail ratio
      - drawdown: max DD, time-to-trough/recovery, Ulcer Index, top events
      - capture: up/down capture vs KSE100
      - technical: ADX14, Stochastic, OBV, Williams %R, RSI14, ATR14

    Each section is best-effort — missing data → null + warning, no crash.
    Call refresh_history(symbol) and refresh_market first for full coverage."""
    return _get_extended_risk_metrics_impl(_cache, symbol)


# ---- dividends ----

async def _refresh_dividends_impl(cache: Cache, client: PSXClient,
                                   symbol: str) -> int:
    """Fetch & cache dividend history for one symbol. Returns count upserted."""
    html = await client.fetch_company_payouts(symbol)
    events = parse_payouts(symbol, html)
    for e in events:
        cache.upsert_dividend(**e)
    return len(events)


def _get_dividend_history_impl(cache: Cache, symbol: str) -> list[DividendEvent]:
    rows = cache.get_dividend_history(symbol)
    return [DividendEvent(**r) for r in rows]


@mcp.tool()
async def refresh_dividends(symbol: str) -> int:
    """Refresh dividend history for one symbol from PSX /company/payouts.
    Returns count of dividend events cached."""
    return await _refresh_dividends_impl(_cache, _client, symbol)


@mcp.tool()
async def get_dividend_history(symbol: str) -> list[DividendEvent]:
    """Cached dividend events for symbol, newest ex-date first.
    Call refresh_dividends(symbol) first to populate."""
    return _get_dividend_history_impl(_cache, symbol)


# ---- cache diagnostics + bulk refresh ----

def _get_cache_status_impl(cache: Cache) -> CacheStatusResponse:
    tables = cache.cache_status()
    note = None
    if not any(t["count"] for t in tables.values()):
        note = "Cache is empty. Start with refresh_market then refresh_history(symbol)."
    return CacheStatusResponse(tables=tables, note=note)


async def _refresh_universe_impl(cache: Cache,
                                  client: Optional[PSXClient],
                                  symbols: Optional[list[str]] = None,
                                  sector: Optional[str] = None) -> BulkRefreshResponse:
    """Bulk refresh history. Resolution: symbols > sector > all-with-quotes."""
    if client is None:
        return BulkRefreshResponse(
            requested=[], succeeded=[], failed=[], elapsed_seconds=0.0,
            note=("No PSX client configured (server.set_dependencies(client=...) "
                  "was called with None). Cannot fetch."),
        )
    if symbols:
        targets = [s.upper() for s in symbols]
    elif sector:
        rows = cache.conn.execute(
            "SELECT symbol FROM symbols WHERE sector = ?", (sector,)
        ).fetchall()
        targets = [r["symbol"] for r in rows]
    else:
        rows = cache.conn.execute(
            "SELECT DISTINCT symbol FROM quotes"
        ).fetchall()
        targets = [r["symbol"] for r in rows]

    succeeded: list[str] = []
    failed: list[dict] = []
    start = time.time()
    for sym in targets:
        try:
            await _refresh_history_impl(cache, client, sym)
            succeeded.append(sym)
        except Exception as e:
            failed.append({"symbol": sym, "error": str(e)})
    elapsed = time.time() - start
    note = None
    if not targets:
        note = ("No symbols resolved. Either pass `symbols=[...]`, or call "
                "refresh_market first to populate the universe.")
    return BulkRefreshResponse(
        requested=targets, succeeded=succeeded, failed=failed,
        elapsed_seconds=elapsed, note=note,
    )


@mcp.tool()
async def get_cache_status() -> CacheStatusResponse:
    """Report row counts and latest-refresh timestamp for each cache table.
    Use this to know what's fresh before relying on screener/score outputs."""
    return _get_cache_status_impl(_cache)


@mcp.tool()
async def refresh_universe(symbols: list[str] | None = None,
                            sector: str | None = None) -> BulkRefreshResponse:
    """Bulk-refresh daily history for many symbols. Resolution order:
       1. `symbols` if given;
       2. else all symbols in `sector` if given;
       3. else all symbols with cached quotes.
    Slow on the full universe. Use sparingly or pre-filter via `sector`."""
    return await _refresh_universe_impl(_cache, _client, symbols, sector)


# ---- upcoming corporate events (heuristic, title-pattern based) ----

UPCOMING_EVENT_PATTERNS = [
    r"\bboard\s+meeting\b",
    r"\bagm\b", r"\bextraordinary\s+general\s+meeting\b", r"\begm\b",
    r"\bfinancial\s+results?\b",
    r"\bcorporate\s+briefing\b", r"\bcbs\b",
    r"\bex[- ]?date\b", r"\bbook\s+closure\b",
]
_UPCOMING_RE = _re.compile("|".join(UPCOMING_EVENT_PATTERNS), _re.I)


def _get_upcoming_events_impl(cache: Cache, lookback_days: int = 14) -> UpcomingEventsResponse:
    """Heuristic 'upcoming events' tool: returns announcements posted in the last
    `lookback_days` whose title matches a curated set of corporate-action
    patterns (Board Meeting, AGM, EGM, Financial Results, Corporate Briefing,
    Ex-Date, Book Closure). Without parsing announcement PDFs we cannot extract
    the actual scheduled date; the user must read the announcement for that."""
    since = (datetime.now() - timedelta(days=lookback_days)).isoformat()
    rows = cache.conn.execute(
        "SELECT symbol, title, posted_at, url FROM announcements "
        "WHERE posted_at >= ? ORDER BY posted_at DESC",
        (since,),
    ).fetchall()
    events = []
    for r in rows:
        title = r["title"] or ""
        if _UPCOMING_RE.search(title):
            events.append(dict(r))
    note = None
    if not events:
        note = (f"No matching announcements in the last {lookback_days} days. "
                f"Try a wider lookback or call refresh_announcements first.")
    return UpcomingEventsResponse(lookback_days=lookback_days, events=events,
                                   note=note)


@mcp.tool()
async def get_upcoming_events(lookback_days: int = 14) -> UpcomingEventsResponse:
    """Surface recently-posted announcements that imply upcoming corporate
    actions (Board Meeting, AGM/EGM, Financial Results, CBS, Ex-Date, Book
    Closure). Heuristic — title-pattern based; actual event dates require
    reading the announcement PDF via its url."""
    return _get_upcoming_events_impl(_cache, lookback_days)


# ---- smoke-test backtest ----

BACKTEST_CAVEATS = [
    "No transaction costs / slippage / spread.",
    "No dividend reinvestment.",
    "Raw prices — bonus/split adjustment status indeterminate (see analytics-v1 Q4).",
    "Per-signal independent positions; no portfolio-level constraint.",
    "Equal-weight at entry; no rebalance.",
    "Smoke-test grade — directional sanity check, NOT a production simulation.",
]


def _backtest_simple_impl(cache: Cache,
                          filter_spec: dict,
                          hold_days: int = 63,
                          since: str = "2025-01-01") -> BacktestResponse:
    """Run a smoke-test backtest using bars_daily.

    Strategy: each trading day in [since, today], use today's filter_spec to identify
    candidate symbols (forward-looking-data leak — see note); buy each candidate at
    that day's close, sell hold_days later."""
    from datetime import date as _d

    since_date = _d.fromisoformat(since)
    # Gather all bars for all cached symbols once.
    rows = cache.conn.execute(
        "SELECT symbol, date, close FROM bars_daily ORDER BY date ASC"
    ).fetchall()
    closes_by_sym_date: dict[tuple[str, _d], float] = {}
    for r in rows:
        closes_by_sym_date[(r["symbol"], _d.fromisoformat(r["date"]))] = r["close"]

    spec = FilterSpec(**{k: v for k, v in filter_spec.items() if v is not None})
    candidate_rows = screen(cache, spec)
    candidate_syms = [r["symbol"] for r in candidate_rows]

    # Build per-symbol date index ONCE — O(total_bars + candidates*candidate_bars)
    # rather than O(symbols*all_bars*candidates).
    dates_by_sym: dict[str, list[_d]] = {}
    for (s, d) in closes_by_sym_date.keys():
        dates_by_sym.setdefault(s, []).append(d)

    signals_by_date: dict[_d, list[str]] = {}
    for sym in candidate_syms:
        for d in dates_by_sym.get(sym, []):
            if d < since_date:
                continue
            signals_by_date.setdefault(d, []).append(sym)

    result = _backtest_simple_pure(
        closes_by_sym_date=closes_by_sym_date,
        signals_by_date=signals_by_date,
        hold_days=hold_days,
    )
    return BacktestResponse(
        filter_spec=filter_spec, hold_days=hold_days, since=since,
        n_trades=result["n_trades"],
        mean_return_pct=result["mean_return_pct"],
        median_return_pct=result["median_return_pct"],
        total_return_pct=result["total_return_pct"],
        win_rate_pct=result["win_rate_pct"],
        trades=[{**t, "entry_date": t["entry_date"].isoformat(),
                 "exit_date": t["exit_date"].isoformat()} for t in result["trades"]],
        caveats=BACKTEST_CAVEATS,
        note=("This is a SMOKE-TEST backtest. Today's fundamentals are used to "
              "generate past signals, which leaks information forward. Treat "
              "results as directional sanity only — do not rely on Sharpe/winrate "
              "for live position sizing."),
    )


@mcp.tool()
async def backtest_simple(filter_spec: dict,
                          hold_days: int = 63,
                          since: str = "2025-01-01") -> BacktestResponse:
    """Smoke-test backtest of a simple buy-on-signal/sell-after-hold strategy.
    WARNING: uses today's fundamentals to label past signals — directional only.
    filter_spec keys correspond to FilterSpec fields (pe_max, min_volume, etc.).
    Read `caveats` field carefully before relying on results."""
    return _backtest_simple_impl(_cache, filter_spec, hold_days, since)


async def _fetch_announcement_body_impl(cache: Cache, client: PSXClient,
                                          announcement_id: str
                                          ) -> AnnouncementBodyResponse:
    """Fetch + cache the body PDF text for a single announcement.

    Idempotent: if any fetch_status is already set, returns cached body
    without re-fetching. Never auto-retries — caller can clear fetch_status
    via raw SQL to force retry."""
    row = cache.conn.execute(
        "SELECT symbol, title, url, body, fetch_status, posted_at "
        "FROM announcements WHERE id = ?",
        (announcement_id,),
    ).fetchone()
    if not row:
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, fetch_status="not_found",
            note="No announcement with that id in cache.",
        )
    if row["fetch_status"]:
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status=row["fetch_status"],
            body=row["body"],
            body_chars=len(row["body"] or ""),
            note="Returning cached body; previously fetched.",
        )
    if not row["url"]:
        cache.update_announcement_body(announcement_id, None, "no_url")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=None,
            fetch_status="no_url",
            note="Announcement has no PDF URL; nothing to fetch.",
        )
    if client is None:
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="no_client",
            note="No PSX client configured (set_dependencies(client=...) was None).",
        )

    pdf_bytes = await client.fetch_url_bytes(row["url"])
    if pdf_bytes is None:
        cache.update_announcement_body(announcement_id, None, "http_error")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="http_error",
            note="Network error or non-200 response.",
        )
    text = extract_text_or_empty(pdf_bytes)
    if not text:
        cache.update_announcement_body(announcement_id, None, "parse_error")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="parse_error",
            note="PDF parsed to empty text; might be encrypted or malformed.",
        )
    if is_probably_scan_only(text):
        cache.update_announcement_body(announcement_id, text, "scan_only")
        return AnnouncementBodyResponse(
            announcement_id=announcement_id, symbol=row["symbol"],
            title=row["title"], url=row["url"],
            fetch_status="scan_only",
            body=text, body_chars=len(text),
            note="PDF looks scan-only; OCR would be needed for full text.",
        )
    cache.update_announcement_body(announcement_id, text, "ok")
    # Auto-populate structured event tables based on title classification.
    # Critic C BLOCKER fix: only route 'board_meeting' to parse_board_meeting.
    # 'financial_results' titles contain "period ended" dates that would
    # otherwise be incorrectly captured as meeting dates.
    cat = classify_announcement(row["title"] or "")
    try:
        if cat == "insider_trade":
            parsed = parse_insider_trade(text)
            if parsed:
                cache.upsert_insider_trade(
                    announcement_id=announcement_id,
                    symbol=row["symbol"],
                    insider_name=parsed["insider_name"],
                    insider_role=parsed["insider_role"],
                    action=parsed["action"],
                    qty=parsed["qty"],
                    pct_holding=parsed["pct_holding"],
                    trade_date=parsed["trade_date"],
                    posted_at=row["posted_at"],
                )
        elif cat == "board_meeting":
            parsed = parse_board_meeting(title=row["title"], body=text)
            if parsed:
                cache.upsert_board_meeting(
                    announcement_id=announcement_id,
                    symbol=row["symbol"],
                    meeting_date=parsed["meeting_date"],
                    agenda=parsed["agenda"],
                    posted_at=row["posted_at"],
                )
    except Exception:
        # Auto-extraction is best-effort; never block the body cache on parser bugs.
        pass
    return AnnouncementBodyResponse(
        announcement_id=announcement_id, symbol=row["symbol"],
        title=row["title"], url=row["url"],
        fetch_status="ok",
        body=text, body_chars=len(text),
    )


async def _bulk_fetch_announcement_bodies_impl(cache: Cache, client: PSXClient,
                                                 symbol: Optional[str],
                                                 since_days: int = 30,
                                                 limit: int = 20,
                                                 concurrency: int = 4,
                                                 delay_ms: int = 250
                                                 ) -> BulkBodyFetchResponse:
    """Concurrent bulk fetch with polite defaults. Per-PDF errors don't kill
    the batch."""
    rows = cache.get_announcements_missing_body(symbol=symbol,
                                                 since_days=since_days,
                                                 limit=limit)
    started = _time.time()
    summary = {"attempted": 0, "succeeded": 0,
               "skipped_no_url": 0, "failed_http": 0,
               "failed_scan": 0, "failed_parse": 0,
               "failed_other": 0}

    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(rid: str):
        async with sem:
            resp = await _fetch_announcement_body_impl(cache, client, rid)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            return resp

    if rows:
        results = await asyncio.gather(*(one(r["id"]) for r in rows),
                                         return_exceptions=False)
    else:
        results = []

    for resp in results:
        summary["attempted"] += 1
        status = resp.fetch_status
        if status == "ok":
            summary["succeeded"] += 1
        elif status == "no_url":
            summary["skipped_no_url"] += 1
        elif status == "http_error":
            summary["failed_http"] += 1
        elif status == "scan_only":
            summary["failed_scan"] += 1
        elif status == "parse_error":
            summary["failed_parse"] += 1
        else:
            summary["failed_other"] += 1

    return BulkBodyFetchResponse(
        symbol=symbol.upper() if symbol else None,
        since_days=since_days,
        attempted=summary["attempted"],
        succeeded=summary["succeeded"],
        skipped_no_url=summary["skipped_no_url"],
        failed_http=summary["failed_http"],
        failed_scan=summary["failed_scan"],
        failed_parse=summary["failed_parse"],
        failed_other=summary["failed_other"],
        elapsed_seconds=_time.time() - started,
    )


@mcp.tool()
async def fetch_announcement_body(announcement_id: str) -> AnnouncementBodyResponse:
    """Fetch + cache the PDF body of a single PSX announcement. Idempotent;
    returns cached body if previously fetched (regardless of prior status —
    we never auto-retry; clear fetch_status to force re-fetch)."""
    return await _fetch_announcement_body_impl(_cache, _client, announcement_id)


@mcp.tool()
async def bulk_fetch_announcement_bodies(symbol: str | None = None,
                                           since_days: int = 30,
                                           limit: int = 20,
                                           concurrency: int = 4,
                                           delay_ms: int = 250
                                           ) -> BulkBodyFetchResponse:
    """Bulk-fetch announcement bodies. Polite defaults: limit=20,
    concurrency=4, 250ms between requests. Raise these cautiously — PSX may
    rate-limit aggressive crawlers."""
    return await _bulk_fetch_announcement_bodies_impl(
        _cache, _client, symbol, since_days, limit, concurrency, delay_ms,
    )


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
