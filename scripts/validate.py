#!/usr/bin/env python3
"""Deterministic gates for the daily run (routine/PROMPT.md; settings in config/validate.yaml).

    python scripts/validate.py --market M --stage collect|news|features|context|forecast|report|all

Prints one JSON summary: `ok`, `failures` and `warnings` (each with `code`, `detail` and the
affected `tickers`), plus `info`. Exit 1 when any blocking failure is found, else 0.

Stages (each runs after the routine step of the same name):
- collect:  freshness of watchlist bars against the exchange calendar (the last completed session,
            market_status.py's `previous_session`; on a late run today's bar may still be missing),
            market symbols, and this run's fetches (quotes, news, filings, announcements); collector
            summaries saved in work/steps/ (or today's row counts); empty, truncated or malformed
            files written today; row schemas (common.SCHEMAS); ISO UTC timestamps not in the
            future; duplicate ids; close > 0; big 1-day moves; news only from configured outlets;
            today's news_articles rows (a warning: nothing reads them yet): known access, no stored
            article text (<= 3 sentences of <= 40 words), pages read only from allowlisted https URLs.
- news:     work/enriched.jsonl (news-analyst output) before it is appended.
- features: every watchlist ticker has a feature row for its latest bar and a regime row exists.
- context:  work/context.md exists, is the pack of today and names every watchlist ticker.
- forecast: work/predictions.jsonl before it is appended (prediction_rules.check_prediction,
            evidence published before made_at, no calls on a late or mid-session run).
- report:   files appended since collect (news_enriched, predictions, ranges) as in collect; no
            AGENT markers left; each number in the agent-written lines of the report, the Slack
            draft and today's daily summary matches a source number of the same kind and scope
            (narrative_numbers.py: the companies or symbols its sentence names plus market-level
            rows, and the text of the news ids it cites); every ticker x horizon has a range or
            a skip reason the calendar explains.
- all:      every stage whose input exists."""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

import events as ev
import market_status
from common import (ROOT, SCHEMAS, clock, connect, data_dir, load_ranges_config, market_arg,
                    require_market, symbols_by_role, utc_today)
import narrative_numbers as nn
from marketbrief.core.settings import load_settings, load_validate_config
from prediction_rules import check_prediction, ts

STAGES = ("collect", "news", "features", "context", "forecast", "report")
# kinds whose day files are named by the trading date, with the column that says when a row was written
TRADING_DATE_KINDS = {"prices": "collected_at", "features": "computed_at", "regime": "computed_at",
                      "calibration": "computed_at", "ranges": "made_at", "replays": "computed_at",
                      "adjustments": "detected_at"}
STAGE_KINDS = {"features": ("features", "regime", "calibration")}
FETCH_COL = {"quotes": "collected_at", "news": "first_seen_at", "filings": "first_seen_at",
             "announcements": "first_seen_at"}


def load_config() -> dict:
    return load_validate_config()


class Result:
    def __init__(self):
        self.failures, self.warnings, self.info = [], [], {}

    def add(self, severity: str, code: str, detail: str, tickers=()):
        item = {"code": code, "detail": detail, "tickers": sorted(set(tickers))}
        (self.failures if severity == "block" else self.warnings).append(item)

    def block(self, code, detail, tickers=()):
        self.add("block", code, detail, tickers)

    def warn(self, code, detail, tickers=()):
        self.add("warning", code, detail, tickers)


# ---------- shared ----------

def run_status(cfg: dict) -> dict:
    return market_status.status(cfg, clock())


def work_dir() -> Path:
    return ROOT / "work"


def kind_files(market: str, kind: str) -> list[Path]:
    ext = SCHEMAS[kind][0]
    return sorted((data_dir(market) / kind).glob(f"**/*.{ext}"))


def file_day(p: Path) -> date | None:
    try:
        return date.fromisoformat(p.stem[:10])
    except ValueError:
        return None


def todays_files(market: str, kind: str, today: date) -> list[Path]:
    """Files this run wrote: named today (UTC), or, for kinds named by the trading date, any file of
    the last 10 days holding a row written today."""
    files = kind_files(market, kind)
    if kind not in TRADING_DATE_KINDS:
        return [p for p in files if file_day(p) == today]
    col, out = TRADING_DATE_KINDS[kind], []
    for p in files:
        d = file_day(p)
        # adjustments are filed by ex-date, which can lie further back than 10 days: all files are read
        if d is None or (kind != "adjustments" and d < today - timedelta(days=10)):
            continue
        if p.stat().st_size == 0 or any(r.get(col) and str(r[col])[:10] == str(today) for r in read_rows(p)[0]):
            out.append(p)
    return out


def read_rows(p: Path) -> tuple[list[dict], list[str]]:
    """(rows, problems) of one data file: truncation, bad JSON, empty file."""
    problems, rows = [], []
    raw = p.read_bytes()
    if not raw:
        return [], ["empty file"]
    if not raw.endswith(b"\n"):
        problems.append("last line has no newline (truncated write?)")
    text = raw.decode("utf-8", errors="replace")
    if p.suffix == ".csv":
        reader = csv.DictReader(text.splitlines())
        return list(reader), problems
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"line {i} is not JSON ({e.msg})")
            continue
        if not isinstance(r, dict):
            problems.append(f"line {i} is not a JSON object")
            continue
        rows.append(r)
    return rows, problems


ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]00:?00)$")


