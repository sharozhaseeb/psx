import pytest
from datetime import date
from psx_mcp.events import (
    classify_announcement, parse_insider_trade, parse_board_meeting,
)


def test_classify_announcement_recognizes_insider_disclosure():
    cat = classify_announcement(
        "Disclosure of Interest by a Director CEO, or Executive of a listed company")
    assert cat == "insider_trade"


def test_classify_announcement_recognizes_board_meeting():
    assert classify_announcement("Notice of Board Meeting") == "board_meeting"
    assert classify_announcement(
        "Board Meeting Other Than Financial Results") == "board_meeting"


def test_classify_announcement_recognizes_financial_results():
    assert classify_announcement(
        "Financial Results for the Quarter Ended 31 March 2026") == "financial_results"


def test_classify_announcement_recognizes_dividend():
    assert classify_announcement(
        "Credit of Final Cash Dividend for the Year Ended December 31, 2025") == "dividend"


def test_classify_announcement_recognizes_corporate_briefing():
    cat = classify_announcement(
        "Dissemination of Video Recording of Corporate Briefing Session")
    assert cat == "corporate_briefing"


def test_classify_announcement_unknown_returns_other():
    assert classify_announcement("Random title with no keywords") == "other"


def test_classify_announcement_recognizes_quarterly_report():
    """Fixes Critic C blocker: 'Quarterly Report' / 'Half Year Report' filings."""
    assert classify_announcement(
        "Transmission of Quarterly Report for the Period Ended 31-03-2026"
    ) == "financial_results"
    assert classify_announcement(
        "Transmission of Half Yearly Report for the Period Ended March 31, 2026"
    ) == "financial_results"


def test_classify_announcement_handles_space_separated_extra_ordinary():
    """Fixes Critic C blocker: 'Extra Ordinary' with space was missed."""
    assert classify_announcement(
        "Newspaper Clippings of Notice of Extra Ordinary General Meeting"
    ) == "egm"


def test_classify_announcement_recognizes_price_query():
    """Fixes Critic C blocker: 'Unusual movement' disclosures are a strong PSX-mandated
    signal that was falling through to 'other'."""
    assert classify_announcement(
        "Explanation regarding unusual movement in the price of shares"
    ) == "price_query"


def test_parse_insider_trade_director_buy():
    body = """
    Disclosure of Interest by a Director, CEO, or Executive of a listed company
    Name of the Director / CEO / Executive: Mr. Asif Peer
    Designation: Director
    Nature of Transaction: Purchase
    Number of Shares: 10,000
    Date of Transaction: 15-April-2026
    """
    result = parse_insider_trade(body)
    assert result is not None
    assert result["insider_name"] == "Mr. Asif Peer"
    assert result["insider_role"].lower().startswith("director")
    assert result["action"] == "buy"
    assert result["qty"] == 10000
    assert result["trade_date"] == date(2026, 4, 15)


def test_parse_insider_trade_sell_action():
    """Regression for Critic A BLOCKER: qty must be 5000, not 1 (don't grab '01' from date)."""
    body = "Director Ms. Rashida Khan sold 5,000 shares on 01-May-2026."
    result = parse_insider_trade(body)
    assert result is not None
    assert result["action"] == "sell"
    assert result["qty"] == 5000
    assert result["trade_date"] == date(2026, 5, 1)


def test_parse_insider_trade_extracts_pct_holding():
    """Critic C MAJOR: pct_holding should populate when 'Holding after transaction: 7.5%' appears."""
    body = (
        "Disclosure of Interest by a Director CEO, or Executive of a listed company\n"
        "Name of the Director: Mr. Asif Peer\n"
        "Designation: Director\n"
        "Nature of Transaction: Purchase\n"
        "Number of Shares: 10,000\n"
        "Holding after transaction: 7.5%\n"
        "Date of Transaction: 15-April-2026\n"
    )
    result = parse_insider_trade(body)
    assert result is not None
    assert result["pct_holding"] == 7.5


def test_parse_insider_trade_no_match_returns_none():
    assert parse_insider_trade("Totally unrelated announcement body") is None


def test_parse_board_meeting_extracts_future_date():
    body = """
    Notice of Board Meeting
    The Board of Directors will meet on 30-June-2026 to consider the
    quarterly financial results.
    """
    result = parse_board_meeting(title="Notice of Board Meeting", body=body)
    assert result is not None
    assert result["meeting_date"] == date(2026, 6, 30)
    assert result["agenda"] == "financial_results"


def test_parse_board_meeting_other_than_financial():
    body = "The board will meet on 5 July 2026 to discuss strategic matters."
    result = parse_board_meeting(
        title="Board Meeting Other Than Financial Results", body=body)
    assert result is not None
    assert result["meeting_date"] == date(2026, 7, 5)
    assert result["agenda"] == "other"


def test_parse_board_meeting_no_date_returns_none():
    """Title classifies as board meeting but no extractable date → None."""
    assert parse_board_meeting(title="Board Meeting",
                                 body="Just a notice with no date.") is None


def test_parse_board_meeting_anchors_on_will_be_held_phrase():
    """Critic C BLOCKER fix: when body references a past 'period ended' date
    AND a future 'will be held on' date, the parser must pick the future one."""
    body = (
        "Notice is hereby given that a meeting of the Board of Directors "
        "will be held on Thursday, 5 June 2026 at 2:00 PM to consider the "
        "financial results for the period ended 31 March 2026."
    )
    result = parse_board_meeting(title="Notice of Board Meeting", body=body)
    assert result is not None
    assert result["meeting_date"] == date(2026, 6, 5)
    # NOT 31 March 2026 (the period-end), which would also parse but be wrong.
    assert result["meeting_date"] != date(2026, 3, 31)
