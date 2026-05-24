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


def test_parse_announcements_extracts_pdf_url(fixtures_dir):
    """The action column has a PDF download link — that's the actionable URL,
    not the symbol's company page. Body text is NOT in the HTML feed (PDF only),
    so url must point at the disclosure PDF for users to read the announcement."""
    items = parse_announcements(_read_any(fixtures_dir, "announcements"))
    assert items, "fixture should produce announcements"
    pdf_items = [a for a in items if a.url and a.url.endswith(".pdf")]
    assert pdf_items, "expected at least one announcement with a PDF url"
    # No item should have the symbol's /company/ page as its url —
    # that's the bug we're fixing (parser was picking the first <a> in the row).
    for a in items:
        if a.url:
            assert "/company/" not in a.url, (
                f"announcement url should be the disclosure link, not the company page: {a.url}"
            )
    # Body intentionally None — HTML feed has no body text (see PSX endpoint matrix).
    assert all(a.body is None for a in items)


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


def test_parse_payouts_extracts_events_from_FFC_fixture(fixtures_dir):
    from psx_mcp.psx_client import parse_payouts
    html = (fixtures_dir / "payouts_FFC.html").read_text(encoding="utf-8")
    events = parse_payouts("FFC", html)
    assert len(events) >= 1
    e = events[0]
    assert e["announcement_id"].startswith("FFC-")
    assert e["symbol"] == "FFC"
    assert e["payout_type"] in ("cash", "bonus", "right")
    assert e["per_share"] is not None or e["bonus_pct"] is not None


def test_parse_payouts_single_row_fixture(fixtures_dir):
    """LUCK pays once annually — confirm single-row fixture parses."""
    from psx_mcp.psx_client import parse_payouts
    html = (fixtures_dir / "payouts_LUCK.html").read_text(encoding="utf-8")
    events = parse_payouts("LUCK", html)
    assert len(events) >= 1


def test_parse_payouts_empty_html_returns_empty(fixtures_dir):
    from psx_mcp.psx_client import parse_payouts
    assert parse_payouts("XXX", "<html></html>") == []
