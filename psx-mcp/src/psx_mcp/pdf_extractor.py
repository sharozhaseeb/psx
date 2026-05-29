"""PDF body extraction for PSX announcement / news PDFs.

Strategy:
  1. Use pypdf to extract text from each page; concatenate.
  2. Callers wanting safety should use extract_text_or_empty.

PDF fetching is done via PSXClient.fetch_url_bytes (psx_client.py).
This module is pure text extraction — no HTTP code here."""
from __future__ import annotations
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError


SCANNED_PDF_TEXT_THRESHOLD = 30  # chars; below this we assume scan-only


def extract_text(pdf_bytes: bytes) -> str:
    """Extract concatenated text from all pages of a PDF.
    Raises pypdf.errors on truly malformed input — use extract_text_or_empty
    if you need a non-raising version."""
    reader = PdfReader(BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


def extract_text_or_empty(pdf_bytes: bytes) -> str:
    """Safe wrapper: returns "" on any extraction failure."""
    if not pdf_bytes:
        return ""
    try:
        return extract_text(pdf_bytes)
    except (PdfReadError, PdfStreamError, OSError, ValueError):
        return ""


def is_probably_scan_only(text: str) -> bool:
    """Heuristic: PDFs with very little extractable text are likely scans.
    Caller can use this to mark fetch_status='scan_only' and skip parsing."""
    return len(text) < SCANNED_PDF_TEXT_THRESHOLD
