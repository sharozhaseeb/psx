# PSX MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-process Python FastMCP server that exposes PSX research tools (quotes, history, fundamentals, announcements, news) plus an on-demand watchlist-alert scanner, all backed by free PSX endpoints with a SQLite cache.

**Architecture:** One async Python process running FastMCP over HTTP/SSE on `127.0.0.1:8765`. Tools are **async**, calling shared `_impl(...)` helpers that contain the actual logic; tests call the impl helpers directly with isolated cache/store. Clean module boundaries: `psx_client` (network), `cache` (SQLite), `indicators` (pure math), `watchlist` (JSON), `alerts` (rule eval), `symbols` (lookup), `news` (RSS), `df_utils` (shared DataFrame helper).

**Tech Stack:** Python 3.12, uv (dep manager), `mcp[cli]` (FastMCP), `httpx[http2]`, `beautifulsoup4` + `lxml`, `pandas` + `numpy`, `feedparser`, `pydantic>=2`, `structlog`. Dev: `pytest`, `pytest-asyncio`, `respx`.

**Spec reference:** `docs/superpowers/specs/2026-05-23-psx-mcp-design.md`

---

## File Structure (locked in here)

```
psx-mcp/
├── pyproject.toml                      # uv-managed deps
├── README.md
├── server.py                           # FastMCP entrypoint (async tools)
├── run-psx-mcp.ps1                     # Windows launcher
├── .gitignore
├── scripts/
│   ├── capture_fixtures.py             # one-off PSX fixture capture
│   └── capture_rss.py                  # one-off RSS fixture capture
├── src/psx_mcp/
│   ├── __init__.py
│   ├── models.py                       # Pydantic types
│   ├── cache.py                        # SQLite + TTL logic
│   ├── df_utils.py                     # bars→DataFrame helper
│   ├── indicators.py                   # pure-math indicators
│   ├── psx_client.py                   # async httpx scrapers + parsers
│   ├── symbols.py                      # symbol search
│   ├── news.py                         # RSS aggregator
│   ├── watchlist.py                    # JSON config
│   ├── alerts.py                       # rule evaluation
│   └── logging_config.py               # structlog setup
├── data/                               # gitignored
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── fixtures/                       # HTML/JSON snapshots
    ├── test_models.py
    ├── test_cache.py
    ├── test_indicators.py
    ├── test_psx_client.py
    ├── test_symbols.py
    ├── test_news.py
    ├── test_watchlist.py
    ├── test_alerts.py
    ├── test_server.py
    └── test_live.py
```

Each file has one responsibility. `psx_client` is the only module that touches the network. `cache` is the only module that touches SQLite. `indicators` is pure math. Tool bodies in `server.py` are thin `async def` wrappers around `_impl` helpers — tests exercise the impls directly.

---

### Task 1: Project skeleton with uv

**Files:**
- Create: `psx-mcp/pyproject.toml`
- Create: `psx-mcp/.gitignore`
- Create: `psx-mcp/src/psx_mcp/__init__.py`
- Create: `psx-mcp/tests/__init__.py`
- Create: `psx-mcp/tests/conftest.py`
- Create: `psx-mcp/tests/fixtures/.gitkeep`

- [ ] **Step 1: Create the project directory and uv-managed `pyproject.toml`**

Working directory throughout this plan: `C:\Users\pc\work\stocks\psx-mcp\`

`pyproject.toml`:
```toml
[project]
name = "psx-mcp"
version = "0.1.0"
description = "MCP server for Pakistan Stock Exchange (PSX) research & on-demand alerts"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.2.0",
    "httpx[http2]>=0.27.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "feedparser>=6.0.10",
    "pydantic>=2.6.0",
    "structlog>=24.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "respx>=0.21.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/psx_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-q"
```

`.gitignore`:
```
data/
__pycache__/
*.pyc
.pytest_cache/
.venv/
*.egg-info/
dist/
build/
```

`src/psx_mcp/__init__.py`: empty file.
`tests/__init__.py`: empty file.
`tests/fixtures/.gitkeep`: empty file.

`tests/conftest.py`:
```python
import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 2: Install deps and verify import**

Run (from `psx-mcp/`):
```powershell
uv sync --extra dev
uv run python -c "import mcp, httpx, bs4, pandas, feedparser, pydantic, structlog; print('ok')"
```
Expected: `ok` printed, no errors.

- [ ] **Step 3: Verify pytest collects (empty) suite**

Run:
```powershell
uv run pytest
```
Expected: `no tests ran`, exit 0.

- [ ] **Step 4: Commit**

```powershell
cd C:\Users\pc\work\stocks
git add psx-mcp/
git commit -m "feat(psx-mcp): project skeleton with uv"
```

---

### Task 2: Pydantic models — the type contracts

**Files:**
- Create: `psx-mcp/src/psx_mcp/models.py`
- Create: `psx-mcp/tests/test_models.py`

**Note on Pydantic v2 validators:** validators must be a **classmethod decorated with `@field_validator(...)`**. Lambdas wrapped via `field_validator("x")(lambda cls, v: ...)` raise `PydanticUserError: @field_validator should be used with classmethod`. Pattern used throughout this file: a single shared classmethod per model that uppercases the symbol.

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`:
```python
from datetime import datetime, date
import pytest
from pydantic import ValidationError

from psx_mcp.models import (
    Quote, Bar, SymbolMatch, MarketSummary, Mover,
    CompanyInfo, Fundamentals, FinancialStatement, Announcement, NewsItem,
    WatchEntry, AlertRule, AlertCondition, AlertHit, ToolError,
    Disclaimer, DEFAULT_DISCLAIMER,
)


def test_quote_round_trip():
    q = Quote(
        symbol="LUCK", price=750.5, change=12.3, change_pct=1.67,
        volume=1_250_000, day_high=755.0, day_low=738.0,
        week52_high=900.0, week52_low=600.0,
        timestamp=datetime(2026, 5, 23, 11, 30),
    )
    assert q.symbol == "LUCK"
    assert q.disclaimer == DEFAULT_DISCLAIMER


def test_symbol_uppercased():
    q = Quote(
        symbol="luck", price=1, change=0, change_pct=0, volume=0,
        day_high=0, day_low=0, week52_high=0, week52_low=0,
        timestamp=datetime.now(),
    )
    assert q.symbol == "LUCK"


def test_announcement_accepts_none_symbol():
    a = Announcement(id="x", symbol=None, posted_at=datetime.now(), title="t")
    assert a.symbol is None


def test_bar_validates_ohlc():
    b = Bar(symbol="LUCK", date=date(2026, 5, 23), open=100, high=105, low=99, close=104, volume=1000)
    assert b.high >= b.close >= b.low


def test_alert_rule_valid():
    rule = AlertRule(
        id="luck-rsi-oversold",
        symbol="LUCK",
        type="indicator",
        condition=AlertCondition(indicator="rsi14", op="<", value=30),
        active=True,
        created_at=date(2026, 5, 23),
    )
    assert rule.active


def test_alert_rule_rejects_unknown_op():
    with pytest.raises(ValidationError):
        AlertCondition(indicator="rsi14", op="<<", value=30)


def test_financial_statement_round_trip():
    fs = FinancialStatement(
        symbol="LUCK", period="annual", period_end=date(2025, 6, 30),
        line_items={"Revenue": 100.0, "NetIncome": 20.0},
    )
    assert fs.line_items["Revenue"] == 100.0


def test_tool_error_shape():
    err = ToolError(code="UPSTREAM_5XX", message="PSX returned 503", symbol="LUCK")
    assert err.code == "UPSTREAM_5XX"


def test_default_disclaimer_text():
    assert "not investment advice" in DEFAULT_DISCLAIMER.lower()
    assert "delayed" in DEFAULT_DISCLAIMER.lower()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError or ModuleNotFoundError.

- [ ] **Step 3: Implement `models.py`**

`src/psx_mcp/models.py`:
```python
from __future__ import annotations
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

DEFAULT_DISCLAIMER = (
    "Informational only — not investment advice. "
    "Data is 15+ min delayed; verify before trading."
)


class Disclaimer(BaseModel):
    disclaimer: str = Field(default=DEFAULT_DISCLAIMER)


class Quote(Disclaimer):
    symbol: str
    price: float
    change: float
    change_pct: float
    volume: int
    day_high: float
    day_low: float
    week52_high: float
    week52_low: float
    timestamp: datetime
    stale: bool = False
    summary: Optional[str] = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class Bar(BaseModel):
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class SymbolMatch(BaseModel):
    symbol: str
    name: str
    sector: Optional[str] = None
    score: float = 1.0

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class SectorChange(BaseModel):
    sector: str
    change_pct: float


class MarketSummary(Disclaimer):
    kse100: float
    kse100_change: float
    kse30: Optional[float] = None
    kse30_change: Optional[float] = None
    allshr: Optional[float] = None
    allshr_change: Optional[float] = None
    sectors: list[SectorChange] = []
    timestamp: datetime
    stale: bool = False
    summary: Optional[str] = None


class Mover(BaseModel):
    symbol: str
    name: Optional[str] = None
    price: float
    change_pct: float
    volume: int

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class CompanyInfo(Disclaimer):
    symbol: str
    name: str
    sector: Optional[str] = None
    listed_shares: Optional[int] = None
    free_float: Optional[int] = None
    profile: Optional[str] = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class Fundamentals(Disclaimer):
    symbol: str
    eps: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    div_yield: Optional[float] = None
    payout: Optional[float] = None
    roe: Optional[float] = None
    refreshed_at: Optional[datetime] = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class FinancialStatement(BaseModel):
    symbol: str
    period: Literal["annual", "quarterly"]
    period_end: date
    line_items: dict[str, float]

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class Announcement(BaseModel):
    id: str
    symbol: Optional[str] = None
    posted_at: datetime
    title: str
    category: Optional[str] = None
    url: Optional[str] = None
    body: Optional[str] = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        if v is None:
            return v
        return v.strip().upper() if isinstance(v, str) else v


class NewsItem(BaseModel):
    id: str
    source: str
    posted_at: datetime
    title: str
    url: str
    symbols: list[str] = []

    @field_validator("symbols")
    @classmethod
    def _upper_symbols(cls, v):
        return [s.upper() for s in v]


class WatchEntry(BaseModel):
    symbol: str
    notes: Optional[str] = None
    added_at: date

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


Operator = Literal["<", "<=", ">", ">=", "==", "crosses_above", "crosses_below"]
RuleType = Literal["price", "indicator", "volume", "announcement"]


class AlertCondition(BaseModel):
    indicator: Optional[str] = None
    op: Operator
    value: float
    lookback_days: Optional[int] = None


class AlertRule(BaseModel):
    id: str
    symbol: str
    type: RuleType
    condition: AlertCondition
    active: bool = True
    created_at: date
    last_checked: Optional[datetime] = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class AlertHit(BaseModel):
    rule_id: str
    symbol: str
    triggered_at: datetime
    message: str
    snapshot: dict


class ToolError(BaseModel):
    code: str
    message: str
    symbol: Optional[str] = None


class VolumeSpike(BaseModel):
    symbol: str
    today_volume: int
    avg_volume: float
    multiplier: float

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class ComparisonRow(BaseModel):
    symbol: str
    metrics: dict[str, Optional[float]]

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class ComparisonTable(Disclaimer):
    metrics: list[str]
    rows: list[ComparisonRow]
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/src/psx_mcp/models.py psx-mcp/tests/test_models.py
git commit -m "feat(psx-mcp): pydantic models for tools & rules"
```

---

### Task 3: Logging config

**Files:**
- Create: `psx-mcp/src/psx_mcp/logging_config.py`

- [ ] **Step 1: Implement `logging_config.py`**

