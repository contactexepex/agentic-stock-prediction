"""Weekly spot-check sample for the judge (routine/PROMPT.md; CLAUDE.md "Judging every change").

    python scripts/spotcheck.py --market M [--if-due] [--week 2026-W40]

Daily runs are gated by validate.py; once a week the judge reviews a small sample of the
previous ISO week's daily output for what scripts cannot see (reasons that do not match their
evidence, wrong claims). The sample is deterministic, seeded by market and ISO week:
SAMPLE_CALLS forecasts (with their evidence rows and outcome), SAMPLE_REPORTS filled report, SAMPLE_LESSONS
reflector lesson and SAMPLE_CLAIMS claim-checker claims (with their event's latest status).
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

from marketbrief.constants.pipeline_messages import MSG_WEEK_MUST_LOOK_LIKE_2026_W40
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.pipeline.review.helpers import previous_week, week_bounds

SAMPLE_CALLS, SAMPLE_REPORTS, SAMPLE_LESSONS, SAMPLE_CLAIMS = 2, 1, 1, 2
CHECKLIST = [
    "Each call's rationale matches what its cited evidence ids actually say (headline/summary), "
    "and every cited id exists and was public before the call's made_at (no look-ahead).",
    "Every number in the sampled report's narrative is real: it is in that day's stored data "
    "(DuckDB) or the report's own script-written tables.",
    "Every factual claim in the report narrative is true and supported by the id it cites; no "
    "background from memory, no cause the cited headline does not state.",
    "Nothing in the sampled output uses information published after it was written.",
    "Each sampled lesson states what its settled call and outcome show (lessons.py validate checks only ids and "
    "numbers): no cause the call's evidence does not support.",
    "Each sampled claim's quote says what its fields (predicate, value, stance) record, from the cited source; the "
    "event's verification status follows from its claims and sources.",
]


def seed(market: str, week: str) -> int:
    """The sampling seed of a market and ISO week."""
    return int.from_bytes(f"{market}:{week}".encode(), "big") % (2**32)


def done(con, week: str) -> bool:
    """True when a spot-check verdict for the week is already stored."""
    return bool(
        con.execute(
            "SELECT count(*) FROM judgments WHERE agent = 'spotcheck' AND id LIKE ?", [f"%-spotcheck-{week}-%"]
        ).fetchone()[0]
    )


def evidence_rows(con, ids: list[str]) -> list[dict]:
    """The stored rows of the evidence ids a sampled call cites."""
    out = []
    for kind, sql in (
        (
            "news",
            "SELECT id, title AS text, url, coalesce(published_at, first_seen_at) AS public_at FROM news WHERE id IN ?",
        ),
        (
            "filings",
            "SELECT id, form || ' ' || coalesce(description, '') AS text, url, "
            "coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) AS public_at FROM filings WHERE id IN ?",
        ),
        (
            "announcements",
            "SELECT id, coalesce(category, '') || ': ' || coalesce(subject, '') AS text, url, "
            "coalesce(published_at, first_seen_at) AS public_at FROM announcements WHERE id IN ?",
        ),
    ):
        for row in con.execute(f"SELECT DISTINCT ON (id) * FROM ({sql}) ORDER BY ALL", [ids]).df().to_dict("records"):
            out.append(
                {
                    "kind": kind,
                    **{
                        key: (
                            str(value)
                            if value is not None and not (isinstance(value, float) and pd.isna(value))
                            else None
                        )
                        for key, value in row.items()
                    },
                }
            )
    enr = (
        con.execute("SELECT id, summary, sentiment, materiality FROM enriched_latest WHERE id IN ?", [ids]).df()
        if ids
        else pd.DataFrame()
    )
    row_by_id = {row["id"]: row for row in enr.to_dict("records")}
    for row in out:
        if row["id"] in row_by_id:
            row["enriched_summary"] = row_by_id[row["id"]]["summary"]
    found = {row["id"] for row in out}
    out += [{"kind": "missing", "id": index, "text": None} for index in ids if index not in found]
    return out


def sample(cfg: dict, week: str) -> dict:
    """The deterministic sample of the week's forecasts and filled report."""
    market = cfg["market"]
    con = connect(market)
    start, end = week_bounds(week)
    rng = random.Random(seed(market, week))
    calls = con.execute(
        "SELECT DISTINCT ON (id) * FROM predictions WHERE CAST(made_at AS DATE) BETWEEN ? AND ? "
        "ORDER BY id, made_at DESC",
        [start, end],
    ).df()
    picked = rng.sample(range(len(calls)), min(SAMPLE_CALLS, len(calls))) if len(calls) else []
    out_calls = []
    for index in sorted(picked):
        call = calls.iloc[index]
        ids = list(call["evidence_ids"]) if call["evidence_ids"] is not None else []
        outcome = (
            con.execute("SELECT * FROM outcomes WHERE prediction_id = ? ORDER BY scored_at DESC LIMIT 1", [call["id"]])
            .df()
            .to_dict("records")
        )
        out_calls.append(
            {
                "id": call["id"],
                "made_at": str(call["made_at"]),
                "ticker": call["ticker"],
                "horizon_days": int(call["horizon_days"]),
                "direction": call["direction"],
                "confidence": float(call["confidence"]),
                "rationale": call["rationale"],
                "evidence": evidence_rows(con, ids),
                "outcome": {key: str(value) for key, value in outcome[0].items()} if outcome else None,
            }
        )
    reports = []
    for day in pd.date_range(start, end):
        report_path = paths.ROOT / "reports" / market / f"{day.date()}.md"
        if report_path.exists() and "<!-- AGENT:" not in report_path.read_text(encoding="utf-8"):
            reports.append(report_path.relative_to(paths.ROOT).as_posix())
    rep = sorted(rng.sample(reports, min(SAMPLE_REPORTS, len(reports)))) if reports else []
    lessons = week_rows(con, LESSONS_SQL, start, end)   # issues #34 and #39: lessons and claims are sampled too
    claims = week_rows(con, CLAIMS_SQL, start, end)
    return {"calls": out_calls, "reports": rep, "n_calls_in_week": int(len(calls)), "n_reports_in_week": len(reports),
            "lessons": picks(rng, lessons, SAMPLE_LESSONS), "n_lessons_in_week": len(lessons),
            "claims": picks(rng, claims, SAMPLE_CLAIMS), "n_claims_in_week": len(claims)}


