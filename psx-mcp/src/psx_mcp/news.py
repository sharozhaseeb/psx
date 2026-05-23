"""News RSS aggregator with symbol mention detection."""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import NewsItem

# RSS feed URLs
FEEDS = {
    "dawn_business": "https://www.dawn.com/feeds/business",
    "profit_pakistan": "https://profit.pakistantoday.com.pk/feed/",
}


def parse_rss(xml_path: Path | str) -> list[NewsItem]:
    """
    Parse RSS feed from XML file.

    Args:
        xml_path: Path to RSS XML file

    Returns:
        List of NewsItem objects
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    items = []
    # Handle RSS with and without namespace
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        pub_date_elem = item.find("pubDate")

        if title_elem is None or link_elem is None:
            continue

        title = title_elem.text or ""
        link = link_elem.text or ""
        pub_date_str = pub_date_elem.text if pub_date_elem is not None else ""

        # Parse RFC 2822 date format
        posted_at = _parse_rfc2822_date(pub_date_str)

        # Extract body from description or content:encoded
        desc_elem = item.find("description")
        content_elem = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        body = ""
        if content_elem is not None and content_elem.text:
            body = content_elem.text
        elif desc_elem is not None and desc_elem.text:
            body = desc_elem.text

        # Strip HTML tags for symbol detection
        plain_text = _strip_html(body + " " + title)

        # Detect PSX symbols
        symbols = _extract_symbols(plain_text)

        # Create unique ID from link
        item_id = _make_id(link)

        items.append(
            NewsItem(
                id=item_id,
                source=_infer_source(link),
                posted_at=posted_at,
                title=title,
                url=link,
                symbols=symbols,
            )
        )

    return items


def _parse_rfc2822_date(date_str: str) -> datetime:
    """Parse RFC 2822 date string (e.g., 'Sat, 23 May 2026 11:03:54 +0500')."""
    if not date_str:
        return datetime.now()

    try:
        # Try email.utils.parsedate_to_datetime for RFC 2822
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        pass

    # Fallback to common formats
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return datetime.now()


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    # Remove script and style elements
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    return text


def _extract_symbols(text: str) -> list[str]:
    """
    Extract PSX stock symbols from text.

    Looks for common stock symbol patterns:
    - 3-4 uppercase letters followed by optional numbers
    - Whole word boundaries
    """
    # Common PSX symbols (sample for detection)
    # In real use, would match against actual PSX symbol list
    symbols = set()

    # Pattern: word boundary, 3-4 uppercase letters, optional numbers, word boundary
    # e.g., "PPL", "HBL", "TRG", "MCB", etc.
    pattern = r"\b([A-Z]{3,4})(?:\d{0,2})\b"

    matches = re.findall(pattern, text)
    for match in matches:
        # Filter out common false positives (very common words)
        if match not in {"THE", "AND", "FOR", "WITH", "FROM", "THAT", "THIS", "WERE"}:
            symbols.add(match)

    return sorted(list(symbols))


def _infer_source(url: str) -> str:
    """Infer feed source from URL."""
    if "dawn.com" in url:
        return "dawn_business"
    if "profit.pakistantoday.com" in url:
        return "profit_pakistan"
    return "unknown"


def _make_id(url: str) -> str:
    """Create stable ID from URL."""
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()
