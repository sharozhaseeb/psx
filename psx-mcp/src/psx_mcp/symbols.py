from __future__ import annotations
from difflib import SequenceMatcher
from .cache import Cache
from .psx_client import parse_symbols


def refresh_symbols_from_payload(cache: Cache, payload: str) -> int:
    rows = parse_symbols(payload)
    for r in rows:
        cache.upsert_symbol(r["symbol"], r["name"], r.get("sector"), None)
    return len(rows)


def _score(query: str, candidate: str) -> float:
    return SequenceMatcher(None, query.lower(), candidate.lower()).ratio()


def search_symbols(cache: Cache, query: str, limit: int = 10) -> list[dict]:
    q = query.strip().upper()
    all_rows = cache.all_symbols()
    scored: list[dict] = []
    for r in all_rows:
        sym, name = r["symbol"], r.get("name") or ""
        s_score = 1.0 if sym == q else _score(q, sym) * 0.9
        n_score = _score(q, name)
        score = max(s_score, n_score)
        if score >= 0.4:
            scored.append({"symbol": sym, "name": name, "sector": r.get("sector"), "score": round(score, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
