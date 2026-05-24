"""Smoke-test backtest. Equal-weight, fixed-hold, no costs."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional


def backtest_simple(closes_by_sym_date: dict[tuple[str, date], float],
                    signals_by_date: dict[date, list[str]],
                    hold_days: int = 63) -> dict:
    """Generate trades from signals; for each signal (date, [symbols]):
      For each symbol with a close on that date, buy at that close,
      sell at the close `hold_days` later (skip if no exit close exists).

    Returns:
      {n_trades, mean_return_pct, median_return_pct, total_return_pct,
       win_rate_pct, trades: [{symbol, entry_date, exit_date, entry, exit, return_pct}]}.
    """
    trades = []
    for sig_date, symbols in sorted(signals_by_date.items()):
        exit_date = sig_date + timedelta(days=hold_days)
        for sym in symbols:
            entry = closes_by_sym_date.get((sym, sig_date))
            if entry is None or entry <= 0:
                continue
            exit_price = closes_by_sym_date.get((sym, exit_date))
            exit_date_used = exit_date
            if exit_price is None:
                found = False
                for delta in range(1, 6):
                    exit_price = closes_by_sym_date.get((sym, exit_date + timedelta(days=delta)))
                    if exit_price is not None:
                        exit_date_used = exit_date + timedelta(days=delta)
                        found = True
                        break
                if not found:
                    continue
            ret_pct = (exit_price / entry - 1.0) * 100.0
            trades.append({
                "symbol": sym, "entry_date": sig_date, "exit_date": exit_date_used,
                "entry": entry, "exit": exit_price, "return_pct": ret_pct,
            })
    if not trades:
        return {"n_trades": 0, "mean_return_pct": None,
                "median_return_pct": None, "total_return_pct": None,
                "win_rate_pct": None, "trades": []}
    rets = sorted(t["return_pct"] for t in trades)
    n = len(rets)
    mean_ret = sum(rets) / n
    median_ret = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    wins = sum(1 for r in rets if r > 0)
    win_rate = 100.0 * wins / n
    total_ret = mean_ret
    return {"n_trades": n, "mean_return_pct": mean_ret,
            "median_return_pct": median_ret, "total_return_pct": total_ret,
            "win_rate_pct": win_rate, "trades": trades}
