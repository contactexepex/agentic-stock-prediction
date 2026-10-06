#!/usr/bin/env python3
"""Reflection log: one short lesson per settled call, read by later forecasts.

Pattern adapted from TauricResearch/TradingAgents (Apache-2.0; tradingagents/memory/reflection.py and settlement.py):
settle past decisions against realised outcomes, write a one-paragraph lesson, and let later decisions read the same
ticker's recent lessons plus recent ones market-wide, only those already known at the decision time. Here the facts
are deterministic (this script) and only the paragraph is written by an agent (`.claude/agents/reflector.md`), checked
by `validate`.

  prepare  [--max N] [--out F]   settled calls without a lesson -> F (default work/lesson_facts.jsonl):
                                 the call (direction, confidence, rationale, evidence ids and what they
                                 said), the outcome (return, hit) and its published range (position of
                                 the close vs the 50%/80% bands). A call whose range is still open
                                 (not late, not yet scored) waits for it.
  validate F                     checks the reflector's records (JSON summary; exit 1 on any error)
  add F                          validate, then append the full records to data/<market>/lessons/
                                 (all or nothing; a lesson id already stored is refused)

The reflector writes one JSON object per lesson: {"prediction_id", "lesson", "prompt_version"}, optionally with copied
fact fields, each of which must equal the stored value. `validate` checks: the prediction id exists and is settled (an
outcome is stored); no lesson for it is stored or repeated in the file; the lesson is 1-60 words; every number in its
text matches the call or its outcome (with a % sign: the return, the close's % distance from a band edge, confidence
in %; without: closes, band edges, confidence, the horizon; either way: the 50/80 band names and numbers already in
the stored rationale; dates and ids are skipped), and a signed return has the right sign. `add` stores the facts
recomputed from data/ (never the agent's copy) plus the text.

Availability: `settled_at` = the outcome's scored_at; `available_from` = the latest scored_at of the facts the lesson
cites (the outcome, and the range outcome when a range is cited). The context pack (context.py) shows a lesson only
once available_from <= its clock (MB_NOW-aware), so a lesson never reveals an outcome unknown at made_at."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock, utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core import paths
from marketbrief.core.storage import append_jsonl, day_file
from score_predictions import is_late

MAX_WORDS = 60
DEFAULT_MAX = 40
FACT_FIELDS = ("id", "prediction_id", "ticker", "horizon_days", "as_of_date", "made_at", "direction",
               "confidence", "rationale", "evidence_ids", "call_prompt_version", "base_date", "base_close",
               "target_date", "target_close", "actual_return", "hit", "range_id", "range_target_date",
               "range_actual_close", "lo80", "lo50", "hi50", "hi80", "hit50", "hit80", "range_position",
               "settled_at", "available_from")
AGENT_FIELDS = ("prediction_id", "lesson", "prompt_version")

SETTLED_SQL = """
WITH o AS (SELECT DISTINCT ON (prediction_id) * FROM outcomes ORDER BY prediction_id, scored_at),
     p AS (SELECT DISTINCT ON (id) * FROM predictions ORDER BY id, made_at)
SELECT p.id, p.ticker, p.horizon_days, p.as_of_date, p.made_at, p.direction, p.confidence, p.rationale,
       p.evidence_ids, p.prompt_version, o.base_date, o.base_close, o.target_date, o.target_close,
       o.actual_return, o.hit, o.scored_at
FROM p JOIN o ON o.prediction_id = p.id
"""
RANGE_SQL = """
SELECT r.id, r.as_of_date, r.made_at, r.lo80, r.lo50, r.hi50, r.hi80, ro.target_date, ro.actual_close,
       ro.hit50, ro.hit80, ro.scored_at
