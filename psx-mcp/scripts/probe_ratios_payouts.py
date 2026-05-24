"""Audit captured Ratios + Payouts + Financial-Statements fixtures for the fields Part 2 needs."""
import re
from pathlib import Path
from bs4 import BeautifulSoup

RATIOS_KEYWORDS = {
    "roe":         ["return on equity", "roe"],
    "pb":          ["p/b", "price to book", "price-to-book", "book value"],
    "div_yield":   ["dividend yield"],
    "payout":      ["payout ratio"],
    "current_ratio": ["current ratio"],
    "debt_equity": ["debt to equity", "debt-to-equity", "d/e ratio"],
    "long_term_debt": ["long term debt", "long-term debt", "lt debt"],
    "total_assets": ["total assets"],
    "current_liab": ["current liabilit"],
    "gross_margin": ["gross margin", "gross profit margin"],
}

PAYOUTS_KEYWORDS = {
    "cash_dividend": ["cash dividend", "interim", "final"],
    "bonus":         ["bonus share", "bonus issue"],
    "right":         ["right share", "rights issue"],
    "date":          ["ex-date", "book closure", "announcement date"],
    "per_share":     ["per share", "per-share", "rs/share"],
}

FIN_STATEMENTS_KEYWORDS = {
    "eps":              ["eps", "earnings per share"],
    "net_income":       ["net income", "profit after tax", "profit after taxation"],
    "cfo":              ["cash flow from operations", "cash from operations", "operating cash"],
    "revenue":          ["sales", "revenue", "turnover"],
    "gross_profit":     ["gross profit", "gross margin"],
    "total_assets":     ["total assets"],
    "current_assets":   ["current assets"],
    "current_liab":     ["current liabilit"],
    "long_term_debt":   ["long term debt", "long-term debt", "non-current borrow"],
    "shares_out":       ["shares issued", "shares outstanding", "share capital"],
}

def audit(fixture_path: Path, keywords: dict, label: str) -> list[str]:
    out = [f"\n=== {label}: {fixture_path.name} ==="]
    if not fixture_path.exists():
        out.append("  MISSING fixture")
        return out
    text = BeautifulSoup(fixture_path.read_text(encoding="utf-8"), "lxml").get_text(" ", strip=True).lower()
    for category, terms in keywords.items():
        hits = sum(text.count(t) for t in terms)
        sample = next((re.search(r".{0,40}" + re.escape(t) + r".{0,40}", text).group(0)
                       for t in terms if t in text), "")
        out.append(f"  [{category:18s}] hits={hits:>3d}  sample={sample[:80]!r}")
    return out

def main():
    fx = Path("tests/fixtures")
    log = []
    for f in sorted(fx.glob("ratios_*.html")):
        log += audit(f, RATIOS_KEYWORDS, "RATIOS")
    for f in sorted(fx.glob("payouts_*.html")):
        log += audit(f, PAYOUTS_KEYWORDS, "PAYOUTS")
    for f in sorted(fx.glob("financial_statements_*.html")):
        log += audit(f, FIN_STATEMENTS_KEYWORDS, "FIN_STATEMENTS")
    text = "\n".join(log)
    Path("tests/fixtures/ratios_payouts_audit.txt").write_text(text, encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()
