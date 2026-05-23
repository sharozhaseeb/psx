from __future__ import annotations
import re
import hashlib
from datetime import datetime
from typing import Iterable

import feedparser

from .models import NewsItem


FEEDS = {
    "dawn_business": "https://www.dawn.com/feeds/business",
    "profit_pakistan": "https://profit.pakistantoday.com.pk/feed/",
}


def parse_rss(source: str, xml: str) -> list[NewsItem]:
    parsed = feedparser.parse(xml)
    items: list[NewsItem] = []
    for e in parsed.entries:
        url = getattr(e, "link", "")
        title = getattr(e, "title", "")
        pub = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        ts = datetime(*pub[:6]) if pub else datetime.now()
        nid = hashlib.sha1(f"{source}:{url}".encode("utf-8")).hexdigest()[:16]
        items.append(NewsItem(id=nid, source=source, posted_at=ts, title=title, url=url, symbols=[]))
    return items


def find_symbol_mentions(title: str, body: str, universe: Iterable[str]) -> list[str]:
    text = f"{title} {body}"
    hits = []
    for sym in universe:
        if re.search(rf"\b{re.escape(sym)}\b", text):
            hits.append(sym)
    return hits
