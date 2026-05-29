"""Pure-function event extractors for PSX announcement text.

These functions are intentionally heuristic — PSX disclosure text varies by
company and form. Each parser returns None when it can't confidently extract,
and the caller (server impl) falls back to storing raw body only."""
from __future__ import annotations
import re
from datetime import date, datetime
from typing import Optional


# --- Classification ----------------------------------------------------------

_CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("insider_trade", re.compile(r"\bDisclosure of Interest by a Director", re.I)),
    ("insider_trade", re.compile(r"\bDisclosure of Shares acquired", re.I)),
    ("price_query",   re.compile(r"\bExplanation regarding unusual (?:movement|increase|decrease)", re.I)),
    ("price_query",   re.compile(r"\bunusual movement in (?:the )?(?:price|share)", re.I)),
    ("board_meeting", re.compile(r"\bBoard Meeting\b", re.I)),
    # Fixes Critic C blocker: "Extra Ordinary" with a space + "EOGM" alt
    ("egm",            re.compile(r"\b(Extra[-\s]?Ordinary General Meeting|EOGM|\bEGM)\b", re.I)),
    ("agm",            re.compile(r"\b(Annual General Meeting|AGM)\b", re.I)),
    # Fixes Critic C blocker: "Quarterly Report" / "Half Year Report" titles are the most
    # common earnings-data filings and were previously falling through to "other".
    ("financial_results",
                       re.compile(r"\b(Financial Results|(?:Quarterly|Half[-\s]?Year(?:ly)?|Annual)\s+Report)\b", re.I)),
    ("corporate_briefing",
                       re.compile(r"\b(Corporate Briefing|CBS)\b", re.I)),
    ("dividend",       re.compile(r"\b(Cash Dividend|Bonus Issue|Final Dividend|Interim Dividend|Credit of (?:Final|Interim))\b", re.I)),
    ("right_shares",   re.compile(r"\b(Right Shares|Declaration of Right)\b", re.I)),
    ("book_closure",   re.compile(r"\bBook Closure\b", re.I)),
    ("material_info",  re.compile(r"\bMaterial Information\b", re.I)),
    ("appointment",    re.compile(r"\b(Appointment of (?:Chairman|Chairperson|Chief Executive)|Election of Chairman)\b", re.I)),
]


def classify_announcement(title: str) -> str:
    """Return the best-match category for an announcement title.
    Returns 'other' if no pattern matches."""
    if not title:
        return "other"
    for cat, pat in _CATEGORY_PATTERNS:
        if pat.search(title):
            return cat
    return "other"


# --- Insider trade parsing ---------------------------------------------------

# PSX dates appear in many forms; this list is in order of preference.
_DATE_FORMATS = [
    "%d-%B-%Y",         # 15-April-2026
    "%d-%b-%Y",         # 15-Apr-2026
    "%d %B %Y",         # 15 April 2026
    "%d %b %Y",         # 15 Apr 2026
    "%d-%m-%Y",         # 15-04-2026
    "%d/%m/%Y",         # 15/04/2026
    "%B %d, %Y",        # April 15, 2026
    "%b %d, %Y",        # Apr 15, 2026
    "%Y-%m-%d",         # 2026-04-15
]


def _try_parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# Catches dates in a free-text blob — greedy on numeric + alphabetic months.
_DATE_RE = re.compile(
    r"(\d{1,2}[-/ ]"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
    r"April|June|July|August|September|October|November|December|\d{1,2})"
    r"[-/ ,]+\d{2,4}"
    r"|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
    r"April|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}"
    r")",
    re.I,
)


def _extract_first_date(text: str, after: int = 0) -> Optional[date]:
    """Find the first parseable date in text starting at position `after`."""
    for m in _DATE_RE.finditer(text, pos=after):
        d = _try_parse_date(m.group(0))
        if d is not None:
            return d
    return None


# Insider-trade name extraction patterns. Defensive — PSX doesn't standardize.
_INSIDER_NAME_PATTERNS = [
    re.compile(r"(?:Name of the (?:Director|CEO|Executive)[^:]*):\s*([A-Z][A-Za-z\.\s]+?)(?:\n|$|,)", re.I),
    re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})", re.I),
]

_INSIDER_ROLE_PATTERNS = [
    re.compile(r"\b(Director|CEO|Chief Executive|Executive|Chairman|Chairperson)\b", re.I),
]

_ACTION_BUY_RE = re.compile(r"\b(?:purchas\w*|bought|buy|acquired|acquisition)\b", re.I)
_ACTION_SELL_RE = re.compile(r"\b(?:sold|sale|sell|disposed|divested|disposal)\b", re.I)

# Fixes Critic A BLOCKER: prior _QTY_RE matched "shares" then captured the next digit
# anywhere (e.g., "01" from a date), producing qty=1 for "sold 5,000 shares on 01-May".
# Anchored on a colon or whitespace+amount, with comma OR 4+ digits required.
_QTY_LABELED_RE = re.compile(
    r"(?:number of shares|qty|quantity)\s*[:\-]?\s*(\d{1,3}(?:,\d{3})+|\d{4,})",
    re.I,
)
# Fallback for free-text "sold 5,000 shares" / "purchased 10000 shares".
_QTY_FREE_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\b\s+shares?", re.I
)