def type_problem(v, typ: str, csv_row: bool) -> str | None:
    """Why a value does not fit a DuckDB column type (None = fits; null always fits)."""
    if v is None or (csv_row and v == ""):
        return None
    if typ == "VARCHAR":
        return None if isinstance(v, str) else "not text"
    if typ in ("DOUBLE", "INTEGER", "BIGINT"):
        if csv_row:
            try:
                x = float(v)
            except ValueError:
                return "not a number"
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return "not a number"
            x = float(v)
        if typ != "DOUBLE" and x != int(x):
            return "not an integer"
        return None
    if typ == "BOOLEAN":
        return None if isinstance(v, bool) or (csv_row and v in ("true", "false")) else "not true/false"
    if typ == "DATE":
        try:
            date.fromisoformat(str(v)[:10])
            return None if len(str(v)) == 10 else "not YYYY-MM-DD"
        except ValueError:
            return "not YYYY-MM-DD"
    if typ == "TIMESTAMPTZ":
        return None if isinstance(v, str) and ISO_UTC.match(v) else "not an ISO 8601 UTC timestamp"
    if typ.endswith("[]"):
        return None if isinstance(v, list) and all(x is None or isinstance(x, str) for x in v) else "not a list of text"
    return None  # JSON


def check_rows(kind: str, rows: list[dict], csv_row: bool, now: pd.Timestamp, tol: timedelta) -> list[str]:
    """Schema and timestamp problems of one kind's rows (at most a few per kind)."""
    cols = SCHEMAS[kind][1]
    out = []
    for i, r in enumerate(rows, 1):
        unknown = [k for k in r if k not in cols]
        if unknown:
            out.append(f"row {i}: fields not in the {kind} schema: {unknown}")
        if "id" in cols and not r.get("id"):
            out.append(f"row {i}: missing id")
        for k, typ in cols.items():
            if k not in r:
                continue
            why = type_problem(r[k], typ, csv_row)
            if why:
                out.append(f"row {i}: {k}={str(r[k])[:40]!r} {why}")
            elif typ == "TIMESTAMPTZ" and r[k]:
                t = ts(r[k])
                if t is not None and t > now + tol:
                    out.append(f"row {i}: {k} {r[k]} is in the future (now {now.isoformat()})")
        if len(out) >= 5:
            out.append("...")
            break
    return out


def tickers_in(rows: list[dict]) -> list[str]:
    return [str(r.get("ticker")) for r in rows if r.get("ticker")]


# ---------- collect ----------

def check_files(res: Result, cfg: dict, kinds, today: date, now: pd.Timestamp, vc: dict) -> dict:
    """Empty, truncated or malformed files written today, and their rows against the schemas."""
    counts, tol = {}, timedelta(minutes=vc["future_tolerance_minutes"])
    for kind in kinds:
        files = todays_files(cfg["market"], kind, today)
        n = 0
        for p in files:
            rows, problems = read_rows(p)
            rel = p.relative_to(ROOT).as_posix()
            if problems:
                res.block("BAD_FILE", f"{rel}: {'; '.join(problems[:3])}", tickers_in(rows))
            if kind in TRADING_DATE_KINDS:
                col = TRADING_DATE_KINDS[kind]
                rows = [r for r in rows if r.get(col) and str(r[col])[:10] == str(today)]
            n += len(rows)
            bad = check_rows(kind, rows, p.suffix == ".csv", now, tol)
            if bad:
                res.block("SCHEMA", f"{rel}: {'; '.join(bad)}", tickers_in(rows))
        counts[kind] = n
    return counts


def check_duplicates(res: Result, cfg: dict, con, vc: dict):
    keys = {k: "id" for k in vc["unique_id_kinds"]} | dict(vc.get("unique_keys") or {})
    for kind, key in keys.items():
        if kind not in SCHEMAS:
            continue
        rows = con.execute(f"SELECT {key}, count(*) FROM {kind} GROUP BY 1 HAVING count(*) > 1 ORDER BY 1 LIMIT 20").fetchall()
        if rows:
            res.block("DUPLICATE_ID", f"{kind}: {len(rows)} duplicated {key}(s), e.g. {[r[0] for r in rows[:5]]}")


