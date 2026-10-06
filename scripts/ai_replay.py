#!/usr/bin/env python3
"""As-of replay harness for the AI agents (deterministic; it never runs an LLM itself).

The model's training data runs to about mid-2026. ForecastBench's leakage rule (Karger et al.,
arXiv 2409.19839): only as-of dates AFTER the model's training cutoff (`model_training_cutoff` in
config/settings.yaml, 2026-06-30) are a fair test of the forecaster; earlier dates are labelled
"contaminated" (the model may have seen what happened), `prepare` refuses them unless
--allow-training-period, and `record`/`score` label every row and score the two groups separately,
never pooled. For a past as-of date D (a trading day: its close
is known) this script rebuilds what the routine would have known pre-open on the next session S,
lets the orchestrator run the agents on it, then records and scores their calls:

  dates   --market M                 the sample: every 5th trading day 2026-07-01..2026-09-25
  backfill --market M --source S --since 2026-06-01
          S = a scratch source root (refused: the repo, its data/ or anything inside/above them): a copy
          of data/<M>/ plus config/ whose lookbacks are lengthened in S only; the existing collectors
          then run into S one after another (US: SEC filings, Form 4, 13D/13G, events; India: NSE
          announcements and results filings, SEBI PIT insider trades, bulk/block deals with their
          `--since` option, events). Rows keep their real publication/acceptance times.
  prepare --market M --date D --root R [--source S] [--assume-earnings-known DAYS]
          R = a scratch root: copies of config/, sql/, templates/ and data/<M>/ truncated to what
          was public at the cutoff (the routine's start time on S, before the open; CUTOFF_LOCAL).
          Then features.py, calibrate.py, context.py (R/work/context.md) and ranges.py run with
          MB_ROOT=R and MB_NOW=cutoff (scripts/common.py clock(): every "now"/"today" and DuckDB's
          current_date is the cutoff). Prints and saves (R/ai_replay.json) what was kept or dropped.
  record  --market M --date D --root R --calls F --results DIR
          validates forecaster-format records (schema `predictions` in common.py and the CLAUDE.md
          prediction rules, checked against R) and appends the valid ones to
          DIR/<M>/calls.jsonl tagged replay=true (never to data/<M>/predictions/).
  score   --market M --results DIR --out PAGE.html
          scores the recorded calls on the REAL stored closes (direction hit at 1 or 5 trading
          days, as score_predictions.py), against always-up and replay.py's rule baselines on the
          same ticker-days; writes a novice-first HTML page and PAGE.json.

Inclusion rules of `prepare` (per data kind; a row is kept only if public by the cutoff):
- prices: bars dated <= D (every symbol, also foreign cues);
- filings, fundamentals: SEC acceptance time, else the end of the filing date (UTC), as the
  fundamentals_*_asof macros in sql/views.sql; stakes, insiders, holdings: acceptance/disclosure/
  filing time, else first_seen_at; announcements: published_at; financials: filed_at;
- events: first_seen_at <= cutoff, plus backfilled past events (source *_history) dated <= D;
- predictions, ranges: made_at; outcomes, range_outcomes: scored_at and target_date <= D;
  lessons: available_from and target_date <= D;
  features, regime, calibration, reviews, replays: computed_at; judgments: recorded_at;
  quotes, options: collected_at; graph: added_at; graph_runs: run_at;
- deals: trade date <= D (assumed: NSE publishes the day's bulk and block deals after the close);
- kinds with only an observation date and no publication time (macro, shorts, short_interest,
  fpi, indices, flows, delivery): kept only if first_seen_at <= cutoff, i.e. backfilled rows are
  dropped;
- --assume-earnings-known DAYS (off by default) adds the actual earnings dates within DAYS after D
  as events first seen at the cutoff, labelled ASSUMED (stored rows do not say when a date was
  announced);
- news and news_enriched: dropped (stored news only starts when live collection began); any other
  kind: dropped and listed. summaries/ and reports/ are never copied."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

import common
import events as ev
import replay
from common import ACCEPTED_KEYS, CODE, SCHEMAS, connect, load_market, market_names, utc_now
from features import load_bars
from prediction_rules import HORIZONS, check_prediction

FAIR, CONTAMINATED = "fair", "contaminated"   # ForecastBench leakage rule (see the docstring)
SAMPLE_START, SAMPLE_END, SAMPLE_STEP = date(2026, 7, 1), date(2026, 9, 25), 5
# The data cutoff (and made_at) is the routine's scheduled start on the next session, exchange time
# (docs/DESIGN.md section 2); other markets: REGULAR_LEAD before the open.
CUTOFF_LOCAL = {"india": time(8, 10), "us": time(8, 15)}
REGULAR_LEAD = timedelta(minutes=75)
MARKER = ".ai_replay_root"
EVIDENCE_KINDS = ("news", "filings", "announcements")   # ids a call may cite (CLAUDE.md: news/filing ids)
EVIDENCE_DAYS = 14
BANDS = (("0.50-0.59", 0.50, 0.60), ("0.60-0.69", 0.60, 0.70), ("0.70-0.90", 0.70, 0.9001))

# kind -> columns tried in order for when a row became public (first non-null wins).
# "x+1d" = the end of date column x in UTC (when no acceptance time is stored).
PUBLIC_AT: dict[str, list[str]] = {
    "filings": ["accepted_at", "filing_date+1d"],
    "fundamentals": ["accepted_at", "filing_date+1d"],
    "stakes": ["accepted_at", "filing_date+1d", "first_seen_at"],
    "insiders": ["accepted_at", "disclosed_at", "filing_date+1d", "first_seen_at"],
    "holdings": ["accepted_at", "filed_at", "filing_date+1d", "first_seen_at"],
    "announcements": ["published_at", "first_seen_at"],
    "financials": ["filed_at", "first_seen_at"],
    "predictions": ["made_at"], "ranges": ["made_at"],
    "outcomes": ["scored_at"], "range_outcomes": ["scored_at"], "lessons": ["available_from"],
    "features": ["computed_at"], "regime": ["computed_at"], "calibration": ["computed_at"],
    "reviews": ["computed_at"], "replays": ["computed_at"], "judgments": ["recorded_at"],
    "quotes": ["collected_at"], "options": ["collected_at"],
    "graph": ["added_at"], "graph_runs": ["run_at"],
    # SEC acceptance times from the filing's SGML header (check_sec_times.py): a permanent fact
    # about the filing, public from its acceptance; checked_at is only when we looked it up
    "sec_times": ["accepted_at"],
}
FIRST_SEEN_ONLY = ("macro", "shorts", "short_interest", "fpi", "indices", "flows", "delivery")
# Bulk and block deals have only a trade date; NSE publishes each session's deals after its close,
# so a deal dated <= D was public before the next pre-open (an assumption, listed in the summary).
DATE_PUBLIC_AFTER_CLOSE = ("deals",)
for _k in FIRST_SEEN_ONLY:
    PUBLIC_AT[_k] = ["first_seen_at"]
TARGET_DATE_KINDS = ("outcomes", "range_outcomes", "lessons")     # also need target_date <= D
DROPPED = {"news": "stored news only starts when live collection began ({first}); no history before",
           "news_enriched": "AI enrichment of news (no news history before {first})"}


# ---------- dates and cutoff ----------

def training_cutoff() -> date:
    """`model_training_cutoff` from config/settings.yaml: the model may have seen data up to this date."""
    v = (yaml.safe_load((common.CONFIG / "settings.yaml").read_text()) or {}).get("model_training_cutoff")
    if v is None:
        raise SystemExit(f"{common.CONFIG / 'settings.yaml'} has no model_training_cutoff (YYYY-MM-DD)")
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def leakage_label(d, cutoff: date | None = None) -> str:
    """"fair" for an as-of date after the training cutoff, else "contaminated" (never pooled)."""
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return FAIR if d > (cutoff or training_cutoff()) else CONTAMINATED


def next_session(cfg: dict, d: date) -> date:
    return ev.next_session(cfg, d, include=False)


def cutoff_for(cfg: dict, d: date) -> datetime:
    """Pre-open time of the session after d (UTC): the routine's start on that session."""
    s = next_session(cfg, d)
    opens = ev.session_open_utc(cfg, s)
    local = CUTOFF_LOCAL.get(cfg["market"])
    at = (datetime.combine(s, local, ZoneInfo(cfg["timezone"])).astimezone(timezone.utc) if local
          else opens - REGULAR_LEAD)
    return min(at, opens - timedelta(minutes=1)).replace(microsecond=0)


