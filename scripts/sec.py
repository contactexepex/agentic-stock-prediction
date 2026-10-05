"""SEC EDGAR helpers for the relationship collectors (collect_insiders, collect_stakes,
collect_holdings). Free endpoints only. SEC requires a descriptive User-Agent with contact
info (SEC_USER_AGENT="your-name your@email.com") and at most 10 requests/second; every request
here goes through one throttle (MIN_INTERVAL) and backs off on 429/503. The throttle is per
process, so the SEC collectors must run one after another, never in parallel.

Tests run offline: with MB_SEC_FIXTURES=<dir>, URLs are served from <dir>/urls.json
({url: file path, absolute or relative to <dir>}) instead of the network."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

MIN_INTERVAL = 0.15  # seconds between requests (<= ~7 req/s, under SEC's 10/s limit)
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"


class Edgar:
    def __init__(self, ua: str):
        self.ua = ua
        self.last = 0.0
        self.requests = 0
        fx = os.environ.get("MB_SEC_FIXTURES")
        self.fixtures = Path(fx) if fx else None
        self.urls = json.loads((self.fixtures / "urls.json").read_text()) if fx else {}

    def _fixture(self, url: str) -> Path:
        if url not in self.urls:
            raise FileNotFoundError(f"no fixture for {url}")
        return self.fixtures / self.urls[url]

    def open(self, url: str):
        """Streaming response (file-like). Throttled; retries twice on 429/5xx."""
        self.requests += 1
        if self.fixtures:
            return self._fixture(url).open("rb")
        for attempt in range(3):
            wait = self.last + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
                return urllib.request.urlopen(req, timeout=60)
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(2 + 3 * attempt)
                    continue
                raise
        raise RuntimeError("unreachable")

    def get(self, url: str) -> bytes:
        with self.open(url) as resp:
            return resp.read()

    def json(self, url: str):
        return json.loads(self.get(url))

    def cik_map(self) -> dict[str, int]:
        data = self.json("https://www.sec.gov/files/company_tickers.json")
        return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}

    def recent(self, cik: int) -> dict:
        """The `filings.recent` block of a company's submissions (latest ~1000 filings)."""
        d = self.json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        return {"name": d.get("name"), **d["filings"]["recent"]}


def filings(recent: dict, forms: set[str], since: date | None = None) -> list[dict]:
    """Filings of the given forms filed on/after `since`, newest first."""
    n, out = len(recent["form"]), []
    accepted = recent.get("acceptanceDateTime") or [None] * n
    reported = recent.get("reportDate") or [None] * n
    for i, form in enumerate(recent["form"]):
        filed = recent["filingDate"][i]
        if form not in forms or (since and date.fromisoformat(filed) < since):
            continue
        out.append({"accession": recent["accessionNumber"][i], "form": form, "filing_date": filed,
                    "accepted_at": accepted[i] or None, "primary_doc": recent["primaryDocument"][i],
                    "report_date": reported[i] or None})
    return out


def raw_doc(primary_doc: str) -> str:
    """Form 4 / 13D / 13G primary documents are listed as an XSL rendering
    ("xslF345X06/form4.xml"); the raw XML is the same file without the XSL folder."""
    return primary_doc.split("/", 1)[1] if primary_doc.startswith("xsl") and "/" in primary_doc else primary_doc


def archive_url(cik: int | str, accession: str, doc: str = "") -> str:
    return f"{ARCHIVE}/{int(cik)}/{accession.replace('-', '')}/{doc}"


def xml_root(data: bytes) -> ET.Element:
    """Parse XML and drop namespaces so paths read like the plain tag names."""
    root = ET.fromstring(data)
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    v = el.findtext(path)
    v = v.strip() if v else None
    return v or None


def num(v: str | None) -> float | None:
    try:
        return float(v.replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def flag(v: str | None) -> bool | None:
    if v is None:
        return None
    return v.strip().lower() in ("1", "true", "y", "yes")


def us_date(v: str | None) -> str | None:
    """MM/DD/YYYY (13D/13G cover pages) or ISO -> ISO date string."""
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip()[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def require_sec(cfg: dict, collector: str) -> str | None:
    """User-Agent for SEC markets; prints a JSON summary and returns None when not applicable."""
    if cfg.get("filings") != "sec":
        print(json.dumps({"collector": collector, "market": cfg["market"],
                          "skipped": "no SEC filings for this market (the market's own collector covers it)"}))
        return None
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        print(json.dumps({"collector": collector, "market": cfg["market"], "error": "SEC_USER_AGENT not set"}))
        raise SystemExit(1)
    return ua


def watch_ciks(cfg: dict, edgar: Edgar) -> tuple[dict[str, int], list[str]]:
    """Watchlist ticker -> CIK (via SEC's ticker map); tickers not registered with the SEC are skipped."""
    cmap = edgar.cik_map()
    found, skipped = {}, []
    for ticker, meta in cfg["tickers"].items():
        cik = cmap.get(str(meta.get("sec_ticker", ticker)).upper())
        if cik is None:
            skipped.append(ticker)
        else:
            found[ticker] = cik
    return found, skipped
