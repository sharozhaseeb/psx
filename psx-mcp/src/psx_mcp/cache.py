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
CREATE TABLE IF NOT EXISTS indices (
  index_code TEXT PRIMARY KEY,
  value REAL NOT NULL,
  change REAL,
  change_pct REAL,
  refreshed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol_date ON bars_daily(symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_anns_symbol_posted ON announcements(symbol, posted_at DESC);
CREATE TABLE IF NOT EXISTS fundamentals_history (
  symbol TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  eps REAL,
  pe REAL,
  pb REAL,
  div_yield REAL,
  payout REAL,
  roe REAL,
  gross_margin REAL,
  net_income REAL,
  cfo REAL,
  revenue REAL,
  total_assets REAL,
  long_term_debt REAL,
  current_liab REAL,
  current_assets REAL,
  shares_outstanding REAL,
  source_url TEXT,
  refreshed_at TEXT NOT NULL,
  PRIMARY KEY(symbol, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_fundh_symbol_year
  ON fundamentals_history(symbol, fiscal_year DESC);
CREATE TABLE IF NOT EXISTS indices_history (
  index_code TEXT NOT NULL,
  bar_date TEXT NOT NULL,
  close REAL NOT NULL,
  volume REAL,
  PRIMARY KEY(index_code, bar_date)
);
CREATE INDEX IF NOT EXISTS idx_idxh_code_date
  ON indices_history(index_code, bar_date);
CREATE TABLE IF NOT EXISTS dividends (
  announcement_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  ex_date TEXT,
  announcement_date TEXT,
  payout_type TEXT,
  per_share REAL,
  bonus_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_div_symbol_exdate
  ON dividends(symbol, ex_date DESC);
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

    def top_movers(self, n: int = 5) -> dict:
        """Return top gainers, losers, and volume leaders from latest quotes.

        change_pct is computed as ``change / (price - change) * 100`` using the
        prev_close-based convention; rows where ``price <= 0`` or
        ``prev_close <= 0`` are skipped. Each entry is a dict with keys
        ``symbol``, ``name``, ``price``, ``change_pct``, ``volume``.
        """
        rows = self.conn.execute(
            """SELECT q.symbol, q.price, q.change, q.volume, s.name
               FROM quotes q LEFT JOIN symbols s ON s.symbol=q.symbol
               WHERE q.ts = (SELECT MAX(ts) FROM quotes q2 WHERE q2.symbol=q.symbol)
               AND q.price > 0"""
        ).fetchall()
        movers = []
        for r in rows:
            d = dict(r)
            prev_close = d["price"] - d["change"]
            if prev_close <= 0:
                continue
            change_pct = d["change"] / prev_close * 100
            movers.append({
                "symbol": d["symbol"],
                "name": d.get("name"),
                "price": d["price"],
                "change_pct": change_pct,
                "volume": d["volume"],
            })
        gainers = sorted(movers, key=lambda m: m["change_pct"], reverse=True)[:n]
        losers = sorted(movers, key=lambda m: m["change_pct"])[:n]
        by_volume = sorted(movers, key=lambda m: m["volume"], reverse=True)[:n]
        return {"gainers": gainers, "losers": losers, "by_volume": by_volume}

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

    def closes_for(self, symbol: str, limit: Optional[int] = None) -> list[float]:
        """Return cached close prices for symbol, oldest first.
        If limit is given, returns the most-recent `limit` closes (still oldest-first within window)."""
        sql = "SELECT close FROM bars_daily WHERE symbol = ? ORDER BY date ASC"
        params: tuple = (symbol.upper(),)
        if limit is not None:
            sql = ("SELECT close FROM (SELECT close, date FROM bars_daily "
                   "WHERE symbol = ? ORDER BY date DESC LIMIT ?) ORDER BY date ASC")
            params = (symbol.upper(), limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [r["close"] for r in rows]

    def closes_for_many(self, symbols: list[str]) -> dict[str, list[float]]:
        """Return {symbol: [closes_ascending], ...} for the given symbols.
        Symbols with no bars get an empty list (never missing-key)."""
        syms_upper = [s.upper() for s in symbols]
        if not syms_upper:
            return {}
        placeholders = ",".join("?" * len(syms_upper))
        rows = self.conn.execute(
            f"""SELECT symbol, close FROM bars_daily
                WHERE symbol IN ({placeholders})
                ORDER BY symbol ASC, date ASC""",
            syms_upper,
        ).fetchall()
        out: dict[str, list[float]] = {s: [] for s in syms_upper}
        for r in rows:
            out[r["symbol"]].append(r["close"])
        return out

    def screen_candidates(self, where_clause: str, params: list) -> list[dict]:
        """Return [{symbol, name, sector, price, change, volume, pe, eps, pb, div_yield, payout, roe}]
        for the latest-quote-per-symbol JOIN, filtered by an arbitrary parameterized WHERE clause.

        SECURITY: where_clause is treated as trusted SQL — callers MUST never include
        user input directly; only the `params` list carries user-provided values. The
        screener uses a closed-set of column names from FilterSpec, so this is safe.
        """
        sql = f"""
            SELECT s.symbol, s.name, s.sector,
                   q.price, q.change, q.volume,
                   f.pe, f.eps, f.pb, f.div_yield, f.payout, f.roe
            FROM symbols s
            JOIN quotes q ON q.symbol = s.symbol
                AND q.ts = (SELECT MAX(ts) FROM quotes q2 WHERE q2.symbol = s.symbol)
            LEFT JOIN fundamentals f ON f.symbol = s.symbol
            WHERE {where_clause if where_clause else "1=1"}
            LIMIT 500
        """
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

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

    # ---- fundamentals history (multi-year) ----
    def upsert_fundamentals_history(self, *, symbol: str, fiscal_year: int,
                                    eps, pe, pb, div_yield, payout, roe,
                                    gross_margin, net_income, cfo, revenue,
                                    total_assets, long_term_debt,
                                    current_liab, current_assets, shares_outstanding,
                                    source_url, refreshed_at) -> None:
        self.conn.execute(
            """INSERT INTO fundamentals_history
               (symbol, fiscal_year, eps, pe, pb, div_yield, payout, roe,
                gross_margin, net_income, cfo, revenue,
                total_assets, long_term_debt, current_liab,
                current_assets, shares_outstanding, source_url, refreshed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol, fiscal_year) DO UPDATE SET
                 eps=excluded.eps, pe=excluded.pe, pb=excluded.pb,
                 div_yield=excluded.div_yield, payout=excluded.payout, roe=excluded.roe,
                 gross_margin=excluded.gross_margin,
                 net_income=excluded.net_income, cfo=excluded.cfo, revenue=excluded.revenue,
                 total_assets=excluded.total_assets,
                 long_term_debt=excluded.long_term_debt, current_liab=excluded.current_liab,
                 current_assets=excluded.current_assets,
                 shares_outstanding=excluded.shares_outstanding,
                 source_url=excluded.source_url, refreshed_at=excluded.refreshed_at""",
            (symbol.upper(), fiscal_year, eps, pe, pb, div_yield, payout, roe,
             gross_margin, net_income, cfo, revenue,
             total_assets, long_term_debt, current_liab,
             current_assets, shares_outstanding, source_url, _iso(refreshed_at)),
        )
        self.conn.commit()

    def get_fundamentals_history(self, symbol: str) -> list[dict]:
        """Return all cached fiscal-year snapshots for symbol, newest year first."""
        rows = self.conn.execute(
            "SELECT * FROM fundamentals_history WHERE symbol=? ORDER BY fiscal_year DESC",
            (symbol.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]

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

    # ---- indices ----
    def upsert_index(self, code: str, value: float, change: Optional[float],
                     change_pct: Optional[float], refreshed_at: str) -> None:
        self.conn.execute(
            """INSERT INTO indices(index_code, value, change, change_pct, refreshed_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(index_code) DO UPDATE SET
                 value=excluded.value, change=excluded.change,
                 change_pct=excluded.change_pct,
                 refreshed_at=excluded.refreshed_at""",
            (code.upper(), value, change, change_pct, refreshed_at),
        )
        self.conn.commit()

    def index_snapshot(self) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT index_code, value, change, change_pct, refreshed_at FROM indices"
        ).fetchall()
        return {
            r["index_code"]: {
                "value": r["value"],
                "change": r["change"],
                "change_pct": r["change_pct"],
                "refreshed_at": r["refreshed_at"],
            }
            for r in rows
        }

    # ---- indices history (EOD bars per index) ----
    def upsert_index_bar(self, *, index_code: str, bar_date,
                         close: float, volume) -> None:
        self.conn.execute(
            """INSERT INTO indices_history (index_code, bar_date, close, volume)
               VALUES(?,?,?,?)
               ON CONFLICT(index_code, bar_date) DO UPDATE SET
                 close=excluded.close, volume=excluded.volume""",
            (index_code, _iso(bar_date), close, volume),
        )
        self.conn.commit()

    def upsert_index_bars_bulk(self, index_code: str,
                               bars: list[dict]) -> int:
        """bars: [{bar_date: date, close: float, volume: float|None}, ...].
        Returns count of rows passed in (per-call, NOT connection-cumulative)."""
        self.conn.executemany(
            """INSERT INTO indices_history (index_code, bar_date, close, volume)
               VALUES(?,?,?,?)
               ON CONFLICT(index_code, bar_date) DO UPDATE SET
                 close=excluded.close, volume=excluded.volume""",
            [(index_code, _iso(b["bar_date"]), b["close"], b.get("volume")) for b in bars],
        )
        self.conn.commit()
        return len(bars)

    def get_index_history(self, index_code: str,
                          since: Optional[str] = None) -> list[dict]:
        """Return all (or since onward) EOD bars for an index, oldest first.
        `since` is a YYYY-MM-DD string."""
        if since:
            rows = self.conn.execute(
                """SELECT * FROM indices_history WHERE index_code=? AND bar_date>=?
                   ORDER BY bar_date ASC""",
                (index_code, since),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM indices_history WHERE index_code=? ORDER BY bar_date ASC",
                (index_code,),
            ).fetchall()
        return [dict(r) for r in rows]

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

    # ---- dividends ----
    def upsert_dividend(self, *, symbol: str, ex_date, announcement_date,
                        payout_type: str, per_share, bonus_pct,
                        announcement_id: str) -> None:
        self.conn.execute(
            """INSERT INTO dividends
               (announcement_id, symbol, ex_date, announcement_date,
                payout_type, per_share, bonus_pct)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(announcement_id) DO UPDATE SET
                 ex_date=excluded.ex_date,
                 announcement_date=excluded.announcement_date,
                 payout_type=excluded.payout_type,
                 per_share=excluded.per_share, bonus_pct=excluded.bonus_pct""",
            (announcement_id, symbol.upper(), _iso(ex_date), _iso(announcement_date),
             payout_type, per_share, bonus_pct),
        )
        self.conn.commit()

    def get_dividend_history(self, symbol: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM dividends WHERE symbol=?
               ORDER BY COALESCE(ex_date, announcement_date) DESC""",
            (symbol.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]
