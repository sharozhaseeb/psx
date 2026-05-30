"""Pull current data on Shariah-compliant alternatives + MIIETF peers."""
from __future__ import annotations
import asyncio
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd

from psx_mcp.cache import Cache
from psx_mcp.psx_client import PSXClient, parse_historical
from psx_mcp.risk import (
    drawdown_current, drawdown_max,
    volatility_annualized, sharpe, relative_strength,
)

DB = "data/miietf.db"

# Shariah ETFs + canonical KMI-30 large-caps (confirmed Shariah-compliant)
WATCH = [
    ("MIIETF",  "ETF"),
    ("MZNPETF", "ETF"),
    ("MEBL",    "stock - Islamic bank"),
    ("MARI",    "stock - oil & gas"),
    ("OGDC",    "stock - oil & gas"),
    ("PPL",     "stock - oil & gas"),
    ("POL",     "stock - oil & gas"),
    ("LUCK",    "stock - cement"),
    ("FFC",     "stock - fertilizer"),
    ("HUBC",    "stock - power"),
    ("SYS",     "stock - tech"),
]


async def fetch_all():
    cache = Cache(DB)
    client = PSXClient()
    try:
        # KSE100 EOD history for relative_strength
        try:
            kse_bars = await client.fetch_index_eod_history("KSE100")
            if kse_bars:
                cache.upsert_index_bars_bulk("KSE100", kse_bars)
            print(f"KSE100 history: {len(kse_bars)} bars")
        except Exception as e:
            print(f"KSE100 history failed: {e!r}")

        # Per-symbol history
        for sym, _ in WATCH:
            try:
                hp = await client.fetch_historical(sym)
                bars = parse_historical(sym, hp)
                if bars:
                    cache.upsert_bars(bars)
                    print(f"  {sym:8s}: {len(bars)} bars")
            except Exception as e:
                print(f"  {sym:8s}: ERROR {e!r}")
    finally:
        await client.close()
        cache.close()


def analyze():
    cache = Cache(DB)
    print("\n" + "=" * 92)
    print(f"  {'Symbol':<9} {'Type':<22} {'Price':>7} {'52w%':>5} {'1m':>6} {'3m':>6} {'1y':>7} {'Vol':>5} {'MaxDD':>6} {'Sharpe':>6} {'RS-1y':>6}")
    print("=" * 92)

    idx_rows = cache.get_index_history("KSE100")
    idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}

    for sym, kind in WATCH:
        q = cache.get_latest_quote(sym)
        if not q:
            print(f"  {sym:<9} {kind:<22} (no quote)")
            continue

        hi52, lo52 = cache.fifty_two_week(sym)
        pos52 = (q["price"] - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 0

        stock_pairs = cache.closes_for_with_dates(sym)
        if len(stock_pairs) < 60:
            print(f"  {sym:<9} {kind:<22} {q['price']:>7.2f} {pos52:>4.0f}%  (insufficient bars)")
            continue

        stock_by_date = dict(stock_pairs)
        common = sorted(set(stock_by_date) & set(idx_by_date))
        if len(common) < 30:
            print(f"  {sym:<9} {kind:<22} {q['price']:>7.2f} {pos52:>4.0f}%  (no aligned bars)")
            continue

        stock_series = pd.Series([stock_by_date[d] for d in common])
        idx_series = pd.Series([idx_by_date[d] for d in common])

        # Returns
        def ret_over(n):
            if len(stock_series) <= n:
                return None
            return float(stock_series.iloc[-1] / stock_series.iloc[-n - 1] - 1.0) * 100

        ret_1m = ret_over(22)
        ret_3m = ret_over(66)
        ret_1y = ret_over(252)

        vol = volatility_annualized(stock_series) * 100
        sh = sharpe(stock_series, rf_annual=0.125)  # current Pakistan T-bill ~12.5%
        dd_max = drawdown_max(stock_series)["max_drawdown_pct"]
        rs_1y = relative_strength(stock_series, idx_series, window=252)
        rs_1y = rs_1y * 100 if rs_1y is not None else None

        def fmt(v, w, p=1):
            if v is None:
                return f"{'N/A':>{w}}"
            return f"{v:>{w}.{p}f}"

        print(f"  {sym:<9} {kind:<22} "
              f"{q['price']:>7.2f} {pos52:>4.0f}% "
              f"{fmt(ret_1m, 5)} {fmt(ret_3m, 5)} {fmt(ret_1y, 6)} "
              f"{fmt(vol, 4, 0)} {fmt(dd_max, 5, 0)} "
              f"{fmt(sh, 5, 2)} {fmt(rs_1y, 5, 0)}")

    print("\nNote: Sharpe uses rf=12.5% (current PK 12-month T-bill).")
    print("RS-1y = return - KSE-100 return over last 252 trading days (>0 = outperformed).")
    cache.close()


def main():
    Path("data").mkdir(exist_ok=True)
    asyncio.run(fetch_all())
    analyze()


if __name__ == "__main__":
    main()