```python
from __future__ import annotations
import logging
from pathlib import Path
import structlog

LOG_DIR = Path("data")


def configure_logging(log_file: str = "server.log", level: str = "INFO") -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 2: Smoke-test logging import**

Run:
```powershell
uv run python -c "from psx_mcp.logging_config import configure_logging, get_logger; configure_logging(); get_logger('test').info('hello', x=1)"
```
Expected: JSON log line with `event: hello` printed to stdout, no errors.

- [ ] **Step 3: Commit**

```powershell
git add psx-mcp/src/psx_mcp/logging_config.py
git commit -m "feat(psx-mcp): structlog JSON logging config"
```

---

### Task 4: SQLite cache module — schema, TTL, append-only bars

**Files:**
- Create: `psx-mcp/src/psx_mcp/cache.py`
- Create: `psx-mcp/tests/test_cache.py`

**Note:** We store all timestamps as ISO TEXT strings and convert explicitly in Python. Do **not** pass `detect_types=sqlite3.PARSE_DECLTYPES` — the codebase converts manually, and Python 3.12 deprecates the default `timestamp` converter.

- [ ] **Step 1: Write the failing tests**

`tests/test_cache.py`:
```python
from datetime import datetime, date, timedelta
import pytest
from psx_mcp.cache import Cache
from psx_mcp.models import Bar, Announcement


@pytest.fixture
def cache(tmp_path):
    db = tmp_path / "t.db"
    return Cache(str(db))


def test_schema_created(cache):
    tables = cache.list_tables()
    for t in ["symbols", "quotes", "bars_daily", "announcements", "fundamentals", "news"]:
        assert t in tables


def test_upsert_quote_and_fetch(cache):
    cache.upsert_quote(
        symbol="LUCK", ts=datetime(2026, 5, 23, 10, 0),
        price=750.0, change=10.0, volume=1000, day_high=760, day_low=740,
        fetched_at=datetime(2026, 5, 23, 10, 1),
    )
    q = cache.get_latest_quote("LUCK")
    assert q is not None
    assert q["price"] == 750.0


def test_quote_freshness(cache):
    cache.upsert_quote(
        symbol="LUCK", ts=datetime.now(),
        price=1, change=0, volume=0, day_high=0, day_low=0,
        fetched_at=datetime.now() - timedelta(minutes=2),
    )
    assert cache.is_quote_fresh("LUCK", ttl_seconds=300)
    assert not cache.is_quote_fresh("LUCK", ttl_seconds=30)


def test_append_bars_idempotent(cache):
    today = date.today()
    bars = [
        Bar(symbol="LUCK", date=today - timedelta(days=2), open=700, high=710, low=695, close=705, volume=10),
        Bar(symbol="LUCK", date=today - timedelta(days=1), open=705, high=720, low=702, close=718, volume=12),
    ]
    cache.upsert_bars(bars)
    cache.upsert_bars(bars)
    rows = cache.get_bars("LUCK", today - timedelta(days=10), today)
    assert len(rows) == 2


def test_get_bars_date_range(cache):
    today = date.today()
    bars = [
        Bar(symbol="LUCK", date=today - timedelta(days=d), open=1, high=1, low=1, close=1, volume=1)
        for d in (4, 3, 2, 1, 0)
    ]
    cache.upsert_bars(bars)
    got = cache.get_bars("LUCK", today - timedelta(days=2), today - timedelta(days=1))
    assert len(got) == 2


def test_announcements_upsert(cache):
    a = Announcement(
        id="a1", symbol="LUCK", posted_at=datetime(2026, 5, 23, 9),
        title="Board Meeting", category="board", url="http://x", body=None,
    )
    cache.upsert_announcement(a)
    cache.upsert_announcement(a)
    rows = cache.get_announcements(symbol="LUCK", since=datetime(2026, 1, 1))
    assert len(rows) == 1


def test_symbol_master_refresh(cache):
    cache.upsert_symbol("LUCK", "Lucky Cement Limited", "Cement", 323_375_503)
    s = cache.get_symbol("LUCK")
    assert s["name"] == "Lucky Cement Limited"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_cache.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `cache.py`**

`src/psx_mcp/cache.py`:
```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_cache.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/src/psx_mcp/cache.py psx-mcp/tests/test_cache.py
git commit -m "feat(psx-mcp): SQLite cache with schema, TTL, append-only bars"
```

---

### Task 5: Pure-math indicators

**Files:**
- Create: `psx-mcp/src/psx_mcp/indicators.py`
- Create: `psx-mcp/tests/test_indicators.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_indicators.py`:
```python
import numpy as np
import pandas as pd
import pytest
from psx_mcp.indicators import (
    rsi, sma, ema, macd, bollinger, volume_zscore, last_crosses,
)


@pytest.fixture
def closes_15():
    return pd.Series(
        [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
         45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    )


def test_sma_last_value():
    s = pd.Series([1, 2, 3, 4, 5])
    assert sma(s, 3).iloc[-1] == pytest.approx(4.0)


def test_ema_last_value():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ema(s, 3).iloc[-1]
    assert out > 0


def test_rsi_in_bounds(closes_15):
    out = rsi(closes_15, 14).iloc[-1]
    assert 0.0 <= out <= 100.0


def test_rsi_oversold_detected():
    s = pd.Series([float(x) for x in range(100, 85, -1)] + [86.0])
    out = rsi(s, 14).iloc[-1]
    assert out < 50.0


def test_macd_shape():
    s = pd.Series(np.linspace(100, 200, 60))
    m = macd(s)
    assert {"macd", "signal", "hist"} <= set(m.columns)
    assert len(m) == 60


def test_bollinger_bands_ordering():
    s = pd.Series(np.random.RandomState(0).randn(40).cumsum() + 100)
    b = bollinger(s, 20, 2.0)
    assert (b["upper"] >= b["middle"]).all()
    assert (b["middle"] >= b["lower"]).all()


def test_volume_zscore_positive_spike():
    v = pd.Series([100.0] * 19 + [500.0])
    z = volume_zscore(v, 20)
    assert z.iloc[-1] > 2.0


def test_crosses_above_detected():
    a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    b = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0])
    assert last_crosses(a, b, "crosses_above") is True


def test_crosses_below_detected():
    a = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
    b = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0])
    assert last_crosses(a, b, "crosses_below") is True


def test_no_cross_when_flat():
    a = pd.Series([1.0, 1.0, 1.0, 1.0])
    b = pd.Series([2.0, 2.0, 2.0, 2.0])
    assert last_crosses(a, b, "crosses_above") is False
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_indicators.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `indicators.py`**

`src/psx_mcp/indicators.py`:
```python
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Literal


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_e = ema(series, fast)
    slow_e = ema(series, slow)
    macd_line = fast_e - slow_e
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=1).std().fillna(0)
    return pd.DataFrame({
        "middle": mid,
        "upper": mid + n_std * std,
        "lower": mid - n_std * std,
    })


def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    avg = volume.rolling(window=window, min_periods=1).mean()
    std = volume.rolling(window=window, min_periods=1).std().replace(0, np.nan)
    return (volume - avg) / std


Cross = Literal["crosses_above", "crosses_below"]


def last_crosses(a: pd.Series, b: pd.Series, op: Cross) -> bool:
    if len(a) < 2 or len(b) < 2:
        return False
    prev_a, prev_b = a.iloc[-2], b.iloc[-2]
    curr_a, curr_b = a.iloc[-1], b.iloc[-1]
    if op == "crosses_above":
        return prev_a <= prev_b and curr_a > curr_b
    return prev_a >= prev_b and curr_a < curr_b
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_indicators.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/src/psx_mcp/indicators.py psx-mcp/tests/test_indicators.py
git commit -m "feat(psx-mcp): indicators — RSI, MACD, SMA/EMA, Bollinger, vol z, crosses"
```

---

### Task 6: Bars→DataFrame helper

**Files:**
- Create: `psx-mcp/src/psx_mcp/df_utils.py`

This helper is the single source of truth for converting cached bar rows into a DataFrame. Used by both `alerts.py` and `server.py` so column conventions stay consistent.

- [ ] **Step 1: Implement `df_utils.py`**

```python
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
```

- [ ] **Step 2: Smoke test**

Run:
```powershell
uv run python -c "from psx_mcp.df_utils import bars_df; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```powershell
git add psx-mcp/src/psx_mcp/df_utils.py
git commit -m "feat(psx-mcp): shared bars→DataFrame helper"
```

---

### Task 7: PSX HTTP client — discovery script + parsers

**Files:**
- Create: `psx-mcp/scripts/capture_fixtures.py`
- Create: `psx-mcp/src/psx_mcp/psx_client.py`
- Create: `psx-mcp/tests/test_psx_client.py`
- Create: `psx-mcp/tests/fixtures/market_watch.html` (captured at runtime)
- Create: `psx-mcp/tests/fixtures/historical_LUCK.{json|html}` (captured)
- Create: `psx-mcp/tests/fixtures/symbols.{json|html}` (captured)
- Create: `psx-mcp/tests/fixtures/announcements.{json|html}` (captured)
- Create: `psx-mcp/tests/fixtures/profile_LUCK.html` (captured)
- Create: `psx-mcp/tests/fixtures/financial_LUCK.html` (captured)

**IMPORTANT:** PSX endpoints are not formally documented. Step 1 captures real responses into fixtures **and detects whether each endpoint returns JSON or HTML**. Parsers in Step 4 use a `_try_json` helper that handles both. Intraday endpoint (`/timeseries/int/<SYM>`) is **explicitly deferred** to a future iteration — daily bars from `/historical/<SYM>` cover all indicator/alert needs at 15-min delay.

- [ ] **Step 1: Create the fixture-capture script**

`psx-mcp/scripts/capture_fixtures.py`:
```python
"""One-off: capture real PSX responses into tests/fixtures/.

Run from psx-mcp/:  uv run python scripts/capture_fixtures.py
"""
import asyncio
import httpx
from pathlib import Path

FIX = Path("tests/fixtures")
FIX.mkdir(parents=True, exist_ok=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1",
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}

URLS = [
    ("https://dps.psx.com.pk/market-watch", "market_watch"),
    ("https://dps.psx.com.pk/historical/LUCK", "historical_LUCK"),
    ("https://dps.psx.com.pk/symbols", "symbols"),
    ("https://dps.psx.com.pk/announcements/companies", "announcements"),
    ("https://www.psx.com.pk/psx/profile/LUCK", "profile_LUCK"),
    ("https://www.psx.com.pk/psx/quote/financial-information/LUCK", "financial_LUCK"),
]


def _ext_from(response: httpx.Response) -> str:
    ctype = response.headers.get("content-type", "").lower()
    if "json" in ctype:
        return "json"
    return "html"


async def main():
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=20) as c:
        for url, stem in URLS:
            try:
                r = await c.get(url, headers=HEADERS)
            except Exception as e:
                print(f"{url} -> ERROR: {e}")
                continue
            ext = _ext_from(r)
            out = FIX / f"{stem}.{ext}"
            print(f"{url} -> {r.status_code} ({len(r.content)} bytes) -> {out.name}")
            if r.status_code == 200:
                out.write_text(r.text, encoding="utf-8")
            else:
                print(f"  WARN: non-200; adapt URL in psx_client.py before continuing")


if __name__ == "__main__":
    asyncio.run(main())
```

Run from `psx-mcp/`:
```powershell
uv run python scripts/capture_fixtures.py
```
Expected: each URL printed with status 200; fixture files written with appropriate `.json` or `.html` extension. If any returns 4xx/5xx, **stop** and report the failing URL — the parser for that endpoint needs the URL revised before continuing. Document the actual working URL in `psx_client.py` constants.

- [ ] **Step 2: Inspect each captured fixture and write a shape table at top of `psx_client.py`**

For each fixture, open and inspect the first ~50 lines. Determine:
- **format**: JSON or HTML
- **top-level shape**: if JSON, the keys / whether wrapped in `{data: [...]}`; if HTML, the relevant tag/class
- **example record**: one example row with field names

Write this matrix as the module docstring in `psx_client.py`:
```python
"""PSX endpoint shape matrix (captured YYYY-MM-DD):

market-watch:     HTML — single <table>, columns: SYMBOL, LDCP, OPEN, HIGH, LOW, CURRENT, CHANGE, CHANGE%, VOLUME
historical/LUCK:  <fill in: JSON list with Date/Open/High/Low/Close/Volume keys | HTML table>
symbols:          <fill in>
announcements:    <fill in>
profile_LUCK:     HTML — sector + listed-shares appear in dt/dd or table rows
financial_LUCK:   HTML — EPS/P/E/P/B in <th>/<td> pairs
"""
```

This docstring is the contract. Parsers in Step 4 must conform to it.

- [ ] **Step 3: Write failing parser tests**

`tests/test_psx_client.py`:
```python
from pathlib import Path
from datetime import date, datetime
import pytest

