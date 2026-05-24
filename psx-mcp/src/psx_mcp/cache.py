from __future__ import annotations
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Iterable

from .models import Bar, Announcement


SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
  symbol TEXT PRIMARY KEY, name TEXT, sector TEXT,
  listed_shares INTEGER, refreshed_at TEXT
);
CREATE TABLE IF NOT EXISTS quotes (
  symbol TEXT, ts TEXT, price REAL, change REAL,
  volume INTEGER, day_high REAL, day_low REAL,
  fetched_at TEXT, PRIMARY KEY(symbol, ts)
);
CREATE TABLE IF NOT EXISTS bars_daily (
  symbol TEXT, date TEXT, open REAL, high REAL, low REAL,
  close REAL, volume INTEGER, PRIMARY KEY(symbol, date)
);
CREATE TABLE IF NOT EXISTS announcements (
  id TEXT PRIMARY KEY, symbol TEXT, posted_at TEXT,
  title TEXT, category TEXT, url TEXT, body TEXT
);
CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT PRIMARY KEY, eps REAL, pe REAL, pb REAL,
  div_yield REAL, payout REAL, roe REAL, refreshed_at TEXT
);
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, source TEXT, posted_at TEXT,
  title TEXT, url TEXT, symbols TEXT
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol_date ON bars_daily(symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_anns_symbol_posted ON announcements(symbol, posted_at DESC);
"""


def _iso(v) -> str:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


class Cache:
    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def list_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return [r["name"] for r in rows]

    # ---- symbols ----
    def upsert_symbol(self, symbol: str, name: str, sector: Optional[str],
                      listed_shares: Optional[int]) -> None:
        self.conn.execute(
            """INSERT INTO symbols(symbol, name, sector, listed_shares, refreshed_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET
                 name=excluded.name, sector=excluded.sector,
                 listed_shares=excluded.listed_shares,
                 refreshed_at=excluded.refreshed_at""",
            (symbol.upper(), name, sector, listed_shares, _iso(datetime.now())),
        )
        self.conn.commit()

    def get_symbol(self, symbol: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM symbols WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
        return dict(r) if r else None

    def all_symbols(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM symbols ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]

    def symbols_master_age_seconds(self) -> Optional[float]:
        r = self.conn.execute("SELECT MAX(refreshed_at) AS t FROM symbols").fetchone()
        if not r or not r["t"]:
            return None
        t = datetime.fromisoformat(r["t"])
        return (datetime.now() - t).total_seconds()

    # ---- quotes ----
    def upsert_quote(self, *, symbol: str, ts: datetime, price: float,
                     change: float, volume: int, day_high: float, day_low: float,
                     fetched_at: datetime) -> None:
        self.conn.execute(
            """INSERT INTO quotes(symbol, ts, price, change, volume, day_high, day_low, fetched_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol, ts) DO UPDATE SET
                 price=excluded.price, change=excluded.change, volume=excluded.volume,
                 day_high=excluded.day_high, day_low=excluded.day_low,
                 fetched_at=excluded.fetched_at""",
            (symbol.upper(), _iso(ts), price, change, volume, day_high, day_low, _iso(fetched_at)),
        )
        self.conn.commit()

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        r = self.conn.execute(
            """SELECT * FROM quotes WHERE symbol=? ORDER BY ts DESC LIMIT 1""",
            (symbol.upper(),),
        ).fetchone()
        return dict(r) if r else None

    def is_quote_fresh(self, symbol: str, ttl_seconds: int) -> bool:
        r = self.get_latest_quote(symbol)
        if not r:
            return False
        fetched_at = datetime.fromisoformat(r["fetched_at"])
        return (datetime.now() - fetched_at).total_seconds() < ttl_seconds

    # ---- bars ----
    def upsert_bars(self, bars: Iterable[Bar]) -> None:
        rows = [
            (b.symbol.upper(), _iso(b.date), b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        self.conn.executemany(
            """INSERT INTO bars_daily(symbol, date, open, high, low, close, volume)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(symbol, date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume""",
            rows,
        )
        self.conn.commit()

    def get_bars(self, symbol: str, from_date: date, to_date: date) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM bars_daily
               WHERE symbol=? AND date BETWEEN ? AND ?
               ORDER BY date ASC""",
            (symbol.upper(), _iso(from_date), _iso(to_date)),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["date"] = date.fromisoformat(d["date"])
            out.append(d)
        return out

    def fifty_two_week(self, symbol: str) -> tuple[float, float]:
        """Return (highest high, lowest low) over the last 252 trading rows for symbol.

        Falls back to (0.0, 0.0) if no history is cached.
        """
        row = self.conn.execute(
            """
            SELECT MAX(high) AS hi, MIN(low) AS lo FROM (
                SELECT high, low FROM bars_daily
                WHERE symbol = ?
                ORDER BY date DESC
                LIMIT 252
            )
            """,
            (symbol.upper(),),
        ).fetchone()
        hi, lo = (row["hi"], row["lo"]) if row else (None, None)
        return (
            float(hi) if hi is not None else 0.0,
            float(lo) if lo is not None else 0.0,
        )

    def bars_latest_date(self, symbol: str) -> Optional[date]:
        r = self.conn.execute(
            "SELECT MAX(date) AS d FROM bars_daily WHERE symbol=?",
            (symbol.upper(),),
        ).fetchone()
        if not r or not r["d"]:
            return None
        return date.fromisoformat(r["d"])

    # ---- announcements ----
    def upsert_announcement(self, a: Announcement) -> None:
        self.conn.execute(
            """INSERT INTO announcements(id, symbol, posted_at, title, category, url, body)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 symbol=excluded.symbol, posted_at=excluded.posted_at,
                 title=excluded.title, category=excluded.category,
                 url=excluded.url, body=excluded.body""",
            (a.id, a.symbol, _iso(a.posted_at), a.title, a.category, a.url, a.body),
        )
        self.conn.commit()

    def get_announcements(self, *, symbol: Optional[str] = None,
                          since: Optional[datetime] = None) -> list[dict]:
        sql = "SELECT * FROM announcements WHERE 1=1"
        args: list = []
        if symbol:
            sql += " AND symbol=?"
            args.append(symbol.upper())
        if since:
            sql += " AND posted_at >= ?"
            args.append(_iso(since))
        sql += " ORDER BY posted_at DESC"
        rows = self.conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["posted_at"] = datetime.fromisoformat(d["posted_at"])
            out.append(d)
        return out

    # ---- fundamentals ----
    def upsert_fundamentals(self, *, symbol: str, eps, pe, pb, div_yield,
                            payout, roe) -> None:
        self.conn.execute(
            """INSERT INTO fundamentals(symbol, eps, pe, pb, div_yield, payout, roe, refreshed_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET
                 eps=excluded.eps, pe=excluded.pe, pb=excluded.pb,
                 div_yield=excluded.div_yield, payout=excluded.payout,
                 roe=excluded.roe, refreshed_at=excluded.refreshed_at""",
            (symbol.upper(), eps, pe, pb, div_yield, payout, roe, _iso(datetime.now())),
        )
        self.conn.commit()

    def get_fundamentals(self, symbol: str) -> Optional[dict]:
        r = self.conn.execute(
            "SELECT * FROM fundamentals WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
        return dict(r) if r else None

    def fundamentals_age_seconds(self, symbol: str) -> Optional[float]:
        f = self.get_fundamentals(symbol)
        if not f or not f.get("refreshed_at"):
            return None
        t = datetime.fromisoformat(f["refreshed_at"])
        return (datetime.now() - t).total_seconds()

    # ---- news ----
    def upsert_news(self, *, id: str, source: str, posted_at: datetime,
                    title: str, url: str, symbols: list[str]) -> None:
        self.conn.execute(
            """INSERT INTO news(id, source, posted_at, title, url, symbols)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 source=excluded.source, posted_at=excluded.posted_at,
                 title=excluded.title, url=excluded.url, symbols=excluded.symbols""",
            (id, source, _iso(posted_at), title, url, ",".join(s.upper() for s in symbols)),
        )
        self.conn.commit()

    def get_news(self, *, symbol: Optional[str] = None,
                 since: Optional[datetime] = None) -> list[dict]:
        sql = "SELECT * FROM news WHERE 1=1"
        args: list = []
        if since:
            sql += " AND posted_at >= ?"
            args.append(_iso(since))
        sql += " ORDER BY posted_at DESC"
        rows = self.conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["posted_at"] = datetime.fromisoformat(d["posted_at"])
            d["symbols"] = [s for s in (d["symbols"] or "").split(",") if s]
            if symbol and symbol.upper() not in d["symbols"]:
                continue
            out.append(d)
        return out
