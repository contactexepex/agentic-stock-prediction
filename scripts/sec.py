"""SEC EDGAR helpers for the SEC collectors (collect_filings, collect_events, collect_insiders,
collect_stakes, collect_holdings, collect_fundamentals). Free endpoints only. SEC requires a descriptive User-Agent with contact
info (SEC_USER_AGENT="your-name your@email.com") and at most 10 requests/second; every request
here goes through one throttle (MIN_INTERVAL) and backs off on 429/503. The throttle is per
process, so the SEC collectors must run one after another, never in parallel.

A ticker's filings can sit under more than one CIK: SEC's ticker map names the current
registrant, while an earlier (or related) registrant may still file (XOM: the holding company
2115436 since 2026-07-01, while Exxon Mobil Corp 34088 still lists filings and holds the
earlier history). `related_ciks`
reads those CIKs from the market config (`fundamentals.predecessor_ciks`) and `ticker_submissions`
fetches and merges the submission lists of all of a ticker's CIKs; every per-ticker collector
uses it (collect_holdings follows 13F filers, not tickers).

Acceptance times. The submissions JSON's `acceptanceDateTime` (labelled UTC, "Z") is not always
true: since 2026-10-05 some CIKs' submission files are served with every acceptance time shifted
later by the New York UTC offset of that moment (+4h in EDT, +5h in EST; the ET wall-clock time
converted to UTC twice), while other CIKs' files are right (by 2026-10-06 the shifted files were
exactly those regenerated after a new filing on 2026-10-05). The shift is uniform over a whole
file, so `Edgar.recent` checks each file against the authoritative time, the SGML header
`<ACCEPTANCE-DATETIME>` (YYYYMMDDHHMMSS, US Eastern; `<acc>.hdr.sgml`, the same time as the index
page's "Accepted") of its newest and its oldest listed filing. Both right: the column is kept
("ok"). Both shifted: every value is corrected ("shifted": true = JSON minus the ET offset; the
JSON value is kept in `acceptanceDateTimeJson`). Anything else (a header that cannot be read, a
difference that is not that offset, or a mixed file with one right and one shifted) keeps the
column as served and says so ("unverified: ..."): never unshift a value that may be right, which
would make it 4-5h too early (look-ahead). Statuses are in `Edgar.time_checks` (CIK -> status);
`time_summary` goes into the collectors' summaries as `sec_times`, and `time_warnings` puts each
unverified CIK into their `warnings` (the routine lists them in data_quality). Header times are
immutable, so they are cached per accession in work/sec_acceptance.json (under MB_ROOT): a second
collector in the same run, or a later run whose newest filing is unchanged, costs no extra
request. Stored rows (including those stored from an unverified file) are corrected on read
through `sec_times`: scripts/check_sec_times.py, run by the routine after the SEC collectors,
appends each new accession's header time, and common.connect applies them.

Tests run offline: with MB_SEC_FIXTURES=<dir>, URLs are served from <dir>/urls.json
({url: file path, absolute or relative to <dir>}) instead of the network (a header missing from
the fixtures leaves the file "unverified" without counting a request; the disk cache is not used)."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MIN_INTERVAL = 0.15  # seconds between requests (<= ~7 req/s, under SEC's 10/s limit)
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
EASTERN = ZoneInfo("America/New_York")   # EDGAR's clock (SGML header and index page times)
ROOT = Path(os.environ.get("MB_ROOT", Path(__file__).resolve().parents[1]))
ACCEPT_CACHE = "work/sec_acceptance.json"


def iso_z(ts: datetime) -> str:
    """UTC instant in the submissions JSON's format (2026-07-14T10:30:38.000Z)."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_z(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)


