"""Cross-sectional ranking helpers.
Pulls from cache through screener.sector_summary; does not query SQL directly."""
from __future__ import annotations
from typing import Literal
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
