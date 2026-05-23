from psx_mcp.news import parse_rss, find_symbol_mentions


def test_parse_dawn_business(fixtures_dir):
    xml = (fixtures_dir / "dawn_business_feed.xml").read_text(encoding="utf-8")
    items = parse_rss("dawn_business", xml)
    assert len(items) > 0
    it = items[0]
    assert it.source == "dawn_business"
    assert it.title
    assert it.url


def test_parse_profit(fixtures_dir):
    xml = (fixtures_dir / "profit_feed.xml").read_text(encoding="utf-8")
    items = parse_rss("profit_pakistan", xml)
    assert len(items) > 0
    it = items[0]
    assert it.source == "profit_pakistan"


def test_symbol_mentions_finds_ticker():
    title = "Lucky Cement (LUCK) reports record profits"
    mentions = find_symbol_mentions(title, "", {"LUCK", "OGDC"})
    assert "LUCK" in mentions
    assert "OGDC" not in mentions


def test_symbol_mentions_requires_word_boundary():
    title = "Plucky bidder wins auction"
    mentions = find_symbol_mentions(title, "", {"LUCK"})
    assert "LUCK" not in mentions
