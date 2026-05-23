from __future__ import annotations
from datetime import date
from typing import Optional

import pandas as pd
from .cache import Cache


def bars_df(cache: Cache, symbol: str, lookback_days: int = 250) -> pd.DataFrame:
    """Load all bars for a symbol and return the most-recent `lookback_days * 2` as a DataFrame
    sorted ascending by date with a fresh integer index. Empty DataFrame if no bars cached."""
    rows = cache.get_bars(symbol, date(1970, 1, 1), date.today())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if lookback_days > 0:
        df = df.tail(lookback_days * 2).reset_index(drop=True)
    return df
