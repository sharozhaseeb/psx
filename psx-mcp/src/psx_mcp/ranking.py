"""Cross-sectional ranking helpers.
Pulls from cache through screener.sector_summary; does not query SQL directly."""
from __future__ import annotations
from typing import Literal, Optional
import pandas as pd
from psx_mcp.quality import compute_4quadrant_score
from psx_mcp.df_utils import bars_df
from psx_mcp.indicators import rsi
from psx_mcp.screener import sector_summary


SectorRankMetric = Literal[
    "avg_change_pct",
    "median_pe",
    "pct_above_sma200",
    "n",
]


def rank_sectors(cache, sectors: list[str],
                 by: str = "avg_change_pct",
                 desc: bool = True) -> list[dict]:
    """Score each sector via sector_summary, return rank list sorted by `by`.

    Empty sectors (n == 0) are dropped. None values sort to the end regardless
    of `desc`."""
    rows = []
    for s in sectors:
        summary = sector_summary(cache, s)
        if summary.get("n", 0) == 0:
            continue
        rows.append(summary)
    rows.sort(key=lambda r: (r.get(by) is None, r.get(by)), reverse=desc)
    return rows


def rank_universe(cache, by: str = "composite",
                  sector: str | None = None,
                  limit: int = 20,
                  candidate_cap: int = 200) -> list[dict]:
    """Rank cached symbols by a metric. Always computes against the LATEST quote
    JOIN; only symbols with cached quotes are scored.

    `by`:
      "composite"   — 4-quadrant total (0..4), descending
      "change_pct"  — today's % change, descending
      "rsi14"       — RSI(14), descending (overbought first)
      "pe"          — P/E, ascending (cheapest first)

    `candidate_cap` limits how many symbols' indicators we compute (expensive)
    to avoid blowing up on the full ~1000-symbol universe. Default 200 keeps
    end-to-end < ~10s on a warm cache.
    """
    sql = "SELECT s.symbol, s.sector FROM symbols s JOIN quotes q ON q.symbol = s.symbol"
    params: list = []
    if sector:
        sql += " WHERE s.sector = ?"
        params.append(sector)
    sql += " LIMIT ?"
    params.append(candidate_cap)
    rows = cache.conn.execute(sql, params).fetchall()
    out = []
    # Memoize sector_summary per call (M2 fix from review).
    sector_med_cache: dict[str, Optional[float]] = {}

    for r in rows:
        sym = r["symbol"]
        df = bars_df(cache, sym, lookback_days=260)
        if df.empty:
            continue
        quote = cache.get_latest_quote(sym) or {}
        fund = cache.get_fundamentals(sym) or {}
        price = float(quote.get("price") or 0)
        change = float(quote.get("change") or 0)
        prev_close = price - change
        change_pct = (change / prev_close * 100) if prev_close > 0 else None

        record = {
            "symbol": sym, "sector": r["sector"],
            "price": price, "change_pct": change_pct,
            "pe": fund.get("pe"), "eps": fund.get("eps"),
        }

        if by == "composite":
            closes = pd.Series(cache.closes_for(sym))
            sector_med = None
            if r["sector"]:
                if r["sector"] not in sector_med_cache:
                    ss = sector_summary(cache, r["sector"])
                    sector_med_cache[r["sector"]] = ss.get("median_pe")
                sector_med = sector_med_cache[r["sector"]]
            hist = cache.get_fundamentals_history(sym) or []
            eps_history = list(reversed([h["eps"] for h in hist if h.get("eps") is not None]))
            snap = {
                "pe": fund.get("pe"), "eps": fund.get("eps"),
                "price": price, "roe": fund.get("roe"),
                "eps_history": eps_history, "closes": closes,
                "sector_median_pe": sector_med,
            }
            sc = compute_4quadrant_score(snap)
            record["composite"] = sc["total"]
            record["quadrants"] = {k: sc[k] for k in ("value", "quality", "momentum", "trend")}
        elif by == "rsi14":
            closes = pd.Series(cache.closes_for(sym))
            if len(closes) < 15:
                continue
            record["rsi14"] = float(rsi(closes, 14).iloc[-1])
        elif by == "change_pct":
            if change_pct is None:
                continue
        elif by == "pe":
            if record["pe"] is None:
                continue
        else:
            raise ValueError(f"unknown ranking metric: {by}")

        out.append(record)

    if by == "pe":
        out.sort(key=lambda r: (r.get("pe") is None, r.get("pe")), reverse=False)
    else:
        out.sort(key=lambda r: (r.get(by) is None, r.get(by)), reverse=True)
    return out[:limit]