def check_bars(res: Result, cfg: dict, con, st: dict, vc: dict):
    need = date.fromisoformat(st["previous_session"])
    last = dict(con.execute("SELECT ticker, max(date) FROM bars GROUP BY 1").fetchall())
    missing = [t for t in cfg["tickers"] if t not in last]
    stale = [t for t in cfg["tickers"] if t in last and last[t] < need]
    if missing:
        res.block("MISSING_BARS", "no stored price bars", missing)
    if stale:
        res.block("STALE_BARS", f"newest bar older than the last completed session {need} "
                  f"(e.g. {stale[0]} {last[stale[0]]})", stale)
    if st["late_run"]:
        # the run started after session_date closed: its bar is not required (the routine works as
        # of the previous session), but a missing one is noted
        sess = date.fromisoformat(st["session_date"])
        no_bar = [t for t in cfg["tickers"] if t in last and last[t] < sess]
        if no_bar:
            res.warn("LATE_RUN_NO_SESSION_BAR", f"late run: session {sess} has closed but has no stored bar "
                     "(the run is as of the previous session)", no_bar)
    core = [k for role in ("benchmark", "vol_index") for k in symbols_by_role(cfg, role)]
    never = [k for k in core if k not in last]
    if never:
        res.block("MISSING_SYMBOL", "benchmark / vol index: no bars stored at all (never collected; the regime needs them)",
                  never)
    bad_core = [k for k in core if k in last and last[k] < need]
    if bad_core:
        res.block("STALE_SYMBOL", f"benchmark / vol index bar older than {need} (the regime needs them; newest "
                  + ", ".join(f"{k} {last[k]}" for k in bad_core) + ")", bad_core)
    old = need - timedelta(days=vc["symbol_max_age_days"])
    others = [k for k in cfg["symbols"] if k not in core]
    never = [k for k in others if k not in last]
    if never:
        res.warn("MISSING_SYMBOL", "market symbols with no bars stored at all (never collected: cues, factors, "
                 "sector ETFs)", never)
    stale = [k for k in others if k in last and last[k] < old]
    if stale:
        res.warn("STALE_SYMBOL", f"market symbols with no bar since {old} (cues, factors, sector ETFs; newest "
                 + ", ".join(f"{k} {last[k]}" for k in stale) + ")", stale)
    # close > 0 on recent bars; big 1-day moves
    since = need - timedelta(days=14)
    bad = con.execute("SELECT DISTINCT ticker FROM prices WHERE date >= ? AND (close IS NULL OR close <= 0) ORDER BY 1",
                      [since]).fetchall()
    if bad:
        res.block("BAD_CLOSE", f"close missing or <= 0 on a bar since {since}", [b[0] for b in bad])
    moves = con.execute("SELECT DISTINCT ON (ticker) ticker, date, ret_1d FROM returns ORDER BY ticker, date DESC").fetchall()
    for t, d, r in moves:
        if t not in cfg["tickers"] or r is None or abs(r) <= vc["big_move_1d"]:
            continue
        if not corporate_action_near(con, t, d, vc):
            res.warn("BIG_MOVE", f"{t} 1-day return {r:+.1%} on {d} with no split/corporate-action event on file", [t])


def corporate_action_near(con, ticker: str, d: date, vc: dict) -> bool:
    lo, hi = d - timedelta(days=vc["big_move_event_days"]), d + timedelta(days=vc["big_move_event_days"])
    words = [w.lower() for w in vc["big_move_event_words"]]
    texts = [" ".join(str(x) for x in r) for r in con.execute(
        "SELECT type, name FROM events WHERE ticker = ? AND date BETWEEN ? AND ?", [ticker, lo, hi]).fetchall()]
    texts += [" ".join(str(x) for x in r) for r in con.execute(
        "SELECT category, subject FROM announcements WHERE ticker = ? AND CAST(published_at AS DATE) BETWEEN ? AND ?",
        [ticker, lo, hi]).fetchall()]
    return any(w in t.lower() for t in texts for w in words)


def fetch_kinds(cfg: dict) -> list[str]:
    kinds = ["quotes", "news"]
    if cfg.get("filings") == "sec":
        kinds.append("filings")
    if cfg["market"] == "india":
        kinds.append("announcements")
    return kinds


def check_fetches(res: Result, cfg: dict, con, now: pd.Timestamp, today: date, vc: dict):
    for kind in fetch_kinds(cfg):
        col = FETCH_COL[kind]
        newest = con.execute(f"SELECT max({col}) FROM {kind}").fetchone()[0]
        limit = vc["fetch_max_age_hours"][kind]
        t = ts(newest)
        if t is None:
            res.add(vc["fetch_severity"], "NOT_FETCHED", f"{kind}: no stored rows at all")
        elif t.date() != today or now - t > pd.Timedelta(hours=limit):
            res.add(vc["fetch_severity"], "NOT_FETCHED",
                    f"{kind}: newest {col} {t.isoformat()} is not from this run (today {today}, max age {limit} h)")


