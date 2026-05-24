"""Multi-criteria filter over the cached PSX universe.

Pulls quotes + fundamentals + computed indicators into a single result set.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from psx_mcp import indicators


SORTABLE = {"change_pct", "volume", "pe", "rsi14", "symbol", "price"}


@dataclass
class FilterSpec:
    sector: Optional[str] = None
    sectors: list[str] = field(default_factory=list)
    pe_min: Optional[float] = None
    pe_max: Optional[float] = None
    eps_min: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    rsi_min: Optional[float] = None
    rsi_max: Optional[float] = None
    above_sma200: Optional[bool] = None
    sma20_gt_sma50: Optional[bool] = None
    min_volume: Optional[int] = None
    min_turnover_pkr: Optional[float] = None
    sort_by: str = "symbol"
    desc: bool = False
    limit: int = 50


def screen(cache, spec: FilterSpec) -> list[dict]:
    """Filter the cached universe by spec, return sorted matching rows."""
    # 1) SQL-friendly filters
    where: list[str] = []
    params: list = []
    if spec.sector:
        where.append("s.sector = ?")
        params.append(spec.sector)
    elif spec.sectors:
        where.append("s.sector IN (" + ",".join("?" * len(spec.sectors)) + ")")
        params.extend(spec.sectors)
    if spec.pe_min is not None:
        where.append("f.pe >= ?")
        params.append(spec.pe_min)
    if spec.pe_max is not None:
        where.append("f.pe <= ?")
        params.append(spec.pe_max)
    if spec.eps_min is not None:
        where.append("f.eps >= ?")
        params.append(spec.eps_min)
    if spec.price_min is not None:
        where.append("q.price >= ?")
        params.append(spec.price_min)
    if spec.price_max is not None:
        where.append("q.price <= ?")
        params.append(spec.price_max)
    if spec.min_volume is not None:
        where.append("q.volume >= ?")
        params.append(spec.min_volume)
    if spec.min_turnover_pkr is not None:
        where.append("q.price * q.volume >= ?")
        params.append(spec.min_turnover_pkr)

    rows = cache.screen_candidates(" AND ".join(where), params)
    all_symbols = [r["symbol"] for r in rows]
    closes_by_sym = cache.closes_for_many(all_symbols)

    # 2) Compute change_pct and indicators per candidate
    results: list[dict] = []
    for r in rows:
        sym = r["symbol"]
        price = r["price"]
        change = r["change"]
        prev_close = price - change
        change_pct = (change / prev_close * 100) if prev_close > 0 else None

        # Fetch close series for indicators (batched up-front)
        closes_list = closes_by_sym.get(sym, [])
        technical_active = any(
            x is not None for x in [
                spec.rsi_min, spec.rsi_max,
                spec.above_sma200, spec.sma20_gt_sma50,
            ]
        )
        if len(closes_list) < 50:
            # Not enough bars for reliable indicators — skip if technical filter active
            if technical_active:
                continue
            sma20 = sma50 = sma200 = rsi14 = None
        else:
            closes = pd.Series(closes_list)
            sma20 = float(indicators.sma(closes, 20).iloc[-1]) if len(closes) >= 20 else None
            sma50 = float(indicators.sma(closes, 50).iloc[-1]) if len(closes) >= 50 else None
            sma200 = float(indicators.sma(closes, 200).iloc[-1]) if len(closes) >= 200 else None
            rsi14 = float(indicators.rsi(closes, 14).iloc[-1])

        if spec.rsi_min is not None and (rsi14 is None or rsi14 < spec.rsi_min):
            continue
        if spec.rsi_max is not None and (rsi14 is None or rsi14 > spec.rsi_max):
            continue
        if spec.above_sma200 is True and (sma200 is None or price <= sma200):
            continue
        if spec.above_sma200 is False and (sma200 is not None and price > sma200):
            continue
        if spec.sma20_gt_sma50 is True and not (sma20 and sma50 and sma20 > sma50):
            continue
        if spec.sma20_gt_sma50 is False and (sma20 and sma50 and sma20 > sma50):
            continue

        results.append({
            "symbol": sym, "name": r["name"], "sector": r["sector"],
            "price": price, "change_pct": change_pct, "volume": r["volume"],
            "pe": r["pe"], "eps": r["eps"],
            "pb": r["pb"], "div_yield": r["div_yield"],
            "payout": r["payout"], "roe": r["roe"],
            "sma20": sma20, "sma50": sma50, "sma200": sma200, "rsi14": rsi14,
        })

    # 3) Sort & limit
    sort_key = spec.sort_by if spec.sort_by in SORTABLE else "symbol"
    results.sort(
        key=lambda r: (r.get(sort_key) is None, r.get(sort_key)),
        reverse=spec.desc,
    )
    return results[: spec.limit]


def sector_summary(cache, sector: str) -> dict:
    """Return aggregate stats for a sector: breadth, median PE, leaders."""
    rows = screen(cache, FilterSpec(sector=sector, limit=500))
    if not rows:
        return {
            "sector": sector, "n": 0,
            "median_pe": None, "avg_change_pct": None,
            "pct_above_sma200": None,
            "top_5_by_change": [], "bottom_5_by_change": [],
        }
    pes = sorted([r["pe"] for r in rows if r["pe"] is not None])
    chgs = [r["change_pct"] for r in rows if r["change_pct"] is not None]
    above = sum(1 for r in rows
                if r.get("sma200") is not None and r["price"] > r["sma200"])
    by_chg = sorted([r for r in rows if r["change_pct"] is not None],
                    key=lambda r: r["change_pct"])
    return {
        "sector": sector,
        "n": len(rows),
        "median_pe": (pes[len(pes) // 2] if pes else None),
        "avg_change_pct": (sum(chgs) / len(chgs) if chgs else None),
        "pct_above_sma200": round(100 * above / len(rows), 1),
        "top_5_by_change": [{"symbol": r["symbol"], "change_pct": r["change_pct"]}
                            for r in by_chg[-5:][::-1]],
        "bottom_5_by_change": [{"symbol": r["symbol"], "change_pct": r["change_pct"]}
                               for r in by_chg[:5]],
    }
