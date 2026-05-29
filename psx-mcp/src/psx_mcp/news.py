from __future__ import annotations
import re
import hashlib
from datetime import datetime
from typing import Iterable, Optional

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


def extract_article_body(html: str, url: Optional[str] = None) -> str:
    """Article-body extraction. Tries per-host selectors first (Dawn / Profit /
    Tribune / Brecorder), then a generic semantic-selector pass, then a
    longest-<p>-block fallback. Per-host selectors prevent missing Dawn's
    `div.story__content` (double-underscore) and Profit's `td-post-content`."""
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    HOST_SELECTORS = [
        ("dawn.com",       ["div.story__content", "div.story-content"]),
        ("profit.pakistantoday.com.pk",
                            ["div.td-post-content", "article.entry-content"]),
        ("tribune.com.pk", ["div.story-text", "div.story-content"]),
        ("brecorder.com",  ["div.story-content", "div.entry-content"]),
    ]
    host = ""
    if url:
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
    for host_sub, selectors in HOST_SELECTORS:
        if host_sub in host:
            for sel in selectors:
                for el in soup.select(sel):
                    text = el.get_text("\n", strip=True)
                    if len(text) > 200:
                        return text

    candidates = []
    for sel in ("article", "main", "div.story__content", "div.story-content",
                  "div.article-body", "div#article-body", "div.entry-content",
                  "div.td-post-content"):
        for el in soup.select(sel):
            text = el.get_text("\n", strip=True)
            if len(text) > 200:
                candidates.append(text)
    if candidates:
        return max(candidates, key=len)

    best_text = ""
    for div in soup.find_all(["div", "section", "article"]):
        ps = div.find_all("p", recursive=False)
        if len(ps) >= 3:
            text = "\n".join(p.get_text(" ", strip=True) for p in ps)
            if len(text) > len(best_text):
                best_text = text
    return best_text
