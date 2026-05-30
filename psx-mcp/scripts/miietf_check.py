"""One-off: pull MIIETF data + cross-check vs KSE-100."""
from __future__ import annotations
import asyncio
from datetime import datetime, date, timedelta
from pathlib import Path

from psx_mcp.cache import Cache
from psx_mcp.psx_client import (
    PSXClient, parse_market_watch, parse_historical, parse_announcements,
)
from psx_mcp.models import Bar
import pandas as pd

DB = "data/miietf.db"
SYM = "MIIETF"


async def fetch():
    cache = Cache(DB)
    client = PSXClient()
    try:
        print("[1/5] refresh_market...")
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
            if r.get("sector"):
                cache.upsert_symbol(r["symbol"], r.get("name") or r["symbol"],
                                    r["sector"], None)
        print(f"  -> {len(rows)} quotes upserted")

        print("\n[2/5] index snapshot...")
        idx = await client.fetch_indices()
        for i in idx:
            cache.upsert_index(i["code"], i["value"], i["change"],
                               i["change_pct"], i["refreshed_at"])
        for i in idx:
            print(f"  {i['code']:8s} {i['value']:>12,.2f}  ({i['change_pct']:+.2f}%)")

        print(f"\n[3/5] MIIETF historical bars...")
        try:
            hp = await client.fetch_historical(SYM)
            bars = parse_historical(SYM, hp)
            if bars:
                cache.upsert_bars(bars)
                print(f"  -> {len(bars)} bars cached")
            else:
                print("  -> no historical bars returned")
        except Exception as e:
            print(f"  history fetch failed: {e!r}")

        print(f"\n[4/5] KSE100 EOD history...")
        try:
            kse_bars = await client.fetch_index_eod_history("KSE100")
            if kse_bars:
                cache.upsert_index_bars_bulk("KSE100", kse_bars)
            print(f"  -> {len(kse_bars)} KSE-100 EOD bars cached")
        except Exception as e:
            print(f"  KSE100 history failed: {e!r}")

        print(f"\n[5/5] announcements...")
        try:
            ann_html = await client.fetch_announcements()
            anns = parse_announcements(ann_html)
            for a in anns:
                cache.upsert_announcement(a)
            print(f"  -> {len(anns)} latest announcements (market-wide)")
        except Exception as e:
            print(f"  announcements failed: {e!r}")
    finally:
        await client.close()
        cache.close()


def analyze():
    cache = Cache(DB)

    print("\n" + "=" * 72)
    print(f"  MIIETF — current state")
    print("=" * 72)

    q = cache.get_latest_quote(SYM)
    if not q:
        print(f"  No quote cached for {SYM}.")
    else:
        prev = q["price"] - q["change"]
        pct = (q["change"] / prev * 100) if prev > 0 else 0
        hi52, lo52 = cache.fifty_two_week(SYM)
        print(f"  Price          : Rs {q['price']:.2f}")
        print(f"  Change         : {q['change']:+.2f} ({pct:+.2f}%)")
        print(f"  Day H/L        : {q['day_high']:.2f} / {q['day_low']:.2f}")
        print(f"  Volume         : {q['volume']:,}")
        print(f"  52w high/low   : Rs {hi52:.2f} / Rs {lo52:.2f}")
        if hi52 > 0:
            print(f"  Position in 52w: {(q['price'] - lo52) / (hi52 - lo52) * 100:.1f}% of range")

    print("\n  Symbol record:")
    sym = cache.get_symbol(SYM)
    if sym:
        for k, v in sym.items():
            if v is not None:
                print(f"    {k:15s}: {v}")

    print("\n" + "=" * 72)
    print("  Recent MIIETF announcements")
    print("=" * 72)
    anns = cache.get_announcements(symbol=SYM, since=datetime.now() - timedelta(days=30))
    if not anns:
        print(f"  No MIIETF announcements in last 30 days.")
    for a in anns[:5]:
        print(f"  [{a['posted_at'][:10]}] {a['title'][:80]}")
        if a.get("url"):
            print(f"    {a['url']}")

    print("\n" + "=" * 72)
    print("  MIIETF vs KSE-100 (date-aligned)")
    print("=" * 72)
    stock_pairs = cache.closes_for_with_dates(SYM)
    if not stock_pairs:
        print(f"  No MIIETF bars cached. Cannot compare.")
    else:
        stock_by_date = dict(stock_pairs)
        idx_rows = cache.get_index_history("KSE100")
        idx_by_date = {r["bar_date"]: r["close"] for r in idx_rows}
        common = sorted(set(stock_by_date) & set(idx_by_date))
        print(f"  MIIETF bars cached  : {len(stock_pairs)}")
        print(f"  KSE-100 EOD cached  : {len(idx_rows)}")
        print(f"  Aligned trading days: {len(common)}")
        if len(common) >= 30:
            from psx_mcp.risk import (
                relative_strength, drawdown_current, drawdown_max,
                volatility_annualized, sharpe,
            )
            stock_series = pd.Series([stock_by_date[d] for d in common])
            idx_series   = pd.Series([idx_by_date[d]   for d in common])

            # Various windows
            for window in (30, 90, 252):
                if len(common) >= window + 1:
                    rs = relative_strength(stock_series, idx_series, window=window)
                    if rs is not None:
                        stk_ret = float(stock_series.iloc[-1] / stock_series.iloc[-window - 1] - 1.0) * 100
                        idx_ret = float(idx_series.iloc[-1] / idx_series.iloc[-window - 1] - 1.0) * 100
                        print(f"  {window:>3}d : MIIETF {stk_ret:+6.2f}%  KSE-100 {idx_ret:+6.2f}%  RS {rs * 100:+5.2f}%")

            # Risk metrics
            dd_cur = drawdown_current(stock_series)
            dd_max = drawdown_max(stock_series)
            vol = volatility_annualized(stock_series)
            sh = sharpe(stock_series, rf_annual=0.0)
            print(f"\n  MIIETF risk metrics (over {len(common)} aligned bars):")
            print(f"    Current drawdown   : {dd_cur['drawdown_pct']:+.2f}%  (peak Rs {dd_cur['peak']:.2f})")
            print(f"    Max drawdown       : {dd_max['max_drawdown_pct']:+.2f}%")
            print(f"    Annualized vol     : {vol * 100:.2f}%")
            print(f"    Sharpe (rf=0)      : {sh:.2f}" if sh is not None else "    Sharpe: N/A")

            # Tracking error vs KSE-100 (rough proxy for ETF tracking quality)
            stock_rets = stock_series.pct_change().dropna()
            idx_rets = idx_series.pct_change().dropna()
            n_align = min(len(stock_rets), len(idx_rets))
            if n_align >= 30:
                tracking_diff = (stock_rets.iloc[-n_align:].values - idx_rets.iloc[-n_align:].values)
                tracking_std = float(tracking_diff.std(ddof=1) * (252 ** 0.5))
                print(f"    Tracking error vs KSE-100 (annualized): {tracking_std * 100:.2f}%")
                print(f"    (lower = tighter ETF; > 5% = surprising for an index ETF)")

    print("\n" + "=" * 72)
    print("  Quick check: your buy")
    print("=" * 72)
    print(f"  Position size  : 1,000 shares")
    if q:
        notional = 1000 * q['price']
        print(f"  Current value  : Rs {notional:,.0f}  (at today's Rs {q['price']:.2f})")
    print(f"  Bought         : 2026-05-25 (yesterday)")
    cache.close()


def main():
    Path("data").mkdir(exist_ok=True)
    asyncio.run(fetch())
    analyze()


if __name__ == "__main__":
    main()
