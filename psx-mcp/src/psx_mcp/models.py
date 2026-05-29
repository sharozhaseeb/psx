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
RuleType = Literal["price", "indicator", "volume", "announcement", "fundamental"]


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
    warnings: list[str] = []


class SectorSummaryResponse(Disclaimer):
    sector: str
    n: int
    median_pe: Optional[float] = None
    avg_change_pct: Optional[float] = None
    pct_above_sma200: Optional[float] = None
    top_5_by_change: list[dict] = []
    bottom_5_by_change: list[dict] = []


class SectorRankResponse(Disclaimer):
    metric: str
    desc: bool
    rows: list[dict]
    note: Optional[str] = None


class UniverseRankResponse(Disclaimer):
    metric: str
    sector: Optional[str] = None
    limit: int
    rows: list[dict]
    note: Optional[str] = None


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
    warnings: list[str] = []


class DrawdownResponse(Disclaimer):
    symbol: str
    drawdown_pct: float
    max_drawdown_pct: float
    peak: Optional[float] = None
    current: Optional[float] = None
    note: Optional[str] = None


class RiskMetricsResponse(Disclaimer):
    symbol: str
    volatility_annualized: float
    sharpe: Optional[float] = None
    max_drawdown_pct: float
    n_bars: int
    rf_annual: float = 0.0
    note: Optional[str] = None


class ReturnStatsResponse(Disclaimer):
    symbol: str
    cagr_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    rolling_return_window_days: int
    rolling_returns_best_pct: Optional[float] = None
    rolling_returns_worst_pct: Optional[float] = None
    rolling_returns_median_pct: Optional[float] = None
    n_bars: int
    note: Optional[str] = None


class DistributionStatsResponse(Disclaimer):
    symbol: str
    skewness: Optional[float] = None
    excess_kurtosis: Optional[float] = None
    var_5pct_pct: Optional[float] = None
    cvar_5pct_pct: Optional[float] = None
    tail_ratio_5pct: Optional[float] = None
    n_bars: int
    note: Optional[str] = None


class DrawdownDetailsResponse(Disclaimer):
    symbol: str
    max_drawdown_pct: float
    peak_index: Optional[int] = None
    trough_index: Optional[int] = None
    recovery_index: Optional[int] = None
    drawdown_duration_bars: Optional[int] = None
    recovery_duration_bars: Optional[int] = None
    ulcer_index: Optional[float] = None
    top_drawdowns: list[dict] = []
    n_bars: int
    note: Optional[str] = None


class UpDownCaptureResponse(Disclaimer):
    symbol: str
    index_code: str
    up_capture_pct: Optional[float] = None
    down_capture_pct: Optional[float] = None
    n_up_periods: int = 0
    n_down_periods: int = 0
    n_aligned_bars: int = 0
    note: Optional[str] = None


class RelativeStrengthResponse(Disclaimer):
    symbol: str
    index_code: str
    window: int
    relative_strength_pct: Optional[float] = None
    stock_return_pct: Optional[float] = None
    index_return_pct: Optional[float] = None
    n_bars: int
    note: Optional[str] = None


class CorrelationMatrixResponse(Disclaimer):
    symbols: list[str]
    matrix: dict[str, dict[str, Optional[float]]]
    note: Optional[str] = None


class PositionSizeResponse(Disclaimer):
    symbol: str
    portfolio_value: float
    risk_pct: float
    stop_atr_mult: float
    price: Optional[float] = None
    atr: Optional[float] = None
    risk_budget: float
    risk_per_share: Optional[float] = None
    qty: Optional[int] = None
    notional: Optional[float] = None
    note: Optional[str] = None