from psx_mcp.psx_client import (
    parse_market_watch, parse_historical, parse_symbols,
    parse_announcements, parse_profile, parse_financials,
    parse_financial_statements,
)


def _read_any(fixtures_dir: Path, stem: str) -> str:
    for ext in ("json", "html"):
        p = fixtures_dir / f"{stem}.{ext}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No fixture for {stem}.* in {fixtures_dir}")


def test_parse_market_watch_returns_rows(fixtures_dir):
    rows = parse_market_watch((fixtures_dir / "market_watch.html").read_text(encoding="utf-8"))
    assert len(rows) > 100, "expected ~540 PSX symbols, got fewer"
    sample = next((r for r in rows if r["price"] is not None), None)
    assert sample is not None, "every row had price=None — column detection broken"
    assert set(sample.keys()) >= {"symbol", "price", "change", "volume"}
    assert isinstance(sample["price"], float)


def test_parse_historical_returns_bars(fixtures_dir):
    bars = parse_historical("LUCK", _read_any(fixtures_dir, "historical_LUCK"))
    assert len(bars) > 0
    b = bars[0]
    assert b.symbol == "LUCK"
    assert isinstance(b.date, date)


def test_parse_symbols_returns_master(fixtures_dir):
    syms = parse_symbols(_read_any(fixtures_dir, "symbols"))
    assert len(syms) > 100
    assert all("symbol" in s and "name" in s for s in syms)


def test_parse_announcements_returns_items(fixtures_dir):
    items = parse_announcements(_read_any(fixtures_dir, "announcements"))
    assert isinstance(items, list)
    if items:
        a = items[0]
        assert isinstance(a.posted_at, datetime)
        assert a.title


def test_parse_profile_extracts_fields(fixtures_dir):
    info = parse_profile("LUCK", (fixtures_dir / "profile_LUCK.html").read_text(encoding="utf-8"))
    assert info.symbol == "LUCK"
    assert info.name


def test_parse_financials_best_effort(fixtures_dir):
    f = parse_financials("LUCK", (fixtures_dir / "financial_LUCK.html").read_text(encoding="utf-8"))
    assert f.symbol == "LUCK"
    # at least one of eps/pe/pb populated
    assert any(v is not None for v in [f.eps, f.pe, f.pb])


def test_parse_financial_statements_returns_list(fixtures_dir):
    out = parse_financial_statements(
        "LUCK", "annual",
        (fixtures_dir / "financial_LUCK.html").read_text(encoding="utf-8"),
    )
    assert isinstance(out, list)
    # may be empty if filings absent; if present, validate shape
    if out:
        assert out[0].symbol == "LUCK"
        assert out[0].period == "annual"
```

- [ ] **Step 4: Run tests — expect failure**

Run: `uv run pytest tests/test_psx_client.py -v`
Expected: ImportError.

- [ ] **Step 5: Implement `psx_client.py`**

`src/psx_mcp/psx_client.py`:
```python
"""PSX endpoint shape matrix (captured at fixture-capture time):

market-watch:     HTML — single <table>, columns include SYMBOL, LDCP, OPEN, HIGH, LOW, CURRENT, CHANGE, CHANGE%, VOLUME
historical/LUCK:  format determined at capture time; parser handles JSON list and HTML table
symbols:          format determined at capture time; parser handles JSON list and HTML table
announcements:    format determined at capture time; parser handles JSON list and HTML table
profile_LUCK:     HTML — name in <h1>/<h2>; sector and listed shares in dt/dd pairs or table rows
financial_LUCK:   HTML — EPS / P/E / P/B in label-value pairs
"""
from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime, date
from typing import Optional, Union

import httpx
from bs4 import BeautifulSoup

from .models import Bar, CompanyInfo, Fundamentals, Announcement, FinancialStatement
from .logging_config import get_logger

log = get_logger("psx_client")

BASE_DPS = "https://dps.psx.com.pk"
BASE_PSX = "https://www.psx.com.pk"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PSX-MCP/0.1"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-PK,en;q=0.9",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
}


class ParseError(Exception):
    pass


# ---------- low-level HTTP ----------

class PSXClient:
    """Async HTTP client for PSX endpoints. Polite: max 2 concurrent requests."""

    def __init__(self, *, timeout: float = 10.0):
        self._sem = asyncio.Semaphore(2)
        self._client = httpx.AsyncClient(
            http2=True, headers=HEADERS, timeout=timeout, follow_redirects=True
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str) -> str:
        async with self._sem:
            for attempt in (1, 2):
                try:
                    r = await self._client.get(url)
                    r.raise_for_status()
                    return r.text
                except httpx.HTTPStatusError as e:
                    if 500 <= e.response.status_code < 600 and attempt == 1:
                        await asyncio.sleep(2.0)
                        continue
                    raise
                except (httpx.ConnectError, httpx.ReadTimeout):
                    if attempt == 1:
                        await asyncio.sleep(2.0)
                        continue
                    raise
            raise httpx.HTTPError(f"unreachable after retries: {url}")

    async def fetch_market_watch(self) -> str:
        return await self._get(f"{BASE_DPS}/market-watch")

    async def fetch_historical(self, symbol: str) -> str:
        return await self._get(f"{BASE_DPS}/historical/{symbol.upper()}")

    async def fetch_symbols(self) -> str:
        return await self._get(f"{BASE_DPS}/symbols")

    async def fetch_announcements(self) -> str:
        return await self._get(f"{BASE_DPS}/announcements/companies")

    async def fetch_profile(self, symbol: str) -> str:
        return await self._get(f"{BASE_PSX}/psx/profile/{symbol.upper()}")

    async def fetch_financials(self, symbol: str) -> str:
        return await self._get(f"{BASE_PSX}/psx/quote/financial-information/{symbol.upper()}")


# ---------- shared helpers ----------

def _try_json(payload: str) -> tuple[Optional[Union[list, dict]], Optional[BeautifulSoup]]:
    """Return (json_obj, None) if payload parses as JSON; otherwise (None, BeautifulSoup)."""
    try:
        return json.loads(payload), None
    except (json.JSONDecodeError, ValueError):
        return None, BeautifulSoup(payload, "lxml")


def _f(x) -> Optional[float]:
    if x is None or x == "" or x == "-":
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _i(x) -> int:
    v = _f(x)
    return int(v) if v is not None else 0


def _parse_date_flex(s: str) -> Optional[date]:
    """Parse PSX dates in any common format. Strips any time suffix first."""
    raw = str(s).strip()
    # Drop any trailing time component (after first space or 'T')
    head = re.split(r"[ T]", raw, maxsplit=1)[0]
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d %b %Y", "%b %d, %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    # Last-ditch: ISO parse the first 10 chars
    try:
        return date.fromisoformat(head[:10])
    except ValueError:
        return None


# ---------- parsers ----------

