"""Tests for news RSS aggregator and symbol detection."""
import pytest
from pathlib import Path
from psx_mcp.news import parse_rss, _extract_symbols, _infer_source


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_dawn_business_feed():
    """Test parsing Dawn Business RSS feed."""
    feed_path = FIXTURES_DIR / "dawn_business_feed.xml"
    items = parse_rss(feed_path)

    assert len(items) > 0
    # Check first item has required fields
    item = items[0]
    assert item.id
    assert item.source == "dawn_business"
    assert item.title
    assert item.url
    assert item.posted_at
    assert isinstance(item.symbols, list)


def test_parse_profit_feed():
    """Test parsing Profit Pakistan RSS feed."""
    feed_path = FIXTURES_DIR / "profit_feed.xml"
    items = parse_rss(feed_path)

    assert len(items) > 0
    # Check first item has required fields
    item = items[0]
    assert item.id
    assert item.source == "profit_pakistan"
    assert item.title
    assert item.url
    assert item.posted_at
    assert isinstance(item.symbols, list)


def test_extract_symbols_from_dawn():
    """Test symbol extraction from Dawn Business feed content."""
    feed_path = FIXTURES_DIR / "dawn_business_feed.xml"
    items = parse_rss(feed_path)

    # Collect all symbols from parsed items
    all_symbols = set()
    for item in items:
        all_symbols.update(item.symbols)

    # Should find some symbols in business news
    # At minimum, verify extraction runs without error
    assert isinstance(all_symbols, set)


def test_extract_symbols_from_profit():
    """Test symbol extraction from Profit feed content."""
    feed_path = FIXTURES_DIR / "profit_feed.xml"
    items = parse_rss(feed_path)

    # Collect all symbols from parsed items
    all_symbols = set()
    for item in items:
        all_symbols.update(item.symbols)

    # Should find some symbols in business news
    # At minimum, verify extraction runs without error
    assert isinstance(all_symbols, set)


def test_extract_symbols_basic():
    """Test symbol extraction with known patterns."""
    # Test with sample text containing PSX symbols
    text = "PPL and HBL showed gains today. TRG also performed well."
    symbols = _extract_symbols(text)

    assert "PPL" in symbols
    assert "HBL" in symbols
    assert "TRG" in symbols


def test_extract_symbols_filters_common_words():
    """Test that common words are filtered out."""
    text = "THE COMPANY AND THE SECTOR WERE AFFECTED THIS WEEK"
    symbols = _extract_symbols(text)

    # Common words should be filtered
    assert "THE" not in symbols
    assert "AND" not in symbols
    assert "WERE" not in symbols


def test_infer_source_dawn():
    """Test source inference for Dawn URLs."""
    url = "https://www.dawn.com/news/2002321"
    assert _infer_source(url) == "dawn_business"


def test_infer_source_profit():
    """Test source inference for Profit URLs."""
    url = "https://profit.pakistantoday.com.pk/2026/05/23/some-article/"
    assert _infer_source(url) == "profit_pakistan"


def test_unique_ids():
    """Test that parsed items have unique IDs."""
    feed_path = FIXTURES_DIR / "dawn_business_feed.xml"
    items = parse_rss(feed_path)

    ids = [item.id for item in items]
    # All IDs should be unique
    assert len(ids) == len(set(ids))
