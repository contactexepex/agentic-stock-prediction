#!/usr/bin/env python3
"""Weekly spot-check sample for the judge (routine/PROMPT.md; CLAUDE.md "Judging every change").

    python scripts/spotcheck.py --market M [--if-due] [--week 2026-W40]

Daily runs are gated by validate.py; once a week the judge reviews a small sample of the
previous ISO week's daily output for what scripts cannot see (reasons that do not match their
evidence, wrong claims). The sample is deterministic, seeded by market and ISO week:
SAMPLE_CALLS forecasts (with their evidence rows and outcome) and SAMPLE_REPORTS filled report.
Prints JSON with the sample, the review checklist and the judgments record to append
(`agent` "spotcheck", id `<today>-spotcheck-<week>-<round>-<HHMMSS>`).
With --if-due it prints `due: false` and nothing else when a spot-check verdict for that week is
already stored in data/<market>/judgments/ (so a missed first trading day is caught up later)."""
from __future__ import annotations

import json
import random
import re
import sys

import pandas as pd

from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core import paths
from review import previous_week, week_bounds

SAMPLE_CALLS, SAMPLE_REPORTS = 2, 1
CHECKLIST = [
    "Each call's rationale matches what its cited evidence ids actually say (headline/summary), "
    "and every cited id exists and was public before the call's made_at (no look-ahead).",
    "Every number in the sampled report's narrative is real: it is in that day's stored data "
    "(DuckDB) or the report's own script-written tables.",
    "Every factual claim in the report narrative is true and supported by the id it cites; no "
    "background from memory, no cause the cited headline does not state.",
    "Nothing in the sampled output uses information published after it was written.",
]


def seed(market: str, week: str) -> int:
    return int.from_bytes(f"{market}:{week}".encode(), "big") % (2 ** 32)


def done(con, week: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM judgments WHERE agent = 'spotcheck' AND id LIKE ?",
                            [f"%-spotcheck-{week}-%"]).fetchone()[0])


def evidence_rows(con, ids: list[str]) -> list[dict]:
    out = []
    for kind, sql in (
        ("news", "SELECT id, title AS text, url, coalesce(published_at, first_seen_at) AS public_at FROM news WHERE id IN ?"),
        ("filings", "SELECT id, form || ' ' || coalesce(description, '') AS text, url, "
                    "coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) AS public_at FROM filings WHERE id IN ?"),
        ("announcements", "SELECT id, coalesce(category, '') || ': ' || coalesce(subject, '') AS text, url, "
                          "coalesce(published_at, first_seen_at) AS public_at FROM announcements WHERE id IN ?"),
    ):
        for r in con.execute(f"SELECT DISTINCT ON (id) * FROM ({sql}) ORDER BY ALL", [ids]).df().to_dict("records"):
            out.append({"kind": kind, **{k: (str(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None)
                                         for k, v in r.items()}})
    enr = con.execute("SELECT id, summary, sentiment, materiality FROM enriched_latest WHERE id IN ?", [ids]).df() \
        if ids else pd.DataFrame()
    by = {r["id"]: r for r in enr.to_dict("records")}
    for r in out:
        if r["id"] in by:
            r["enriched_summary"] = by[r["id"]]["summary"]
    found = {r["id"] for r in out}
    out += [{"kind": "missing", "id": i, "text": None} for i in ids if i not in found]
    return out


def sample(cfg: dict, week: str) -> dict:
    market = cfg["market"]
    con = connect(market)
    start, end = week_bounds(week)
    rng = random.Random(seed(market, week))
    calls = con.execute("SELECT DISTINCT ON (id) * FROM predictions WHERE CAST(made_at AS DATE) BETWEEN ? AND ? "
                        "ORDER BY id, made_at DESC", [start, end]).df()
    picked = rng.sample(range(len(calls)), min(SAMPLE_CALLS, len(calls))) if len(calls) else []
    out_calls = []
    for i in sorted(picked):
        c = calls.iloc[i]
        ids = list(c["evidence_ids"]) if c["evidence_ids"] is not None else []
        outcome = con.execute("SELECT * FROM outcomes WHERE prediction_id = ? ORDER BY scored_at DESC LIMIT 1",
                              [c["id"]]).df().to_dict("records")
        out_calls.append({
            "id": c["id"], "made_at": str(c["made_at"]), "ticker": c["ticker"], "horizon_days": int(c["horizon_days"]),
            "direction": c["direction"], "confidence": float(c["confidence"]), "rationale": c["rationale"],
            "evidence": evidence_rows(con, ids),
            "outcome": {k: str(v) for k, v in outcome[0].items()} if outcome else None})
    reports = []
    for d in pd.date_range(start, end):
        p = paths.ROOT / "reports" / market / f"{d.date()}.md"
        if p.exists() and "<!-- AGENT:" not in p.read_text(encoding="utf-8"):
            reports.append(p.relative_to(paths.ROOT).as_posix())
    rep = sorted(rng.sample(reports, min(SAMPLE_REPORTS, len(reports)))) if reports else []
    return {"calls": out_calls, "reports": rep, "n_calls_in_week": int(len(calls)), "n_reports_in_week": len(reports)}


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--if-due", action="store_true", help="do nothing if this week's spot-check verdict is stored")
    ap.add_argument("--week", help="ISO week to sample, e.g. 2026-W40 (default: the previous ISO week)")
    args = ap.parse_args()
    cfg = require_market(args)
    week = args.week or previous_week(utc_today())
    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise SystemExit(f"--week must look like 2026-W40 (got {week!r})")
    con = connect(cfg["market"])
    if args.if_due and done(con, week):
        print(json.dumps({"step": "spotcheck", "market": cfg["market"], "week": week, "due": False}))
        return 0
    s = sample(cfg, week)
    today, now = utc_today(), utc_now()
    empty = not s["calls"] and not s["reports"]
    print(json.dumps({
        "step": "spotcheck", "market": cfg["market"], "week": week, "due": True, "empty": empty,
        "sample": s, "checklist": CHECKLIST,
        "record": {"id": f"{today}-spotcheck-{week}-1-{now[11:19].replace(':', '')}", "run_date": str(today),
                   "agent": "spotcheck", "round": 1,
                   "verdict": "SKIP" if empty else "<PASS|FAIL>",
                   "summary": "nothing to sample in " + week if empty else "<max 40 words>",
                   "dropped": None, "recorded_at": now},
        "append_to": f"data/{cfg['market']}/judgments/{today:%Y}/{today:%m}/{today}.jsonl",
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