def check_summaries(res: Result, cfg: dict, counts: dict, vc: dict) -> dict:
    """Collector summaries saved by the routine (work/steps/<collector>.json); without them, today's
    row counts per kind stand in."""
    seen = {}
    steps = work_dir() / "steps"
    for p in sorted(steps.glob("collect_*.json")) if steps.exists() else []:
        try:
            s = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as e:
            res.warn("COLLECTOR_SUMMARY", f"{p.name} is not a JSON summary ({e})")
            continue
        name = s.get("collector") or p.stem.removeprefix("collect_")
        seen[name] = s
        if s.get("market") not in (None, cfg["market"]):
            continue
        if s.get("error"):
            res.warn("COLLECTOR_ERROR", f"{name}: {str(s['error'])[:200]}")
        failed = s.get("failed")
        if failed:
            what = [f.get("symbol") or f.get("feed") or f.get("ticker") or f.get("series") or str(f)[:60]
                    if isinstance(f, dict) else str(f) for f in (failed if isinstance(failed, list) else [failed])]
            res.warn("COLLECTOR_FAILED", f"{name}: {len(what)} failed: {what[:10]}",
                     [w for w in what if w in cfg["tickers"]])
        if name == "prices" and s.get("warnings"):   # split/bonus checks (issue #31): basis left unconfirmed
            ws = [str(w) for w in s["warnings"]]
            res.warn("PRICE_BASIS", f"prices: {len(ws)} price-basis warning(s): {'; '.join(ws[:5])[:600]}",
                     [w.split(":", 1)[0] for w in ws if w.split(":", 1)[0] in cfg["tickers"]])
        key = (vc.get("expect_output") or {}).get(name)
        explained = s.get("failed") or s.get("warnings") or s.get("error") or s.get("skipped")
        if key and s.get(key) == 0 and not explained:
            res.warn("EMPTY_OUTPUT", f"{name}: {key} is 0 and the summary gives no reason")
    if not seen:
        for kind in (vc.get("expect_output") or {}):
            if counts.get(kind, 0) == 0 and kind in counts:
                res.warn("EMPTY_OUTPUT", f"{kind}: no rows written today (no collector summaries in work/steps/)")
    return {"summaries": sorted(seen), "rows_today": counts}


def registrable(host: str) -> str:
    parts = host.lower().split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "gov", "ac", "edu"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def allowed_news_sources(cfg: dict) -> tuple[set[str], dict[str, set[str]]]:
    """(domains of the Google News base, outlet name -> allowed link domains)."""
    news = cfg.get("news") or {}
    gn = news.get("google_news") or {}
    gdom = {registrable(urlparse(gn["base"]).hostname)} if gn.get("base") else set()
    outlets = {}
    for o in news.get("outlets") or []:
        doms = {registrable(urlparse(o["url"]).hostname)} | {registrable(d) for d in o.get("link_domains") or []}
        outlets[o["name"]] = doms
    return gdom, outlets


def check_news_sources(res: Result, cfg: dict, con, today: date):
    gdom, outlets = allowed_news_sources(cfg)
    rows = con.execute("SELECT id, url, feed, tickers FROM news WHERE CAST(first_seen_at AS DATE) = ?", [today]).fetchall()
    bad = []
    for nid, url, feed, tickers in rows:
        u = urlparse(url or "")
        dom = registrable(u.hostname or "")
        if u.scheme != "https":
            bad.append((nid, f"scheme {u.scheme or 'none'}", tickers))
        elif str(feed).startswith("gnews:"):
            if dom not in gdom:
                bad.append((nid, f"Google News feed but link domain {dom}", tickers))
        elif feed in outlets:
            if dom not in outlets[feed]:
                bad.append((nid, f"outlet {feed} but link domain {dom} (allowed {sorted(outlets[feed])})", tickers))
        else:
            bad.append((nid, f"feed {feed!r} is not a configured outlet", tickers))
    if bad:
        res.block("NEWS_SOURCE", f"{len(bad)} news rows from unconfigured sources or not https, e.g. "
                  + "; ".join(f"{i}: {w}" for i, w, _ in bad[:5]),
                  [t for *_, ts_ in bad for t in (ts_ or []) if t in cfg["tickers"]])


def check_articles(res: Result, cfg: dict, today: date):
    """news_articles written today (collect_articles.py): a known access value, no stored article
    text (extract: at most 3 sentences of at most 40 words), and a page read only from an
    allowlisted https:// URL (config/news_sources.yaml)."""
    import news_verify as nv
    src, bad = nv.load_sources(), []
    for p in todays_files(cfg["market"], "news_articles", today):
        for r in read_rows(p)[0]:
            ext = r.get("extract") or []
            if r.get("access") not in nv.ACCESS:
                bad.append(f"{r.get('id')}: access {r.get('access')!r}")
            elif len(ext) > 3 or any(len(str(s).split()) > 40 for s in ext):
                bad.append(f"{r.get('id')}: extract longer than 3 sentences of 40 words")
            elif r["access"] in ("full", "partial", "paywalled") and r.get("http_status") is not None \
                    and not nv.url_check(r.get("final_url"), src)[0]:
                bad.append(f"{r.get('id')}: read from a URL that is not an allowlisted https page "
                           f"({str(r.get('final_url'))[:60]})")
            elif r["access"] in ("skipped_unlisted", "undecoded") and r.get("http_status") is not None:
                bad.append(f"{r.get('id')}: access {r['access']} but an HTTP status is stored")
    if bad:
        res.warn("ARTICLE_ROWS", f"{len(bad)} news_articles rows break the article rules, e.g. {bad[:3]}")


def stage_collect(res, cfg, con, st, now, today, vc):
    kinds = [k for k in SCHEMAS if k not in STAGE_KINDS["features"] and k not in ("ranges", "predictions",
                                                                                  "news_enriched", "judgments")]
    counts = check_files(res, cfg, kinds, today, now, vc)
    check_duplicates(res, cfg, con, vc)
    check_bars(res, cfg, con, st, vc)
    check_fetches(res, cfg, con, now, today, vc)
    res.info["collect"] = check_summaries(res, cfg, {k: v for k, v in counts.items() if v or k in ("prices", "quotes", "news")}, vc)
    check_news_sources(res, cfg, con, today)
    check_articles(res, cfg, today)