# Fixes Critic C MAJOR: pct_holding is in PSX Form 31 ("Holding after transaction").
# High-signal for "is the director loading up?" questions.
_PCT_HOLDING_RE = re.compile(
    r"(?:holding|stake|interest)[^\d]{0,40}?(\d+(?:\.\d+)?)\s*%", re.I,
)


def parse_insider_trade(body: str) -> Optional[dict]:
    """Parse director-trade fields from announcement body text.
    Returns None when essential fields can't be found.

    Note (Critic B M4 fix): symbol parameter was unused; dropped."""
    if not body:
        return None
    # Action
    is_buy = bool(_ACTION_BUY_RE.search(body))
    is_sell = bool(_ACTION_SELL_RE.search(body))
    if not (is_buy ^ is_sell):
        # Need exactly one to be confident
        return None
    action = "buy" if is_buy else "sell"

    # Name
    name: Optional[str] = None
    for pat in _INSIDER_NAME_PATTERNS:
        m = pat.search(body)
        if m:
            candidate = m.group(1).strip().rstrip(",")
            # Avoid grabbing words like "Director" by themselves
            if len(candidate.split()) >= 1 and not candidate.lower().startswith(
                ("director", "ceo", "executive")
            ):
                name = candidate
                break

    # Role
    role: Optional[str] = None
    for pat in _INSIDER_ROLE_PATTERNS:
        m = pat.search(body)
        if m:
            role = m.group(1)
            break

    # Qty — labeled form first (PSX Form 31 layout), then free-text fallback.
    qty: Optional[int] = None
    m_qty = _QTY_LABELED_RE.search(body) or _QTY_FREE_RE.search(body)
    if m_qty:
        qty = int(m_qty.group(1).replace(",", ""))

    # pct_holding (Critic C MAJOR fix)
    pct_holding: Optional[float] = None
    m_pct = _PCT_HOLDING_RE.search(body)
    if m_pct:
        try:
            val = float(m_pct.group(1))
            # Sanity: holdings are 0-100%
            if 0 < val <= 100:
                pct_holding = val
        except ValueError:
            pass

    # Date
    trade_date = _extract_first_date(body)

    # Need at minimum qty > 0 + action + date (Critic B nitpick: zero-qty is nonsense)
    if qty is None or qty <= 0 or trade_date is None:
        return None

    return {
        "insider_name": name,
        "insider_role": role,
        "action": action,
        "qty": qty,
        "pct_holding": pct_holding,
        "trade_date": trade_date,
    }


# --- Board meeting parsing ---------------------------------------------------

_FIN_RESULTS_TITLE_RE = re.compile(
    r"\b(Quarterly|Half[-\s]?Year(?:ly)?|Annual|Financial)\s+Result", re.I
)

# Critic C BLOCKER fix: anchor meeting-date extraction on phrases that
# UNAMBIGUOUSLY signal a future meeting, instead of grabbing the first date in
# body (which is often the prior "period ended" reference date).
_MEETING_DATE_ANCHOR_RE = re.compile(
    r"(?:will\s+(?:be\s+held|meet)|is\s+scheduled|hereby\s+given\s+that\s+"
    r"(?:a\s+)?meeting.{0,80}?will\s+be\s+held|Board(?:\s+of\s+Directors)?\s+"
    r"will\s+meet|meeting\s+(?:of\s+the\s+Board\s+)?on)",
    re.I,
)
# When falling back to first-date-in-body, skip dates immediately preceded by
# words that indicate a reference period, not a meeting.
_PERIOD_PHRASE_RE = re.compile(
    r"\b(?:period\s+ended|year\s+ended|ending|as\s+(?:on|at))\s+$", re.I,
)


def parse_board_meeting(title: str, body: str) -> Optional[dict]:
    """Extract meeting_date + agenda from board-meeting announcement.
    Returns None if no date can be parsed.

    Note (Critic B M4 fix): symbol parameter was unused; dropped.
    Note (Critic C BLOCKER fix): anchors on 'will be held on'-style phrases
    before falling back to first-date-in-body; skips dates preceded by
    'period ended' / 'year ended' so we don't return the reference period."""
    if not body:
        return None
    title = title or ""
    # Classify agenda from title (cheap) before scanning body
    if "Other Than Financial" in title:
        agenda = "other"
    elif _FIN_RESULTS_TITLE_RE.search(title):
        agenda = "financial_results"
    else:
        if _FIN_RESULTS_TITLE_RE.search(body):
            agenda = "financial_results"
        elif re.search(r"\bdividend\b", body, re.I):
            agenda = "dividend"
        else:
            agenda = "other"

    # 1) Look for an explicit "will be held on" anchor; prefer a date in the
    # 200 chars FOLLOWING the anchor.
    meeting_date: Optional[date] = None
    for anchor in _MEETING_DATE_ANCHOR_RE.finditer(body):
        window = body[anchor.end():anchor.end() + 200]
        d = _extract_first_date(window)
        if d is not None:
            meeting_date = d
            break

    # 2) Fallback: scan the body, but skip any date whose preceding 24 chars
    # contain a "period ended"/"year ended" phrase.
    if meeting_date is None:
        for m in _DATE_RE.finditer(body):
            preceding = body[max(0, m.start() - 24):m.start()]
            if _PERIOD_PHRASE_RE.search(preceding):
                continue
            d = _try_parse_date(m.group(0))
            if d is not None:
                meeting_date = d
                break

    if meeting_date is None:
        return None
    return {
        "meeting_date": meeting_date,
        "agenda": agenda,
    }
