from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import operator as _op

import pandas as pd

from .cache import Cache
from .watchlist import WatchlistStore
from .df_utils import bars_df
from .models import AlertRule, AlertHit
from .indicators import rsi, macd, sma, ema, bollinger, last_crosses

_OPS = {
    "<": _op.lt, "<=": _op.le, ">": _op.gt, ">=": _op.ge, "==": _op.eq,
}


def _indicator_series(df: pd.DataFrame, name: str) -> pd.Series:
    if name == "rsi14":
        return rsi(df["close"], 14)
    if name == "macd":
        return macd(df["close"])["macd"]
    if name == "macd_signal":
        return macd(df["close"])["signal"]
    if name.startswith("sma"):
        return sma(df["close"], int(name[3:]))
    if name.startswith("ema"):
        return ema(df["close"], int(name[3:]))
    if name == "bollinger_upper":
        return bollinger(df["close"])["upper"]
    if name == "bollinger_lower":
        return bollinger(df["close"])["lower"]
    raise ValueError(f"unknown indicator: {name}")


def evaluate_rule(cache: Cache, rule: AlertRule) -> Optional[AlertHit]:
    if not rule.active:
        return None
    now = datetime.now()
    cond = rule.condition

    if rule.type == "price":
        q = cache.get_latest_quote(rule.symbol)
        if not q:
            return None
        op = _OPS.get(cond.op)
        if op and op(q["price"], cond.value):
            return AlertHit(
                rule_id=rule.id, symbol=rule.symbol, triggered_at=now,
                message=f"{rule.symbol} price {q['price']} {cond.op} {cond.value}",
                snapshot={"price": q["price"], "threshold": cond.value},
            )
        return None

    if rule.type == "indicator":
        df = bars_df(cache, rule.symbol)
        if df.empty or len(df) < 20:
            return None
        series = _indicator_series(df, cond.indicator or "rsi14")
        latest = float(series.iloc[-1])
        if cond.op in ("crosses_above", "crosses_below"):
            ref = pd.Series([cond.value] * len(series), index=series.index)
            if last_crosses(series, ref, cond.op):
                return AlertHit(
                    rule_id=rule.id, symbol=rule.symbol, triggered_at=now,
                    message=f"{rule.symbol} {cond.indicator} {cond.op} {cond.value} (now {latest:.2f})",
                    snapshot={"indicator": cond.indicator, "value": latest},
                )
            return None
        op = _OPS.get(cond.op)
        if op and op(latest, cond.value):
            return AlertHit(
                rule_id=rule.id, symbol=rule.symbol, triggered_at=now,
                message=f"{rule.symbol} {cond.indicator}={latest:.2f} {cond.op} {cond.value}",
                snapshot={"indicator": cond.indicator, "value": latest},
            )
        return None

    if rule.type == "volume":
        df = bars_df(cache, rule.symbol)
        if df.empty or len(df) < 2:
            return None
        window = cond.lookback_days or 20
        today_vol = float(df["volume"].iloc[-1])
        if len(df) > window:
            avg_vol = float(df["volume"].iloc[-window-1:-1].mean())
        else:
            avg_vol = float(df["volume"].iloc[:-1].mean())
        multiplier = today_vol / avg_vol if avg_vol else 0.0
        op = _OPS.get(cond.op)
        if op and op(multiplier, cond.value):
            return AlertHit(
                rule_id=rule.id, symbol=rule.symbol, triggered_at=now,
                message=f"{rule.symbol} volume {multiplier:.2f}x avg {cond.op} {cond.value}",
                snapshot={"today_volume": today_vol, "avg_volume": avg_vol, "multiplier": multiplier},
            )
        return None

    if rule.type == "announcement":
        since = rule.last_checked or (now - timedelta(days=1))
        anns = cache.get_announcements(symbol=rule.symbol, since=since)
        if anns:
            titles = "; ".join(a["title"] for a in anns[:3])
            return AlertHit(
                rule_id=rule.id, symbol=rule.symbol, triggered_at=now,
                message=f"{rule.symbol} new filings: {titles}",
                snapshot={"count": len(anns), "titles": [a["title"] for a in anns]},
            )
        return None

    return None


def run_alerts(cache: Cache, store: WatchlistStore,
               symbols: Optional[list[str]] = None) -> list[AlertHit]:
    rules = store.list_alert_rules()
    if symbols:
        symset = {s.upper() for s in symbols}
        rules = [r for r in rules if r.symbol in symset]
    hits: list[AlertHit] = []
    now = datetime.now()
    for r in rules:
        h = evaluate_rule(cache, r)
        if h:
            hits.append(h)
        store.mark_checked(r.id, now)
    return hits