def parse_market_watch(html: str) -> list[dict]:
    """Returns list of {symbol, price, change, volume, day_high, day_low}.
    Uses header-row detection to map columns by name rather than fixed indices."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        raise ParseError("market-watch: no <table> found")

    # Build header → index map
    header_cells = []
    thead = table.find("thead")
    if thead:
        header_cells = [th.get_text(strip=True).upper() for th in thead.find_all(["th", "td"])]
    if not header_cells:
        first_tr = table.find("tr")
        if first_tr:
            header_cells = [th.get_text(strip=True).upper() for th in first_tr.find_all(["th", "td"])]

    def col(name_options: list[str]) -> Optional[int]:
        for i, h in enumerate(header_cells):
            for opt in name_options:
                if opt in h:
                    return i
        return None

    idx_sym = col(["SYMBOL", "SCRIP"])
    idx_price = col(["CURRENT", "PRICE", "LAST"])
    idx_change = col(["CHANGE"])  # absolute change
    idx_volume = col(["VOLUME", "VOL"])
    idx_high = col(["HIGH"])
    idx_low = col(["LOW"])

    # Fallback to positional if header detection fails (very old shape)
    if idx_sym is None:
        idx_sym, idx_price, idx_change, idx_volume, idx_high, idx_low = 0, 5, 6, 8, 3, 4

    rows = []
    body = table.find("tbody") or table
    needed = [i for i in (idx_sym, idx_price, idx_change, idx_volume, idx_high, idx_low) if i is not None]
    min_cells = (max(needed) + 1) if needed else 1
    for tr in body.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < min_cells:
            continue
        sym = cells[idx_sym].upper() if idx_sym is not None else ""
        if not sym or sym == "SYMBOL":
            continue
        rows.append({
            "symbol": sym,
            "price": _f(cells[idx_price]) if idx_price is not None else None,
            "change": _f(cells[idx_change]) if idx_change is not None else 0.0,
            "volume": _i(cells[idx_volume]) if idx_volume is not None else 0,
            "day_high": _f(cells[idx_high]) if idx_high is not None else None,
            "day_low": _f(cells[idx_low]) if idx_low is not None else None,
        })
    return rows


def parse_historical(symbol: str, payload: str) -> list[Bar]:
    """Daily OHLCV. Handles JSON (list or {data: [...]}) and HTML tables."""
    data, soup = _try_json(payload)
    bars: list[Bar] = []

    if data is not None:
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        for r in data:
            d_raw = r.get("Date") or r.get("date") or r.get("DATE")
            if not d_raw:
                continue
            d = _parse_date_flex(d_raw)
            if not d:
                continue
            bars.append(Bar(
                symbol=symbol.upper(), date=d,
                open=_f(r.get("Open") or r.get("open")) or 0,
                high=_f(r.get("High") or r.get("high")) or 0,
                low=_f(r.get("Low") or r.get("low")) or 0,
                close=_f(r.get("Close") or r.get("close")) or 0,
                volume=_i(r.get("Volume") or r.get("volume")),
            ))
        return bars

    # HTML table path
    if soup is None:
        return bars
    table = soup.find("table")
    if not table:
        return bars
    header_cells = [th.get_text(strip=True).upper() for th in (table.find("thead") or table).find_all(["th", "td"])]
    def col(name): return next((i for i, h in enumerate(header_cells) if name in h), None)
    i_d, i_o, i_h, i_l, i_c, i_v = col("DATE"), col("OPEN"), col("HIGH"), col("LOW"), col("CLOSE"), col("VOL")
    for tr in (table.find("tbody") or table).find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells or i_d is None or len(cells) <= i_d:
            continue
        d = _parse_date_flex(cells[i_d])
        if not d:
            continue
        bars.append(Bar(
            symbol=symbol.upper(), date=d,
            open=_f(cells[i_o]) if i_o is not None and len(cells) > i_o else 0,
            high=_f(cells[i_h]) if i_h is not None and len(cells) > i_h else 0,
            low=_f(cells[i_l]) if i_l is not None and len(cells) > i_l else 0,
            close=_f(cells[i_c]) if i_c is not None and len(cells) > i_c else 0,
            volume=_i(cells[i_v]) if i_v is not None and len(cells) > i_v else 0,
        ))
    return bars


def parse_symbols(payload: str) -> list[dict]:
    """Symbol master. Handles JSON list and HTML table."""
    data, soup = _try_json(payload)
    out = []
    if data is not None:
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        for r in data:
            sym = (r.get("symbol") or r.get("Symbol") or r.get("SYMBOL") or "").upper()
            name = r.get("name") or r.get("Name") or r.get("companyName") or ""
            sector = r.get("sector") or r.get("Sector")
            if sym:
                out.append({"symbol": sym, "name": name, "sector": sector})
        return out

    if soup is None:
        return out
    table = soup.find("table")
    if not table:
        return out
    for tr in (table.find("tbody") or table).find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) >= 2 and cells[0]:
            out.append({"symbol": cells[0].upper(), "name": cells[1],
                        "sector": cells[2] if len(cells) > 2 else None})
    return out


def parse_announcements(payload: str) -> list[Announcement]:
    """Corporate actions. Handles JSON list and HTML table."""
    data, soup = _try_json(payload)
    out: list[Announcement] = []

    def _push(*, sym, title, posted, category=None, url=None, body=None, ann_id=None):
        if not title:
            return
        sym_u = sym.upper() if sym else None
        aid = ann_id or f"{sym_u or 'X'}-{posted.isoformat()}-{title[:30]}"
        out.append(Announcement(
            id=str(aid), symbol=sym_u, posted_at=posted,
            title=title, category=category, url=url, body=body,
        ))

    if data is not None:
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        for r in data:
            sym = (r.get("symbol") or r.get("Symbol") or "") or None
            title = r.get("title") or r.get("Title") or r.get("subject") or ""
            d_raw = r.get("date") or r.get("Date") or r.get("posted_at") or r.get("dateTime")
            posted = datetime.now()
            if d_raw:
                try:
                    posted = datetime.fromisoformat(str(d_raw))
                except ValueError:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
                        try:
                            posted = datetime.strptime(str(d_raw), fmt)
                            break
                        except ValueError:
                            continue
            _push(sym=sym, title=title, posted=posted, category=r.get("category"),
                  url=r.get("url") or r.get("URL") or r.get("link"),
                  body=r.get("body"), ann_id=r.get("id"))
        return out

    if soup is None:
        return out
    for tr in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        # Heuristic: look for a date-like cell and a title-ish cell
        posted = datetime.now()
        for cell in cells:
            try:
                posted = datetime.fromisoformat(cell[:19])
                break
            except ValueError:
                continue
        title = cells[-1] if cells else ""
        sym = None
        link = tr.find("a")
        url = link.get("href") if link else None
        _push(sym=sym, title=title, posted=posted, url=url)
    return out


def parse_profile(symbol: str, html: str) -> CompanyInfo:
    soup = BeautifulSoup(html, "lxml")
    name = None
    if (h := soup.find(["h1", "h2"])):
        name = h.get_text(strip=True)
    sector = None
    listed = None

    # Look for label/value pairs in <dt>/<dd> first, then table rows
    for dt in soup.find_all("dt"):
        label = dt.get_text(" ", strip=True).lower()
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        val = dd.get_text(" ", strip=True)
        if "sector" in label and not sector:
            sector = val
        elif "listed shares" in label or "shares outstanding" in label:
            listed = _i(val) or None

    if not sector or not listed:
        for tr in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            label = cells[0].lower()
            val = cells[1]
            if "sector" in label and not sector:
                sector = val
            elif ("listed shares" in label or "shares outstanding" in label) and not listed:
                listed = _i(val) or None

    return CompanyInfo(
        symbol=symbol.upper(),
        name=name or symbol.upper(),
        sector=sector, listed_shares=listed,
    )


def parse_financials(symbol: str, html: str) -> Fundamentals:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    def find(label_regex: str) -> Optional[float]:
        m = re.search(rf"{label_regex}[^0-9\-]*(-?\d+(?:\.\d+)?)", text, re.I)
        return float(m.group(1)) if m else None

    return Fundamentals(
        symbol=symbol.upper(),
        eps=find(r"EPS"),
        pe=find(r"P\s*/\s*E"),
        pb=find(r"P\s*/\s*B"),
        div_yield=find(r"Dividend\s*Yield"),
        payout=find(r"Payout"),
        roe=find(r"ROE"),
        refreshed_at=datetime.now(),
    )


def parse_financial_statements(symbol: str, period: str, html: str) -> list[FinancialStatement]:
    """Best-effort scrape of annual/quarterly financial statements from the PSX
    financial-information page. Returns empty list if no statements found."""
    if period not in ("annual", "quarterly"):
        raise ValueError("period must be 'annual' or 'quarterly'")
    soup = BeautifulSoup(html, "lxml")
    statements: list[FinancialStatement] = []
    # Look for tables that resemble financial statements (label + numeric columns)
    for table in soup.find_all("table"):
        header = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        if not header or len(header) < 2:
            continue
        # Try to find a period column from header names (e.g. "2024", "FY2024")
        period_cols: list[tuple[int, date]] = []
        for i, h in enumerate(header):
            m = re.search(r"(20\d{2})", h)
            if m:
                period_cols.append((i, date(int(m.group(1)), 12, 31)))
        if not period_cols:
            continue
        items_by_period: dict[date, dict[str, float]] = {pe: {} for _, pe in period_cols}
        for tr in (table.find("tbody") or table).find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            label = cells[0]
            for col_idx, pe in period_cols:
                if col_idx < len(cells):
                    v = _f(cells[col_idx])
                    if v is not None and label:
                        items_by_period[pe][label] = v
        for pe, items in items_by_period.items():
            if items:
                statements.append(FinancialStatement(
                    symbol=symbol.upper(), period=period, period_end=pe, line_items=items,
                ))
    return statements
```

- [ ] **Step 6: Run tests — expect pass**

Run: `uv run pytest tests/test_psx_client.py -v`
Expected: all parser tests pass against the captured fixtures. If a test fails, **adapt the parser** to match the real fixture shape rather than weakening the test.

- [ ] **Step 7: Commit (fixtures + parsers)**

```powershell
git add psx-mcp/src/psx_mcp/psx_client.py psx-mcp/tests/test_psx_client.py psx-mcp/tests/fixtures/ psx-mcp/scripts/capture_fixtures.py
git commit -m "feat(psx-mcp): async HTTP client + fixture-driven parsers"
```

---

### Task 8: Symbols module — search & lookup

**Files:**
- Create: `psx-mcp/src/psx_mcp/symbols.py`
- Create: `psx-mcp/tests/test_symbols.py`

- [ ] **Step 1: Write failing tests**

`tests/test_symbols.py`:
```python
from pathlib import Path
import pytest
from psx_mcp.cache import Cache
from psx_mcp.symbols import search_symbols, refresh_symbols_from_payload


def _payload(fixtures_dir: Path) -> str:
    for ext in ("json", "html"):
        p = fixtures_dir / f"symbols.{ext}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("symbols fixture missing")


def test_refresh_and_search(tmp_path, fixtures_dir):
    c = Cache(str(tmp_path / "t.db"))
    refresh_symbols_from_payload(c, _payload(fixtures_dir))
    matches = search_symbols(c, "lucky", limit=5)
    assert any(m["symbol"] == "LUCK" for m in matches)


def test_search_by_exact_symbol(tmp_path, fixtures_dir):
    c = Cache(str(tmp_path / "t.db"))
    refresh_symbols_from_payload(c, _payload(fixtures_dir))
    matches = search_symbols(c, "LUCK", limit=1)
    assert matches[0]["symbol"] == "LUCK"
    assert matches[0]["score"] >= 0.9
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_symbols.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `symbols.py`**

`src/psx_mcp/symbols.py`:
```python
from __future__ import annotations
from difflib import SequenceMatcher
from .cache import Cache
from .psx_client import parse_symbols


def refresh_symbols_from_payload(cache: Cache, payload: str) -> int:
    rows = parse_symbols(payload)
    for r in rows:
        cache.upsert_symbol(r["symbol"], r["name"], r.get("sector"), None)
    return len(rows)


def _score(query: str, candidate: str) -> float:
    return SequenceMatcher(None, query.lower(), candidate.lower()).ratio()


def search_symbols(cache: Cache, query: str, limit: int = 10) -> list[dict]:
    q = query.strip().upper()
    all_rows = cache.all_symbols()
    scored: list[dict] = []
    for r in all_rows:
        sym, name = r["symbol"], r.get("name") or ""
        s_score = 1.0 if sym == q else _score(q, sym) * 0.9
        n_score = _score(q, name)
        score = max(s_score, n_score)
        if score >= 0.4:
            scored.append({"symbol": sym, "name": name, "sector": r.get("sector"), "score": round(score, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_symbols.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/src/psx_mcp/symbols.py psx-mcp/tests/test_symbols.py
git commit -m "feat(psx-mcp): symbol master refresh + fuzzy search"
```

---

### Task 9: News aggregator (RSS via feedparser)

**Files:**
- Create: `psx-mcp/scripts/capture_rss.py`
- Create: `psx-mcp/src/psx_mcp/news.py`
- Create: `psx-mcp/tests/test_news.py`
- Create: `psx-mcp/tests/fixtures/brecorder_feed.xml` (captured)
- Create: `psx-mcp/tests/fixtures/profit_feed.xml` (captured)

- [ ] **Step 1: Create RSS capture script**

`psx-mcp/scripts/capture_rss.py`:
```python
"""Capture RSS feeds into tests/fixtures/.
Run from psx-mcp/:  uv run python scripts/capture_rss.py
"""
import httpx
from pathlib import Path

FIX = Path("tests/fixtures")
HEADERS = {"User-Agent": "Mozilla/5.0"}

FEEDS = [
    ("https://www.brecorder.com/feed", "brecorder_feed.xml"),
    ("https://profit.pakistantoday.com.pk/feed/", "profit_feed.xml"),
]

for url, out in FEEDS:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        print(url, r.status_code, len(r.content))
        if r.status_code == 200:
            (FIX / out).write_text(r.text, encoding="utf-8")
    except Exception as e:
        print(f"{url} ERROR {e}")
```

Run: `uv run python scripts/capture_rss.py`
Expected: both 200; XML written. If a feed 404s, swap to the working URL and update `news.py FEEDS`.

- [ ] **Step 2: Write failing tests**

`tests/test_news.py`:
```python
from psx_mcp.news import parse_rss, find_symbol_mentions


def test_parse_brecorder(fixtures_dir):
    xml = (fixtures_dir / "brecorder_feed.xml").read_text(encoding="utf-8")
    items = parse_rss("brecorder", xml)
    assert len(items) > 0
    it = items[0]
    assert it.source == "brecorder"
    assert it.title
    assert it.url


def test_symbol_mentions_finds_ticker():
    title = "Lucky Cement (LUCK) reports record profits"
    mentions = find_symbol_mentions(title, "", {"LUCK", "OGDC"})
    assert "LUCK" in mentions
    assert "OGDC" not in mentions


def test_symbol_mentions_requires_word_boundary():
    title = "Plucky bidder wins auction"
    mentions = find_symbol_mentions(title, "", {"LUCK"})
    assert "LUCK" not in mentions
```

- [ ] **Step 3: Run — expect failure**

Run: `uv run pytest tests/test_news.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `news.py`**

`src/psx_mcp/news.py`:
```python
from __future__ import annotations
import re
import hashlib
from datetime import datetime
from typing import Iterable

import feedparser

from .models import NewsItem


FEEDS = {
    "brecorder": "https://www.brecorder.com/feed",
    "profit_pakistan": "https://profit.pakistantoday.com.pk/feed/",
}


def parse_rss(source: str, xml: str) -> list[NewsItem]:
    parsed = feedparser.parse(xml)
    items: list[NewsItem] = []
    for e in parsed.entries:
        url = getattr(e, "link", "")
        title = getattr(e, "title", "")
        pub = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        ts = datetime(*pub[:6]) if pub else datetime.now()
        nid = hashlib.sha1(f"{source}:{url}".encode("utf-8")).hexdigest()[:16]
        items.append(NewsItem(id=nid, source=source, posted_at=ts, title=title, url=url, symbols=[]))
    return items


def find_symbol_mentions(title: str, body: str, universe: Iterable[str]) -> list[str]:
    text = f"{title} {body}"
    hits = []
    for sym in universe:
        if re.search(rf"\b{re.escape(sym)}\b", text):
            hits.append(sym)
    return hits
```

- [ ] **Step 5: Run — expect pass**

Run: `uv run pytest tests/test_news.py -v`
Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add psx-mcp/scripts/capture_rss.py psx-mcp/src/psx_mcp/news.py psx-mcp/tests/test_news.py psx-mcp/tests/fixtures/brecorder_feed.xml psx-mcp/tests/fixtures/profit_feed.xml
git commit -m "feat(psx-mcp): RSS news aggregator with symbol mention detection"
```

---

### Task 10: Watchlist module — JSON-backed rules store

**Files:**
- Create: `psx-mcp/src/psx_mcp/watchlist.py`
- Create: `psx-mcp/tests/test_watchlist.py`

- [ ] **Step 1: Write failing tests**

`tests/test_watchlist.py`:
```python
from datetime import date
import pytest
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.models import AlertCondition


@pytest.fixture
def store(tmp_path):
    return WatchlistStore(str(tmp_path / "wl.json"))


def test_add_and_list_watch(store):
    store.add_watch("LUCK", "favorite cement")
    entries = store.list_watch()
    assert len(entries) == 1
    assert entries[0].symbol == "LUCK"


def test_add_is_idempotent(store):
    store.add_watch("LUCK")
    store.add_watch("luck")
    assert len(store.list_watch()) == 1


def test_remove_watch(store):
    store.add_watch("LUCK")
    assert store.remove_watch("LUCK") is True
    assert store.list_watch() == []


def test_set_alert_rule_generates_id(store):
    cond = AlertCondition(indicator="rsi14", op="<", value=30)
    rule = store.set_alert_rule(symbol="LUCK", type="indicator", condition=cond)
    assert rule.id
    assert rule.symbol == "LUCK"


def test_list_and_remove_rule(store):
    cond = AlertCondition(op=">", value=800)
    rule = store.set_alert_rule(symbol="LUCK", type="price", condition=cond)
    rules = store.list_alert_rules(symbol="LUCK")
    assert any(r.id == rule.id for r in rules)
    assert store.remove_alert_rule(rule.id) is True
    assert store.list_alert_rules() == []


def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "wl.json")
    s1 = WatchlistStore(p)
    s1.add_watch("LUCK")
    s2 = WatchlistStore(p)
    assert s2.list_watch()[0].symbol == "LUCK"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_watchlist.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `watchlist.py`**

`src/psx_mcp/watchlist.py`:
```python
from __future__ import annotations
import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .models import AlertCondition, AlertRule, WatchEntry, RuleType


def _today() -> date:
    return date.today()


def _ser(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump()
    raise TypeError(f"not serializable: {type(o)}")


class WatchlistStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {"watch": [], "rules": []}
        if self.path.exists() and self.path.stat().st_size:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, default=_ser, indent=2), encoding="utf-8")

    # ---- watch ----
    def add_watch(self, symbol: str, notes: Optional[str] = None) -> WatchEntry:
        sym = symbol.upper()
        for w in self._data["watch"]:
            if w["symbol"] == sym:
                return WatchEntry(**{**w, "added_at": date.fromisoformat(w["added_at"])})
        entry = WatchEntry(symbol=sym, notes=notes, added_at=_today())
        self._data["watch"].append(json.loads(entry.model_dump_json()))
        self._save()
        return entry

    def remove_watch(self, symbol: str) -> bool:
        sym = symbol.upper()
        before = len(self._data["watch"])
        self._data["watch"] = [w for w in self._data["watch"] if w["symbol"] != sym]
        if len(self._data["watch"]) < before:
            self._save()
            return True
        return False

    def list_watch(self) -> list[WatchEntry]:
        return [
            WatchEntry(**{**w, "added_at": date.fromisoformat(w["added_at"])})
            for w in self._data["watch"]
        ]

    # ---- rules ----
    def set_alert_rule(self, *, symbol: str, type: RuleType,
                       condition: AlertCondition, rule_id: Optional[str] = None) -> AlertRule:
        rid = rule_id or f"{symbol.lower()}-{type}-{uuid.uuid4().hex[:6]}"
        rule = AlertRule(
            id=rid, symbol=symbol, type=type, condition=condition,
            active=True, created_at=_today(),
        )
        self._data["rules"] = [r for r in self._data["rules"] if r["id"] != rid]
        self._data["rules"].append(json.loads(rule.model_dump_json()))
        self._save()
        return rule

    def list_alert_rules(self, symbol: Optional[str] = None) -> list[AlertRule]:
        out = []
        for r in self._data["rules"]:
            if symbol and r["symbol"] != symbol.upper():
                continue
            out.append(AlertRule(**{
                **r,
                "created_at": date.fromisoformat(r["created_at"]),
                "last_checked": (datetime.fromisoformat(r["last_checked"])
                                 if r.get("last_checked") else None),
            }))
        return out

    def remove_alert_rule(self, rule_id: str) -> bool:
        before = len(self._data["rules"])
        self._data["rules"] = [r for r in self._data["rules"] if r["id"] != rule_id]
        if len(self._data["rules"]) < before:
            self._save()
            return True
        return False

    def mark_checked(self, rule_id: str, at: datetime) -> None:
        for r in self._data["rules"]:
            if r["id"] == rule_id:
                r["last_checked"] = at.isoformat()
        self._save()
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_watchlist.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/src/psx_mcp/watchlist.py psx-mcp/tests/test_watchlist.py
git commit -m "feat(psx-mcp): JSON-backed watchlist & alert rules store"
```

---

### Task 11: Alert evaluator

**Files:**
- Create: `psx-mcp/src/psx_mcp/alerts.py`
- Create: `psx-mcp/tests/test_alerts.py`

- [ ] **Step 1: Write failing tests**

All seeded dates are **relative to `date.today()`** so tests don't bit-rot.

`tests/test_alerts.py`:
```python
from datetime import datetime, date, timedelta
import pytest

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.alerts import evaluate_rule, run_alerts
from psx_mcp.models import AlertRule, AlertCondition, Bar, Announcement


def _seed_bars(cache: Cache, symbol: str, closes: list[float],
               volumes: list[int] | None = None) -> None:
    volumes = volumes or [1000] * len(closes)
    bars = []
    end = date.today()
    n = len(closes)
    for i, (c, v) in enumerate(zip(closes, volumes)):
        bars.append(Bar(symbol=symbol, date=end - timedelta(days=(n - 1 - i)),
                        open=c, high=c, low=c, close=c, volume=v))
    cache.upsert_bars(bars)


def test_price_rule_triggers(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_quote(symbol="LUCK", ts=datetime.now(), price=850.0, change=10,
                   volume=1000, day_high=860, day_low=840, fetched_at=datetime.now())
    rule = AlertRule(id="r1", symbol="LUCK", type="price",
                     condition=AlertCondition(op=">", value=800),
                     active=True, created_at=date.today())
    hit = evaluate_rule(c, rule)
    assert hit is not None
    assert "850" in hit.message


def test_price_rule_does_not_trigger(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_quote(symbol="LUCK", ts=datetime.now(), price=750.0, change=0,
                   volume=0, day_high=0, day_low=0, fetched_at=datetime.now())
    rule = AlertRule(id="r1", symbol="LUCK", type="price",
                     condition=AlertCondition(op=">", value=800),
                     active=True, created_at=date.today())
    assert evaluate_rule(c, rule) is None


def test_indicator_rsi_oversold(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    _seed_bars(c, "LUCK", [float(x) for x in range(120, 80, -1)])  # 40 falling closes
    rule = AlertRule(id="r2", symbol="LUCK", type="indicator",
                     condition=AlertCondition(indicator="rsi14", op="<", value=40),
                     active=True, created_at=date.today())
    hit = evaluate_rule(c, rule)
    assert hit is not None


def test_volume_rule_triggers_on_spike(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    volumes = [1000] * 19 + [5000]
    _seed_bars(c, "LUCK", [100.0] * 20, volumes)
    rule = AlertRule(id="r3", symbol="LUCK", type="volume",
                     condition=AlertCondition(op=">", value=2.0, lookback_days=20),
                     active=True, created_at=date.today())
    hit = evaluate_rule(c, rule)
    assert hit is not None


def test_announcement_rule_triggers_for_new_filing(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_announcement(Announcement(
        id="a1", symbol="LUCK", posted_at=datetime.now() - timedelta(hours=1),
        title="Board Meeting", category=None, url=None, body=None,
    ))
    rule = AlertRule(id="r4", symbol="LUCK", type="announcement",
                     condition=AlertCondition(op=">", value=0),
                     active=True, created_at=date.today(),
                     last_checked=datetime.now() - timedelta(hours=2))
    hit = evaluate_rule(c, rule)
    assert hit is not None
    assert "Board Meeting" in hit.message


def test_announcement_rule_no_trigger_when_already_checked(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_announcement(Announcement(
        id="a1", symbol="LUCK", posted_at=datetime.now() - timedelta(hours=3),
        title="Board Meeting", category=None, url=None, body=None,
    ))
    rule = AlertRule(id="r4", symbol="LUCK", type="announcement",
                     condition=AlertCondition(op=">", value=0),
                     active=True, created_at=date.today(),
                     last_checked=datetime.now() - timedelta(hours=1))
    assert evaluate_rule(c, rule) is None


def test_run_alerts_iterates_active_rules(tmp_path):
    c = Cache(str(tmp_path / "t.db"))
    store = WatchlistStore(str(tmp_path / "wl.json"))
    c.upsert_quote(symbol="LUCK", ts=datetime.now(), price=900.0, change=0,
                   volume=0, day_high=0, day_low=0, fetched_at=datetime.now())
    store.set_alert_rule(symbol="LUCK", type="price",
                         condition=AlertCondition(op=">", value=800))
    hits = run_alerts(c, store)
    assert len(hits) == 1
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `alerts.py`**

`src/psx_mcp/alerts.py`:
```python
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
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/src/psx_mcp/alerts.py psx-mcp/tests/test_alerts.py
git commit -m "feat(psx-mcp): alert rule evaluation for price/indicator/volume/announcement"
```

---

### Task 12: MCP server — bootstrap, impl helpers, market-data tools

**Files:**
- Create: `psx-mcp/server.py`
- Create: `psx-mcp/tests/test_server.py`

**Architecture note:** every MCP tool is a thin `async def` wrapper around a sync `_<tool>_impl(cache, ...)` helper. Tests call the impl helpers directly with isolated dependencies. Tools themselves are exercised end-to-end by Task 17.

- [ ] **Step 1: Write failing tests**

`tests/test_server.py`:
```python
import pytest
from datetime import datetime, date, timedelta
from pathlib import Path

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.models import Bar
from psx_mcp.symbols import refresh_symbols_from_payload


@pytest.fixture
def deps(tmp_path, fixtures_dir):
    """Build server-module dependencies in isolation, seeded with fixtures + cached data."""
    import server as srv
    cache = Cache(str(tmp_path / "psx.db"))
    store = WatchlistStore(str(tmp_path / "wl.json"))
    # Seed symbol master from fixture so search works offline
    for ext in ("json", "html"):
        p = fixtures_dir / f"symbols.{ext}"
        if p.exists():
            refresh_symbols_from_payload(cache, p.read_text(encoding="utf-8"))
            break
    # Seed a quote
    cache.upsert_quote(symbol="LUCK", ts=datetime.now(), price=750.0,
                       change=10.0, volume=1000, day_high=760, day_low=740,
                       fetched_at=datetime.now())
    # Seed 30 days of bars ending today
    today = date.today()
    bars = [Bar(symbol="LUCK", date=today - timedelta(days=29 - i),
                open=700 + i, high=710 + i, low=695 + i, close=705 + i, volume=10000)
            for i in range(30)]
    cache.upsert_bars(bars)
    srv.set_dependencies(cache=cache, store=store, client=None)
    return srv


def test_get_quote_impl_returns_cached(deps):
    result = deps._get_quote_impl(deps._cache, "LUCK")
    assert result.symbol == "LUCK"
    assert result.price == 750.0
    assert "not investment advice" in result.disclaimer.lower()


def test_get_quote_handles_missing(deps):
    result = deps._get_quote_impl(deps._cache, "MISSING")
    assert result.stale is True


def test_change_pct_subrupee_safe(tmp_path):
    """Verify change_pct doesn't blow up on sub-rupee penny stocks (issue from review)."""
    import server as srv
    c = Cache(str(tmp_path / "t.db"))
    c.upsert_quote(symbol="PNY", ts=datetime.now(), price=0.5, change=0.05,
                   volume=1, day_high=0.55, day_low=0.45, fetched_at=datetime.now())
    srv.set_dependencies(cache=c, store=WatchlistStore(str(tmp_path / "w.json")), client=None)
    r = srv._get_quote_impl(c, "PNY")
    # prev close = 0.45 → change_pct ≈ 11.1
    assert 10.0 < r.change_pct < 12.0


