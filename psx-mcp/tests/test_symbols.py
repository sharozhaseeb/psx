from pathlib import Path
import pytest
from psx_mcp.cache import Cache
from psx_mcp.symbols import search_symbols, refresh_symbols_from_payload


def _payload(fixtures_dir: Path) -> str:
    for ext in ("json", "html"):
        p = fixtures_dir / f"symbols.{ext}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError("symbols fixture missing")


def test_refresh_and_search(tmp_path, fixtures_dir):
    c = Cache(str(tmp_path / "t.db"))
    refresh_symbols_from_payload(c, _payload(fixtures_dir))
    matches = search_symbols(c, "lucky", limit=5)
    assert any(m["symbol"] == "LUCK" for m in matches)


def test_search_by_exact_symbol(tmp_path, fixtures_dir):
    c = Cache(str(tmp_path / "t.db"))
    refresh_symbols_from_payload(c, _payload(fixtures_dir))
    matches = search_symbols(c, "LUCK", limit=1)
    assert matches[0]["symbol"] == "LUCK"
    assert matches[0]["score"] >= 0.9