FROM ranges_latest r
LEFT JOIN (SELECT DISTINCT ON (range_id) * FROM range_outcomes ORDER BY range_id, scored_at) ro ON ro.range_id = r.id
WHERE r.id = ?
"""


def _iso(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    t = pd.Timestamp(v)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).isoformat()


def _date(v) -> str | None:
    return None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)[:10]


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def position(y: float, lo80: float, lo50: float, hi50: float, hi80: float) -> str:
    """Where the close landed against the published bands."""
    if y < lo80:
        return "below_80"
    if y < lo50:
        return "in_80_below_50"
    if y <= hi50:
        return "in_50"
    if y <= hi80:
        return "in_80_above_50"
    return "above_80"


def settled(cfg: dict, con) -> dict[str, dict]:
    """prediction_id -> deterministic lesson facts, for every call with a stored outcome. A call whose
    range is open (published, not late, not scored) maps to None: it waits for the range."""
    out = {}
    for r in con.execute(SETTLED_SQL).df().itertuples(index=False):
        rec = {"id": f"lesson-{r.id}", "prediction_id": r.id, "ticker": r.ticker, "horizon_days": int(r.horizon_days),
               "as_of_date": _date(r.as_of_date), "made_at": _iso(r.made_at), "direction": r.direction,
               "confidence": _num(r.confidence), "rationale": r.rationale,
               "evidence_ids": [str(x) for x in (r.evidence_ids if r.evidence_ids is not None else [])],
               "call_prompt_version": r.prompt_version, "base_date": _date(r.base_date),
               "base_close": _num(r.base_close), "target_date": _date(r.target_date),
               "target_close": _num(r.target_close), "actual_return": _num(r.actual_return), "hit": bool(r.hit),
               "range_id": None, "range_target_date": None, "range_actual_close": None, "lo80": None, "lo50": None,
               "hi50": None, "hi80": None, "hit50": None, "hit80": None, "range_position": None,
               "settled_at": _iso(r.scored_at), "available_from": _iso(r.scored_at)}
        rg = con.execute(RANGE_SQL, [r.id]).df()
        if len(rg):
            g = rg.iloc[0]
            if g["scored_at"] is None or pd.isna(g["scored_at"]):
                if not is_late(cfg, g["as_of_date"], g["made_at"]):
                    out[r.id] = None        # its range is still open: wait so the lesson can cite it
                    continue
            else:
                y = float(g["actual_close"])
                rec.update({"range_id": g["id"], "range_target_date": _date(g["target_date"]), "range_actual_close": y,
                            "lo80": float(g["lo80"]), "lo50": float(g["lo50"]), "hi50": float(g["hi50"]),
                            "hi80": float(g["hi80"]), "hit50": bool(g["hit50"]), "hit80": bool(g["hit80"]),
                            "range_position": position(y, g["lo80"], g["lo50"], g["hi50"], g["hi80"]),
                            "available_from": max(pd.Timestamp(rec["settled_at"]),
                                                  pd.Timestamp(_iso(g["scored_at"]))).isoformat()})
        out[r.id] = rec
    return out


def stored_ids(con) -> set[str]:
    return set(con.execute("SELECT DISTINCT id FROM lessons").df()["id"])


def evidence(con, ids: list[str]) -> list[dict]:
    """What each cited id said (title/description), for the reflector to read; not stored."""
    if not ids:
        return []
    rows = con.execute("""
        SELECT * FROM (SELECT id, 'news' AS kind, title AS text, published_at AS at FROM news WHERE list_contains(?, id)
        UNION ALL SELECT id, 'filing', form || ': ' || coalesce(description, ''), accepted_at FROM filings
            WHERE list_contains(?, id)
        UNION ALL SELECT id, 'announcement', coalesce(category, '') || ': ' || coalesce(subject, ''), published_at
            FROM announcements WHERE list_contains(?, id)
        ) ORDER BY id, kind = 'announcement', kind = 'filing', "at", text""", [ids, ids, ids]).df()
    first: dict[str, dict] = {}   # per id the news row, else the filing, else the announcement (ORDER BY)
    for r in rows.itertuples(index=False):
        first.setdefault(r.id, {"id": r.id, "kind": r.kind, "text": r.text, "at": _iso(r.at)})
    return [first.get(i, {"id": i, "kind": "unknown", "text": None, "at": None}) for i in dict.fromkeys(ids)]


# ---------- validation ----------

ID_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[0-9:.+\-Z]+)?(?:-[A-Za-z0-9&.\-]+-\d+d)?\b")
NUM_RE = re.compile(r"(?<![\w.])([+\-−]?)(\d+(?:,\d{3})*(?:\.\d+)?)(\s*%)?")


PCT_KINDS = ("return", "confidence_pct")       # (and "distance from ...") only with a % sign
BOTH_KINDS = ("band", "rationale")              # with or without a % sign


def allowed_numbers(f: dict) -> list[tuple[float, str]]:
    """(value, what) pairs a lesson's text may cite, as absolute values."""
    vals = [(1.0, "horizon"), (5.0, "horizon"), (float(f["horizon_days"]), "horizon"),
            (50.0, "band"), (80.0, "band")]
    if f.get("actual_return") is not None:
        vals.append((abs(100 * f["actual_return"]), "return"))
    if f.get("confidence") is not None:
        vals += [(f["confidence"], "confidence"), (100 * f["confidence"], "confidence_pct")]
    for k in ("base_close", "target_close", "range_actual_close", "lo80", "lo50", "hi50", "hi80"):
        if f.get(k) is not None:
            vals.append((abs(f[k]), k))
    for num in NUM_RE.findall(ID_RE.sub(" ", f.get("rationale") or "")):   # numbers the stored rationale cites
        vals.append((float(num[1].replace(",", "")), "rationale"))
    y = f.get("range_actual_close")
    if y is not None:
        for k in ("lo80", "lo50", "hi50", "hi80"):
            if f.get(k):
                vals.append((abs(100 * (y / f[k] - 1)), f"distance from {k}"))
    return vals