def sample_dates(cfg: dict, start: date = SAMPLE_START, end: date = SAMPLE_END, step: int = SAMPLE_STEP) -> list[date]:
    """Every `step`-th exchange trading day from start to end (inclusive), starting with the first."""
    days, d = [], start
    while d <= end:
        if ev.is_session(cfg, d):
            days.append(d)
        d += timedelta(days=1)
    return days[::step]


# ---------- prepare: the as-of copy ----------

def _ts(v) -> pd.Timestamp | None:
    if v is None or v == "":
        return None
    try:
        t = pd.Timestamp(v)
    except (ValueError, TypeError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def public_at(kind: str, row: dict) -> pd.Timestamp | None:
    for col in PUBLIC_AT.get(kind, []):
        if col.endswith("+1d"):
            t = _ts(row.get(col[:-3]))
            if t is not None:
                return t.normalize() + pd.Timedelta(days=1)
        else:
            t = _ts(row.get(col))
            if t is not None:
                return t
    return None


def load_sec_times(base: Path) -> dict[str, str]:
    """Accession -> SGML-header acceptance time (newest check wins) from data/<market>/sec_times/,
    the correction common.connect applies to accepted_at (see scripts/sec.py)."""
    best: dict[str, tuple[str, str]] = {}
    for f in sorted((base / "sec_times").glob("**/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            acc, at, checked = r.get("accession"), r.get("accepted_at"), str(r.get("checked_at") or "")
            if acc and at and (acc not in best or checked >= best[acc][1]):
                best[acc] = (at, checked)
    return {a: at for a, (at, _) in best.items()}


def keep_row(kind: str, row: dict, d: date, cutoff: pd.Timestamp, times: dict[str, str] | None = None) -> bool:
    """True when the row was public by the cutoff (pre-open of the session after d). `times`
    (load_sec_times) replaces a SEC row's stored accepted_at with its header time, as the
    corrected views do: a value stored from a shifted submissions file is 4-5h late."""
    if times and kind in ACCEPTED_KEYS and row.get(ACCEPTED_KEYS[kind]) in times:
        row = {**row, "accepted_at": times[row[ACCEPTED_KEYS[kind]]]}
    if kind == "prices":
        t = _ts(row.get("date"))
        return t is not None and t.date() <= d
    if kind in DATE_PUBLIC_AFTER_CLOSE:
        t = _ts(row.get("date"))
        return t is not None and t.date() <= d
    if kind == "events":
        seen = _ts(row.get("first_seen_at"))
        if seen is not None and seen <= cutoff:
            return True
        day = _ts(row.get("date"))
        return str(row.get("source") or "").endswith("_history") and day is not None and day.date() <= d
    t = public_at(kind, row)
    if t is None or t > cutoff:
        return False
    if kind in TARGET_DATE_KINDS:
        td = _ts(row.get("target_date"))
        return td is not None and td.date() <= d
    return True


def rule_text(kind: str) -> str:
    if kind == "prices":
        return "bar date <= D"
    if kind in DATE_PUBLIC_AFTER_CLOSE:
        return "trade date <= D (assumed: NSE publishes the day's deals after the close)"
    if kind == "events":
        return "first_seen_at <= cutoff, or a backfilled past event (*_history) dated <= D"
    cols = " else ".join(c.replace("+1d", " (end of day UTC)") for c in PUBLIC_AT[kind])
    extra = " and target_date <= D" if kind in TARGET_DATE_KINDS else ""
    if kind in ACCEPTED_KEYS:
        cols = cols.replace("accepted_at", "accepted_at (SGML header time from sec_times when checked)", 1)
    return f"{cols} <= cutoff{extra}"


def _filter_jsonl(text: str, kind: str, d: date, cutoff: pd.Timestamp,
                  times: dict[str, str] | None = None) -> tuple[list[str], int]:
    kept, n = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        n += 1
        if keep_row(kind, json.loads(line), d, cutoff, times):
            kept.append(line)
    return kept, n


def _filter_csv(text: str, kind: str, d: date, cutoff: pd.Timestamp,
                times: dict[str, str] | None = None) -> tuple[list[str], int]:
    lines = text.splitlines()
    if not lines:
        return [], 0
    header = next(csv.reader([lines[0]]))
    kept, n = [], 0
    for line in lines[1:]:
        if not line.strip():
            continue
        n += 1
        if keep_row(kind, dict(zip(header, next(csv.reader([line])))), d, cutoff, times):
            kept.append(line)
    return ([lines[0]] + kept if kept else []), n


def earliest_news(src_market: Path) -> str | None:
    files = sorted((src_market / "news").glob("**/*.jsonl"))
    return files[0].stem if files else None


def copy_asof(market: str, src: Path, dst: Path, d: date, cutoff: datetime) -> dict:
    """Copy src/data/<market>/ into dst/data/<market>/, keeping only rows public by the cutoff."""
    cut = pd.Timestamp(cutoff)
    base, out_base = src / "data" / market, dst / "data" / market
    kinds, excluded = {}, {}
    first_news = earliest_news(base) or "none stored"
    times = load_sec_times(base)       # SEC accepted_at corrected to the header time (sec_times)
    for kdir in sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []:
        kind = kdir.name
        if kind in DROPPED:
            excluded[kind] = DROPPED[kind].format(first=first_news)
            continue
        if kind not in ("prices", "events", *DATE_PUBLIC_AFTER_CLOSE) and kind not in PUBLIC_AT:
            excluded[kind] = "no known publication-time rule for this kind"
            continue
        ext = SCHEMAS[kind][0] if kind in SCHEMAS else "jsonl"
        stat = {"rule": rule_text(kind), "files_in": 0, "files_out": 0, "rows_in": 0, "rows_kept": 0}
        for f in sorted(kdir.glob(f"**/*.{ext}")):
            text = f.read_text(encoding="utf-8")
            kept, n = (_filter_csv if ext == "csv" else _filter_jsonl)(text, kind, d, cut, times)
            stat["files_in"] += 1
            stat["rows_in"] += n
            rows = len(kept) - (1 if ext == "csv" and kept else 0)
            stat["rows_kept"] += rows
            if rows:
                out = out_base / f.relative_to(base)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(kept) + "\n", encoding="utf-8")
                stat["files_out"] += 1
        stat["rows_dropped"] = stat["rows_in"] - stat["rows_kept"]
        kinds[kind] = stat
    for kind in DROPPED:
        excluded.setdefault(kind, DROPPED[kind].format(first=first_news))
    return {"kinds": kinds, "excluded": excluded, "first_news_file": first_news}


@contextmanager
def data_root(root: Path):
    """Point common.connect() at another root inside this process."""
    old = common.ROOT
    common.ROOT = Path(root)
    try:
        yield
    finally:
        common.ROOT = old


def evidence(market: str, root: Path, cutoff: datetime, days: int = EVIDENCE_DAYS) -> tuple[pd.DataFrame, dict]:
    """Citable ids in root (news, SEC filings, NSE announcements), with when each became public."""
    with data_root(root):
        con = connect(market)
        frames = []
        for kind, sql in (
            ("news", "SELECT id, array_to_string(tickers, ',') AS ticker, 'news' AS form, "
                     "coalesce(published_at, first_seen_at) AS public_at, title AS text FROM news"),
            ("filings", "SELECT id, ticker, form, coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) AS public_at, "
                        "description AS text FROM filings"),
            ("announcements", "SELECT id, ticker, category AS form, coalesce(published_at, first_seen_at) AS public_at, "
                              "subject AS text FROM announcements"),
        ):
            df = con.execute(sql).df()
            df["kind"] = kind
            frames.append(df)
    ev_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    ev_df = ev_df.drop_duplicates("id")
    since = pd.Timestamp(cutoff) - pd.Timedelta(days=days)
    pub = pd.to_datetime(ev_df["public_at"], utc=True)
    recent = ev_df[pub >= since]
    counts = {"total": int(len(ev_df)), f"last_{days}d": int(len(recent)),
              "by_kind_total": {k: int((ev_df["kind"] == k).sum()) for k in EVIDENCE_KINDS},
              f"by_kind_last_{days}d": {k: int((recent["kind"] == k).sum()) for k in EVIDENCE_KINDS},
              "tickers_with_recent_ids": int(recent["ticker"].replace("", np.nan).dropna().nunique()),
              f"by_form_last_{days}d": {str(k): int(v) for k, v in recent["form"].fillna("").value_counts().items()}}
    return ev_df, counts


def evidence_section(ev_df: pd.DataFrame, cutoff: datetime, days: int = EVIDENCE_DAYS, limit: int = 200) -> str:
    since = pd.Timestamp(cutoff) - pd.Timedelta(days=days)
    df = ev_df.assign(public_at=pd.to_datetime(ev_df["public_at"], utc=True))
    df = df[df["public_at"] >= since].sort_values(["public_at", "id"], ascending=[False, True])
    head = (f"## Citable evidence ids (as-of replay; public in the {days} days before {cutoff.isoformat()})\n\n"
            "Only these kinds of ids may go in `evidence_ids` (news, SEC filings, NSE announcements). There is no "
            "stored news before live collection began, so in a replay only filings or announcements can be cited.\n\n")
    if df.empty:
        return head + "_none: no citable ids in this window, so every call must be an abstention_\n"
    lines = ["| id | kind | ticker | form | public_utc | text |", "|---|---|---|---|---|---|"]
    for r in df.head(limit).itertuples():
        txt = str(r.text or "").replace("|", "/").replace("\n", " ")[:120]
        lines.append(f"| {r.id} | {r.kind} | {r.ticker or ''} | {r.form or ''} | {str(r.public_at)[:16]} | {txt} |")
    more = f"\n{len(df) - limit} more in this window (query DuckDB in the replay root).\n" if len(df) > limit else "\n"
    return head + "\n".join(lines) + "\n" + more


def run_script(script: str, root: Path, market: str, *args: str, now: str | None = None,
               timeout: int | None = None) -> subprocess.CompletedProcess:
    """Run scripts/<script> on another root (MB_ROOT=root, MB_CONFIG=root/config), as of `now` if given."""
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(root / "config"), "MB_MARKET": market}
    env.pop("MB_NOW", None)
    if now:
        env["MB_NOW"] = now
    return subprocess.run([sys.executable, str(CODE / "scripts" / script), "--market", market, *args],
                          cwd=CODE / "scripts", env=env, capture_output=True, text=True, check=False, timeout=timeout)


def run_step(script: str, root: Path, market: str, now: str, *args: str, stdout: Path | None = None) -> str:
    p = run_script(script, root, market, *args, now=now)
    if p.returncode != 0:
        raise SystemExit(f"{script} failed in {root} (exit {p.returncode}):\n{p.stderr[-3000:]}")
    if stdout is not None:
        stdout.parent.mkdir(parents=True, exist_ok=True)
        stdout.write_text(p.stdout, encoding="utf-8")
    return p.stdout


def _json_or_text(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s.strip()[-2000:]


def check_root(root: Path, src: Path, force: bool) -> None:
    root, src = root.resolve(), src.resolve()
    if root == src or src in root.parents and (src / "data") in [root, *root.parents]:
        raise SystemExit(f"--root {root} must not be the source root or inside its data/")
    if root in src.parents or root == src:
        raise SystemExit(f"--root {root} must not contain the source root")
    if root.exists() and any(root.iterdir()):
        if not (root / MARKER).exists():
            raise SystemExit(f"--root {root} exists, is not empty and is not an ai_replay root; choose another path")
        if not force:
            raise SystemExit(f"--root {root} already holds a prepared replay; pass --force to rebuild it")
        shutil.rmtree(root)


def assumed_earnings(cfg: dict, src: Path, d: date, cutoff: datetime, days: int) -> list[dict]:
    """ASSUMPTION (opt-in, --assume-earnings-known DAYS): the actual earnings dates in (D, D + DAYS]
    from the source's backfilled past events (range_inputs.earnings_events over every *_history row,
    i.e. with today's knowledge) are treated as announced before the cutoff, as replay.py treats past
    event dates. Stored rows do not say when a date was first announced (companies usually announce
    2-4 weeks ahead), so this is labelled in the event name, the source and the prepare summary."""
    import range_inputs as ri
    with data_root(src):
        evdf = ri.load_events(connect(cfg["market"]))
    if evdf.empty:
        return []
    out = []
    for t, evs in ri.earnings_events(evdf).items():
        if t not in cfg["tickers"]:
            continue
        for day, timing in evs:
            if d < day <= d + timedelta(days=days):
                name = cfg["tickers"][t].get("name", t)
                out.append({"id": f"{t}-earnings-{day}-assumed", "date": str(day), "type": "earnings", "ticker": t,
                            "name": f"{name} earnings (ASSUMED known in advance: actual date from later data)",
                            "source": "assumed_known", "first_seen_at": cutoff.isoformat(), "timing": timing})
                break
    return out


def prepare(cfg: dict, d: date, root: Path, src: Path | None = None, force: bool = False,
            allow_training_period: bool = False, assume_earnings_days: int = 0) -> dict:
    market = cfg["market"]
    src = Path(src or common.ROOT)
    model_cut = training_cutoff()
    if leakage_label(d, model_cut) == CONTAMINATED and not allow_training_period:
        raise SystemExit(f"{d} is on or before the model's training cutoff {model_cut} (config/settings.yaml "
                         "model_training_cutoff): contaminated, not a fair test. "
                         "Pass --allow-training-period to prepare it anyway.")
    if not ev.is_session(cfg, d):
        raise SystemExit(f"{d} is not a {market} trading day")
    check_root(root, src, force)
    session, cutoff = next_session(cfg, d), cutoff_for(cfg, d)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text(f"{market} {d}\n")
    shutil.copytree(common.CONFIG, root / "config")
    for name in ("sql", "templates"):
        if (CODE / name).exists():
            shutil.copytree(CODE / name, root / name)
    copied = copy_asof(market, src, root, d, cutoff)
    assumed = assumed_earnings(cfg, src, d, cutoff, assume_earnings_days) if assume_earnings_days else []
    if assumed:
        path = root / "data" / market / "events" / f"{cutoff:%Y}" / f"{cutoff:%m}" / f"{cutoff:%Y-%m-%d}.assumed.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        common.append_jsonl(path, assumed)
    bench = common.benchmark_key(cfg)
    with data_root(root):
        last = connect(market).execute("SELECT max(date) FROM ohlc WHERE ticker = ?", [bench]).fetchone()[0]
    if last is None or pd.Timestamp(last).date() != d:
        raise SystemExit(f"no {bench} bar dated {d} in {src} (latest kept: {last})")
    now = cutoff.isoformat()
    steps = {"features": _json_or_text(run_step("features.py", root, market, now)),
             "calibrate": _json_or_text(run_step("calibrate.py", root, market, now))}
    ctx = root / "work" / "context.md"
    run_step("context.py", root, market, now, stdout=ctx)
    steps["ranges"] = _json_or_text(run_step("ranges.py", root, market, now, "--now", now))
    ev_df, counts = evidence(market, root, cutoff)
    with ctx.open("a", encoding="utf-8") as f:
        f.write("\n" + evidence_section(ev_df, cutoff))
    text = ctx.read_text(encoding="utf-8")
    if isinstance(steps["calibrate"], dict):   # keep the summary short
        steps["calibrate"] = {"calibration": [{k: c.get(k) for k in ("horizon_days", "source", "n_history", "n_live")}
                                              for c in steps["calibrate"].get("calibration", [])]}
    out = {
        "step": "ai_replay.prepare", "market": market, "as_of_date": str(d), "session_date": str(session),
        "cutoff_utc": now, "cutoff_rule": ("routine start on the next session, exchange time "
                                           f"{CUTOFF_LOCAL.get(market, 'open - 75 min')}"),
        "fair_test": leakage_label(d, model_cut) == FAIR, "test": leakage_label(d, model_cut),
        "model_training_cutoff": str(model_cut), "source_root": str(src), "root": str(root),
        "context_pack": {"path": str(ctx), "bytes": len(text.encode("utf-8")), "lines": text.count("\n"),
                         "approx_tokens": round(len(text) / 4), "sha256": hashlib.sha256(text.encode()).hexdigest()},
        "citable_evidence": counts,
        "assumptions": ([f"ASSUMED: {len(assumed)} actual earnings dates within {assume_earnings_days} days after D "
                         "treated as announced before the cutoff (--assume-earnings-known): "
                         + ", ".join(f"{a['ticker']} {a['date']}" for a in assumed)] if assume_earnings_days else [])
                       + (["ASSUMED: bulk/block deals dated <= D were public before the cutoff (NSE publishes "
                           "them after the close)"] if copied["kinds"].get("deals", {}).get("rows_kept") else []),
        "upcoming_earnings": upcoming(root, market, d),
        "included": copied["kinds"], "excluded": copied["excluded"],
        "not_copied": ["summaries/ (written live with later knowledge)", "reports/"],
        "steps": steps,
        "limitations": limitations(copied, counts),
        "prepared_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    (root / "ai_replay.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out


def upcoming(root: Path, market: str, d: date) -> dict:
    """The as-of indicator snapshot's earnings view: tickers with days_to_earnings, those <= 1 (no call
    allowed) and BLOCKED tickers."""
    with data_root(root):
        f = connect(market).execute("SELECT ticker, quality, days_to_earnings FROM features_latest "
                                    "WHERE as_of_date = ? ORDER BY ticker", [d]).df()
    known = f[f["days_to_earnings"].notna()]
    return {"with_days_to_earnings": {r.ticker: int(r.days_to_earnings) for r in known.itertuples()},
            "earnings_within_1_day": sorted(known.loc[known["days_to_earnings"] <= 1, "ticker"]),
            "blocked": sorted(f.loc[f["quality"] == "BLOCKED", "ticker"])}


def limitations(copied: dict, counts: dict) -> list[str]:
    k = copied["kinds"]
    out = [f"No news: stored news starts {copied['first_news_file']} (live collection only), so the news-analyst "
           "has nothing to read and calls can cite only SEC filings (US) or NSE announcements (India).",
           "No overnight quotes before live collection: cue_change_pct is empty and the vol-index level is the "
           "last close, not the pre-open quote.",
           "Upcoming earnings and ex-dividend dates first seen after the cutoff are dropped, so days_to_earnings "
           "is empty unless such a row was stored before the cutoff; the earnings-day block can then not apply.",
           "Price bars are the stored (later) downloads: a split after D is already applied to earlier closes.",
           "The model's own memory is the remaining risk: only as-of dates after "
           f"{training_cutoff()} (model_training_cutoff) are treated as a fair test; earlier ones are "
           "labelled contaminated and scored separately."]
    if counts["total"] == 0:
        out.insert(0, "No citable evidence ids at all as of the cutoff: under the CLAUDE.md rule (evidence_ids "
                      "required) the forecaster can only abstain.")
    if not k.get("prices", {}).get("rows_kept"):
        out.insert(0, "No price bars kept.")
    return out


# ---------- backfill: a scratch source root with longer histories ----------

SOURCE_MARKER = ".ai_replay_source"
# Collectors run into the scratch source, one after another (SEC: the shared 10 requests/s budget and
# the SEC_USER_AGENT contact; NSE: one polite session per collector, never two at once).
BACKFILL_STEPS = {
    "us": [("collect_filings.py",), ("collect_insiders.py",), ("collect_stakes.py",), ("collect_events.py",)],
    "india": [("collect_nse_india.py", "--only", "announcements", "--only", "financials", "--since", "{since}"),
              ("collect_relations_india.py", "--only", "insiders", "--only", "deals", "--since", "{since}"),
              ("collect_events.py",)],
}
BACKFILL_KINDS = {"us": ("filings", "insiders", "stakes", "events"),
                  "india": ("announcements", "financials", "insiders", "deals", "events")}


def check_source(source: Path) -> Path:
    """The scratch source must not be the repo, the real data/ or anything inside or above it."""
    s = source.resolve()
    for real_root in {CODE.resolve(), Path(common.ROOT).resolve()}:
        real = real_root / "data"
        if s == real_root or s == real or real in s.parents or s in real_root.parents:
            raise SystemExit(f"--source {s} is the repo, its real data/ or contains them; use a scratch directory")
    for a in [s, *s.parents]:   # any other market-brief checkout's data/ (e.g. the main clone of a worktree)
        if a.name == "data" and (a.parent / "config" / "markets").is_dir() and (a.parent / "scripts").is_dir():
            raise SystemExit(f"--source {s} is inside the real data/ of the checkout {a.parent}; use a scratch directory")
    if s.exists() and any(s.iterdir()) and not (s / SOURCE_MARKER).exists():
        raise SystemExit(f"--source {s} exists, is not empty and is not an ai_replay source; choose another path")
    return s


def backfill_config(cfg_dir: Path, market: str, since: date, today: date) -> dict:
    """Longer lookbacks in the scratch source's config copy only (never the repo's config)."""
    import yaml
    path = cfg_dir / "markets" / f"{market}.yaml"
    doc = yaml.safe_load(path.read_text())
    days = (today - since).days + 1
    changed = {}
    if doc.get("filings") == "sec":
        doc["filing_lookback_days"] = changed["filing_lookback_days"] = days
        for k in ("insiders", "stakes"):
            if k in (doc.get("relationships") or {}):
                doc["relationships"][k]["lookback_days"] = changed[f"relationships.{k}.lookback_days"] = days
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return changed


def stored_by_month(market: str, root: Path, kinds) -> dict:
    """Rows per kind by month of their publication/acceptance time (events: event date)."""
    out = {}
    for kind in kinds:
        cols = PUBLIC_AT.get(kind, [])
        months: dict[str, int] = {}
        for f in sorted((root / "data" / market / kind).glob("**/*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                t = _ts(r.get("date")) if kind in ("events", "deals") else public_at(kind, r) if cols else None
                key = "unknown" if t is None else f"{t:%Y-%m}"
                months[key] = months.get(key, 0) + 1
        out[kind] = dict(sorted(months.items()))
    return out


def backfill(cfg: dict, source: Path, since: date, timeout: int = 3600) -> dict:
    market = cfg["market"]
    if market not in BACKFILL_STEPS:
        raise SystemExit(f"no backfill steps for market {market}")
    s = check_source(source)
    today = common.utc_today()
    if since >= today:
        raise SystemExit("--since must be before today")
    s.mkdir(parents=True, exist_ok=True)
    (s / SOURCE_MARKER).write_text("ai_replay backfill source (scratch; never the repo's data)\n")
    src_data = Path(common.ROOT) / "data" / market
    if not (s / "data" / market).exists():
        shutil.copytree(src_data, s / "data" / market)
    if not (s / "config").exists():
        shutil.copytree(common.CONFIG, s / "config")
    changed = backfill_config(s / "config", market, since, today)
    before = stored_by_month(market, s, BACKFILL_KINDS[market])
    steps = []
    for step in BACKFILL_STEPS[market]:
        script, args = step[0], [a.format(since=since) for a in step[1:]]
        t0 = datetime.now(timezone.utc)
        try:
            p = run_script(script, s, market, *args, timeout=timeout)
            code, out, err = p.returncode, _json_or_text(p.stdout), p.stderr[-1500:]
        except subprocess.TimeoutExpired:
            code, out, err = None, None, f"timed out after {timeout} s"
        if isinstance(out, dict):   # keep the summary readable
            out = {k: v for k, v in out.items() if k not in ("notes",)} | (
                {"notes": out["notes"][:12]} if isinstance(out.get("notes"), list) else {})
        steps.append({"script": script, "args": args, "exit": code, "seconds": round(
            (datetime.now(timezone.utc) - t0).total_seconds()), "summary": out, "stderr_tail": err if code else ""})
    res = {"step": "ai_replay.backfill", "market": market, "source": str(s), "copied_from": str(src_data),
           "since": str(since), "today": str(today), "config_overrides": changed, "steps": steps,
           "rows_by_public_month_before": before, "rows_by_public_month_after": stored_by_month(
               market, s, BACKFILL_KINDS[market]),
           "note": "each backfilled row keeps its real publication/acceptance time; first_seen_at is the "
                   "backfill time, and prepare filters on the publication/acceptance time"}
    (s / f"backfill-{market}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


# ---------- record: validate and store calls ----------

def store_dir(results: Path, market: str) -> Path:
    p = Path(results) / market
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def replay_context(cfg: dict, root: Path, d: date) -> dict:
    """What the forecaster saw in the prepared root: snapshot quality, earnings, citable ids."""
    meta_path = root / "ai_replay.json"
    if not (root / MARKER).exists() or not meta_path.exists():
        raise SystemExit(f"{root} is not a prepared ai_replay root (run prepare first)")
    meta = json.loads(meta_path.read_text())
    if meta["market"] != cfg["market"] or meta["as_of_date"] != str(d):
        raise SystemExit(f"{root} was prepared for {meta['market']} {meta['as_of_date']}, not {cfg['market']} {d}")
    with data_root(root):
        con = connect(cfg["market"])
        feats = con.execute("SELECT ticker, quality, days_to_earnings FROM features_latest WHERE as_of_date = ?",
                            [d]).df()
    ev_df, _ = evidence(cfg["market"], root, datetime.fromisoformat(meta["cutoff_utc"]))
    return {"meta": meta, "features": {r.ticker: {"quality": r.quality,
                                                  "days_to_earnings": None if pd.isna(r.days_to_earnings) else int(r.days_to_earnings)}
                                       for r in feats.itertuples()},
            "evidence": set(ev_df["id"]), "tickers": set(cfg["tickers"])}


def validate(rec, ctx: dict, d: date, seen: set[str]) -> list[str]:
    """Reasons a forecaster record breaks the schema or the CLAUDE.md prediction rules (empty = valid):
    the shared check in prediction_rules.py, with the replay date as every ticker's as_of_date."""
    return check_prediction(rec, ctx, seen, as_of=d, as_of_label="the replay date",
                            evidence_label="the replay root's news/filings/announcements")


def record(cfg: dict, d: date, root: Path, calls_file: Path, results: Path) -> dict:
    market = cfg["market"]
    ctx = replay_context(cfg, root, d)
    sd = store_dir(results, market)
    days = read_jsonl(sd / "days.jsonl")
    if any(x["date"] == str(d) for x in days):
        raise SystemExit(f"{market} {d} is already recorded in {sd}; use a new --results directory to re-run it")
    seen = {x["id"] for x in read_jsonl(sd / "calls.jsonl")}
    raw = [x for x in calls_file.read_text(encoding="utf-8").splitlines() if x.strip()] if calls_file.exists() else []
    now, cutoff = utc_now(), ctx["meta"]["cutoff_utc"]
    model_cut = training_cutoff()
    label = leakage_label(d, model_cut)
    good, bad = [], []
    for i, line in enumerate(raw, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            bad.append({"line": i, "id": None, "reasons": [f"not JSON: {e}"]})
            continue
        errs = validate(rec, ctx, d, seen)
        if errs:
            bad.append({"line": i, "id": rec.get("id") if isinstance(rec, dict) else None, "reasons": errs})
            continue
        seen.add(rec["id"])
        good.append({**rec, "agent_made_at": rec.get("made_at"), "made_at": cutoff, "market": market,
                     "replay": True, "recorded_at": now, "test": label, "model_training_cutoff": str(model_cut),
                     "context_sha256": ctx["meta"]["context_pack"]["sha256"]})
    common.append_jsonl(sd / "calls.jsonl", good)
    common.append_jsonl(sd / "rejected.jsonl", [{**b, "market": market, "date": str(d), "recorded_at": now}
                                                for b in bad])
    eligible = sorted(t for t, f in ctx["features"].items() if t in ctx["tickers"] and f["quality"] != "BLOCKED"
                      and not (f["days_to_earnings"] is not None and f["days_to_earnings"] <= 1))
    day = {"market": market, "date": str(d), "test": label, "model_training_cutoff": str(model_cut),
           "session_date": ctx["meta"]["session_date"], "cutoff_utc": cutoff,
           "root": str(root), "n_tickers": len(ctx["tickers"]), "eligible": eligible,
           "n_calls": len(good), "n_rejected": len(bad),
           "prompt_versions": sorted({g["prompt_version"] for g in good}), "recorded_at": now,
           "citable_ids": ctx["meta"]["citable_evidence"]["total"]}
    common.append_jsonl(sd / "days.jsonl", [day])
    return {"step": "ai_replay.record", "market": market, "date": str(d), "test": label, "results": str(sd),
            "recorded": len(good), "rejected": bad, "eligible_tickers": len(eligible)}


# ---------- score ----------

def band_of(c: float) -> str:
    return next(name for name, lo, hi in BANDS if lo <= c < hi)


def score_rows(cfg: dict, calls: list[dict], bars: dict) -> pd.DataFrame:
    """One row per call: base close at as_of_date, close `h` stored bars later, hit as
    score_predictions.py (a flat close is a miss), and the rule-baseline inputs known at as_of."""
    rows, cache = [], {}
    for c in calls:
        t, h, d = c["ticker"], int(c["horizon_days"]), pd.Timestamp(c["as_of_date"])
        df = bars.get(t)
        row = {"id": c["id"], "date": d.date(), "ticker": t, "h": h, "direction": c["direction"],
               "confidence": float(c["confidence"]), "prompt_version": c.get("prompt_version"),
               "evidence_ids": c.get("evidence_ids"), "status": "no bars"}
        if df is not None and len(df):
            if t not in cache:
                close = df["close"]
                cache[t] = (close, replay.rsi_series(close))
            close, rsi = cache[t]
            i = int(close.index.searchsorted(d, side="right")) - 1
            if i >= 0:
                base = float(close.iloc[i])
                row.update({"base_date": close.index[i].date(), "base": base,
                            "ret1": base / float(close.iloc[i - 1]) - 1 if i >= 1 else np.nan,
                            "ret5": base / float(close.iloc[i - 5]) - 1 if i >= 5 else np.nan,
                            "rsi": float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else np.nan,
                            "status": "pending"})
                if i + h < len(close):
                    tgt = float(close.iloc[i + h])
                    up = c["direction"] == "up"
                    row.update({"target_date": close.index[i + h].date(), "target": tgt, "ret": tgt / base - 1,
                                "fwd": math.log(tgt / base), "hit": (tgt > base) if up else (tgt < base),
                                "status": "scored"})
        rows.append(row)
    return pd.DataFrame(rows)


def _rate(k: int, n: int) -> dict:
    lo, hi = replay.wilson(k, n)
    return {"n": n, "hits": k, "hit_rate": replay._r(k / n) if n else None, "ci95": [replay._r(lo), replay._r(hi)],
            "p_vs_50": None if not n else float(f"{replay.binom_p_two_sided(k, n):.3g}")}


def group_stats(g: pd.DataFrame) -> dict:
    """AI hit rate (Wilson 95% interval, exact binomial p vs 50%), stated confidence and Brier score,
    always-up and replay.py's rule baselines on the same ticker-days."""
    if g.empty:
        return {"n": 0}
    hit = g["hit"].astype(bool)
    out = _rate(int(hit.sum()), len(g))
    out.update({"mean_confidence": replay._r(g["confidence"].mean()),
                "brier": replay._r(((g["confidence"] - hit.astype(float)) ** 2).mean())})
    au = (g["fwd"] > 0)
    out["always_up"] = _rate(int(au.sum()), len(g))
    diff = (hit.astype(float) - au.astype(float)).to_numpy()
    blocks = pd.factorize(g["date"])[0]
    lo, hi = replay.clustered_ci(diff, blocks)
    out["diff_vs_always_up"] = {"pts": replay._r(diff.mean()), "ci95": [replay._r(lo), replay._r(hi)],
                                "note": "95% interval clustered by as-of date"}
    rules = {}
    sig = replay.signals(g.assign(ret1=g["ret1"], ret5=g["ret5"], rsi=g["rsi"]))
    up, down = g["fwd"] > 0, g["fwd"] < 0
    for name, s in sig.items():
        if name == "always_up":
            continue
        call = s != 0
        rhit = ((s > 0) & up) | ((s < 0) & down)
        r = _rate(int(rhit[call].sum()), int(call.sum()))
        r["label"] = replay.SIGNAL_LABELS[name]
        r["ai_hit_rate_same_rows"] = replay._r(hit[call].mean()) if call.any() else None
        rules[name] = r
    out["rules"] = rules
    return out


def summarize(cfg: dict, calls: list[dict], days: list[dict], bars: dict, cutoff: date | None = None) -> dict:
    """Scores per leakage group (ForecastBench rule): `fair` = as-of dates after the model's training
    cutoff, `contaminated` = on or before it. Each group is scored on its own rows only; nothing is
    pooled across groups. The label comes from the current config cutoff, not from the stored rows."""
    cutoff = cutoff or training_cutoff()
    out = {"market": cfg["market"], "name": cfg.get("name"), "computed_at": utc_now(),
           "model_training_cutoff": str(cutoff),
           "rule": (f"fair = as-of date after {cutoff} (the model's training cutoff); contaminated = on or before "
                    "it. Scored separately, never pooled.")}
    for label in (FAIR, CONTAMINATED):
        g_days = [x for x in days if leakage_label(x["date"], cutoff) == label]
        g_calls = [c for c in calls if leakage_label(c["as_of_date"], cutoff) == label]
        out[label] = summarize_group(cfg, g_calls, g_days, bars, label)
    return out


def summarize_group(cfg: dict, calls: list[dict], days: list[dict], bars: dict, label: str) -> dict:
    df = score_rows(cfg, calls, bars)
    sc = df[df["status"] == "scored"] if len(df) else df
    out = {"test": label, "n_days": len(days), "dates": sorted(x["date"] for x in days), "n_calls": int(len(df)),
           "n_scored": int(len(sc)), "n_pending": int((df["status"] == "pending").sum()) if len(df) else 0,
           "n_no_bars": int((df["status"] == "no bars").sum()) if len(df) else 0,
           "prompt_versions": sorted({c.get("prompt_version") for c in calls if c.get("prompt_version")}),
           "fair_test": label == FAIR,
           "overall": group_stats(sc) if len(sc) else {"n": 0},
           "by_horizon": {str(h): group_stats(sc[sc["h"] == h]) if len(sc) else {"n": 0} for h in HORIZONS},
           "by_band": []}
    for name, lo, hi in BANDS:
        g = sc[(sc["confidence"] >= lo) & (sc["confidence"] < hi)] if len(sc) else sc
        r = _rate(int(g["hit"].astype(bool).sum()), len(g)) if len(g) else {"n": 0}
        r.update({"band": name, "stated": replay._r(g["confidence"].mean()) if len(g) else None})
        out["by_band"].append(r)
    # abstention: a call slot is an eligible ticker (not BLOCKED, no earnings within 1 day) x horizon x day
    called = {(c["as_of_date"], c["ticker"], int(c["horizon_days"])) for c in calls}
    ab = {}
    for h in HORIZONS:
        slots = sum(len(x["eligible"]) for x in days)
        n = sum(1 for x in days for t in x["eligible"] if (x["date"], t, h) in called)
        ab[f"{h}d"] = {"slots": slots, "calls": n, "abstention_rate": replay._r(1 - n / slots) if slots else None}
    slots = sum(len(x["eligible"]) for x in days)
    anyc = sum(1 for x in days for t in x["eligible"] if any((x["date"], t, h) in called for h in HORIZONS))
    ab["any"] = {"slots": slots, "ticker_days_with_a_call": anyc,
                 "abstention_rate": replay._r(1 - anyc / slots) if slots else None}
    ab["ineligible_ticker_days"] = sum(x["n_tickers"] - len(x["eligible"]) for x in days)
    out["abstention"] = ab
    per_day = []
    for x in sorted(days, key=lambda x: x["date"]):
        g = sc[sc["date"].astype(str) == x["date"]] if len(sc) else sc
        per_day.append({"date": x["date"], "test": label, "calls": x["n_calls"], "rejected": x["n_rejected"],
                        "citable_ids": x.get("citable_ids"), "scored": int(len(g)),
                        "hits": int(g["hit"].astype(bool).sum()) if len(g) else 0})
    out["per_day"] = per_day
    keep = ["id", "date", "ticker", "h", "direction", "confidence", "status", "base_date", "base", "target_date",
            "target", "ret", "hit", "evidence_ids"]
    out["calls"] = [{"test": label, **{k: (None if (isinstance(v, float) and not math.isfinite(v)) else v)
                                       for k, v in r.items()}}
                    for r in df.reindex(columns=keep).astype(object).where(df.reindex(columns=keep).notna(), None)
                    .to_dict("records")] if len(df) else []
    out["top"] = top_sentences(out)
    return out


def pct(x, k: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{k}f}%"


def top_sentences(s: dict) -> list[str]:
    o, ab = s["overall"], s["abstention"]["any"]
    if not o.get("n"):
        return ["Did the AI beat a coin flip? No call has been scored yet, so there is nothing to judge.",
                "Did it beat simple rules? Not measurable without scored calls.",
                f"Is its confidence honest? Not measurable yet; it abstained on {pct(ab['abstention_rate'])} of the "
                f"{ab['slots']} stock-days it could call."]
    lo, hi = o["ci95"]
    verdict = ("clearly better than a coin flip" if lo > 0.5 else "clearly worse than a coin flip" if hi < 0.5
               else "not distinguishable from a coin flip")
    s1 = (f"Did the AI beat a coin flip? Its {o['n']} scored calls were right {pct(o['hit_rate'])} of the time "
          f"(95% interval {pct(lo)} to {pct(hi)}), {verdict} (50%).")
    d = o["diff_vs_always_up"]
    dlo, dhi = d["ci95"]
    noise = ("within noise" if dlo is None or (dlo <= 0 <= dhi) else "a clear difference")
    rules = [f"{r['label']} {pct(r['hit_rate'])} on its {r['n']} calls (AI {pct(r['ai_hit_rate_same_rows'])} there)"
             for r in o["rules"].values() if r.get("n")]
    s2 = (f"Did it beat simple rules? On the same stocks and days always calling up was right "
          f"{pct(o['always_up']['hit_rate'])}, so the AI was {100 * d['pts']:+.1f} points vs always-up ({noise})"
          + ("; " + "; ".join(rules) if rules else "") + ".")
    gap = o["hit_rate"] - o["mean_confidence"]
    honest = ("about right" if abs(gap) <= 0.05 else "overconfident" if gap < 0 else "underconfident")
    s3 = (f"Is its confidence honest? It stated {pct(o['mean_confidence'])} on average and was right "
          f"{pct(o['hit_rate'])}, so it looks {honest} on this sample; it abstained on {pct(ab['abstention_rate'])} "
          f"of the {ab['slots']} stock-days it could call.")
    return [s1, s2, s3]


# ---------- HTML ----------

def _f(x, k=1) -> str:
    return "n/a" if x is None else f"{100 * x:.{k}f}%"


def svg_hit_bars(s: dict) -> str:
    groups = [("1-day", s["by_horizon"]["1"]), ("5-day", s["by_horizon"]["5"]), ("All", s["overall"])]
    W, H, L, R, T, B = 640, 300, 48, 16, 16, 44
    pw, ph = W - L - R, H - T - B
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Hit rate: AI vs always-up">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    slot, bw = pw / len(groups), 28
    for i, (name, g) in enumerate(groups):
        cx = L + slot * (i + .5)
        out.append(f'<text x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{cx:.1f}" y="{H - B + 30}" text-anchor="middle">{g.get("n", 0)} calls</text>')
        if not g.get("n"):
            continue
        for j, (key, color, label) in enumerate((("ai", "var(--s1)", "AI"), ("au", "var(--s2)", "Always up"))):
            r = g if key == "ai" else g["always_up"]
            v = r["hit_rate"]
            x = cx + (j - 1) * (bw + 2) + 1
            y0, y1 = Y(0), Y(v)
            hgt = max(y0 - y1, 0.5)
            rr = min(4, hgt)
            d = (f"M{x:.1f},{y0:.1f} L{x:.1f},{y1 + rr:.1f} Q{x:.1f},{y1:.1f} {x + rr:.1f},{y1:.1f} "
                 f"L{x + bw - rr:.1f},{y1:.1f} Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 + rr:.1f} L{x + bw:.1f},{y0:.1f} Z")
            ci = r["ci95"]
            tip = f"{name}, {label}: right {_f(v)} of {r['n']} (95% interval {_f(ci[0])} to {_f(ci[1])})"
            out.append(f'<path class="mark" d="{d}" fill="{color}" data-tip="{html.escape(tip, quote=True)}"/>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(.5):.1f}" y2="{Y(.5):.1f}" stroke="var(--ink2)" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{L + 4}" y="{Y(.5) - 5:.1f}" text-anchor="start">coin flip</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--axis)"/></svg>')
    return "".join(out)


def svg_calibration(s: dict) -> str:
    pts = [b for b in s["by_band"] if b.get("n")]
    W, H, L, R, T, B = 640, 340, 48, 16, 16, 40
    pw, ph = W - L - R, H - T - B
    lo_x, hi_x = 0.45, 0.95
    X = lambda v: L + (v - lo_x) / (hi_x - lo_x) * pw  # noqa: E731
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Stated confidence vs actual hit rate">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    for v in (0.5, 0.6, 0.7, 0.8, 0.9):
        out.append(f'<text x="{X(v):.1f}" y="{H - B + 16}" text-anchor="middle">{int(v * 100)}%</text>')
    out.append(f'<text x="{L + pw / 2}" y="{H - 4}" text-anchor="middle">stated confidence (average in each band)</text>')
    out.append(f'<line x1="{X(lo_x):.1f}" y1="{Y(lo_x):.1f}" x2="{X(hi_x):.1f}" y2="{Y(hi_x):.1f}" '
               'stroke="var(--muted)" stroke-dasharray="4 4"/>')
    for b in pts:
        x, y = X(b["stated"]), Y(b["hit_rate"])
        lo, hi = b["ci95"]
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{Y(lo):.1f}" y2="{Y(hi):.1f}" stroke="var(--s1)" stroke-width="2"/>')
        tip = (f"Band {b['band']}: stated {_f(b['stated'])}, right {_f(b['hit_rate'])} of {b['n']} calls "
               f"(95% interval {_f(lo)} to {_f(hi)})")
        out.append(f'<circle class="mark" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="var(--s1)" stroke="var(--surface)" '
                   f'stroke-width="2" data-tip="{html.escape(tip, quote=True)}"/>')
        out.append(f'<text x="{x + 10:.1f}" y="{y + 4:.1f}" text-anchor="start">{b["n"]} calls</text>')
    out.append("</svg>")
    return "".join(out)


def pts(x) -> str:
    return "" if x is None else f"{100 * x:+.1f} pts"


def signed_pct(x) -> str:
    return "" if x is None else f"{100 * x:+.2f}%"


def html_page(s: dict) -> str:
    """The score page: the fair group (as-of dates after the training cutoff) is the result; the
    contaminated group, if any, is a separate, labelled section scored on its own rows only."""
    esc = replay.esc
    f, c = s[FAIR], s[CONTAMINATED]
    cut = esc(s["model_training_cutoff"])
    banner = (f'<p class="note"><b>Fair test</b> = an as-of date after {cut}, the model\'s training cutoff '
              '(<code>model_training_cutoff</code> in config/settings.yaml; ForecastBench leakage rule). Dates on or '
              f'before it are <b>contaminated</b>: the model may have seen what happened. The two groups are scored '
              f'separately and never pooled: {f["n_days"]} fair and {c["n_days"]} contaminated days.</p>')
    if f["n_days"]:
        sub = (f'<p class="sub">On {f["n_days"]} past trading days after the model\'s training data '
               f'({esc(f["dates"][0])} to {esc(f["dates"][-1])}), the AI forecaster saw only what was known before the '
               'next session opened, and its up/down calls were checked against the actual closes. Research only, not '
               'investment advice.</p>')
        body = group_html(f)
    else:
        sub = ('<p class="sub">No fair-test day is recorded yet, so there is no fair result. Research only, not '
               'investment advice.</p>')
        body = ""
    if c["n_days"]:
        body += (f'<section class="contaminated"><h2>Contaminated dates (on or before {cut}): not a fair test</h2>'
                 f'<p class="note bad">CONTAMINATED: {c["n_days"]} as-of dates ({esc(c["dates"][0])} to '
                 f'{esc(c["dates"][-1])}) fall inside the model\'s training period, so it may have seen these prices. '
                 'They are scored on their own below, never pooled with the fair result.</p>'
                 f'{group_html(c)}</section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Replay {esc(s['market'].upper())}</title>
<style>{replay.CSS}</style></head><body><main>
<h1>AI forecaster replay: {esc(s.get('name') or s['market'])}</h1>
{sub}{banner}{body}
</main><div id="tip" class="tip"></div><script>{replay.JS}</script></body></html>"""


def group_html(g: dict) -> str:
    """One leakage group's results (fair or contaminated): answers, tiles, charts and detail tables."""
    esc = replay.esc
    lab = g["test"]
    o, hz, ab = g["overall"], g["by_horizon"], g["abstention"]

    def tile(label, r, note):
        v = r.get("hit_rate") if r else None
        ci = (r or {}).get("ci95") or [None, None]
        span = "" if ci[0] is None else f"95% interval {_f(ci[0])} to {_f(ci[1])}"
        return (f'<div class="card tile"><div class="l">{esc(label)}</div><div class="v">{_f(v)}</div>'
                f'<div class="n">{esc(note)}</div><div class="n">{span}</div></div>')

    tiles = "".join([
        tile("AI calls right, 5 days ahead", hz["5"], f"{hz['5'].get('n', 0)} scored calls · coin flip 50%"),
        tile("AI calls right, 1 day ahead", hz["1"], f"{hz['1'].get('n', 0)} scored calls · coin flip 50%"),
        tile("“Always up” right on the same calls", o.get("always_up") or {}, "same stocks, days and horizons"),
        f'<div class="card tile"><div class="l">Stock-days with no call</div>'
        f'<div class="v">{_f(ab["any"]["abstention_rate"])}</div><div class="n">abstained on '
        f'{ab["any"]["slots"] - ab["any"]["ticker_days_with_a_call"]} of {ab["any"]["slots"]} stock-days</div>'
        f'<div class="n">abstaining is allowed and often right</div></div>'])
    top = "".join(f"<p class=\"answer\"><b>{esc(x.split('? ', 1)[0])}?</b> {esc(x.split('? ', 1)[1])}</p>"
                  for x in g["top"])
    hrows = []
    for name, x in (("1-day", hz["1"]), ("5-day", hz["5"]), ("All", o)):
        if not x.get("n"):
            hrows.append(f"<tr><td>{name}</td><td>0</td>" + "<td></td>" * 6 + "</tr>")
            continue
        d = x["diff_vs_always_up"]
        hrows.append(f"<tr><td>{name}</td><td>{x['n']}</td><td>{_f(x['hit_rate'])}</td>"
                     f"<td>{_f(x['ci95'][0])} to {_f(x['ci95'][1])}</td><td>{esc(replay.fmt_p(x['p_vs_50']))}</td>"
                     f"<td>{_f(x['mean_confidence'])}</td><td>{_f(x['always_up']['hit_rate'])}</td>"
                     f"<td>{pts(d['pts'])}</td></tr>")
    rrows = []
    for name, x in (("1-day", hz["1"]), ("5-day", hz["5"]), ("All", o)):
        for r in (x.get("rules") or {}).values():
            if not r.get("n"):
                continue
            rrows.append(f"<tr><td>{esc(r['label'])}</td><td>{name}</td><td>{r['n']}</td><td>{_f(r['hit_rate'])}</td>"
                         f"<td>{_f(r['ci95'][0])} to {_f(r['ci95'][1])}</td><td>{_f(r['ai_hit_rate_same_rows'])}</td></tr>")
    brows = "".join(f"<tr><td>{b['band']}</td><td>{b.get('n', 0)}</td><td>{_f(b.get('stated'))}</td>"
                    f"<td>{_f(b.get('hit_rate'))}</td><td>"
                    f"{'' if not b.get('n') else _f(b['ci95'][0]) + ' to ' + _f(b['ci95'][1])}</td></tr>"
                    for b in g["by_band"])
    arows = "".join(f"<tr><td>{k}</td><td>{v['slots']}</td><td>{v.get('calls', v.get('ticker_days_with_a_call'))}</td>"
                    f"<td>{_f(v['abstention_rate'])}</td></tr>" for k, v in ab.items() if isinstance(v, dict))
    drows = "".join(f"<tr><td>{x['date']}</td><td>{lab}</td><td>{x['citable_ids']}</td><td>{x['calls']}</td><td>{x['rejected']}</td>"
                    f"<td>{x['scored']}</td><td>{x['hits']}</td></tr>" for x in g["per_day"])
    crows = "".join(f"<tr><td>{esc(str(c['date']))}</td><td>{esc(c['test'])}</td><td>{esc(c['ticker'])}</td><td>{c['h']}d</td><td>{esc(c['direction'])}</td>"
                    f"<td>{c['confidence']:.2f}</td><td>{esc(c['status'])}</td>"
                    f"<td>{signed_pct(c.get('ret'))}</td>"
                    f"<td>{'' if c.get('hit') is None else ('right' if c['hit'] else 'wrong')}</td>"
                    f"<td>{esc(', '.join(c.get('evidence_ids') or []))}</td></tr>" for c in g["calls"])
    legend = ('<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>AI forecaster</span>'
              '<span><span class="sw" style="background:var(--s2)"></span>Always up (same calls)</span>'
              '<span><span class="dash"></span>coin flip 50%</span></div>')
    tag = (f'<p class="note"><b>Group: {esc(lab)}</b> ({g["n_days"]} as-of days, {g["n_calls"]} calls); '
           'every number in this group uses only its own rows.</p>')
    return f"""{tag}
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">A call is right if the close 1 or 5 trading days later moved the called way (no change counts as wrong).
95% interval = the span the true hit rate most likely lies in; with few calls it is wide.</p>
<h2>Was the AI right more often than “always up”?</h2>
<div class="card">{legend}{svg_hit_bars(g)}
<p class="caption">Look for: blue bars above both the dashed 50% line and the orange bar beside them. Bars that differ by
less than their 95% intervals (hover a bar) are within noise.</p></div>
<h2>Does its confidence mean what it says?</h2>
<div class="card"><div class="legend"><span><span class="sw" style="background:var(--s1)"></span>AI calls by confidence band
(line = 95% interval)</span><span><span class="dash"></span>perfect calibration</span></div>{svg_calibration(g)}
<p class="caption">Look for: points on the dashed line. Below it, calls stated with that confidence were right less often
than promised (overconfident); above it, more often.</p></div>
<h2>More detail</h2>
<details><summary>Hit rates by horizon (table)</summary><div class="scroll"><table><thead><tr><th>Horizon</th><th>Calls</th>
<th>Hit rate</th><th>95% interval</th><th>p vs 50%</th><th>Stated</th><th>Always up</th><th>AI vs always up</th></tr></thead>
<tbody>{''.join(hrows)}</tbody></table></div>
<p class="note">95% interval: Wilson binomial interval; p: exact two-sided binomial test vs 50%. Both treat calls as
independent; calls on the same day move together, so they overstate the evidence. "AI vs always up" is in percentage
points on the same calls (its 95% interval, clustered by date, is in the JSON).</p></details>
<details><summary>Simple rules on the same stocks and days</summary><div class="scroll"><table><thead><tr><th>Rule</th>
<th>Horizon</th><th>Rule calls</th><th>Rule hit rate</th><th>95% interval</th><th>AI hit rate on those calls</th></tr></thead>
<tbody>{''.join(rrows) or '<tr><td>no scored calls</td><td></td><td></td><td></td><td></td><td></td></tr>'}</tbody></table></div>
<p class="note">Rules from replay.py, on the ticker-days where the AI made a call: momentum (sign of the last 1 or 5 days'
return) and RSI(14) mean reversion (below {replay.RSI_LOW:g} up, above {replay.RSI_HIGH:g} down, else no call).</p></details>
<details><summary>Confidence bands (calibration)</summary><div class="scroll"><table><thead><tr><th>Band</th><th>Calls</th>
<th>Stated</th><th>Right</th><th>95% interval</th></tr></thead><tbody>{brows}</tbody></table></div>
<p class="note">Brier score (lower is better; 0.25 = always saying 50%): {o.get('brier', 'n/a')}.</p></details>
<details><summary>Abstention</summary><div class="scroll"><table><thead><tr><th>Horizon</th><th>Stock-days</th><th>Calls</th>
<th>No call</th></tr></thead><tbody>{arows}</tbody></table></div>
<p class="note">Stock-days count only tickers the rules allow a call on (not BLOCKED, no earnings within 1 day).</p></details>
<details><summary>Per sample day</summary><div class="scroll"><table><thead><tr><th>As-of date</th><th>Test</th><th>Citable ids</th>
<th>Calls</th><th>Rejected</th><th>Scored</th><th>Right</th></tr></thead><tbody>{drows}</tbody></table></div></details>
<details><summary>Every call</summary><div class="scroll"><table><thead><tr><th>As-of</th><th>Test</th><th>Ticker</th><th>Horizon</th>
<th>Call</th><th>Confidence</th><th>Status</th><th>Return</th><th>Result</th><th>Evidence</th></tr></thead>
<tbody>{crows}</tbody></table></div></details>
<details><summary>Method and limits</summary><ul>
<li>Each day was prepared by <code>scripts/ai_replay.py prepare</code>: prices up to that day's close, and filings,
announcements and other records only if public before the routine's pre-open start on the next session.</li>
<li>No news before live collection began, so calls could cite only SEC filings (US) or NSE announcements (India).</li>
<li>Scored on the real stored closes, {g['n_pending']} calls still pending (target after the last stored bar).</li>
<li>Prompt versions: {esc(', '.join(g['prompt_versions']) or 'none')}.</li>
<li>A small sample: a dozen days per market cannot show a small edge; treat the result as a smoke test.</li></ul></details>"""


def score(cfg: dict, results: Path, out: Path) -> dict:
    sd = Path(results) / cfg["market"]
    calls, days = read_jsonl(sd / "calls.jsonl"), read_jsonl(sd / "days.jsonl")
    if not days:
        raise SystemExit(f"nothing recorded in {sd}")
    bars = load_bars(connect(cfg["market"]))
    s = summarize(cfg, calls, days, bars)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_page(s), encoding="utf-8")
    js = out.with_suffix(".json")
    js.write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    return {"step": "ai_replay.score", "market": cfg["market"], "html": str(out), "json": str(js),
            "model_training_cutoff": s["model_training_cutoff"], "rule": s["rule"],
            **{label: {"n_days": g["n_days"], "n_calls": g["n_calls"], "n_scored": g["n_scored"],
                       "n_pending": g["n_pending"], "overall": {k: g["overall"].get(k) for k in ("n", "hit_rate", "ci95")},
                       "abstention": g["abstention"], "top": g["top"]}
               for label, g in ((FAIR, s[FAIR]), (CONTAMINATED, s[CONTAMINATED]))}}


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--market", default=os.environ.get("MB_MARKET"), help=f"one of {market_names()}")
        return p

    add("dates", "print the sample of as-of dates")
    p = add("prepare", "build an as-of scratch root and its context pack and ranges")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--source", type=Path, help="root whose data/ is read, e.g. a `backfill` source "
                                               "(default: $MB_ROOT or the repo)")
    p.add_argument("--force", action="store_true", help="rebuild a root this script prepared before")
    p.add_argument("--allow-training-period", action="store_true",
                   help="allow an as-of date on or before model_training_cutoff in config/settings.yaml "
                        "(labelled contaminated: not a fair test, scored separately)")
    p.add_argument("--assume-earnings-known", type=int, default=0, metavar="DAYS",
                   help="ASSUMPTION, off by default: treat actual earnings dates within DAYS after D as announced "
                        "before the cutoff (labelled in the context pack and the summary)")
    p = add("backfill", "copy data/<market> to a scratch source and run the collectors into it from --since")
    p.add_argument("--source", required=True, type=Path, help="scratch source root (never the repo or its data/)")
    p.add_argument("--since", required=True, type=date.fromisoformat)
    p = add("record", "validate forecaster calls and store them in the replay results")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--calls", required=True, type=Path, help="forecaster-format JSONL (may be empty: all abstain)")
    p.add_argument("--results", type=Path, default=CODE / "work" / "ai_replay", help="results dir (default work/ai_replay)")
    p = add("score", "score the recorded calls on real closes; write HTML and JSON")
    p.add_argument("--results", type=Path, default=CODE / "work" / "ai_replay")
    p.add_argument("--out", required=True, type=Path, help="HTML path; the JSON goes next to it")
    args = ap.parse_args()
    if not args.market:
        raise SystemExit(f"--market is required; available: {market_names()}")
    cfg = load_market(args.market)
    if args.cmd == "dates":
        ds = sample_dates(cfg)
        res = {"market": cfg["market"], "rule": f"every {SAMPLE_STEP}th {cfg['calendar']} trading day from "
               f"{SAMPLE_START} to {SAMPLE_END}, starting with the first", "n": len(ds),
               "dates": [{"as_of_date": str(d), "session_date": str(next_session(cfg, d)),
                          "cutoff_utc": cutoff_for(cfg, d).isoformat()} for d in ds]}
    elif args.cmd == "prepare":
        res = prepare(cfg, args.date, args.root.resolve(), args.source, args.force, args.allow_training_period,
                      args.assume_earnings_known)
        res = {k: v for k, v in res.items() if k != "steps"} | {"steps": {k: (v if k != "features" else {
            x: v.get(x) for x in ("as_of_date", "session_date", "regime", "tickers", "blocked")} if isinstance(v, dict) else v)
            for k, v in res["steps"].items()}}
    elif args.cmd == "backfill":
        res = backfill(cfg, args.source, args.since)
    elif args.cmd == "record":
        res = record(cfg, args.date, args.root.resolve(), args.calls, args.results)
    else:
        res = score(cfg, args.results, args.out)
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
