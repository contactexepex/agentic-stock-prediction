#!/usr/bin/env python3
"""Collect India relationship data for watchlist tickers from NSE's public JSON endpoints:
  insiders  SEBI PIT insider/promoter trading disclosures   -> data/india/insiders/
  deals     bulk and block deals                             -> data/india/deals/
  holdings  quarterly shareholding (promoter %) and promoter pledges -> data/india/holdings/
Append-only, de-duplicated by id; files are dated by the UTC collection day. Prints a JSON
summary; a source that fails gets a "failed" entry naming the host to allowlist. Exit code 1
only if every source failed. Needs `relations.source: nse` in the market config.

NSE serves these only to browser-like clients: the session first loads the home page for its
cookies, then calls /api/... with a Referer. Field names follow public open-source NSE scrapers
and are not yet checked against a live NSE response (NSE was not reachable when this was built).
`--replay DIR` reads responses from local files instead of the network, named
<endpoint>[_<symbol or optionType>].json and <name>.csv. The files in tests/fixtures/nse are
synthetic (hand-written to match those field names), so replay only writes to an explicit
scratch root: MB_ROOT must contain a `.scratch-ok` file, must not look like a repo checkout or a
real data store (.git, CLAUDE.md, price files), and every write target must resolve inside
MB_ROOT's own data/ (no symlinks out), outside any repo checkout, and not be a hard-linked file."""
from __future__ import annotations

import csv
import hashlib
import http.cookiejar
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from common import (CODE, ROOT, SCHEMAS, append_jsonl, data_dir, day_file, market_arg, recent_ids,
                    require_market, utc_now, utc_today)

IST = ZoneInfo("Asia/Kolkata")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
PAGES = {  # Referer per API: NSE checks that the call comes from its own page
    "corporates-pit": "/companies-listing/corporate-filings-insider-trading",
    "bulk-block-short-deals": "/report-detail/display-bulk-and-block-deals",
    "snapshot-capital-market-largedeal": "/market-data/large-deals",
    "corporate-share-holdings-master": "/companies-listing/corporate-filings-shareholding-pattern",
    "corporate-pledgedata": "/companies-listing/corporate-filings-pledged-data",
}
KEEP_QUARTERS = 4   # shareholding periods kept per ticker (enough for a q/q pledge change)


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
    """Minimal NSE client: cookie warm-up, browser headers, polite pacing."""

    def __init__(self, base: str, archives: str, replay: Path | None = None, pause: float = 0.7):
        self.base, self.archives, self.replay, self.pause = base.rstrip("/"), archives.rstrip("/"), replay, pause
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.warm_error: FetchError | None = None
        self.warmed = False

    def _open(self, url: str, accept: str, referer: str | None = None) -> bytes:
        headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9,en-IN;q=0.8"}
        if referer:
            headers["Referer"] = referer
        host = urllib.parse.urlsplit(url).hostname
        try:
            with self.opener.open(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise FetchError(url, f"HTTP {exc.code} from {host} (NSE refused: cookie/headers or rate limit)") from exc
        except (urllib.error.URLError, OSError) as exc:
            reason = str(getattr(exc, "reason", exc))
            if "Tunnel connection failed" in reason or "403" in reason:
                raise FetchError(url, f"egress proxy denied {host}: {reason}", host) from exc
            raise FetchError(url, f"{host} unreachable: {reason}", host) from exc
        finally:
            time.sleep(self.pause)

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
            key = params.get("symbol") or params.get("optionType")
            name = endpoint.rsplit("/", 1)[-1] + (f"_{key}" if key else "")
            return self._replay(name + ".json", json.loads)
        url = f"{self.base}/api/{endpoint}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        self._warm()
        referer = self.base + PAGES.get(endpoint.rsplit("/", 1)[-1], "/")
        try:
            return json.loads(self._open(url, "application/json, text/plain, */*", referer))
        except json.JSONDecodeError as exc:
            raise FetchError(url, f"not JSON (likely an NSE block page): {exc}") from exc

    def text(self, path: str) -> str:
        if self.replay:
            return self._replay(path.rsplit("/", 1)[-1], lambda s: s)
        return self._open(self.archives + path, "text/csv,*/*", self.base + "/").decode("utf-8", "replace")

    def _replay(self, name: str, parse):
        f = self.replay / name
        if not f.exists():
            raise FetchError(f"replay:{name}", "no replay file")
        return parse(f.read_text(encoding="utf-8"))


# ---------- parsing helpers (NSE fields are strings; "-", "" and "Nil" mean missing) ----------

def num(x) -> float | None:
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
                "%d %b %Y", "%d-%B-%Y", "%Y-%m-%dT%H:%M:%S"):
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


# ---------- sources ----------

