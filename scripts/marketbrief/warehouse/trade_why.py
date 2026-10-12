"""Why each paper trade is going the way it is (UX3, docs/ux/paper_portfolio_redesign.md v3; owner approval
2026-10-12), as of the cut-off. Research only: a paper trade is a record, never an order.

- `why` of an open strategy trade: its ticker's latest intraday check by the cut-off on or after the trade's entry
  session (WS5's attribution: the move since the session's open, the benchmark's move, the sector's move, the stock's
  beta and the residual = its own move) and that check's deviation-explainer note when one was written by the
  cut-off. Null without such a check.
- `why` of a closed strategy trade: B2's automatic reason (F1.10: move, market, sector, news and company parts, main
  reason code) and the newest end-of-day AI reason (trade_reasons_ai) written by the cut-off.
- `prediction`: the prediction behind a trade (direction, chance of a rise, the AI trader's own words).
- `sessions` of an open trade: of its hold's k + 1 market sessions, those up to its latest price's session.
- `learning`: what the system learns, as stored: the reflector's lessons (only the AI forecaster reads them), the
  newest weekly research review and the next one's time, and why the rule strategies traded or not on the newest
  session (their best chance of a rise against their bar).
- Lifecycle additions (B12's rm.lifecycle): every check of the ticker in the page's trade window with its
  attribution, the deviation notes and the lessons on the page's AI forecaster predictions."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from marketbrief.core import calendar
from marketbrief.lab import reads as lab_reads
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext

PCT_DIGITS = 2
SOURCE_CHECK, SOURCE_SETTLEMENT = "intraday_check", "settlement"
WHY_KEYS = (
    "source", "check_at", "session_date", "move_pct", "market_pct", "market_pull_pct", "sector_pct", "own_pct",
    "news_pct", "company_pct", "beta", "sector_source", "reason_code", "note", "ai_reason",
)  # fmt: skip
LESSON_READER = "ai.combined.opus.v1"  # the forecaster, the only agent whose input carries the lessons
REVIEW_ZONE, REVIEW_WEEKDAY, REVIEW_TIME = "America/New_York", 4, (19, 30)  # routine/WEEKLY_PROMPT.md: Friday 19:30
FAMILY_RULE = "rule"
CHECKS_SQL = """
SELECT id, ticker, CAST(session_date AS VARCHAR) AS session_date, check_at, ret_since_open, bench_ret, sector_ret,
       sector_source, beta, residual
FROM (SELECT DISTINCT ON (id) * FROM intraday_checks WHERE computed_at <= ? AND check_at <= ? ORDER BY id, computed_at)
ORDER BY ticker, check_at, id
"""
NOTES_SQL = """
SELECT ticker, check_at, text, cited_ids
FROM (SELECT DISTINCT ON (check_row_id) * FROM intraday_explanations WHERE created_at <= ?
      ORDER BY check_row_id, created_at, id)
