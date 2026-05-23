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
