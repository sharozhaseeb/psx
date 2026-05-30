"""One-off research script: pull live PSX data, screen across sectors, output candidates.

Refreshes market + index snapshot, pulls latest announcements (a leading indicator
of corporate action / earnings), then for a curated list of liquid PSX names pulls
historical bars + fundamentals so the screener can be applied.

Output: ranked candidates per sector, with the announcement/data point that
motivates each pick.
"""
from __future__ import annotations
import asyncio
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from psx_mcp.cache import Cache
from psx_mcp.psx_client import (
    PSXClient, parse_market_watch, parse_historical, parse_announcements,
    parse_profile, parse_financials,
)
from psx_mcp.models import Announcement
from psx_mcp.df_utils import bars_df
from psx_mcp.indicators import sma, rsi, atr
from psx_mcp.screener import screen, FilterSpec, sector_summary
import pandas as pd

DB_PATH = "data/research_picks.db"


# Liquid PSX large-cap names across major sectors, used to seed history+fundamentals
# (refresh_market gives us quotes for the whole universe but not bars/fundamentals).
UNIVERSE_BY_SECTOR = {
    "TECHNOLOGY & COMMUNICATION": ["SYS", "NETSOL", "TRG", "AVN", "PTC"],
    "CEMENT":                     ["LUCK", "MLCF", "DGKC", "FCCL", "KOHC", "PIOC", "BWCL"],
    "OIL & GAS EXPLORATION COMPANIES": ["OGDC", "PPL", "POL", "MARI"],
    "OIL & GAS MARKETING COMPANIES":    ["PSO", "APL", "SHEL"],
    "COMMERCIAL BANKS":           ["MCB", "UBL", "HBL", "MEBL", "BAFL", "AKBL", "BAHL", "ABL"],
    "FERTILIZER":                 ["FFC", "ENGRO", "FFBL", "FATIMA", "EFERT"],
    "POWER GENERATION & DISTRIBUTION": ["HUBC", "KEL", "NPL", "NCPL", "KAPCO"],
    "AUTOMOBILE ASSEMBLER":       ["INDU", "HCAR", "PSMC", "MTL"],
    "FOOD & PERSONAL CARE PRODUCTS": ["NESTLE", "EFOODS", "UPFL", "UNILEVER"],
    "PHARMACEUTICALS":            ["SEARL", "GSK", "ABOT", "FEROZ", "GLAXO", "HINOON"],
    "TEXTILE COMPOSITE":          ["NML", "ILP", "GATM", "KTML"],
    "CHEMICAL":                   ["LOTCHEM", "EPCL", "ICI"],
    "REFINERY":                   ["ATRL", "NRL", "PRL"],
}


async def fetch_and_seed(cache: Cache, client: PSXClient):
    print("\n[1/4] Refreshing market watch (all PSX quotes)...")
    html = await client.fetch_market_watch()
    rows = parse_market_watch(html)
    from datetime import datetime
    now = datetime.now()
    for r in rows:
        cache.upsert_quote(
            symbol=r["symbol"], ts=now, price=r["price"] or 0,
            change=r["change"] or 0, volume=r["volume"] or 0,
            day_high=r["day_high"] or 0, day_low=r["day_low"] or 0,
            fetched_at=now,
        )
        # Also upsert the symbol with sector if available
        if r.get("sector"):
            cache.upsert_symbol(r["symbol"], r.get("name") or r["symbol"], r["sector"], None)
    print(f"  -> {len(rows)} quotes upserted")

    print("\n[2/4] Refreshing index snapshot (KSE-100/30/All-Share)...")
    try:
        indices = await client.fetch_indices()
        for idx in indices:
            cache.upsert_index(idx["code"], idx["value"], idx["change"],
                               idx["change_pct"], idx["refreshed_at"])
        for idx in indices:
            print(f"  {idx['code']:8s} {idx['value']:>12,.2f}  ({idx['change_pct']:+.2f}%)")
    except Exception as e:
        print(f"  index refresh failed: {e}")

    print("\n[3/4] Fetching announcements (latest 50, may include earnings/dividends)...")
    try:
        ann_html = await client.fetch_announcements()
        anns = parse_announcements(ann_html)
        for a in anns:
            cache.upsert_announcement(a)
        print(f"  -> {len(anns)} announcements cached")
    except Exception as e:
        import traceback
        print(f"  announcements failed: {e}")
        traceback.print_exc()

    print("\n[4/4] Fetching history + fundamentals for shortlist symbols...")
    all_symbols = sorted({s for sublist in UNIVERSE_BY_SECTOR.values() for s in sublist})
    print(f"  shortlist: {len(all_symbols)} names")
    succeeded = 0
    for sym in all_symbols:
        try:
            # Historical OHLC (no date params → returns full available range)
            hist_payload = await client.fetch_historical(sym)
            bars = parse_historical(sym, hist_payload)
            if bars:
                cache.upsert_bars(bars)
                succeeded += 1
        except Exception as e:
            print(f"    {sym}: history failed — {e!r}")
        try:
            # Fundamentals + company profile (separate endpoints)
            profile_html = await client.fetch_profile(sym)
            profile = parse_profile(sym, profile_html)
            if profile and profile.sector:
                cache.upsert_symbol(sym, profile.name or sym,
                                    profile.sector, profile.listed_shares)
        except Exception as e:
            print(f"    {sym}: profile failed — {e!r}")
        try:
            fin_html = await client.fetch_financials(sym)
            fund = parse_financials(sym, fin_html)
            if fund:
                cache.upsert_fundamentals(
                    symbol=sym,
                    eps=fund.eps,
                    pe=fund.pe,
                    pb=fund.pb,
                    div_yield=fund.div_yield,
                    payout=fund.payout,
                    roe=fund.roe,
                )
        except Exception as e:
            print(f"    {sym}: financials failed — {e!r}")
    print(f"  -> {succeeded}/{len(all_symbols)} histories cached")