# ---------- news (work/enriched.jsonl) ----------

ENRICH_ENUMS = {"materiality": {"low", "medium", "high"}, "urgency": {"low", "medium", "high"},
                "event_type": {"earnings", "macro", "product", "legal", "sector", "analyst", "ma", "flows", "other"}}


def stage_news(res, cfg, con, st, now, today, vc, path: Path | None = None):
    path = path or work_dir() / "enriched.jsonl"
    if not path.exists():
        res.info["news"] = "no work/enriched.jsonl"
        return
    rows, problems = read_rows(path) if path.stat().st_size else ([], [])
    if problems:
        res.block("BAD_FILE", f"{path.name}: {'; '.join(problems[:3])}")
    bad = check_rows("news_enriched", rows, False, now, timedelta(minutes=vc["future_tolerance_minutes"]))
    if bad:
        res.block("SCHEMA", f"{path.name}: {'; '.join(bad)}")
    new_ids = {r[0] for r in con.execute("SELECT id FROM news WHERE CAST(first_seen_at AS DATE) = ?", [today]).fetchall()}
    new_ids |= {r[0] for r in con.execute("SELECT id FROM announcements WHERE CAST(first_seen_at AS DATE) = ?",
                                          [today]).fetchall()}
    done = {r[0] for r in con.execute("SELECT DISTINCT id FROM news_enriched").fetchall()}
    ids = [r.get("id") for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        res.block("DUPLICATE_ID", f"{path.name}: repeated ids {dup[:5]}")
    extra = sorted({i for i in ids if i not in new_ids})
    if extra:
        res.block("ENRICH_UNKNOWN_ID", f"{len(extra)} ids are not news/announcements first seen today, e.g. {extra[:5]}")
    again = sorted({i for i in ids if i in done})
    if again:
        res.block("ENRICH_ALREADY_STORED", f"{len(again)} ids already in news_enriched, e.g. {again[:5]}")
    missing = sorted(new_ids - done - set(ids))
    if missing:
        res.warn("ENRICH_MISSING", f"{len(missing)} of today's news/announcement ids have no enrichment, e.g. {missing[:5]}")
    for r in rows:
        why = []
        for k, lo, hi in (("relevance", 0, 1), ("sentiment", -1, 1), ("novelty", 0, 1)):
            v = r.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                why.append(f"{k} {v!r} not in {lo}..{hi}")
        why += [f"{k} {r.get(k)!r} not one of {sorted(ok)}" for k, ok in ENRICH_ENUMS.items() if r.get(k) not in ok]
        if not isinstance(r.get("summary"), str) or len(r["summary"].split()) > 25:
            why.append("summary missing or over 25 words")
        if not r.get("prompt_version"):
            why.append("prompt_version missing")
        if not r.get("analyzed_at"):
            why.append("analyzed_at missing")
        if why:
            res.block("ENRICH_RULE", f"{r.get('id')}: {'; '.join(why)}")
    res.info["news"] = {"records": len(rows), "new_ids_today": len(new_ids)}


# ---------- features ----------

def stage_features(res, cfg, con, st, now, today, vc):
    check_files(res, cfg, STAGE_KINDS["features"], today, now, vc)
    last = dict(con.execute("SELECT ticker, max(date) FROM bars GROUP BY 1").fetchall())
    feats = {r[0]: (r[1], r[2]) for r in con.execute("SELECT DISTINCT ON (ticker) ticker, as_of_date, quality FROM features_latest "
                                                     "ORDER BY ticker, as_of_date DESC").fetchall()}
    missing = [t for t in cfg["tickers"] if t not in feats]
    behind = [t for t in cfg["tickers"] if t in feats and t in last and feats[t][0] < last[t]]
    if missing:
        res.block("MISSING_FEATURES", "no feature row", missing)
    if behind:
        res.block("STALE_FEATURES", "feature row older than the ticker's newest bar (run features.py)", behind)
    blocked = [t for t in cfg["tickers"] if t in feats and feats[t][1] == "BLOCKED"]
    if blocked:
        res.warn("QUALITY_BLOCKED", "indicator quality BLOCKED: no call allowed", blocked)
    need = date.fromisoformat(st["previous_session"])
    reg = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    if reg is None or reg < need:
        res.block("MISSING_REGIME", f"no regime row as of {need} (newest {reg})")


# ---------- context ----------

def stage_context(res, cfg, con, st, now, today, vc, path: Path | None = None):
    path = path or work_dir() / "context.md"
    if not path.exists() or path.stat().st_size == 0:
        res.block("MISSING_CONTEXT", f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path} is missing or empty")
        return
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text else ""
    if not first.startswith("# Context pack") or str(today) not in first:
        res.block("STALE_CONTEXT", f"first line is not today's pack header: {first[:80]!r}")
    if "Traceback (most recent call last)" in text:
        res.block("CONTEXT_ERROR", "the context pack contains a Python traceback")
    absent = [t for t in cfg["tickers"] if not re.search(rf"(?<![\w&]){re.escape(t)}(?![\w&])", text)]
    if absent:
        res.block("CONTEXT_INCOMPLETE", "watchlist tickers not named in the context pack", absent)
    if "## Market regime" not in text:
        res.block("CONTEXT_INCOMPLETE", "no 'Market regime' section")


# ---------- forecast ----------

def evidence_times(con) -> dict:
    """Citable id -> when it became public (UTC): news published_at, SEC acceptance (else the end
    of the filing date), NSE announcement time; first_seen_at when nothing else is stored."""
    out = {}
    for sql in ("SELECT id, coalesce(published_at, first_seen_at) FROM news",
                "SELECT id, coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ), first_seen_at) FROM filings",
                "SELECT id, coalesce(published_at, first_seen_at) FROM announcements"):
        for i, t in con.execute(f"SELECT * FROM ({sql}) ORDER BY 1, 2").fetchall():   # per id the earliest wins
            out.setdefault(i, ts(t))
    return out


def stage_forecast(res, cfg, con, st, now, today, vc, path: Path | None = None):
    path = path or work_dir() / "predictions.jsonl"
    if not path.exists() or path.stat().st_size == 0:
        res.info["forecast"] = "no predictions (abstained or not run)"
        return
    raw = path.read_text(encoding="utf-8")
    if not raw.endswith("\n"):
        res.block("BAD_FILE", f"{path.name}: last line has no newline (truncated write?)")
    lines = [x for x in raw.splitlines() if x.strip()]
    if lines and (st["late_run"] or st["in_session"]):
        why = "late run" if st["late_run"] else "mid-session run"
        res.block("CALLS_NOT_ALLOWED", f"{why}: the forecaster must abstain on every ticker, but "
                  f"{path.name} holds {len(lines)} record(s)")
    feats = con.execute("SELECT DISTINCT ON (ticker) ticker, as_of_date, quality, days_to_earnings FROM features_latest "
                        "ORDER BY ticker, as_of_date DESC").df()
    ctx = {"tickers": set(cfg["tickers"]),
           "features": {r.ticker: {"quality": r.quality,
                                   "days_to_earnings": None if pd.isna(r.days_to_earnings) else int(r.days_to_earnings)}
                        for r in feats.itertuples()},
           "evidence": evidence_times(con)}
    as_of = {r.ticker: pd.Timestamp(r.as_of_date).date() for r in feats.itertuples()}
    seen = {r[0] for r in con.execute("SELECT id FROM predictions").fetchall()}
    tol = pd.Timedelta(minutes=vc["future_tolerance_minutes"])
    good = 0
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            res.block("FORECAST_RULE", f"line {i}: not JSON ({e.msg})")
            continue
        errs = check_prediction(rec, ctx, seen, as_of=as_of, require_made_at=True)
        made = ts(rec.get("made_at")) if isinstance(rec, dict) else None
        if made is not None:
            if made > now + tol:
                errs.append(f"made_at {rec['made_at']} is in the future")
            if not ISO_UTC.match(str(rec["made_at"])):
                errs.append("made_at is not ISO 8601 UTC")
        tk = [rec.get("ticker")] if isinstance(rec, dict) and rec.get("ticker") else []
        if errs:
            res.block("FORECAST_RULE", f"line {i} ({rec.get('id') if isinstance(rec, dict) else '?'}): " + "; ".join(errs), tk)
        else:
            good += 1
        if isinstance(rec, dict) and rec.get("id"):
            seen.add(rec["id"])
    res.info["forecast"] = {"records": len(lines), "valid": good}


# ---------- report: numbers in narrative (matching in narrative_numbers.py) ----------

def records(con, sql: str, params=(), notes: list | None = None) -> list[dict]:
    """Rows of a source query; a failure (e.g. a view a market does not have) is noted, not raised."""
    try:
        return con.execute(sql, list(params)).df().to_dict("records")
    except Exception as e:  # noqa: BLE001 - noted in info.number_sources
        if notes is not None:
            notes.append(f"source query skipped ({type(e).__name__}: {str(e).splitlines()[0][:120]}): {sql[:80]}")
        return []


def build_pool(cfg: dict, con, vc: dict, today: date, texts: list[str]) -> nn.Pool:
    """The numbers the narrative may quote, by kind and scope (see narrative_numbers.py): the
    script-written texts (context pack, skeletons) line by line, stored rows per ticker or symbol
    (newest features, the newest ranges, quotes of the last 3 days, returns of the last 10 days),
    market-level rows (regime, row counts), collector summaries, and the text of recent news,
    filings and announcements under their own ids."""
    pool = nn.Pool(nn.Entities(cfg))
    notes = pool.notes
    for t in texts:
        pool.add_text(t, pct_sections=True)
    pool.add_rows(records(con, "SELECT DISTINCT ON (ticker) * EXCLUDE (warnings) FROM features_latest "
                               "ORDER BY ticker, as_of_date DESC", notes=notes), "ticker")
    pool.add_rows(records(con, "SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1", notes=notes), None)
    pool.add_rows(records(con, "SELECT * FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)",
                          notes=notes),
                  "ticker")
    pool.add_rows(records(con, "SELECT symbol, price, prev_close, change_pct FROM quotes WHERE collected_at >= ?",
                          [today - timedelta(days=3)], notes), "symbol")
    pool.add_rows(records(con, "SELECT ticker, close, ret_1d, ret_5d, ret_20d FROM returns WHERE date >= ?",
                          [today - timedelta(days=10)], notes), "ticker")
    # row counts the narrative may quote ("902 headlines"): per kind today and in total
    for kind, col in (*FETCH_COL.items(), ("news_enriched", "analyzed_at"), ("predictions", "made_at"),
                      ("ranges", "made_at"), ("events", "first_seen_at")):
        for v in (records(con, f"SELECT count(*) FILTER (WHERE CAST({col} AS DATE) = ?) AS a, count(*) AS b FROM {kind}",
                          [today], notes) or [{}])[0].values():
            pool.add(None, "plain", v)
        # rows per fetch batch today ("72 new items"): one batch per first_seen/collected minute
        if kind in FETCH_COL:
            for r in records(con, f"SELECT count(*) AS n FROM {kind} WHERE CAST({col} AS DATE) = ? "
                                  f"GROUP BY date_trunc('minute', {col})", [today], notes):
                pool.add(None, "plain", r["n"])
    # configured counts: watchlist size, market symbols, news feeds ("31 feeds")
    pool.add(None, "plain", len(cfg["tickers"]))
    pool.add(None, "plain", len(cfg["symbols"]))
    try:
        import collect_news
        pool.add(None, "plain", len(collect_news.build_jobs(cfg.get("news") or {}, cfg)))
    except Exception as e:  # noqa: BLE001 - only a source of numbers: noted, the check goes on
        notes.append(f"news feed count unavailable ({type(e).__name__}: {e})")
    steps = work_dir() / "steps"
    nn.collector_summaries(pool, sorted(steps.glob("collect_*.json")) if steps.exists() else [])
    since = today - timedelta(days=vc["narrative_news_days"])
    for sql in ("SELECT id, title FROM news WHERE first_seen_at >= ?",
                "SELECT id, summary FROM news_enriched WHERE analyzed_at >= ?",
                "SELECT id, description FROM filings WHERE first_seen_at >= ?",
                "SELECT id, subject FROM announcements WHERE first_seen_at >= ?"):
        for i, text in con.execute(sql, [since]).fetchall():
            if text:
                pool.add_text(str(text), scope_by_line=False, scope=("id", i))
    return pool


def skeletons(cfg: dict, session: str) -> tuple[str | None, str | None]:
    """The script-written report and Slack draft (work/ copies report.py saves; else rebuilt)."""
    rp = work_dir() / f"report_{cfg['market']}_{session}.skeleton.md"
    sp = work_dir() / f"slack_{cfg['market']}.skeleton.md"
    if rp.exists() and sp.exists():
        return rp.read_text(encoding="utf-8"), sp.read_text(encoding="utf-8")
    import report as rpt
    settings = load_settings()
    d = rpt.gather(cfg, connect(cfg["market"]))
    r, s, _ = rpt.build(cfg, d, settings)
    return r, s


def agent_lines(filled: str, skeleton: str) -> list[str]:
    script = {x.strip() for x in skeleton.splitlines()}
    return [x for x in filled.splitlines() if x.strip() and x.strip() not in script]


def check_ranges(res: Result, cfg: dict, con, now: pd.Timestamp):
    import ranges as rg
    rc = load_ranges_config(cfg["market"])
    as_of = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    if as_of is None:
        return
    have = {(r[0], int(r[1])) for r in con.execute("SELECT ticker, horizon_days FROM ranges WHERE as_of_date = ?",
                                                    [as_of]).fetchall()}
    feats = {r[0] for r in con.execute("SELECT ticker FROM features_latest WHERE as_of_date = ?", [as_of]).fetchall()}
    first = rg.target_date(cfg, as_of, 1)
    skipped, missing = {}, []
    for h in rc["horizons"]:
        tgt = rg.target_date(cfg, as_of, h)
        for t in cfg["tickers"]:
            if (t, h) in have:
                continue
            if now >= ev.session_close_utc(cfg, tgt):
                skipped.setdefault(f"{h}d: target {tgt} closed (late run)", []).append(t)
            elif tgt == first and now >= ev.session_open_utc(cfg, first):
                skipped.setdefault(f"{h}d: target {tgt} opened (mid-session run)", []).append(t)
            elif t not in feats:
                skipped.setdefault(f"{h}d: no feature row as of {as_of}", []).append(t)
            else:
                missing.append(f"{t} {h}d")
    if missing:
        res.block("MISSING_RANGE", f"no range as of {as_of} and no skip reason: {missing[:10]}",
                  [m.split()[0] for m in missing])
    res.info["ranges_skipped"] = {k: len(v) for k, v in skipped.items()}


def report_session(con, st: dict) -> str:
    """The session report.py names the report after (the latest ranges' session_date)."""
    row = con.execute("SELECT session_date FROM ranges_latest ORDER BY as_of_date DESC, made_at DESC LIMIT 1").fetchone()
    return str(row[0])[:10] if row and row[0] else st["session_date"]


def report_file(cfg: dict, con, st: dict) -> Path:
    return ROOT / "reports" / cfg["market"] / f"{report_session(con, st)}.md"


def stage_report(res, cfg, con, st, now, today, vc, report_path: Path | None = None, slack_path: Path | None = None):
    session = report_session(con, st)
    report_path = report_path or report_file(cfg, con, st)
    slack_path = slack_path or work_dir() / f"slack_{cfg['market']}.md"
    check_files(res, cfg, ("news_enriched", "predictions", "ranges"), today, now, vc)   # appended since collect
    check_ranges(res, cfg, con, now)
    if not report_path.exists():
        res.block("MISSING_REPORT", f"{report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path} not written")
        return
    filled = report_path.read_text(encoding="utf-8")
    slack = slack_path.read_text(encoding="utf-8") if slack_path.exists() else None
    if "<!-- AGENT:" in filled:
        res.block("AGENT_MARKERS", f"{report_path.name} still has {filled.count('<!-- AGENT:')} AGENT marker(s)")
    if "<!-- report-data:" not in filled:
        res.block("REPORT_DATA_LINE", f"{report_path.name} lost its report-data line")
    if slack is None:
        res.block("MISSING_SLACK_DRAFT", f"{slack_path.name} not written")
    elif "<!-- AGENT:" in slack:
        res.block("AGENT_MARKERS", f"{slack_path.name} still has AGENT marker(s)")
    skel_r, skel_s = skeletons(cfg, session)
    pack = work_dir() / "context.md"
    pool = build_pool(cfg, con, vc, today, [skel_r or "", skel_s or "",
                                            pack.read_text(encoding="utf-8") if pack.exists() else ""])
    if pool.notes:
        res.info["number_sources"] = pool.notes
    small = vc["narrative_small_int"]
    targets = [(report_path, agent_lines(filled, skel_r or ""))]
    if slack is not None:
        targets.append((slack_path, agent_lines(slack, skel_s or "")))
    summary = ROOT / "summaries" / cfg["market"] / "daily" / f"{today}.md"
    if summary.exists():
        targets.append((summary, summary.read_text(encoding="utf-8").splitlines()))
    checked = {}
    for path, lines in targets:
        bad = nn.unmatched(lines, pool, small)
        checked[path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)] = {
            "agent_lines": len(lines), "unmatched": len(bad)}
        if bad:
            res.block("UNMATCHED_NUMBER", f"{path.name}: {len(bad)} number(s) with no same-kind source number for "
                      "the companies or symbols named (context pack, script-written report, cited news text, "
                      "stored rows): " + "; ".join(f"{n['token']!r} in \"{n['sentence'][:90]}\"" for n in bad[:12]),
                      [t for n in bad for t in n["entities"] if t in cfg["tickers"]])
    if not pack.exists():
        res.warn("NO_CONTEXT_PACK", "work/context.md missing: narrative numbers checked against the skeleton and DuckDB only")
    res.info["report"] = checked


