"""Cross-sectional / sector analytics helpers."""
from __future__ import annotations
from typing import Optional
import numpy as np
from psx_mcp.screener import sector_summary


def z_score(value: float, universe: list[float]) -> Optional[float]:
    """Z-score of `value` within `universe`. None if universe < 2 or stdev = 0."""
    if value is None or not universe or len(universe) < 2:
        return None
    arr = np.array([v for v in universe if v is not None], dtype=float)
    if len(arr) < 2:
        return None
    sd = float(arr.std(ddof=1))
    if sd == 0:
        return None
    return float((value - arr.mean()) / sd)


def percentile_rank(value: float, universe: list[float]) -> Optional[float]:
    """Percent of universe strictly less than `value`. 0 = at-or-below min;
    100 = at-or-above max. Result is clamped to [0, 100] even if `value` lies
    outside the universe range.

    For n=1 (degenerate universe of single element), returns 50.0 by convention."""
    if value is None or not universe:
        return None
    arr = [v for v in universe if v is not None]
    if not arr:
        return None
    n = len(arr)
    if n == 1:
        return 50.0
    less = sum(1 for v in arr if v < value)
    raw = less / (n - 1) * 100.0
    return float(max(0.0, min(100.0, raw)))


def sector_dispersion(cache, sector: str, metric: str = "pe") -> dict:
    """Dispersion of `metric` across symbols in `sector`. metric in {pe, eps, change_pct}.

    Returns {n, mean, median, stdev, min, max, range_pct, top_z_scores}.
    Useful for spotting high-dispersion sectors (alpha opportunity) vs
    low-dispersion (passive better)."""
    # Pull all symbols in this sector via screener.sector_summary
    summary = sector_summary(cache, sector)
    if summary.get("n", 0) == 0:
        return {"sector": sector, "metric": metric, "n": 0, "mean": None,
                "median": None, "stdev": None, "min": None, "max": None,
                "range_pct": None, "top_z_scores": []}

    # We re-pull the raw rows: sector_summary's top_5/bottom_5 are limited views.
    # Use the screener directly to enumerate sector members.
    from psx_mcp.screener import screen, FilterSpec
    rows = screen(cache, FilterSpec(sector=sector, limit=500))
    values = [r.get(metric) for r in rows if r.get(metric) is not None]
    if not values:
        return {"sector": sector, "metric": metric, "n": 0, "mean": None,
                "median": None, "stdev": None, "min": None, "max": None,
                "range_pct": None, "top_z_scores": []}
    arr = np.array(values, dtype=float)
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1)) if len(arr) > 1 else None
    mn = float(arr.min())
    mx = float(arr.max())
    range_pct = (mx / mn - 1.0) * 100.0 if mn > 0 else None
    # Top-z entries (highest |z|, signed) — symbol + value
    top_z = []
    if sd and sd > 0:
        for r in rows:
            v = r.get(metric)
            if v is None:
                continue
            z = (v - mean) / sd
            top_z.append({"symbol": r["symbol"], "value": v, "z_score": float(z)})
        top_z.sort(key=lambda e: abs(e["z_score"]), reverse=True)
        top_z = top_z[:5]
    return {"sector": sector, "metric": metric, "n": len(values),
            "mean": mean, "median": float(np.median(arr)), "stdev": sd,
            "min": mn, "max": mx, "range_pct": range_pct,
            "top_z_scores": top_z}


def sector_relative_strength(cache, sectors: list[str],
                              window_days: int = 60) -> list[dict]:
    """Per sector, compute (sector avg return) - (KSE-100 return) over the
    given window. Returns sector-by-sector RS sorted descending.

    Sector avg return = mean of `closes_for(sym)[-1] / closes_for(sym)[-window-1] - 1`
    for each symbol whose sector matches.
    """
    import pandas as pd
    idx_rows = cache.get_index_history("KSE100")
    if not idx_rows or len(idx_rows) < window_days + 1:
        return [{"sector": s, "rs_pct": None, "n": 0,
                  "note": "Insufficient index history"} for s in sectors]
    idx_closes = pd.Series([r["close"] for r in idx_rows])
    idx_ret = float(idx_closes.iloc[-1] / idx_closes.iloc[-window_days - 1] - 1.0)

    out = []
    for sector in sectors:
        from psx_mcp.screener import screen, FilterSpec
        members = screen(cache, FilterSpec(sector=sector, limit=500))
        rets = []
        for m in members:
            sym = m["symbol"]
            closes = cache.closes_for(sym)
            if len(closes) <= window_days:
                continue
            try:
                rets.append(closes[-1] / closes[-window_days - 1] - 1.0)
            except (IndexError, ZeroDivisionError):
                continue
        if not rets:
            out.append({"sector": sector, "rs_pct": None, "n": 0,
                         "index_return_pct": idx_ret * 100.0})
            continue
        sector_avg = sum(rets) / len(rets)
        out.append({
            "sector": sector,
            "rs_pct": float((sector_avg - idx_ret) * 100.0),
            "sector_return_pct": float(sector_avg * 100.0),
            "index_return_pct": float(idx_ret * 100.0),
            "n": len(rets),
        })
    out.sort(key=lambda r: (r["rs_pct"] is None, -(r["rs_pct"] or 0)))
    return out
