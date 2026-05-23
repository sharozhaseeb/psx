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
