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
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from common import (CODE, ROOT, SCHEMAS, append_jsonl, data_dir, day_file, market_arg, recent_ids,
                    require_market, utc_today)
from marketbrief.sources.errors import FetchError  # noqa: F401  (re-export: nse.FetchError)
from marketbrief.sources.nse_client import Nse  # noqa: F401  (re-export: nse.Nse)
from marketbrief.utils.numbers import parse_nse_number as num  # noqa: F401  (re-export: nse.num)

IST = ZoneInfo("Asia/Kolkata")


# ---------- parsing helpers (NSE fields are strings; "-", "" and "Nil" mean missing) ----------

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


SINCE_WINDOW_DAYS = 7   # --since backfills ask date-range endpoints one week at a time (smaller answers)


def date_windows(start: date, end: date, days: int = SINCE_WINDOW_DAYS) -> list[tuple[date, date]]:
    """Consecutive [from, to] windows of at most `days` days covering start..end (inclusive)."""
    out, s = [], start
    while s <= end:
        e = min(end, s + timedelta(days=days - 1))
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def since_arg(ap) -> None:
    ap.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD",
                    help="backfill: ask the date-range endpoints from this date to today in one-week windows "
                         "instead of the configured lookback (default: the lookback, unchanged)")


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