def test_search_symbol_impl(deps):
    res = deps._search_symbol_impl(deps._cache, "LUCK")
    assert len(res) >= 1
    assert res[0].symbol == "LUCK"


def test_get_history_impl(deps):
    today = date.today()
    bars = deps._get_history_impl(deps._cache, "LUCK",
                                  (today - timedelta(days=30)).isoformat(),
                                  today.isoformat())
    assert len(bars) > 0
    assert bars[0].symbol == "LUCK"


def test_compute_indicators_impl(deps):
    out = deps._compute_indicators_impl(deps._cache, "LUCK",
                                        indicators=["rsi14", "sma10"], lookback_days=30)
    assert "rsi14" in out
    assert "sma10" in out
    assert isinstance(out["rsi14"], float)
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_server.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `server.py` bootstrap + first impls**

`server.py`:
```python
"""PSX MCP server — FastMCP entrypoint with sync impl helpers + async tool wrappers."""
from __future__ import annotations
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from mcp.server.fastmcp import FastMCP

from psx_mcp.cache import Cache
from psx_mcp.watchlist import WatchlistStore
from psx_mcp.psx_client import (
    PSXClient, parse_market_watch, parse_historical, parse_announcements,
    parse_profile, parse_financials, parse_financial_statements,
)
from psx_mcp.symbols import search_symbols
from psx_mcp.indicators import rsi, sma, ema, macd, bollinger, volume_zscore
from psx_mcp.df_utils import bars_df
from psx_mcp.alerts import run_alerts
from psx_mcp.news import FEEDS, parse_rss, find_symbol_mentions
from psx_mcp.models import (
    Quote, Bar, SymbolMatch, MarketSummary, Mover, CompanyInfo, Fundamentals,
    FinancialStatement, Announcement, NewsItem, WatchEntry, AlertRule,
    AlertCondition, AlertHit, VolumeSpike, ComparisonTable, ComparisonRow,
    DEFAULT_DISCLAIMER,
)
from psx_mcp.logging_config import configure_logging, get_logger

mcp = FastMCP(
    "psx-mcp",
    instructions=(
        "PSX (Pakistan Stock Exchange) research tools. "
        "Data is 15+ minutes delayed. Informational only — not investment advice. "
        "Call refresh_market before quote-based alerts; refresh_history for indicator/volume rules."
    ),
)
log = get_logger("server")

_cache: Optional[Cache] = None
_store: Optional[WatchlistStore] = None
_client: Optional[PSXClient] = None


def set_dependencies(*, cache: Cache, store: WatchlistStore,
                     client: Optional[PSXClient]) -> None:
    global _cache, _store, _client
    _cache, _store, _client = cache, store, client


# ============================================================================
# Impl helpers — sync, fully testable, no MCP / no asyncio dependencies
# ============================================================================

def _search_symbol_impl(cache: Cache, query: str, limit: int = 10) -> list[SymbolMatch]:
    rows = search_symbols(cache, query, limit=limit)
    return [SymbolMatch(**r) for r in rows]


def _get_quote_impl(cache: Cache, symbol: str) -> Quote:
    sym = symbol.upper()
    row = cache.get_latest_quote(sym)
    if not row:
        return Quote(
            symbol=sym, price=0, change=0, change_pct=0, volume=0,
            day_high=0, day_low=0, week52_high=0, week52_low=0,
            timestamp=datetime.now(), stale=True,
            summary=f"No data cached for {sym}. Try refresh_market first.",
        )
    fetched_at = datetime.fromisoformat(row["fetched_at"])
    stale = (datetime.now() - fetched_at).total_seconds() > 300
    prev_close = row["price"] - row["change"]
    change_pct = (row["change"] / prev_close * 100) if prev_close > 0 else 0.0
    return Quote(
        symbol=sym, price=row["price"], change=row["change"],
        change_pct=change_pct,
        volume=row["volume"], day_high=row["day_high"] or 0,
        day_low=row["day_low"] or 0, week52_high=0, week52_low=0,
        timestamp=datetime.fromisoformat(row["ts"]), stale=stale,
        summary=f"{sym} at {row['price']} ({row['change']:+.2f})",
    )


def _get_history_impl(cache: Cache, symbol: str, from_date: str, to_date: str,
                      interval: str = "1d") -> list[Bar]:
    if interval != "1d":
        raise ValueError("Only '1d' interval supported on free PSX data")
    rows = cache.get_bars(symbol, date.fromisoformat(from_date), date.fromisoformat(to_date))
    return [Bar(symbol=symbol, date=r["date"], open=r["open"], high=r["high"],
                low=r["low"], close=r["close"], volume=r["volume"]) for r in rows]


def _compute_indicators_impl(cache: Cache, symbol: str, indicators: list[str],
                              lookback_days: int = 200) -> dict:
    df = bars_df(cache, symbol, lookback_days)
    if df.empty:
        return {"error": f"No bars cached for {symbol}", "disclaimer": DEFAULT_DISCLAIMER}
    out: dict = {}
    for name in indicators:
        try:
            if name == "rsi14":
                out[name] = float(rsi(df["close"], 14).iloc[-1])
            elif name == "macd":
                m = macd(df["close"]).iloc[-1]
                out[name] = {"macd": float(m["macd"]), "signal": float(m["signal"]), "hist": float(m["hist"])}
            elif name.startswith("sma"):
                out[name] = float(sma(df["close"], int(name[3:])).iloc[-1])
            elif name.startswith("ema"):
                out[name] = float(ema(df["close"], int(name[3:])).iloc[-1])
            elif name == "bollinger":
                b = bollinger(df["close"]).iloc[-1]
                out[name] = {"upper": float(b["upper"]), "middle": float(b["middle"]), "lower": float(b["lower"])}
            elif name == "volume_z":
                out[name] = float(volume_zscore(df["volume"], 20).iloc[-1])
            else:
                out[name] = {"error": f"unknown indicator: {name}"}
        except (ValueError, IndexError, KeyError) as e:
            out[name] = {"error": str(e)}
    out["disclaimer"] = DEFAULT_DISCLAIMER
    return out


# ============================================================================
# Async MCP tool wrappers
# ============================================================================

@mcp.tool()
async def search_symbol(query: str, limit: int = 10) -> list[SymbolMatch]:
    """Fuzzy-match a PSX ticker or company name."""
    return _search_symbol_impl(_cache, query, limit)


@mcp.tool()
async def get_quote(symbol: str) -> Quote:
    """Latest cached quote for a PSX symbol (15-min delayed)."""
    return _get_quote_impl(_cache, symbol)


@mcp.tool()
async def get_history(symbol: str, from_date: str, to_date: str, interval: str = "1d") -> list[Bar]:
    """Historical OHLCV. Free PSX data is daily only."""
    return _get_history_impl(_cache, symbol, from_date, to_date, interval)


@mcp.tool()
async def compute_indicators(symbol: str, indicators: list[str], lookback_days: int = 200) -> dict:
    """Compute one or more indicators from cached daily bars."""
    return _compute_indicators_impl(_cache, symbol, indicators, lookback_days)


if __name__ == "__main__":
    configure_logging()
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    set_dependencies(
        cache=Cache(str(data_dir / "psx.db")),
        store=WatchlistStore(str(data_dir / "watchlist.json")),
        client=PSXClient(),
    )
    log.info("psx-mcp server starting on http://127.0.0.1:8765/sse")
    mcp.run(transport="sse")
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): FastMCP server bootstrap + market-data impls"
```

