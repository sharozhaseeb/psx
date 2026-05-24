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
    q_lower = q.lower()
    all_rows = cache.all_symbols()
    scored: list[dict] = []
    for r in all_rows:
        sym, name = r["symbol"], r.get("name") or ""
        sector = r.get("sector") or ""
        s_score = 1.0 if sym == q else _score(q, sym) * 0.9
        n_score = _score(q, name)
        # Sector match: substring boost (sectors are long phrases like
        # "TECHNOLOGY & COMMUNICATION", so SequenceMatcher ratio is too low
        # for short queries; treat any substring hit as a solid match).
        if sector and q_lower in sector.lower():
            sec_score = 0.85
        else:
            sec_score = _score(q, sector) * 0.7
        score = max(s_score, n_score, sec_score)
        if score >= 0.4:
            scored.append({"symbol": sym, "name": name, "sector": r.get("sector"), "score": round(score, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
