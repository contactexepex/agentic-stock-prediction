"""Shared NSE (National Stock Exchange of India) access for the India collectors:
collect_relations_india.py (insiders, deals, holdings) and collect_nse_india.py
(announcements, financials, flows, delivery).

NSE serves its JSON only to browser-like clients: one session per run loads the home page for
its cookies, then calls /api/... with a Referer, pausing between requests. Files on
nsearchives.nseindia.com (XBRL filings, CSV reports) are fetched through the same session.
The environment must allow www.nseindia.com and nsearchives.nseindia.com.

`--replay DIR` reads responses from local files instead of the network: an API call reads
<endpoint>[_<symbol>][_<optionType>].json, an archive file reads its base name. Replayed rows
can be synthetic, so replay only writes to an explicit scratch root (see replay_problem)."""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from common import (CODE, ROOT, SCHEMAS, append_jsonl, data_dir, day_file, market_arg, recent_ids,
                    require_market, utc_today)

IST = ZoneInfo("Asia/Kolkata")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
PAGES = {  # Referer per API: NSE checks that the call comes from its own page
    "corporates-pit-gg": "/companies-listing/corporate-filings-insider-trading",
    "bulk-block-short-deals": "/report-detail/display-bulk-and-block-deals",
    "snapshot-capital-market-largedeal": "/market-data/large-deals",
    "corporate-share-holdings-master": "/companies-listing/corporate-filings-shareholding-pattern",
    "corporate-pledgedata": "/companies-listing/corporate-filings-pledged-data",
    "corporate-announcements": "/companies-listing/corporate-filings-announcements",
    "integrated-filing-results": "/companies-listing/corporate-integrated-filing",
    "corporates-financial-results": "/companies-listing/corporate-filings-financial-results",
    "fiidiiTradeReact": "/reports/fii-dii",
}
ARCHIVES_HOST = "nsearchives.nseindia.com"


class FetchError(Exception):
    def __init__(self, url: str, error: str, host: str | None = None):
        super().__init__(error)
        self.url, self.error, self.host = url, error, host

    def entry(self, source: str) -> dict:
        e = {"source": source, "url": self.url, "error": self.error[:200]}
        if self.host:
            e["allowlist"] = self.host
        return e


class Nse:
    """Minimal NSE client: one cookie session, browser headers, polite pacing."""

    def __init__(self, base: str = "https://www.nseindia.com", archives: str = "https://nsearchives.nseindia.com",
                 replay: Path | None = None, pause: float = 0.7):
        self.base, self.archives, self.replay, self.pause = base.rstrip("/"), archives.rstrip("/"), replay, pause
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.warm_error: FetchError | None = None
        self.warmed = False
        self.requests = 0

    def _open(self, url: str, accept: str, referer: str | None = None) -> bytes:
        headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8"}
        if referer:
            headers["Referer"] = referer
        host = urllib.parse.urlsplit(url).hostname
        for attempt in (1, 2):   # one retry for transient network errors (TLS EOF, reset, timeout)
            self.requests += 1
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                raise FetchError(url, f"HTTP {exc.code} from {host} (NSE refused or no such file)") from exc
            except (urllib.error.URLError, OSError) as exc:
                reason = str(getattr(exc, "reason", exc))
                if "Tunnel connection failed" in reason or "403" in reason:
                    # the egress proxy refuses this host: every later call fails the same way
                    raise FetchError(url, f"egress proxy denied {host}: {reason}", host) from exc
                if attempt == 2:
                    raise FetchError(url, f"{host} unreachable after a retry: {reason}") from exc
                time.sleep(2)
            finally:
                time.sleep(self.pause)
        raise AssertionError("unreachable")

    def _warm(self) -> None:
        if not self.warmed:
            self.warmed = True
            try:
                self._open(self.base + "/", "text/html,application/xhtml+xml")
            except FetchError as exc:
                self.warm_error = exc
        if self.warm_error and self.warm_error.host:   # host not reachable at all: fail fast
            raise self.warm_error

    def json(self, endpoint: str, params: dict | None = None):
        params = params or {}
        if self.replay:
            keys = [params[k] for k in ("symbol", "optionType") if params.get(k)]
            return self._replay("_".join([endpoint.rsplit("/", 1)[-1], *keys]) + ".json", json.loads)
        url = f"{self.base}/api/{endpoint}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        self._warm()
        referer = self.base + PAGES.get(endpoint.rsplit("/", 1)[-1], "/")
        try:
            return json.loads(self._open(url, "application/json, text/plain, */*", referer))
        except json.JSONDecodeError as exc:
            raise FetchError(url, f"not JSON (likely an NSE block page): {exc}") from exc

    def text(self, path_or_url: str) -> str:
        """An archive file by path (/content/...) or by its full nsearchives URL."""
        path = path_or_url.split(ARCHIVES_HOST, 1)[-1] if ARCHIVES_HOST in path_or_url else path_or_url
        if self.replay:
            return self._replay(path.rsplit("/", 1)[-1], lambda s: s)
        return self._open(self.archives + path, "text/csv,application/xml,*/*", self.base + "/").decode("utf-8", "replace")

    def _replay(self, name: str, parse):
        f = self.replay / name
        if not f.exists():
            raise FetchError(f"replay:{name}", "no replay file")
        return parse(f.read_text(encoding="utf-8"))