---

### Task 13: Live refresh impls — market_summary, top_movers, refresh_market

**Files:**
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:
```python
import asyncio
import httpx
import respx
from psx_mcp.psx_client import PSXClient, BASE_DPS


@pytest.fixture
def deps_with_client(deps):
    """Same as `deps` but with a real PSXClient (network mocked via respx in each test)."""
    deps.set_dependencies(cache=deps._cache, store=deps._store, client=PSXClient())
    return deps


@respx.mock
def test_refresh_market_impl_populates_cache(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "market_watch.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_DPS}/market-watch").mock(return_value=httpx.Response(200, text=html))
    n = asyncio.run(deps_with_client._refresh_market_impl(deps_with_client._cache,
                                                           deps_with_client._client))
    assert n > 100


@respx.mock
def test_get_top_movers_after_refresh(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "market_watch.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_DPS}/market-watch").mock(return_value=httpx.Response(200, text=html))
    asyncio.run(deps_with_client._refresh_market_impl(deps_with_client._cache,
                                                       deps_with_client._client))
    gainers = deps_with_client._get_top_movers_impl(deps_with_client._cache, kind="gainers", limit=5)
    assert len(gainers) <= 5


def test_market_summary_returns_stale_when_empty(deps):
    s = deps._get_market_summary_impl(deps._cache)
    assert s.timestamp
    assert s.stale is True
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_server.py -v -k "refresh or top_movers or market_summary"`
Expected: AttributeError.

- [ ] **Step 3: Add impls + async tool wrappers to `server.py`**

Insert after `_compute_indicators_impl` in `server.py`:
```python
async def _refresh_market_impl(cache: Cache, client: Optional[PSXClient]) -> int:
    if not client:
        return 0
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
    log.info("market_refresh", count=len(rows))
    return len(rows)


def _get_market_summary_impl(cache: Cache) -> MarketSummary:
    kse100_row = cache.get_latest_quote("KSE100")
    return MarketSummary(
        kse100=(kse100_row or {}).get("price") or 0.0,
        kse100_change=(kse100_row or {}).get("change") or 0.0,
        sectors=[],
        timestamp=datetime.now(),
        stale=kse100_row is None,
        summary="KSE-100 snapshot — call refresh_market() first if stale.",
    )


def _get_top_movers_impl(cache: Cache, kind: str = "gainers", limit: int = 10) -> list[Mover]:
    rows = cache.conn.execute(
        """SELECT q.symbol, q.price, q.change, q.volume, s.name
           FROM quotes q LEFT JOIN symbols s ON s.symbol=q.symbol
           WHERE q.ts = (SELECT MAX(ts) FROM quotes q2 WHERE q2.symbol=q.symbol)
           AND q.price > 0"""
    ).fetchall()
    movers = []
    for r in rows:
        d = dict(r)
        prev_close = d["price"] - d["change"]
        change_pct = (d["change"] / prev_close * 100) if prev_close > 0 else 0.0
        movers.append(Mover(symbol=d["symbol"], name=d.get("name"),
                            price=d["price"], change_pct=change_pct, volume=d["volume"]))
    if kind == "gainers":
        movers.sort(key=lambda m: m.change_pct, reverse=True)
    elif kind == "losers":
        movers.sort(key=lambda m: m.change_pct)
    elif kind == "volume":
        movers.sort(key=lambda m: m.volume, reverse=True)
    else:
        raise ValueError(f"unknown kind: {kind}")
    return movers[:limit]


@mcp.tool()
async def refresh_market() -> int:
    """Force a refresh of the market-watch snapshot. Returns quotes upserted."""
    return await _refresh_market_impl(_cache, _client)


@mcp.tool()
async def get_market_summary() -> MarketSummary:
    """Index levels + sector aggregates. Best-effort from cached snapshot."""
    return _get_market_summary_impl(_cache)


@mcp.tool()
async def get_top_movers(kind: str = "gainers", limit: int = 10) -> list[Mover]:
    """kind: 'gainers' | 'losers' | 'volume'."""
    return _get_top_movers_impl(_cache, kind, limit)
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): refresh_market, market_summary, top_movers"
```

---

### Task 14: Fundamentals, company info, history-refresh, announcements, news, financials