def insiders(nse: Nse, symbols: dict[str, str], today: date, lookback: int, now: str) -> list[dict]:
    payload = nse.json("corporates-pit", {"index": "equities", "from_date": f"{today - timedelta(days=lookback):%d-%m-%Y}",
                                          "to_date": f"{today:%d-%m-%Y}"})
    out = []
    for r in rows_of(payload):
        ticker = symbols.get((r.get("symbol") or "").strip().upper())
        if not ticker:
            continue
        person, txn = pick(r, "acqName"), pick(r, "tdpTransactionType")
        t_from, t_to = parse_day(pick(r, "acqfromDt")), parse_day(pick(r, "acqtoDt"))
        shares, disclosed = num(pick(r, "secAcq")), parse_ts(pick(r, "date", "intimDt"))
        out.append({
            "id": "nse-pit-" + short_hash(ticker, person, txn, pick(r, "secType"), t_from, t_to, shares, disclosed),
            "ticker": ticker, "source": "nse_pit", "person": person,
            "person_category": pick(r, "personCategory"), "security_type": pick(r, "secType"),
            "transaction": txn, "mode": pick(r, "acqMode"), "shares": shares,
            "value": num(pick(r, "secVal")) or num(pick(r, "buyValue")) or num(pick(r, "sellValue")),
            "holding_before_pct": num(pick(r, "befAcqSharesPer")), "holding_after_pct": num(pick(r, "afterAcqSharesPer")),
            "trade_from": iso(t_from), "trade_to": iso(t_to), "disclosed_at": iso(disclosed),
            "url": pick(r, "xbrl"), "first_seen_at": now,
        })
    return out


def deal_record(r: dict, deal_type: str, source: str, symbols: dict[str, str], now: str) -> dict | None:
    """One bulk/block deal from any NSE shape: historical (BD_*), snapshot (camelCase), archive CSV."""
    sym = (pick(r, "BD_SYMBOL", "symbol", "Symbol") or "").upper()
    ticker = symbols.get(sym)
    if not ticker:
        return None
    day = parse_day(pick(r, "BD_DT_DATE", "date", "Date"))
    client = pick(r, "BD_CLIENT_NAME", "clientName", "Client Name")
    side = (pick(r, "BD_BUY_SELL", "buySell", "Buy/Sell", "Buy / Sell") or "").lower() or None
    shares = num(pick(r, "BD_QTY_TRD", "qty", "Quantity Traded"))
    price = num(pick(r, "BD_TP_WATP", "watp", "Trade Price / Wght. Avg. Price", "Trade Price / Wght. Avg. Price "))
    if day is None or shares is None:
        return None
    return {
        "id": f"nse-{deal_type}-{day}-{ticker}-" + short_hash(client, side, shares, price),
        "date": str(day), "ticker": ticker, "deal_type": deal_type, "client": client, "side": side,
        "shares": shares, "price": price, "value": round(shares * price, 2) if price else None,
        "remarks": pick(r, "BD_REMARKS", "remarks", "Remarks"), "source": source, "first_seen_at": now,
    }


def deals(nse: Nse, symbols: dict[str, str], today: date, lookback: int, now: str,
          notes: list, failed: list) -> list[dict]:
    """Per deal type: historical API over the lookback window, else today's snapshot, else the
    archive CSV. Ids ignore the source, so the same deal from two sources is stored once."""
    since, out, cache = today - timedelta(days=lookback), [], {}

    def snapshot_payload():   # one snapshot call serves both deal types
        if "snap" not in cache:
            cache["snap"] = nse.json("snapshot-capital-market-largedeal")
        return cache["snap"]

    for deal_type in ("bulk", "block"):
        attempts = [
            ("nse_historical", lambda dt=deal_type: rows_of(nse.json(
                "historicalOR/bulk-block-short-deals",
                {"optionType": f"{dt}_deals", "from": f"{since:%d-%m-%Y}", "to": f"{today:%d-%m-%Y}"}))),
            ("nse_snapshot", lambda dt=deal_type: rows_of(snapshot_payload(), f"{dt.upper()}_DEALS_DATA")),
            ("nse_archive", lambda dt=deal_type: list(csv.DictReader(io.StringIO(
                nse.text(f"/content/equities/{dt}.csv"))))),
        ]

        errors = []
        for source, fetch in attempts:
            try:
                rows = [{k.strip() if isinstance(k, str) else k: v for k, v in r.items()} for r in fetch()]
            except FetchError as exc:
                errors.append(exc)
                continue
            recs = [d for r in rows if (d := deal_record(r, deal_type, source, symbols, now))]
            out += [d for d in recs if d["date"] >= str(since)]
            if errors:
                notes.append(f"{deal_type} deals from {source} after {len(errors)} failed source(s)")
            break
        else:
            failed += [e.entry(f"deals:{deal_type}:{src}") for (src, _), e in zip(attempts, errors)]
    return out