ORDER BY ticker, check_at
"""


def pct(value) -> float | None:
    value = json_safe_float(value)
    return None if value is None else round(value, PCT_DIGITS)


def fraction_pct(value) -> float | None:
    value = json_safe_float(value)
    return None if value is None else round(value * 100, PCT_DIGITS)


def market_pull(bench_ret, beta) -> float | None:
    """The market's part of the stock's move, in percent: the benchmark's move times the stock's beta, from the stored
    fractions (rounded once, at the end)."""
    bench_ret, beta = json_safe_float(bench_ret), json_safe_float(beta)
    return None if bench_ret is None or beta is None else fraction_pct(bench_ret * beta)


def iso_z(value) -> str | None:
    return rm_common.iso_z(value)


def checks_by_ticker(ctx: BuildContext) -> dict[str, list[dict]]:
    """Every intraday check row stored by the cut-off (first computation of each id), per collected ticker, oldest
    first, with its note (the deviation-explainer's text written by the cut-off) or null."""

    def compute() -> dict[str, list[dict]]:
        cutoff = ctx.cutoff_time
        notes = {}
        for row in lab_reads.records(ctx.con.execute(NOTES_SQL, [cutoff]).df()):
            notes[(row["ticker"], iso_z(row["check_at"]))] = row["text"]
        out: dict[str, list[dict]] = {}
        for row in lab_reads.records(ctx.con.execute(CHECKS_SQL, [cutoff, cutoff]).df()):
            if row["ticker"] not in ctx.collected:
                continue
            at = iso_z(row["check_at"])
            out.setdefault(row["ticker"], []).append({
                "check_at": at,
                "session_date": str(row["session_date"])[:10],
                "move_pct": fraction_pct(row["ret_since_open"]),
                "market_pct": fraction_pct(row["bench_ret"]),
                "market_pull_pct": market_pull(row["bench_ret"], row["beta"]),
                "sector_pct": fraction_pct(row["sector_ret"]),
                "own_pct": fraction_pct(row["residual"]),
                "beta": json_safe_float(row["beta"]),
                "sector_source": row.get("sector_source"),
                "note": notes.get((row["ticker"], at)),
            })  # fmt: skip
        return out

    return ctx.shared("ux3_checks_by_ticker", compute)


def why_row(**fields) -> dict:
    return {key: fields.get(key) for key in WHY_KEYS}


def open_why(ctx: BuildContext, ticker: str, entry_date: str | None) -> dict | None:
    """The latest check of the ticker by the cut-off, when it is of the trade's entry session or later."""
    rows = checks_by_ticker(ctx).get(ticker) or []
    if not rows or entry_date is None or rows[-1]["session_date"] < entry_date:
        return None
    return why_row(source=SOURCE_CHECK, **rows[-1])


def held_sessions(ctx: BuildContext, trade: dict) -> dict | None:
    """How far an open trade is towards its sale, on the market calendar: of the k + 1 sessions from the entry session
    D to the exit session, those up to its latest price's session (none while its price is pending)."""
    k, exit_day = trade.get("horizon_days"), trade.get("exit_date")
    if not k or not exit_day:
        return None
    days, day = [], calendar.prev_session(ctx.cfg, date.fromisoformat(exit_day))
    for _ in range(k + 1):
        days.append(day.isoformat())
        day = calendar.prev_session(ctx.cfg, day, include=False)
    last = trade.get("last_price_date")
    held = 0 if trade.get("price_pending") or not last else sum(1 for d in days if d <= last)
    return {"held": held, "total": len(days)}


def ai_reasons(ctx: BuildContext) -> dict[str, str]:
    """trade_id -> the newest end-of-day AI reason written by the cut-off."""

    def compute() -> dict[str, str]:
        out = {}
        for row in lab_reads.stored(ctx.con, "trade_reasons_ai", "created_at", ctx.cutoff_time):
            out[row["trade_id"]] = row["text"]
        return out

    return ctx.shared("ux3_ai_reasons", compute)


def settled_why(ctx: BuildContext, row: dict) -> dict:
    """B2's automatic reason of a settlement and the newest end-of-day AI reason of its trade."""
    return why_row(
        source=SOURCE_SETTLEMENT,
        session_date=None if row.get("exit_date_actual") is None else str(row["exit_date_actual"])[:10],
        move_pct=pct(row.get("move_pct")),
        market_pct=pct(row.get("market_pct")),
        sector_pct=pct(row.get("sector_pct")),
        news_pct=pct(row.get("news_pct")),
        company_pct=pct(row.get("company_pct")),
        reason_code=row.get("reason_code"),
        ai_reason=ai_reasons(ctx).get(row["trade_id"]),
    )


def predictions(ctx: BuildContext) -> dict[str, dict]:
    """prediction id -> the strategy prediction made by the cut-off (B2's reads: the first row of each id)."""
    return ctx.shared(
        "ux3_predictions", lambda: {row["id"]: row for row in lab_reads.predictions(ctx.con, ctx.cutoff_time)}
    )


def prediction_fields(ctx: BuildContext, prediction_id: str | None) -> dict:
    """direction, prob_up and the AI trader's reason of the trade's prediction (nulls when unknown)."""
    row = predictions(ctx).get(prediction_id or "") or {}
    return {
        "direction": row.get("direction"),
        "prob_up": json_safe_float(row.get("prob_up")),
        "reason": row.get("reason"),
    }


def next_review_at(cutoff: datetime) -> str:
    """The next weekly research review (Friday 19:30 New York time) after the cut-off, as ISO UTC."""
    zone = ZoneInfo(REVIEW_ZONE)
    local = cutoff.astimezone(zone)
    day = local.date() + timedelta(days=(REVIEW_WEEKDAY - local.weekday()) % 7)
    at = datetime(day.year, day.month, day.day, *REVIEW_TIME, tzinfo=zone)
    if at <= local:
        at += timedelta(days=7)
    return iso_z(at)


def findings_of(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def latest_review(ctx: BuildContext) -> dict | None:
    rows = [row for row in lab_reads.stored(ctx.con, "research_reviews", "written_at", ctx.cutoff_time)
            if row.get("market") == ctx.market]  # fmt: skip
    if not rows:
        return None
    row = rows[-1]
    findings, proposals = findings_of(row.get("findings")), findings_of(row.get("proposals"))
    first = findings[0].get("text") if findings and isinstance(findings[0], dict) else None
    return {
        "id": row["id"], "iso_week": row.get("iso_week"), "written_at": iso_z(row.get("written_at")),
        "first_finding": first, "findings": len(findings), "proposals": len(proposals),
    }  # fmt: skip


def lessons(ctx: BuildContext) -> list[dict]:
    """The reflector's lessons usable by the cut-off (written and available), oldest first."""

    def compute() -> list[dict]:
        frame = ctx.con.execute(
            "SELECT id, prediction_id, ticker, horizon_days, lesson, written_at, available_from FROM lessons "
            "WHERE written_at <= ? AND available_from <= ? ORDER BY written_at, id",
            [ctx.cutoff_time, ctx.cutoff_time],
        ).df()
        return [
            {"id": row["id"], "prediction_id": row["prediction_id"], "ticker": row["ticker"],
             "horizon_days": row["horizon_days"], "lesson": row["lesson"], "written_at": iso_z(row["written_at"])}
            for row in lab_reads.records(frame)
        ]  # fmt: skip

    return ctx.shared("ux3_lessons", compute)


def rule_today(ctx: BuildContext) -> dict | None:
    """The rule strategies on the newest session they predicted by the cut-off: their best chance of a rise, the
    lowest bar among them and how many of their predictions cleared it (each one is a paper trade)."""
    rows = [
        row for row in predictions(ctx).values() if row.get("family") == FAMILY_RULE and row["ticker"] in ctx.collected
    ]
    if not rows:
        return None
    session = max(str(row["session_date"])[:10] for row in rows)
    mine = [row for row in rows if str(row["session_date"])[:10] == session]
    probs = [json_safe_float(row.get("prob_up")) for row in mine]
    bars = [json_safe_float(row.get("threshold")) for row in mine]
    return {
        "session_date": session,
        "predictions": len(mine),
        "qualifying": sum(1 for row in mine if row.get("qualifies")),
        "best_prob_up": max((p for p in probs if p is not None), default=None),
        "bar": min((b for b in bars if b is not None), default=None),
    }


def learning(ctx: BuildContext) -> dict:
    """rm.portfolio `_`'s learning block (see the module docstring)."""
    stored = lessons(ctx)
    return {
        "lessons": {"count": len(stored), "newest": stored[-1] if stored else None, "read_by": LESSON_READER},
        "review": latest_review(ctx),
        "next_review_at": next_review_at(ctx.cutoff_time),
        "rule_today": rule_today(ctx),
    }


def lifecycle_additions(ctx: BuildContext, ticker: str, day: str, page: dict) -> dict:
    """B12's rm.lifecycle `<ticker>:<day>` additions: the ticker's checks from the entry session `day` to the
    page's latest exit (with attribution and note), the deviation notes among them, the lessons on the page's
    AI forecaster predictions and the AI traders' own words for the page's predictions."""
    exits = [str(row.get("exit_date"))[:10] for row in page.get("predictions", []) if row.get("exit_date")]
    last = max(exits, default=day)
    checks = [row for row in checks_by_ticker(ctx).get(ticker, []) if day <= row["session_date"] <= last]
    forecaster = {row["id"].split(":", 1)[1] for row in page.get("predictions", [])
                  if row.get("strategy_id") == LESSON_READER and ":" in row["id"]}  # fmt: skip
    return {
        "checks_attribution": [{key: row[key] for key in row if key != "note"} for row in checks],
        "deviation_notes": [
            {"check_at": row["check_at"], "session_date": row["session_date"], "text": row["note"]}
            for row in checks
            if row["note"]
        ],  # fmt: skip
        "lessons": [row for row in lessons(ctx) if row["prediction_id"] in forecaster],
        "prediction_reasons": [
            {"prediction_id": row["id"], "reason": predictions(ctx)[row["id"]]["reason"]}
            for row in page.get("predictions", [])
            if (predictions(ctx).get(row["id"]) or {}).get("reason")
        ],
    }