def et_offset_hours(ts: datetime) -> int:
    """Hours New York is behind UTC at that instant (4 in EDT, 5 in EST)."""
    return int(-ts.astimezone(EASTERN).utcoffset().total_seconds() // 3600)


def sgml_acceptance(data: bytes) -> str | None:
    """<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS (US Eastern) of a filing's SGML header -> UTC (iso_z)."""
    m = re.search(rb"<ACCEPTANCE-DATETIME>\s*(\d{14})", data)
    if not m:
        return None
    return iso_z(datetime.strptime(m.group(1).decode(), "%Y%m%d%H%M%S").replace(tzinfo=EASTERN))


def is_shifted(json_value: str, true_value: str) -> bool:
    """The submissions-JSON error: the JSON time is later than the true one by exactly the ET
    UTC offset at the true instant."""
    t = parse_z(true_value)
    return parse_z(json_value) - t == timedelta(hours=et_offset_hours(t))


def unshift(json_value: str) -> str:
    """Invert the shift: true = JSON - h with h the ET offset at the true instant (h = 4 or 5,
    the one consistent with itself; around a DST change, where both could be, EST's 5 is tried
    first; filings are not accepted at 1-3am on a Sunday, so this never matters in practice)."""
    j = parse_z(json_value)
    for h in (5, 4):
        if et_offset_hours(j - timedelta(hours=h)) == h:
            return iso_z(j - timedelta(hours=h))
    return iso_z(j - timedelta(hours=et_offset_hours(j)))


class Edgar:
    def __init__(self, ua: str):
        self.ua = ua
        self.last = 0.0
        self.requests = 0
        fx = os.environ.get("MB_SEC_FIXTURES")
        self.fixtures = Path(fx) if fx else None
        self.urls = json.loads((self.fixtures / "urls.json").read_text()) if fx else {}
        self.time_checks: dict[str, str] = {}   # CIK -> ok | shifted | unverified: <why>
        self._accepted: dict[str, str] | None = None   # accession -> true acceptance (iso_z)

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

    def _cache(self) -> dict[str, str]:
        if self._accepted is None:
            self._accepted = {}
            if not self.fixtures:
                try:
                    self._accepted = json.loads((ROOT / ACCEPT_CACHE).read_text())
                except (OSError, ValueError):
                    pass
        return self._accepted

    def acceptance(self, cik: int | str, accession: str) -> str | None:
        """True acceptance time (UTC, iso_z) of a filing from its SGML header (cached)."""
        cache = self._cache()
        if accession not in cache:
            v = sgml_acceptance(self.get(archive_url(cik, accession, f"{accession}.hdr.sgml")))
            if v is None:
                return None
            cache[accession] = v
            if not self.fixtures:
                try:
                    path = ROOT / ACCEPT_CACHE
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(cache))
                    tmp.replace(path)
                except OSError:
                    pass
        return cache[accession]

    def _verdict(self, cik: int | str, accession: str, json_value: str) -> str:
        """One filing: "ok" (JSON = header), "shifted" (JSON = header + ET offset) or
        "unverified: <why>"."""
        if (self.fixtures and accession not in self._cache()
                and archive_url(cik, accession, f"{accession}.hdr.sgml") not in self.urls):
            return "unverified: no header fixture"      # tests without header fixtures: no request
        try:
            true = self.acceptance(cik, accession)
        except Exception as exc:
            return f"unverified: header {accession}: {str(exc)[:100]}"
        if true is None:
            return f"unverified: no ACCEPTANCE-DATETIME in {accession}"
        if parse_z(json_value) == parse_z(true):
            return "ok"
        if is_shifted(json_value, true):
            return "shifted"
        return f"unverified: {accession} JSON {json_value} vs header {true}"

    def check_times(self, cik: int | str, rec: dict) -> str:
        """Check a submissions block's acceptanceDateTime against the SGML headers of its newest
        and its oldest listed filing (one cached request each; one when they are the same filing)
        and correct the whole column in place only when both are shifted. Both right: "ok".
        Anything else, including a mixed file (one right, one shifted), is "unverified: ..." and
        the column is kept as served: correcting a right value would make it 4-5h too early
        (look-ahead), keeping a shifted one only makes it late."""
        acc = rec.get("accessionNumber") or []
        col = rec.get("acceptanceDateTime") or []
        idx = [k for k, v in enumerate(col) if v and k < len(acc) and acc[k]]
        if not idx:
            status = "unverified: no acceptance time with an accession number"
        else:
            probes = list(dict.fromkeys([idx[0], idx[-1]]))         # newest, oldest
            verdicts = [self._verdict(cik, acc[k], col[k]) for k in probes]
            bad = [v for v in verdicts if v.startswith("unverified")]
            if bad:
                status = bad[0]
            elif len(set(verdicts)) > 1:
                status = (f"unverified: mixed file (newest {acc[probes[0]]} {verdicts[0]}, "
                          f"oldest {acc[probes[1]]} {verdicts[1]})")
            elif verdicts[0] == "shifted":
                rec["acceptanceDateTimeJson"] = list(col)
                rec["acceptanceDateTime"] = [unshift(v) if v else v for v in col]
                status = "shifted"
            else:
                status = "ok"
        self.time_checks[str(int(cik))] = status
        return status

    def recent(self, cik: int) -> dict:
        """The `filings.recent` block of a company's submissions (latest ~1000 filings), with
        `acceptanceDateTime` checked and, if shifted, corrected (check_times)."""
        d = self.json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        rec = {"name": d.get("name"), **d["filings"]["recent"]}
        self.check_times(cik, rec)
        return rec