LESSONS_SQL = ("SELECT DISTINCT ON (id) id, prediction_id, ticker, direction, confidence, hit, actual_return, "
               "label_basis, rationale, lesson, written_at FROM lessons "
               "WHERE CAST(written_at AS DATE) BETWEEN ? AND ? ORDER BY id, written_at DESC")
CLAIMS_SQL = ("SELECT c.*, v.status AS event_status FROM (SELECT DISTINCT ON (id) * FROM news_claims "
              "WHERE CAST(extracted_at AS DATE) BETWEEN ? AND ? ORDER BY id, extracted_at DESC) c "
              "LEFT JOIN (SELECT DISTINCT ON (cluster_id) cluster_id, status FROM news_verified "
              "WHERE level = 'cluster' ORDER BY cluster_id, as_of DESC) v USING (cluster_id) ORDER BY c.id")


def week_rows(con, sql: str, start, end) -> list[dict]:
    """The rows of a query over the week, as plain strings."""
    frame = con.execute(sql, [start, end]).df()
    return [{key: None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
             for key, value in row.items()} for row in frame.to_dict("records")]


def picks(rng: random.Random, rows: list[dict], count: int) -> list[dict]:
    """A deterministic sample of rows, in their order."""
    return [rows[index] for index in sorted(rng.sample(range(len(rows)), min(count, len(rows))))] if rows else []


def main() -> int:
    """Print the weekly spot-check sample, checklist and judgments record."""
    parser = market_arg(__doc__)
    parser.add_argument("--if-due", action="store_true", help="do nothing if this week's spot-check verdict is stored")
    parser.add_argument("--week", help="ISO week to sample, e.g. 2026-W40 (default: the previous ISO week)")
    args = parser.parse_args()
    cfg = require_market(args)
    week = args.week or previous_week(utc_today())
    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise SystemExit(MSG_WEEK_MUST_LOOK_LIKE_2026_W40.format(week=week))
    con = connect(cfg["market"])
    if args.if_due and done(con, week):
        print(json.dumps({"step": "spotcheck", "market": cfg["market"], "week": week, "due": False}))
        return 0
    sampled = sample(cfg, week)
    today, now = utc_today(), utc_now()
    empty = not any(sampled[key] for key in ("calls", "reports", "lessons", "claims"))
    print(
        json.dumps(
            {
                "step": "spotcheck",
                "market": cfg["market"],
                "week": week,
                "due": True,
                "empty": empty,
                "sample": sampled,
                "checklist": CHECKLIST,
                "record": {
                    "id": f"{today}-spotcheck-{week}-1-{now[11:19].replace(':', '')}",
                    "run_date": str(today),
                    "agent": "spotcheck",
                    "round": 1,
                    "verdict": "SKIP" if empty else "<PASS|FAIL>",
                    "summary": "nothing to sample in " + week if empty else "<max 40 words>",
                    "dropped": None,
                    "recorded_at": now,
                },
                "append_to": f"data/{cfg['market']}/judgments/{today:%Y}/{today:%m}/{today}.jsonl",
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