# ---------- main ----------

def run(cfg: dict, stage: str, paths: dict | None = None) -> dict:
    paths = paths or {}
    vc = load_config()
    con = connect(cfg["market"])
    now, today = pd.Timestamp(clock()), utc_today()
    st = run_status(cfg)
    res = Result()
    res.info["run"] = {k: st[k] for k in ("session_date", "previous_session", "late_run", "in_session", "trading_day")}
    stages = STAGES if stage == "all" else (stage,)
    for s in stages:
        if s == "collect":
            stage_collect(res, cfg, con, st, now, today, vc)
        elif s == "news":
            stage_news(res, cfg, con, st, now, today, vc, paths.get("enriched"))
        elif s == "features":
            stage_features(res, cfg, con, st, now, today, vc)
        elif s == "context":
            stage_context(res, cfg, con, st, now, today, vc, paths.get("context"))
        elif s == "forecast":
            stage_forecast(res, cfg, con, st, now, today, vc, paths.get("predictions"))
        elif s == "report":
            rp = paths.get("report") or report_file(cfg, con, st)
            if stage == "all" and not rp.exists():
                res.info["report"] = f"skipped: {rp.name} not written yet"
                continue
            stage_report(res, cfg, con, st, now, today, vc, rp, paths.get("slack"))
    return {"step": "validate", "market": cfg["market"], "stage": stage, "checked_at": now.isoformat(),
            "ok": not res.failures, "failures": res.failures, "warnings": res.warnings, "info": res.info}


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--stage", required=True, choices=[*STAGES, "all"])
    for name in ("predictions", "enriched", "context", "report", "slack"):
        ap.add_argument(f"--{name}", type=Path, help=f"path of the {name} file (default: the routine's)")
    args = ap.parse_args()
    cfg = require_market(args)
    out = run(cfg, args.stage, {k: getattr(args, k) for k in ("predictions", "enriched", "context", "report", "slack")
                                if getattr(args, k)})
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