**Files:**
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:
```python
from psx_mcp.psx_client import BASE_PSX


@respx.mock
def test_get_company_info_fetches_and_caches(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "profile_LUCK.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_PSX}/psx/profile/LUCK").mock(return_value=httpx.Response(200, text=html))
    info = asyncio.run(deps_with_client._get_company_info_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK"))
    assert info.symbol == "LUCK"
    assert info.name


@respx.mock
def test_get_fundamentals(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "financial_LUCK.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_PSX}/psx/quote/financial-information/LUCK").mock(
        return_value=httpx.Response(200, text=html))
    f = asyncio.run(deps_with_client._get_fundamentals_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK"))
    assert f.symbol == "LUCK"


@respx.mock
def test_get_financials_statements(deps_with_client, fixtures_dir):
    html = (fixtures_dir / "financial_LUCK.html").read_text(encoding="utf-8")
    respx.get(f"{BASE_PSX}/psx/quote/financial-information/LUCK").mock(
        return_value=httpx.Response(200, text=html))
    out = asyncio.run(deps_with_client._get_financials_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK", "annual"))
    assert isinstance(out, list)


@respx.mock
def test_refresh_history_persists_bars(deps_with_client, fixtures_dir):
    for ext in ("json", "html"):
        p = fixtures_dir / f"historical_LUCK.{ext}"
        if p.exists():
            payload = p.read_text(encoding="utf-8")
            break
    respx.get(f"{BASE_DPS}/historical/LUCK").mock(return_value=httpx.Response(200, text=payload))
    n = asyncio.run(deps_with_client._refresh_history_impl(
        deps_with_client._cache, deps_with_client._client, "LUCK"))
    assert n >= 0  # may be 0 if fixture is empty


@respx.mock
def test_refresh_and_get_announcements(deps_with_client, fixtures_dir):
    for ext in ("json", "html"):
        p = fixtures_dir / f"announcements.{ext}"
        if p.exists():
            payload = p.read_text(encoding="utf-8")
            break
    respx.get(f"{BASE_DPS}/announcements/companies").mock(
        return_value=httpx.Response(200, text=payload))
    asyncio.run(deps_with_client._refresh_announcements_impl(
        deps_with_client._cache, deps_with_client._client))
    anns = deps_with_client._get_announcements_impl(deps_with_client._cache, None, since_days=365)
    assert isinstance(anns, list)
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_server.py -v -k "company_info or fundamentals or refresh_history or announcements or financials_statements"`
Expected: AttributeError.

- [ ] **Step 3: Add impls + tools to `server.py`**

Insert before `if __name__ == "__main__":`:
```python
async def _get_company_info_impl(cache: Cache, client: Optional[PSXClient], symbol: str) -> CompanyInfo:
    sym = symbol.upper()
    cached = cache.get_symbol(sym)
    age = cache.symbols_master_age_seconds()
    if cached and age is not None and age < 7 * 86400 and cached.get("name"):
        return CompanyInfo(
            symbol=sym, name=cached["name"], sector=cached.get("sector"),
            listed_shares=cached.get("listed_shares"),
        )
    if not client:
        return CompanyInfo(symbol=sym, name=(cached or {}).get("name") or sym)
    html = await client.fetch_profile(sym)
    info = parse_profile(sym, html)
    cache.upsert_symbol(sym, info.name, info.sector, info.listed_shares)
    return info


async def _get_fundamentals_impl(cache: Cache, client: Optional[PSXClient], symbol: str) -> Fundamentals:
    sym = symbol.upper()
    age = cache.fundamentals_age_seconds(sym)
    if age is not None and age < 86400:
        row = cache.get_fundamentals(sym)
        return Fundamentals(
            symbol=sym, eps=row["eps"], pe=row["pe"], pb=row["pb"],
            div_yield=row["div_yield"], payout=row["payout"], roe=row["roe"],
            refreshed_at=datetime.fromisoformat(row["refreshed_at"]),
        )
    if not client:
        row = cache.get_fundamentals(sym)
        if not row:
            return Fundamentals(symbol=sym)
        return Fundamentals(
            symbol=sym, eps=row["eps"], pe=row["pe"], pb=row["pb"],
            div_yield=row["div_yield"], payout=row["payout"], roe=row["roe"],
        )
    html = await client.fetch_financials(sym)
    f = parse_financials(sym, html)
    cache.upsert_fundamentals(symbol=sym, eps=f.eps, pe=f.pe, pb=f.pb,
                              div_yield=f.div_yield, payout=f.payout, roe=f.roe)
    return f


async def _get_financials_impl(cache: Cache, client: Optional[PSXClient],
                                symbol: str, period: str = "annual") -> list[FinancialStatement]:
    if period not in ("annual", "quarterly"):
        raise ValueError("period must be 'annual' or 'quarterly'")
    if not client:
        return []
    html = await client.fetch_financials(symbol)
    return parse_financial_statements(symbol, period, html)


async def _refresh_history_impl(cache: Cache, client: Optional[PSXClient], symbol: str) -> int:
    if not client:
        return 0
    payload = await client.fetch_historical(symbol)
    bars = parse_historical(symbol, payload)
    cache.upsert_bars(bars)
    return len(bars)


async def _refresh_announcements_impl(cache: Cache, client: Optional[PSXClient]) -> int:
    if not client:
        return 0
    payload = await client.fetch_announcements()
    items = parse_announcements(payload)
    for a in items:
        cache.upsert_announcement(a)
    log.info("announcements_refresh", count=len(items))
    return len(items)


def _get_announcements_impl(cache: Cache, symbol: Optional[str], since_days: int) -> list[Announcement]:
    since = datetime.now() - timedelta(days=since_days)
    rows = cache.get_announcements(symbol=symbol, since=since)
    return [Announcement(
        id=r["id"], symbol=r.get("symbol"), posted_at=r["posted_at"],
        title=r["title"], category=r.get("category"), url=r.get("url"), body=r.get("body"),
    ) for r in rows]


async def _refresh_news_impl(cache: Cache, client: Optional[PSXClient]) -> int:
    if not client:
        return 0
    universe = {s["symbol"] for s in cache.all_symbols()}
    total = 0
    for source, url in FEEDS.items():
        try:
            xml = await client._get(url)
        except Exception as e:
            log.warning("news_fetch_failed", source=source, error=str(e))
            continue
        items = parse_rss(source, xml)
        for it in items:
            mentions = find_symbol_mentions(it.title, "", universe)
            cache.upsert_news(id=it.id, source=it.source, posted_at=it.posted_at,
                              title=it.title, url=it.url, symbols=mentions)
            total += 1
    return total


def _get_news_impl(cache: Cache, symbol: Optional[str], since_days: int) -> list[NewsItem]:
    since = datetime.now() - timedelta(days=since_days)
    rows = cache.get_news(symbol=symbol, since=since)
    return [NewsItem(id=r["id"], source=r["source"], posted_at=r["posted_at"],
                     title=r["title"], url=r["url"], symbols=r["symbols"]) for r in rows]


@mcp.tool()
async def get_company_info(symbol: str) -> CompanyInfo:
    """Profile, sector, listed shares. Fetches & caches on first call."""
    return await _get_company_info_impl(_cache, _client, symbol)


@mcp.tool()
async def get_fundamentals(symbol: str) -> Fundamentals:
    """EPS, P/E, P/B, dividend yield. Cached for 1 day."""
    return await _get_fundamentals_impl(_cache, _client, symbol)


@mcp.tool()
async def get_financials(symbol: str, period: str = "annual") -> list[FinancialStatement]:
    """Best-effort annual/quarterly financial statements from PSX filings."""
    return await _get_financials_impl(_cache, _client, symbol, period)


@mcp.tool()
async def refresh_history(symbol: str) -> int:
    """Pull daily bars for a symbol from PSX and append to cache."""
    return await _refresh_history_impl(_cache, _client, symbol)


@mcp.tool()
async def refresh_announcements() -> int:
    """Pull recent corporate announcements and cache them."""
    return await _refresh_announcements_impl(_cache, _client)


@mcp.tool()
async def get_announcements(symbol: Optional[str] = None, since_days: int = 7) -> list[Announcement]:
    """Cached corporate announcements; symbol=None returns all."""
    return _get_announcements_impl(_cache, symbol, since_days)


@mcp.tool()
async def refresh_news() -> int:
    """Pull all configured RSS feeds, tag symbol mentions, cache items."""
    return await _refresh_news_impl(_cache, _client)


@mcp.tool()
async def get_news(symbol: Optional[str] = None, since_days: int = 3) -> list[NewsItem]:
    """Cached news items; filter by symbol mention if provided."""
    return _get_news_impl(_cache, symbol, since_days)
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): fundamentals, company info, financials, history/announcements/news"
```

---

### Task 15: Watchlist + alerts tools + analysis helpers

**Files:**
- Modify: `psx-mcp/server.py`
- Modify: `psx-mcp/tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:
```python
def test_watchlist_lifecycle(deps):
    e = deps._add_to_watchlist_impl(deps._store, "OGDC", "energy")
    assert e.symbol == "OGDC"
    assert any(w.symbol == "OGDC" for w in deps._list_watchlist_impl(deps._store))
    assert deps._remove_from_watchlist_impl(deps._store, "OGDC") is True


def test_alert_rule_lifecycle(deps):
    rule = deps._set_alert_rule_impl(deps._store, symbol="LUCK", type="price",
                                     condition={"op": ">", "value": 700})
    assert rule.id
    rules = deps._list_alert_rules_impl(deps._store, symbol="LUCK")
    assert len(rules) == 1
    assert deps._remove_alert_rule_impl(deps._store, rule.id) is True


def test_check_alerts_returns_hits(deps):
    deps._set_alert_rule_impl(deps._store, symbol="LUCK", type="price",
                              condition={"op": ">", "value": 700})
    hits = deps._check_alerts_impl(deps._cache, deps._store, symbols=None)
    assert any(h.symbol == "LUCK" for h in hits)


def test_scan_volume_spikes(deps):
    spikes = deps._scan_volume_spikes_impl(deps._cache, symbols=["LUCK"],
                                            multiplier=0.001, lookback_days=10)
    assert isinstance(spikes, list)


def test_compare_symbols(deps):
    out = deps._compare_symbols_impl(deps._cache, symbols=["LUCK"], metrics=["price", "rsi14"])
    assert len(out.rows) == 1
    assert out.rows[0].symbol == "LUCK"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_server.py -v -k "watchlist or alert or scan_volume or compare"`
Expected: AttributeError.

- [ ] **Step 3: Add impls + tools to `server.py`**

Insert before `if __name__ == "__main__":`:
```python
# ---- watchlist & alerts ----

def _list_watchlist_impl(store: WatchlistStore) -> list[WatchEntry]:
    return store.list_watch()


def _add_to_watchlist_impl(store: WatchlistStore, symbol: str,
                            notes: Optional[str] = None) -> WatchEntry:
    return store.add_watch(symbol, notes)


def _remove_from_watchlist_impl(store: WatchlistStore, symbol: str) -> bool:
    return store.remove_watch(symbol)


def _set_alert_rule_impl(store: WatchlistStore, *, symbol: str, type: str,
                          condition: dict) -> AlertRule:
    cond = AlertCondition(**condition)
    return store.set_alert_rule(symbol=symbol, type=type, condition=cond)


def _list_alert_rules_impl(store: WatchlistStore, symbol: Optional[str] = None) -> list[AlertRule]:
    return store.list_alert_rules(symbol)


def _remove_alert_rule_impl(store: WatchlistStore, rule_id: str) -> bool:
    return store.remove_alert_rule(rule_id)


def _check_alerts_impl(cache: Cache, store: WatchlistStore,
                        symbols: Optional[list[str]] = None) -> list[AlertHit]:
    return run_alerts(cache, store, symbols=symbols)


def _scan_volume_spikes_impl(cache: Cache, symbols: Optional[list[str]],
                              multiplier: float, lookback_days: int) -> list[VolumeSpike]:
    if not symbols:
        symbols = [s["symbol"] for s in cache.all_symbols()]
    out: list[VolumeSpike] = []
    for sym in symbols:
        df = bars_df(cache, sym, lookback_days)
        if len(df) < 5:
            continue
        today_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else 0.0
        mult = today_vol / avg_vol if avg_vol else 0.0
        if mult >= multiplier:
            out.append(VolumeSpike(symbol=sym, today_volume=int(today_vol),
                                    avg_volume=avg_vol, multiplier=mult))
    out.sort(key=lambda v: v.multiplier, reverse=True)
    return out


