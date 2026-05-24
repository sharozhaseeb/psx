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


class FundamentalsHistoryPoint(BaseModel):
    symbol: str
    fiscal_year: int
    eps: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    div_yield: Optional[float] = None
    payout: Optional[float] = None
    roe: Optional[float] = None
    gross_margin: Optional[float] = None
    net_income: Optional[float] = None
    cfo: Optional[float] = None
    revenue: Optional[float] = None
    total_assets: Optional[float] = None
    long_term_debt: Optional[float] = None
    current_liab: Optional[float] = None
    current_assets: Optional[float] = None
    shares_outstanding: Optional[float] = None
    source_url: Optional[str] = None
    refreshed_at: str  # ISO string from cache

    @field_validator("symbol", mode="before")
    @classmethod
    def _u(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class IndexHistoryPoint(BaseModel):
    index_code: str
    bar_date: date  # schema declares NOT NULL, so always present
    close: float
    volume: Optional[float] = None


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


class ScreenResponse(Disclaimer):
    results: list[dict]
    count: int


class SectorSummaryResponse(Disclaimer):
    sector: str
    n: int
    median_pe: Optional[float] = None
    avg_change_pct: Optional[float] = None
    pct_above_sma200: Optional[float] = None
    top_5_by_change: list[dict] = []
    bottom_5_by_change: list[dict] = []


class BetaResponse(Disclaimer):
    symbol: str
    index_code: str
    window: int
    beta: Optional[float]
    alpha: Optional[float]
    r_squared: Optional[float]
    n: int
    note: Optional[str] = None


class QualityScoreResponse(Disclaimer):
    symbol: str
    score: float
    snapshot: dict


class QuadrantScoreResponse(Disclaimer):
    symbol: str
    value: int
    quality: int
    momentum: int
    trend: int
    total: int
    raw: dict


class DividendEvent(BaseModel):
    announcement_id: str
    symbol: str
    ex_date: Optional[date] = None
    announcement_date: Optional[date] = None
    payout_type: Optional[str] = None
    per_share: Optional[float] = None
    bonus_pct: Optional[float] = None

    # Cache stores empty-string dates as "" sometimes; coerce -> None.
    @field_validator("ex_date", "announcement_date", mode="before")
    @classmethod
    def _coerce_blank_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v