class FullAnalysisResponse(Disclaimer):
    symbol: str
    quote: Optional[dict] = None
    fundamentals: Optional[dict] = None
    week52: Optional[dict] = None
    indicators: Optional[dict] = None
    drawdown: Optional[dict] = None
    risk: Optional[dict] = None
    beta: Optional[dict] = None
    relative_strength: Optional[dict] = None
    quadrant_score: Optional[dict] = None
    dividend_history_recent: list[dict] = []
    announcements_recent: list[dict] = []
    warnings: list[str] = []


class ExtendedRiskMetricsResponse(Disclaimer):
    symbol: str
    return_stats: Optional[dict] = None
    risk_adjusted: Optional[dict] = None
    distribution: Optional[dict] = None
    drawdown: Optional[dict] = None
    capture: Optional[dict] = None
    technical: Optional[dict] = None
    warnings: list[str] = []
    note: Optional[str] = None


class CacheStatusResponse(Disclaimer):
    tables: dict[str, dict]
    note: Optional[str] = None


class BulkRefreshResponse(Disclaimer):
    requested: list[str]
    succeeded: list[str]
    failed: list[dict]  # [{symbol, error}, ...]
    elapsed_seconds: float
    note: Optional[str] = None


class UpcomingEventsResponse(Disclaimer):
    lookback_days: int
    events: list[dict]
    note: Optional[str] = None


class WatchlistWithScoresResponse(Disclaimer):
    entries: list[dict]
    note: Optional[str] = None


class BacktestResponse(Disclaimer):
    filter_spec: dict
    hold_days: int
    since: str
    n_trades: int
    mean_return_pct: Optional[float] = None
    median_return_pct: Optional[float] = None
    total_return_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    trades: list[dict] = []
    caveats: list[str]
    note: Optional[str] = None


class CrossSectionalRankResponse(Disclaimer):
    symbol: str
    metric: str
    universe: str
    sector: Optional[str] = None
    value: Optional[float] = None
    z_score: Optional[float] = None
    percentile_pct: Optional[float] = None
    n_in_universe: int
    note: Optional[str] = None


class SectorDispersionResponse(Disclaimer):
    sector: str
    metric: str
    n: int
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    range_pct: Optional[float] = None
    top_z_scores: list[dict] = []
    note: Optional[str] = None


class SectorRelativeStrengthResponse(Disclaimer):
    window_days: int
    rows: list[dict]
    note: Optional[str] = None


class AnnouncementBodyResponse(Disclaimer):
    announcement_id: str
    symbol: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    fetch_status: str
    body: Optional[str] = None
    body_chars: int = 0
    note: Optional[str] = None


class BulkBodyFetchResponse(Disclaimer):
    symbol: Optional[str] = None
    since_days: int
    attempted: int = 0
    succeeded: int = 0
    skipped_no_url: int = 0
    failed_http: int = 0
    failed_scan: int = 0
    failed_parse: int = 0
    failed_other: int = 0
    elapsed_seconds: float = 0.0
    note: Optional[str] = None


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


class InsiderTrade(BaseModel):
    announcement_id: str
    symbol: str
    insider_name: Optional[str] = None
    insider_role: Optional[str] = None
    action: Optional[str] = None
    qty: Optional[int] = None
    pct_holding: Optional[float] = None
    trade_date: Optional[date] = None
    posted_at: str

    @field_validator("trade_date", mode="before")
    @classmethod
    def _coerce_blank(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class InsiderTradeListResponse(Disclaimer):
    symbol: str
    since_days: int
    trades: list[InsiderTrade]
    net_qty: Optional[int] = None
    note: Optional[str] = None


class BoardMeeting(BaseModel):
    announcement_id: str
    symbol: str
    meeting_date: Optional[date] = None
    agenda: Optional[str] = None
    posted_at: str

    @field_validator("meeting_date", mode="before")
    @classmethod
    def _coerce_blank(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class EarningsCalendarResponse(Disclaimer):
    symbol: str
    lookback_days: int
    forward_days: int
    meetings: list[BoardMeeting]
    next_meeting: Optional[BoardMeeting] = None
    note: Optional[str] = None