def holdings(nse: Nse, symbols: dict[str, str], now: str, failed: list) -> list[dict]:
    out = []
    for sym, ticker in symbols.items():
        for source, endpoint in (("nse_shp", "corporate-share-holdings-master"), ("nse_pledge", "corporate-pledgedata")):
            try:
                rows = rows_of(nse.json(endpoint, {"index": "equities", "symbol": sym}))
            except FetchError as exc:
                failed.append(exc.entry(f"holdings:{source}:{ticker}"))
                if exc.host:          # host unreachable: every other symbol fails the same way
                    return out
                continue
            recs = []
            for r in rows:
                if source == "nse_shp":
                    period, filed = parse_day(pick(r, "date")), parse_ts(pick(r, "broadcastDate", "submissionDate"))
                    vals = {"promoter_pct": num(pick(r, "pr_and_prgrp")), "public_pct": num(pick(r, "public_val")),
                            "employee_trust_pct": num(pick(r, "employeeTrusts")), "url": pick(r, "xbrl")}
                else:
                    period, filed = parse_day(pick(r, "shp")), parse_ts(pick(r, "broadcastDt", "disclosureDate", "date"))
                    vals = {"promoter_pct": num(pick(r, "percPromoterHolding")),
                            "pledged_pct_of_promoter": num(pick(r, "percPromoterShares")),
                            "pledged_pct_of_total": num(pick(r, "percTotShares")), "url": None}
                if period is None:
                    continue
                recs.append({"id": f"{source.replace('_', '-')}-{ticker}-{period}-" + short_hash(filed, *vals.values()),
                             "ticker": ticker, "period_end": str(period), "source": source,
                             "filed_at": iso(filed), "first_seen_at": now, **vals})
            recs.sort(key=lambda x: (x["period_end"], x["filed_at"] or ""), reverse=True)
            periods = sorted({x["period_end"] for x in recs}, reverse=True)[:KEEP_QUARTERS]
            out += [x for x in recs if x["period_end"] in periods]
    return out


def nse_symbols(cfg: dict) -> dict[str, str]:
    """NSE symbol -> watchlist ticker."""
    return {meta.get("nse", meta["yahoo"].removesuffix(".NS")).upper(): t for t, meta in cfg["tickers"].items()}


SCRATCH_MARKER = ".scratch-ok"
REPO_MARKERS = (".git", "CLAUDE.md")


def write_target(market: str, kind: str, day: date) -> Path:
    """The file day_file() would append to, computed without creating any directory."""
    ext = SCHEMAS[kind][0]
    return data_dir(market) / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{ext}"


def replay_problem(root: Path, targets: list[Path]) -> str | None:
    """Replayed rows are synthetic, so they may only go to an explicit scratch root. Returns why
    `root` is refused, or None. Checked before anything (even a directory) is created."""
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


def collect(cfg: dict, nse: Nse, kinds: list[str], today: date | None = None) -> dict:
    """Fetch, de-duplicate and append each kind; return the JSON summary."""
    market, rel = cfg["market"], cfg.get("relations") or {}
    symbols, today, now = nse_symbols(cfg), today or utc_today(), utc_now()
    new, failed, notes = {}, [], []
    for kind in kinds:
        try:
            if kind == "insiders":
                rows = insiders(nse, symbols, today, int(rel.get("insider_lookback_days", 14)), now)
            else:
                n_failed = len(failed)
                rows = (deals(nse, symbols, today, int(rel.get("deal_lookback_days", 5)), now, notes, failed)
                        if kind == "deals" else holdings(nse, symbols, now, failed))
                if len(failed) > n_failed and not rows:
                    new[kind] = None
                    continue
        except FetchError as exc:
            failed.append(exc.entry(kind))
            new[kind] = None
            continue
        seen = recent_ids(market, kind, days=120)
        fresh = {r["id"]: r for r in rows if r["id"] not in seen}
        new[kind] = append_jsonl(day_file(market, kind, today), fresh.values())

    hosts = sorted({f["allowlist"] for f in failed if "allowlist" in f})
    summary = {"collector": "relations_india", "market": market, "new": new, "failed": failed, "notes": notes}
    if hosts:
        summary["allowlist_needed"] = hosts
    return summary


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--replay", type=Path,
                    help="read responses from files in this directory instead of NSE (offline tests and "
                         "debugging; writes only to a scratch MB_ROOT that holds a .scratch-ok file)")
    ap.add_argument("--only", choices=["insiders", "deals", "holdings"], action="append",
                    help="collect only these kinds (repeatable)")
    args = ap.parse_args()
    cfg = require_market(args)
    market, rel = cfg["market"], cfg.get("relations") or {}
    if rel.get("source") != "nse":
        print(json.dumps({"collector": "relations_india", "market": market,
                          "skipped": "no `relations.source: nse` in this market's config"}))
        return 0
    kinds, today = args.only or ["insiders", "deals", "holdings"], utc_today()
    if args.replay:
        problem = replay_problem(ROOT, [write_target(market, k, today) for k in kinds])
        if problem:
            print(json.dumps({"collector": "relations_india", "market": market,
                              "error": f"--replay writes synthetic rows; refusing: {problem}"}))
            return 2
    nse = Nse(rel.get("base", "https://www.nseindia.com"), rel.get("archives", "https://nsearchives.nseindia.com"),
              args.replay, pause=0 if args.replay else 0.7)
    summary = collect(cfg, nse, kinds, today)
    print(json.dumps(summary, indent=2))
    return 1 if all(v is None for v in summary["new"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