def time_summary(edgar: Edgar) -> dict:
    """Collector summary of the acceptance-time checks: {"ok": n, "shifted": [CIK], "unverified": {CIK: why}}."""
    checks = getattr(edgar, "time_checks", {})
    return {"ok": sum(v == "ok" for v in checks.values()),
            "shifted": sorted(c for c, v in checks.items() if v == "shifted"),
            "unverified": {c: v.split(": ", 1)[-1] for c, v in checks.items() if v.startswith("unverified")}}


def time_warnings(checked: Edgar | dict) -> list[str]:
    """One warning per CIK whose acceptance times could not be verified (stored as served, maybe
    4-5h late): for the collectors' `warnings` (the routine lists them in data_quality). Takes the
    Edgar client or a time_summary dict."""
    summary = checked if isinstance(checked, dict) else time_summary(checked)
    return [f"SEC acceptance times of CIK {c} unverified, stored as served (maybe 4-5h late): {why}"
            for c, why in (summary.get("unverified") or {}).items()]


def related_ciks(cfg: dict) -> dict[str, list[int]]:
    """Ticker -> CIKs of earlier or related registrants whose filings also belong to the ticker
    (`fundamentals.predecessor_ciks` in config/markets/<market>.yaml: the one list every SEC
    collector reads)."""
    found = (cfg.get("fundamentals") or {}).get("predecessor_ciks") or {}
    return {str(t).upper(): [int(c) for c in (cs if isinstance(cs, list) else [cs])] for t, cs in found.items()}


def merge_recent(parts: list[tuple[int | str, dict]]) -> dict:
    """Merge the `filings.recent` blocks of several CIKs (the mapped CIK first) into one, column
    by column, with an added `cik` column (the CIK whose submission list holds the filing, i.e.
    the archive folder it is served from). A filing listed under several CIKs (a joint filing) is
    kept once, under the first CIK that lists it. One CIK: its block unchanged plus the `cik`
    column. Several: newest first (by filing date, then acceptance time); a column missing from
    one CIK's block is None for its filings."""
    if len(parts) == 1:
        cik, rec = parts[0]
        return {**rec, "cik": [cik] * len(rec["form"])}
    cols = [c for c in dict.fromkeys(k for _, rec in parts for k in rec) if c not in ("name", "cik")]
    rows, seen = [], set()
    for cik, rec in parts:
        n = len(rec["form"])
        accs = rec.get("accessionNumber") or [None] * n
        for i in range(n):
            if accs[i] is not None:
                if accs[i] in seen:
                    continue
                seen.add(accs[i])
            row = {c: (rec[c][i] if isinstance(rec.get(c), list) else None) for c in cols}
            row["cik"] = cik
            rows.append(row)
    rows.sort(key=lambda r: (r.get("filingDate") or "", r.get("acceptanceDateTime") or ""), reverse=True)
    out = {c: [r[c] for r in rows] for c in [*cols, "cik"]}
    out["name"] = parts[0][1].get("name")
    return out


def ticker_submissions(edgar: Edgar, ticker: str, cik, related: dict[str, list[int]] | None = None
                       ) -> tuple[dict | None, list[dict]]:
    """The submissions (`filings.recent`) of a ticker's mapped CIK plus its related CIKs (see
    related_ciks), merged and de-duplicated by accession number (merge_recent). One request per
    CIK, each through the Edgar throttle. Returns (merged block, failures): each CIK whose request
    fails is one failure {"ticker", "cik", "error"}, and the CIKs that answered are still merged;
    the block is None only when every CIK failed."""
    ciks = [cik, *[c for c in (related or {}).get(str(ticker).upper(), []) if int(c) != int(cik)]]
    parts, failed = [], []
    for c in ciks:
        try:
            parts.append((c, edgar.recent(c)))
        except Exception as exc:
            failed.append({"ticker": ticker, "cik": c, "error": str(exc)[:200]})
    return (merge_recent(parts) if parts else None), failed


def filings(recent: dict, forms: set[str], since: date | None = None) -> list[dict]:
    """Filings of the given forms filed on/after `since`, in list order (newest first). `cik` is
    the CIK whose submission list holds the filing (merge_recent's column), else None."""
    n, out = len(recent["form"]), []
    accepted = recent.get("acceptanceDateTime") or [None] * n
    reported = recent.get("reportDate") or [None] * n
    ciks = recent.get("cik") or [None] * n
    for i, form in enumerate(recent["form"]):
        filed = recent["filingDate"][i]
        if form not in forms or (since and date.fromisoformat(filed) < since):
            continue
        out.append({"accession": recent["accessionNumber"][i], "form": form, "filing_date": filed,
                    "accepted_at": accepted[i] or None, "primary_doc": recent["primaryDocument"][i],
                    "report_date": reported[i] or None, "cik": ciks[i]})
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