def text_number_errors(text: str, f: dict) -> list[str]:
    """Numbers in the lesson that match nothing in the call or its outcome (dates, ids, the ticker skipped)."""
    t = text
    for x in [f["prediction_id"], *(f.get("evidence_ids") or [])]:
        t = t.replace(x, " ")
    t = ID_RE.sub(" ", t)
    t = re.sub(rf"(?<![\w]){re.escape(f['ticker'])}(?![\w])", " ", t)
    errs = []
    for sign, num, pct in NUM_RE.findall(t):
        # a percentage may only be a return, a % distance, confidence in %, a band name or a rationale
        # number; a plain number only a close, band edge, confidence, horizon or a rationale number
        vals = [(v, what) for v, what in allowed_numbers(f)
                if (what in PCT_KINDS or what.startswith("distance")) == bool(pct) or what in BOTH_KINDS]
        x = float(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        tol = 0.5 * 10 ** -dec + 1e-9
        matches = [what for v, what in vals if abs(x - v) <= tol]
        if not matches:
            errs.append(f"number {sign}{num}{pct.strip()} in the lesson matches nothing in the call or its outcome")
            continue
        if sign and pct and "return" in matches and f.get("actual_return") and \
                not any(abs(x - v) <= tol for v, what in vals if what.startswith("distance")):
            neg = sign in "-−"
            if neg != (f["actual_return"] < 0):
                errs.append(f"return {sign}{num}% has the wrong sign (actual_return {f['actual_return']:+.6f})")
    return errs


TIME_FIELDS = ("made_at", "settled_at", "available_from")


def same(key: str, a, b) -> bool:
    """A copied fact equals the stored one (numbers to 1e-9, timestamps as instants)."""
    if key in TIME_FIELDS and isinstance(a, str) and isinstance(b, str):
        try:
            return pd.Timestamp(a) == pd.Timestamp(b)
        except ValueError:
            return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(b, float) or isinstance(a, float):
        try:
            return a is not None and b is not None and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b


def validate_records(recs: list, facts: dict, stored: set[str]) -> tuple[list[dict], list[dict]]:
    """(valid full records, errors). facts = settled(); stored = lesson ids already in data/."""
    good, bad, seen = [], [], set()
    for i, rec in enumerate(recs, 1):
        if not isinstance(rec, dict):
            bad.append({"line": i, "prediction_id": None, "errors": ["not a JSON object"]})
            continue
        pid = rec.get("prediction_id")
        errs = [f"unknown field {k!r}" for k in rec if k not in AGENT_FIELDS and k not in FACT_FIELDS]
        for k in AGENT_FIELDS:
            if rec.get(k) in (None, ""):
                errs.append(f"missing {k}")
            elif not isinstance(rec[k], str):
                errs.append(f"{k} must be text")
        f = facts.get(pid) if isinstance(pid, str) else None
        if not isinstance(pid, str):
            pass
        elif pid not in facts:
            errs.append(f"prediction {pid!r} does not exist or is not settled (no stored outcome)")
        elif f is None:
            errs.append(f"prediction {pid!r} is settled but its range is still open; wait for it")
        if isinstance(pid, str):
            if f"lesson-{pid}" in stored:
                errs.append(f"a lesson for {pid} is already stored")
            if pid in seen:
                errs.append(f"duplicate lesson for {pid} in this file")
            seen.add(pid)
        text = rec.get("lesson")
        if isinstance(text, str):
            n = len(text.split())
            if n == 0 or n > MAX_WORDS:
                errs.append(f"lesson must be 1-{MAX_WORDS} words (got {n})")
        if f:
            for k in FACT_FIELDS:
                if k in rec and not same(k, rec[k], f[k]):
                    errs.append(f"{k} is {rec[k]!r} but the stored value is {f[k]!r}")
            if isinstance(text, str):
                errs += text_number_errors(text, f)
        if errs:
            bad.append({"line": i, "prediction_id": pid, "errors": errs})
        else:
            good.append({**f, "lesson": text.strip(), "prompt_version": rec["prompt_version"]})
    return good, bad


def read_file(path: Path) -> list:
    """One entry per non-empty line: the parsed object, or the raw text when it is not JSON
    (validate_records then rejects it as not a JSON object)."""
    if not path.exists():
        raise SystemExit(f"{path} does not exist")
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                recs.append(line)
    return recs


def check(cfg: dict, path: Path) -> tuple[list[dict], list[dict], int]:
    con = connect(cfg["market"])
    recs = read_file(path)
    good, bad = validate_records(recs, settled(cfg, con), stored_ids(con))
    return good, bad, len(recs)


# ---------- CLI ----------

def main() -> int:
    ap = market_arg(__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="write the facts of settled calls without a lesson")
    p.add_argument("--max", type=int, default=DEFAULT_MAX, help="at most N calls, newest settled first")
    p.add_argument("--out", type=Path, default=paths.ROOT / "work" / "lesson_facts.jsonl")
    for name in ("validate", "add"):
        q = sub.add_parser(name)
        q.add_argument("file", type=Path)
    args = ap.parse_args()
    cfg = require_market(args)
    market = cfg["market"]
    if args.cmd == "prepare":
        con = connect(market)
        facts, done = settled(cfg, con), stored_ids(con)
        todo = [f for pid, f in facts.items() if f is not None and f"lesson-{pid}" not in done]
        waiting = sorted(pid for pid, f in facts.items() if f is None and f"lesson-{pid}" not in done)
        todo.sort(key=lambda f: (f["settled_at"], f["prediction_id"]), reverse=True)
        todo = todo[:args.max]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps({**f, "evidence": evidence(con, f["evidence_ids"])}, default=str) + "\n"
                                    for f in todo), encoding="utf-8")
        print(json.dumps({"step": "lessons.prepare", "market": market, "facts": str(args.out), "n": len(todo),
                          "waiting_for_range": waiting, "already_stored": len(done), "now": utc_now()}, indent=2))
        return 0
    good, bad, n = check(cfg, args.file)
    if args.cmd == "validate" or bad:
        print(json.dumps({"step": f"lessons.{args.cmd}", "market": market, "file": str(args.file), "records": n,
                          "valid": len(good), "errors": bad, "appended": 0}, indent=2, default=str))
        return 1 if bad else 0
    now = utc_now()
    rows = [{**g, "written_at": now} for g in good]
    path = day_file(market, "lessons", utc_today())
    append_jsonl(path, rows)
    print(json.dumps({"step": "lessons.add", "market": market, "file": str(args.file), "records": n,
                      "valid": len(good), "errors": [], "appended": len(rows), "to": str(path)}, indent=2))
    return 0


