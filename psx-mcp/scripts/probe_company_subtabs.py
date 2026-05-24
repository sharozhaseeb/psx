"""One-off probe: find PSX /company/<SYM> sub-tab endpoints (Financials, Ratios, Payouts).

Approach:
  1. Fetch landing page /company/LUCK and grep for tab-related JS / AJAX URLs.
  2. Try a curated set of candidate URL patterns.
  3. Save every response's status + content-type + first 400 chars to a fixture.
"""
import re
import httpx
from pathlib import Path

BASE = "https://dps.psx.com.pk"
SYM = "LUCK"

CANDIDATES = [
    ("GET",  f"/company/{SYM}/financials"),
    ("GET",  f"/company/{SYM}/ratios"),
    ("GET",  f"/company/{SYM}/payouts"),
    ("GET",  f"/company/{SYM}/financial-reports"),
    ("GET",  f"/company/{SYM}/announcements"),
    ("GET",  f"/company/{SYM}?tab=financials"),
    ("GET",  f"/company/{SYM}?tab=ratios"),
    ("GET",  f"/company/{SYM}?tab=payouts"),
    ("GET",  f"/financials/{SYM}"),
    ("GET",  f"/ratios/{SYM}"),
    ("GET",  f"/payouts/{SYM}"),
    ("POST", f"/company/{SYM}/financials"),
    ("POST", f"/company/{SYM}/ratios"),
    ("POST", f"/company/{SYM}/payouts"),
    ("POST", "/financial/data"),
    ("POST", "/company/financial"),
    ("POST", "/company/ratios"),
    ("POST", "/company/payouts"),
    # Additional POST candidates discovered after first-round probe: /company/payouts
    # responded 200 with a real <table>. Try the natural siblings.
    ("POST", "/company/financials"),
    ("POST", "/company/financial-reports"),
    ("POST", "/company/announcements"),
    ("POST", "/company/profile"),
    ("POST", "/company/keystats"),
    ("POST", "/company/balancesheet"),
    ("POST", "/company/historical"),
    # /api/... style
    ("GET",  f"/api/company/{SYM}/ratios"),
    ("GET",  f"/api/company/{SYM}/payouts"),
    ("GET",  f"/api/company/{SYM}/financials"),
    # /data/... style
    ("GET",  f"/data/company/{SYM}/ratios"),
    ("POST", f"/data/company/ratios"),
]
# Each candidate is also probed WITHOUT the X-Requested-With header (see probe()).

def probe():
    headers = {
        "User-Agent": "Mozilla/5.0 (PSX-MCP-probe/0.2)",
        "Accept": "application/json,text/html;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/company/{SYM}",
    }
    out = []

    # First grab the landing page, grep for AJAX/tab hints.
    landing = httpx.get(f"{BASE}/company/{SYM}", headers=headers, timeout=10.0)
    out.append(f"=== LANDING {landing.status_code} {landing.headers.get('content-type')}")
    # Look for any URL fragments in inline JS that match tab patterns.
    hints = set(re.findall(r"['\"](/[^'\"<>\s]*?(?:financial|ratio|payout|tab)[^'\"<>\s]*?)['\"]",
                            landing.text, re.I))
    out.append(f"=== LANDING-AJAX-HINTS {sorted(hints)[:40]}")

    with httpx.Client(timeout=10.0, follow_redirects=True) as c:
        for method, path in CANDIDATES:
            url = BASE + path
            for header_variant_name, hdrs in (("ajax", headers),
                                              ("plain", {k: v for k, v in headers.items()
                                                         if k != "X-Requested-With"})):
                try:
                    if method == "GET":
                        r = c.get(url, headers=hdrs)
                    else:
                        body = {"symbol": SYM}
                        r = c.post(url, headers=hdrs, data=body)
                    ct = r.headers.get("content-type", "")
                    snippet = r.text[:400].replace("\n", " ")
                    out.append(f"[{header_variant_name}] {method} {path} -> "
                               f"{r.status_code} {ct} | {snippet}")
                except Exception as e:
                    out.append(f"[{header_variant_name}] {method} {path} -> ERROR {e!r}")

    fixture = Path("tests/fixtures/company_subtabs_probe.txt")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

if __name__ == "__main__":
    probe()