def analyze(cache: Cache):
    print("\n" + "=" * 72)
    print("  SECTOR SUMMARIES")
    print("=" * 72)
    sectors = list(UNIVERSE_BY_SECTOR.keys())
    sector_data = {}
    for s in sectors:
        summary = sector_summary(cache, s)
        sector_data[s] = summary
        if summary.get("n", 0) > 0:
            print(f"\n  {s}")
            print(f"    n={summary['n']}, median P/E={summary.get('median_pe')}, "
                  f"avg change_pct={summary.get('avg_change_pct'):+.2f}%, "
                  f"pct above SMA200={summary.get('pct_above_sma200')}%")
            tops = summary.get("top_5_by_change", [])
            if tops:
                print(f"    leaders: " + ", ".join(
                    f"{m['symbol']} ({m['change_pct']:+.2f}%)" for m in tops[:3]
                ))

    # Pull recent announcements per symbol for context
    print("\n" + "=" * 72)
    print("  RECENT ANNOUNCEMENTS (last ~50 across whole market)")
    print("=" * 72)
    rows = cache.conn.execute(
        "SELECT symbol, title, category, posted_at, url FROM announcements ORDER BY posted_at DESC LIMIT 50"
    ).fetchall()
    by_symbol = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(dict(r))
    for sym, items in sorted(by_symbol.items()):
        for item in items[:1]:  # latest only per symbol
            t = item.get("title") or ""
            print(f"  {sym:8s}  {item['posted_at']:>16s}  {t[:60]}")
    return sector_data, by_symbol


def screen_per_sector(cache: Cache, sector: str) -> list[dict]:
    """Apply value+momentum filters per sector, return ranked candidates."""
    # First: pure-quality filter (positive EPS, reasonable PE, above-trend)
    out = screen(cache, FilterSpec(
        sector=sector,
        eps_min=0.5,        # require profitability
        pe_max=30,          # not crazy expensive
        rsi_min=40,         # not deeply oversold
        rsi_max=75,         # not blow-off top
        above_sma200=True,  # in primary uptrend
        sort_by="change_pct",
        desc=True,
        limit=10,
    ))
    return out


def main():
    Path("data").mkdir(exist_ok=True)
    cache = Cache(DB_PATH)
    client = PSXClient()

    async def run():
        try:
            await fetch_and_seed(cache, client)
        finally:
            await client.close()

    asyncio.run(run())
    sector_data, ann_by_symbol = analyze(cache)

    print("\n" + "=" * 72)
    print("  PER-SECTOR SCREENS (value + momentum)")
    print("=" * 72)
    for sector in UNIVERSE_BY_SECTOR.keys():
        rows = screen_per_sector(cache, sector)
        if not rows:
            continue
        print(f"\n  {sector}")
        for r in rows[:5]:
            anns = ann_by_symbol.get(r["symbol"], [])
            ann_hint = anns[0]["title"][:50] if anns else ""
            print(f"    {r['symbol']:8s} P/E={r['pe']:>6.2f}  RSI={r['rsi14']:>5.1f}  "
                  f"chg={r['change_pct']:>+5.2f}%  price={r['price']:>8.2f}  | {ann_hint}")

    # Dump everything to JSON for follow-up analysis
    out_path = "data/research_picks_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "sectors": {k: v for k, v in sector_data.items()},
            "announcements_by_symbol": {k: v for k, v in ann_by_symbol.items()},
            "screens": {
                s: screen_per_sector(cache, s) for s in UNIVERSE_BY_SECTOR.keys()
            },
        }, f, indent=2, default=str)
    print(f"\n  full output -> {out_path}")


if __name__ == "__main__":
    main()
