from pathlib import Path
import pytest
from psx_mcp.pdf_extractor import extract_text, extract_text_or_empty

FIXTURE = Path(__file__).parent / "fixtures" / "extractor_smoke.pdf"


def test_extract_text_returns_known_string():
    """The committed fixture PDF has the literal sentence below."""
    pdf_bytes = FIXTURE.read_bytes()
    txt = extract_text(pdf_bytes)
    assert "Board meeting" in txt
    assert "15-June-2026" in txt


def test_extract_text_or_empty_handles_garbage_bytes():
    """Non-PDF input -> empty string, not exception."""
    assert extract_text_or_empty(b"not a pdf at all") == ""


def test_extract_text_or_empty_handles_empty_input():
    assert extract_text_or_empty(b"") == ""