# ---------- parsing helpers (NSE fields are strings; "-", "" and "Nil" mean missing) ----------

def num(x) -> float | None:
    """'1,234.5' -> 1234.5. A literal '0' is a real zero; missing markers give None."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def pick(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "-", "Nil", "NA"):
            return v.strip() if isinstance(v, str) else v
    return None


def parse_ts(s) -> datetime | None:
    """NSE dates/times (IST) -> aware UTC datetime."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d",
                "%d %b %Y", "%d-%B-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def parse_day(s) -> date | None:
    ts = parse_ts(s)
    return ts.astimezone(IST).date() if ts else None


def rows_of(payload, key: str | None = None) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get(key) if key else payload.get("data", [])
    return [r for r in payload or [] if isinstance(r, dict)]


def short_hash(*parts) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()[:12]


def iso(x) -> str | None:
    return x.isoformat() if x else None


def nse_symbols(cfg: dict) -> dict[str, str]:
    """NSE symbol -> watchlist ticker."""
    return {meta.get("nse", meta["yahoo"].removesuffix(".NS")).upper(): t for t, meta in cfg["tickers"].items()}


# ---------- XBRL (SEBI PIT and Integrated Filing instance documents) ----------

_CTX = re.compile(r"<xbrli:context id=\"([^\"]+)\">(.*?)</xbrli:context>", re.S)
_PER = re.compile(r"<xbrli:(startDate|endDate|instant)>([^<]+)<")
_FACT = re.compile(r"<([A-Za-z][\w-]*):([A-Za-z]\w*)\s+contextRef=\"([^\"]+)\"[^>]*?(?:/>|>([^<]*)</\1:\2>)", re.S)


def xbrl(text: str) -> tuple[dict[str, dict], dict[str, dict[str, str]]]:
    """(contexts, facts): contexts[id] = {start, end, instant, dimensional}; facts[context][name] = value."""
    contexts = {}
    for cid, body in _CTX.findall(text):
        per = dict(_PER.findall(body))
        contexts[cid] = {"start": per.get("startDate"), "end": per.get("endDate"), "instant": per.get("instant"),
                         "dimensional": "xbrldi:" in body}
    facts: dict[str, dict[str, str]] = {}
    for _prefix, name, ctx, value in _FACT.findall(text):
        facts.setdefault(ctx, {})[name] = (value or "").strip()
    return contexts, facts


# ---------- replay guard ----------

SCRATCH_MARKER = ".scratch-ok"
REPO_MARKERS = (".git", "CLAUDE.md")


def write_target(market: str, kind: str, day: date) -> Path:
    """The file day_file() would append to, computed without creating any directory."""
    ext = SCHEMAS[kind][0]
    return data_dir(market) / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{ext}"


