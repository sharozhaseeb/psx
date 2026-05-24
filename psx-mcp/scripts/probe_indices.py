"""One-off probe: discover PSX DPS endpoint(s) that serve index data as JSON."""
import httpx
from pathlib import Path

BASE = "https://dps.psx.com.pk"
CANDIDATES = [
    ("GET",  "/indices"),
    ("GET",  "/indices/KSE100"),
    ("GET",  "/indices/KSE30"),
    ("GET",  "/indices/ALLSHR"),
    ("GET",  "/market-summary"),
    ("GET",  "/timeseries/eod/KSE100"),
    ("GET",  "/timeseries/int/KSE100"),
    ("POST", "/indices"),
    ("POST", "/historical"),  # try with symbol="KSE100" body
]


def probe():
    headers = {
        "User-Agent": "Mozilla/5.0 (PSX-MCP probe)",
        "Accept": "application/json,text/html;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
    }
    out = []
    with httpx.Client(timeout=10.0, follow_redirects=True) as c:
        for method, path in CANDIDATES:
            url = BASE + path
            try:
                if method == "GET":
                    r = c.get(url, headers=headers)
                else:
                    body = {"symbol": "KSE100"} if "historical" in path else {}
                    r = c.post(url, headers=headers, data=body)
                ct = r.headers.get("content-type", "")
                snippet = r.text[:200].replace("\n", " ")
                out.append(f"{method} {path} -> {r.status_code} {ct} | {snippet}")
            except Exception as e:
                out.append(f"{method} {path} -> ERROR {e}")
    fixture = Path("tests/fixtures/indices_probe.txt")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    probe()