# ---------- context pack ----------

def context_section(cfg: dict, con, per_ticker: int = 3, market_wide: int = 3) -> tuple[str, str]:
    """("Lessons from past calls", markdown): the latest `market_wide` lessons market-wide and each
    ticker's last `per_ticker`, using only lessons with available_from <= now (core.clock.clock(), so an
    MB_NOW replay sees only what was settled by then). Newest version of a lesson id wins."""
    now = clock()
    df = con.execute("""
        SELECT * FROM lessons WHERE available_from <= ?::TIMESTAMPTZ
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY written_at DESC) = 1
        ORDER BY available_from DESC, target_date DESC, id""", [now.isoformat()]).df()
    title = "Lessons from past calls (settled before now; anecdotes, n=1 each: weigh against the track record)"
    if df.empty:
        return title, "_none_\n"

    def table(rows: pd.DataFrame) -> str:
        out = ["| ticker | call | conf | result | return % | close vs range | lesson |", "|---|---|---|---|---|---|---|"]
        for r in rows.itertuples(index=False):
            ret = "" if pd.isna(r.actual_return) else f"{100 * r.actual_return:+.2f}"
            pos = "" if r.range_position is None or pd.isna(r.range_position) else r.range_position
            lesson = str(r.lesson).replace("|", "/").replace("\n", " ")
            out.append(f"| {r.ticker} | {r.prediction_id} {r.direction} | {r.confidence:.2f} | "
                       f"{'hit' if r.hit else 'miss'} | {ret} | {pos} | {lesson} |")
        return "\n".join(out) + "\n"

    tickers = [t for t in cfg["tickers"] if t in set(df["ticker"])]
    by_t = pd.concat([df[df["ticker"] == t].head(per_ticker) for t in tickers]) if tickers else df.head(0)
    body = (f"Most recent {market_wide}, market-wide:\n\n{table(df.head(market_wide))}\n"
            f"Last {per_ticker} per ticker:\n\n{table(by_t)}")
    return title, body


if __name__ == "__main__":
    sys.exit(main())