def replay_problem(root: Path, targets: list[Path]) -> str | None:
    """Replayed rows can be synthetic, so they may only go to an explicit scratch root. Returns
    why `root` is refused, or None. Checked before anything (even a directory) is created."""
    root = Path(root)
    if not (root / SCRATCH_MARKER).is_file():
        return f"no {SCRATCH_MARKER} marker file in MB_ROOT ({root}); create it to mark a scratch root"
    for marker in REPO_MARKERS:
        if (root / marker).exists():
            return f"MB_ROOT ({root}) contains {marker}: looks like a repo checkout"
    if any(p.is_file() for p in (root / "data").glob("*/prices/**/*")):
        return f"MB_ROOT ({root}) has price files under data/*/prices: looks like a real data store"
    base = root.resolve() / "data"           # the root's own data/, not where a data/ symlink points
    real = (CODE / "data").resolve()
    for t in targets:
        r = t.resolve()                      # follows any symlinked directory on the way
        if not r.is_relative_to(base):
            return f"write target {t} resolves to {r}, outside {base} (symlink?)"
        if r.is_relative_to(real):
            return f"write target {t} resolves into this checkout's data/ ({real})"
        for parent in r.parents:             # never inside any repo checkout's data
            if any((parent / m).exists() for m in REPO_MARKERS):
                return f"write target {t} resolves into a repo checkout ({parent})"
        if r.exists():                       # hard links survive resolve(): check the inode itself
            st = r.stat()
            if st.st_nlink > 1:
                return f"write target {t} is hard-linked ({st.st_nlink} links); replay never appends to it"
            real_inodes = {(s.st_dev, s.st_ino) for f in real.rglob("*") if f.is_file() for s in [f.stat()]}
            if (st.st_dev, st.st_ino) in real_inodes:
                return f"write target {t} is the same file as one in this checkout's data/"
    return None


# ---------- shared collector plumbing ----------

def store(market: str, kind: str, rows: list[dict], today: date, seen_days: int = 400) -> int:
    """Append rows whose id is new (append-only, de-duplicated against recent files)."""
    seen = recent_ids(market, kind, days=seen_days)
    fresh = {r["id"]: r for r in rows if r["id"] not in seen}
    return append_jsonl(day_file(market, kind, today), fresh.values())


def coverage(source: str, total: int, matched: int | None, notes: list, warnings: list) -> None:
    """Say how many rows an endpoint returned market-wide and how many were for the watchlist,
    so an endpoint that returns nothing at all (blocked, retired or changed) is never mistaken
    for a quiet period with nothing for our tickers."""
    if total == 0:
        warnings.append(f"{source}: endpoint returned no rows at all (not just none for the watchlist); "
                        "check it is still live")
    else:
        notes.append(f"{source}: {total} rows returned" +
                     ("" if matched is None else f", {matched} for watchlist tickers"))


def summary_of(name: str, market: str, new: dict, failed: list, notes: list, nse: Nse,
               warnings: list | None = None) -> dict:
    out = {"collector": name, "market": market, "new": new, "failed": failed, "warnings": warnings or [],
           "notes": notes, "requests": nse.requests}
    hosts = sorted({f["allowlist"] for f in failed if "allowlist" in f})
    if hosts:
        out["allowlist_needed"] = hosts
    return out


def collector_main(doc: str, name: str, kinds: list[str], collect, extra_args=None) -> int:
    """Argument parsing, market check, replay guard, one NSE session, JSON summary.
    `collect(cfg, nse, kinds, today, args) -> summary`."""
    ap = market_arg(doc)
    ap.add_argument("--replay", type=Path,
                    help="read responses from files in this directory instead of NSE (offline tests and "
                         "debugging; writes only to a scratch MB_ROOT that holds a .scratch-ok file)")
    ap.add_argument("--only", choices=kinds, action="append", help="collect only these kinds (repeatable)")
    ap.add_argument("--today", type=date.fromisoformat,
                    help="with --replay only: the collection date the saved responses belong to (YYYY-MM-DD)")
    if extra_args:
        extra_args(ap)
    args = ap.parse_args()
    cfg = require_market(args)
    market, rel = cfg["market"], cfg.get("relations") or {}
    if rel.get("source") != "nse":
        print(json.dumps({"collector": name, "market": market,
                          "skipped": "no `relations.source: nse` in this market's config"}))
        return 0
    if args.today and not args.replay:
        raise SystemExit("--today is only allowed with --replay")
    only, today = args.only or kinds, args.today or utc_today()
    if args.replay:
        problem = replay_problem(ROOT, [write_target(market, k, today) for k in only])
        if problem:
            print(json.dumps({"collector": name, "market": market,
                              "error": f"--replay writes synthetic rows; refusing: {problem}"}))
            return 2
    nse = Nse(rel.get("base", "https://www.nseindia.com"), rel.get("archives", "https://nsearchives.nseindia.com"),
              args.replay, pause=0 if args.replay else float(rel.get("pause_seconds", 0.7)))
    summary = collect(cfg, nse, only, today, args)
    print(json.dumps(summary, indent=2))
    return 1 if all(v is None for v in summary["new"].values()) else 0


if __name__ == "__main__":
    sys.exit("library module; run collect_relations_india.py or collect_nse_india.py")
