"""Collect stage: files, duplicates, price bars, fetch results and the collectors' summaries."""
from __future__ import annotations

import json
from datetime import date, timedelta
import pandas as pd
from marketbrief.utils.timefmt import as_utc_timestamp
from marketbrief.core import market_config, paths, schemas
from marketbrief.constants.validation import FETCH_COL, TRADING_DATE_KINDS
from marketbrief.pipeline.validate.gate_result import Result, work_dir
from marketbrief.pipeline.validate.row_checks import check_rows, read_rows, tickers_in, todays_files


def check_files(res: Result, cfg: dict, kinds, today: date, now: pd.Timestamp, vc: dict) -> dict:
    """Empty, truncated or malformed files written today, and their rows against the schemas."""
    counts, tol = {}, timedelta(minutes=vc["future_tolerance_minutes"])
    for kind in kinds:
        files = todays_files(cfg["market"], kind, today)
        n = 0
        for p in files:
            rows, problems = read_rows(p)
            rel = p.relative_to(paths.ROOT).as_posix()
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
        if kind not in schemas.SCHEMAS:
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
    core = [k for role in ("benchmark", "vol_index") for k in market_config.symbols_by_role(cfg, role)]
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
        t = as_utc_timestamp(newest)
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