def _compare_symbols_impl(cache: Cache, symbols: list[str], metrics: list[str]) -> ComparisonTable:
    rows: list[ComparisonRow] = []
    for sym in symbols:
        m: dict = {}
        q = cache.get_latest_quote(sym)
        f = cache.get_fundamentals(sym)
        df = bars_df(cache, sym, lookback_days=400)
        for name in metrics:
            if name == "price":
                m[name] = q["price"] if q else None
            elif name == "rsi14" and not df.empty and len(df) >= 14:
                m[name] = float(rsi(df["close"], 14).iloc[-1])
            elif name.startswith("sma") and not df.empty:
                window = int(name[3:])
                m[name] = float(sma(df["close"], window).iloc[-1]) if len(df) >= window else None
            elif name in ("pe", "eps", "pb", "div_yield", "payout", "roe"):
                m[name] = (f or {}).get(name)
            else:
                m[name] = None
        rows.append(ComparisonRow(symbol=sym, metrics=m))
    return ComparisonTable(metrics=metrics, rows=rows)


@mcp.tool()
async def list_watchlist() -> list[WatchEntry]:
    return _list_watchlist_impl(_store)


@mcp.tool()
async def add_to_watchlist(symbol: str, notes: Optional[str] = None) -> WatchEntry:
    return _add_to_watchlist_impl(_store, symbol, notes)


@mcp.tool()
async def remove_from_watchlist(symbol: str) -> bool:
    return _remove_from_watchlist_impl(_store, symbol)


@mcp.tool()
async def set_alert_rule(symbol: str, type: str, condition: dict) -> AlertRule:
    """Create or replace an alert rule.

    type: 'price' | 'indicator' | 'volume' | 'announcement'
    condition: {indicator?, op, value, lookback_days?}
    """
    return _set_alert_rule_impl(_store, symbol=symbol, type=type, condition=condition)


@mcp.tool()
async def list_alert_rules(symbol: Optional[str] = None) -> list[AlertRule]:
    return _list_alert_rules_impl(_store, symbol)


@mcp.tool()
async def remove_alert_rule(rule_id: str) -> bool:
    return _remove_alert_rule_impl(_store, rule_id)


@mcp.tool()
async def check_alerts(symbols: Optional[list[str]] = None) -> list[AlertHit]:
    """Evaluate all (or selected) alert rules against latest cached data."""
    return _check_alerts_impl(_cache, _store, symbols)


@mcp.tool()
async def scan_volume_spikes(symbols: Optional[list[str]] = None,
                              multiplier: float = 2.0,
                              lookback_days: int = 20) -> list[VolumeSpike]:
    """Find symbols whose latest volume is >= multiplier * recent average."""
    return _scan_volume_spikes_impl(_cache, symbols, multiplier, lookback_days)


@mcp.tool()
async def compare_symbols(symbols: list[str], metrics: list[str]) -> ComparisonTable:
    """Side-by-side metric table. metrics: price | rsi14 | sma50 | sma200 | pe | eps | div_yield | …"""
    return _compare_symbols_impl(_cache, symbols, metrics)
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add psx-mcp/server.py psx-mcp/tests/test_server.py
git commit -m "feat(psx-mcp): watchlist, alert tools, scan_volume_spikes, compare_symbols"
```

---

### Task 16: Run script + README

**Files:**
- Create: `psx-mcp/run-psx-mcp.ps1`
- Create: `psx-mcp/README.md`

- [ ] **Step 1: Create the launcher script**

`run-psx-mcp.ps1`:
```powershell
# Launch the PSX MCP server on http://127.0.0.1:8765/sse
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
uv run python server.py
```

- [ ] **Step 2: Write the README**

Note: outer fence in README uses `~~~` to avoid nested-backtick collision when rendered.

`README.md`:
~~~markdown
# PSX MCP Server

Local MCP server exposing PSX (Pakistan Stock Exchange) research tools and on-demand alerts.

**Data is 15+ minutes delayed.** Informational only — not investment advice.

## Install

```powershell
cd C:\Users\pc\work\stocks\psx-mcp
uv sync --extra dev
```

## Capture fixtures (first time only)

```powershell
uv run python scripts/capture_fixtures.py
uv run python scripts/capture_rss.py
```

## Run

```powershell
.\run-psx-mcp.ps1
```

Server listens on `http://127.0.0.1:8765/sse`.

## Register with Claude Code

```powershell
claude mcp add --transport sse psx http://127.0.0.1:8765/sse
```

## Test

```powershell
uv run pytest
```

Live smoke test (gated, hits real PSX):

```powershell
$env:PSX_LIVE="1"; uv run pytest tests/test_live.py
```

## Tools

| Tool | Purpose |
|---|---|
| `search_symbol` | fuzzy ticker/name match |
| `get_quote` | latest cached quote |
| `get_history` | daily OHLCV from cache |
| `get_market_summary` | KSE-100 snapshot |
| `get_top_movers` | gainers/losers/volume |
| `refresh_market` | force-pull market snapshot |
| `refresh_history` | force-pull history for one symbol |
| `refresh_announcements` | force-pull announcements |
| `refresh_news` | force-pull RSS feeds |
| `get_announcements` | cached corporate announcements |
| `get_news` | cached news, filterable by symbol |
| `get_company_info` | profile + listed shares |
| `get_fundamentals` | EPS, P/E, P/B, etc. |
| `get_financials` | annual/quarterly statements (best-effort) |
| `list_watchlist` / `add_to_watchlist` / `remove_from_watchlist` | watchlist mgmt |
| `set_alert_rule` / `list_alert_rules` / `remove_alert_rule` | rule mgmt |
| `check_alerts` | on-demand alert scan |
| `compute_indicators` | RSI/MACD/SMA/EMA/Bollinger/vol-z |
| `scan_volume_spikes` | volume-spike scanner |
| `compare_symbols` | side-by-side metric table |

## Usage tips

- Call `refresh_market` before `check_alerts` for fresh quote-based rules.
- Indicator/volume rules need history — call `refresh_history` for watched symbols first.
- `data/psx.db` and `data/watchlist.json` persist between runs.
~~~

- [ ] **Step 3: Commit**

```powershell
git add psx-mcp/run-psx-mcp.ps1 psx-mcp/README.md
git commit -m "docs(psx-mcp): README + launcher script"
```

---

### Task 17: Live smoke test (gated)

**Files:**
- Create: `psx-mcp/tests/test_live.py`

- [ ] **Step 1: Write the live test (skipped by default)**

`tests/test_live.py`:
```python
import os
import pytest
from psx_mcp.psx_client import PSXClient, parse_market_watch

LIVE = os.environ.get("PSX_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="set PSX_LIVE=1 to run")


@pytest.mark.asyncio
async def test_market_watch_live():
    c = PSXClient()
    try:
        html = await c.fetch_market_watch()
        rows = parse_market_watch(html)
        assert len(rows) > 100
    finally:
        await c.close()
```

- [ ] **Step 2: Verify gated test is skipped by default**

Run: `uv run pytest tests/test_live.py -v`
Expected: `1 skipped`.

- [ ] **Step 3: Run live (optional sanity check)**

Run:
```powershell
$env:PSX_LIVE="1"; uv run pytest tests/test_live.py -v
```
Expected: pass. If it fails, the live PSX site shape may have changed — re-run `scripts/capture_fixtures.py` and adapt parsers.

- [ ] **Step 4: Commit**

```powershell
git add psx-mcp/tests/test_live.py
git commit -m "test(psx-mcp): live smoke test, gated by PSX_LIVE"
```

---

### Task 18: Register MCP and end-to-end manual verification

- [ ] **Step 1: Start the server**

In one PowerShell window from `psx-mcp/`:
```powershell
.\run-psx-mcp.ps1
```
Expected: log line `psx-mcp server starting on http://127.0.0.1:8765/sse`.

- [ ] **Step 2: Register with Claude Code**

In another window:
```powershell
claude mcp add --transport sse psx http://127.0.0.1:8765/sse
claude mcp list
```
Expected: `psx` listed and healthy.

- [ ] **Step 3: Manual verification checklist (run inside a Claude Code session)**

Ask Claude in a new session:
1. `Use the psx MCP to refresh the market and tell me the top 5 gainers.` → expect a list with prices & %s.
2. `Get the latest quote and 90-day chart for LUCK.` → quote + bars returned.
3. `Add LUCK to my watchlist and set an alert when RSI(14) drops below 30.` → entry + rule created.
4. `Check my alerts.` → returns hits (likely empty).
5. `Compare LUCK and DGKC on price, P/E, RSI(14).` → table returned (after `refresh_history` on both).

If any step errors, fix the underlying tool; do not silence the test.

- [ ] **Step 4: Commit any final fixes**

```powershell
git add -A
git commit -m "chore(psx-mcp): post-verification fixes" --allow-empty
```

---

## Self-Review

Ran the self-review checks against the spec:

1. **Spec coverage** — every spec section maps to a task:
   - §3 Architecture → Tasks 1, 12, 16
   - §4 Tool surface — every tool listed in spec is now implemented:
     - market data → Tasks 12, 13
     - fundamentals (including `get_financials`) → Task 14
     - announcements & news → Task 14
     - watchlist & alerts → Task 15
     - analysis helpers → Tasks 12, 15
   - §5 Data sources → Task 7 (intraday `/timeseries/int/<SYM>` explicitly deferred — daily covers all needs)
   - §6 Storage → Task 4
   - §7 Error handling → `PSXClient._get` retries (Task 7), `stale=True` quotes (Task 12), parser fallbacks (Task 7)
   - §8 Disclaimers → `DEFAULT_DISCLAIMER` on every Disclaimer-derived model (Task 2), repeated in `FastMCP(..., instructions=...)` (Task 12)
   - §9 Testing → fixture-driven tests in Tasks 4–15, gated live test in Task 17
   - §10 Dependencies → Task 1
   - §11 Registration → Task 18

2. **Placeholders** — no TBD/TODO. The fixture-capture step in Task 7 has explicit "stop and report" guidance instead of vague language. Parsers handle both JSON and HTML payloads via `_try_json`.

3. **Type / signature consistency**:
   - `Quote`, `Bar`, `AlertRule`, `AlertCondition`, `WatchEntry`, `FinancialStatement` defined once in Task 2; used identically in Tasks 4, 7, 11, 14.
   - `_impl` helper signatures match between implementation (`server.py`) and tests (`test_server.py`).
   - `bars_df` is the single shared DataFrame helper, used by `alerts.py`, `_compute_indicators_impl`, `_scan_volume_spikes_impl`, `_compare_symbols_impl`.

4. **Critic-pass blockers from prior review — all addressed**:
   - B1 (Pydantic validator) → fixed: all validators are `@field_validator(..., mode="before")` + `@classmethod`
   - B2 (asyncio runner) → fixed: tools are `async def`, no `_async` helper; tests use `asyncio.run(...)` directly
   - B3 (FastMCP tools as callables) → fixed: every tool body delegates to a sync/async `_<name>_impl(...)` helper that tests exercise directly
   - B4 (PowerShell here-strings) → fixed: discovery scripts at `scripts/capture_fixtures.py` and `scripts/capture_rss.py`
   - B5 (JSON-only parsers) → fixed: `_try_json` helper + dual-path parsers in `parse_historical`, `parse_symbols`, `parse_announcements`
   - M1 (missing `get_financials`) → fixed: added in Task 14 with `parse_financial_statements`
   - M2 (intraday endpoint) → fixed: dropped from capture, deferred explicitly
   - M3 (`change_pct` for sub-rupee) → fixed: explicit `prev_close > 0` guard; test included
   - M5 (`PARSE_DECLTYPES`) → fixed: removed
   - M6 (hardcoded test dates) → fixed: all test bar seeding is relative to `date.today()`
   - m7 (FastMCP instructions) → fixed: passed via `FastMCP(..., instructions=...)`

No outstanding issues.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-psx-mcp-implementation.md`.

User has chosen **subagent-driven development** for execution. After this critic pass, dispatch a final critic if any major changes were made; otherwise begin task-by-task implementation via `superpowers:subagent-driven-development`.
