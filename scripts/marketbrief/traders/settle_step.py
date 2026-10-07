"""The post-close settlement step (docs/SPEC.md F6.1): every paper trade whose exit session has closed is settled
through session B2's engine interface (`marketbrief.contracts.protocol.settle`), never computed here.

Due by the run's clock: accuracy view = each qualifying strategy prediction (`qualifies` true) with exit_date on or
before the session, trade id `acc:<prediction_id>`; head-to-head view = each `picked` head_to_head_picks row of such a
prediction, trade id `h2h:<pick_rule>:<prediction_id>`. A trade id that already has a settlement row is skipped, so the
step is re-runnable. The engine returns one paper_trades_settled row, or None while it cannot settle yet (e.g. the
exit close is not stored: it settles on the next stored close, flagged exit_delayed). Rows go to the day file of
settled_at."""
from __future__ import annotations

from datetime import date, datetime

from marketbrief.contracts import protocol
from marketbrief.core.storage import append_jsonl, day_file

PREDICTIONS_SQL = """
SELECT DISTINCT ON (id) * FROM strategy_predictions
WHERE qualifies AND exit_date <= ?::DATE AND made_at <= ?::TIMESTAMPTZ ORDER BY id, made_at"""
PICKS_SQL = """
SELECT DISTINCT ON (id) * FROM head_to_head_picks
WHERE status = 'picked' AND made_at <= ?::TIMESTAMPTZ ORDER BY id, made_at"""
SETTLED_SQL = "SELECT DISTINCT trade_id FROM paper_trades_settled"


class EngineUnavailableError(RuntimeError):
    """Session B2's settlement engine is not built yet."""


def records(con, sql: str, params: list) -> list[dict]:
    """Rows as dicts (DuckDB types: dates, timestamps, lists)."""
    cursor = con.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def due(con, session: date, now: datetime) -> list[tuple[dict, str, dict | None, str]]:
    """(prediction, view, pick or None, trade id) of every unsettled trade whose exit is on or before `session`."""
    done = {row[0] for row in con.execute(SETTLED_SQL).fetchall()}
    preds = {row["id"]: row for row in records(con, PREDICTIONS_SQL, [session.isoformat(), now.isoformat()])}
    out = [(pred, "accuracy", None, f"acc:{pid}") for pid, pred in sorted(preds.items())]
    for pick in records(con, PICKS_SQL, [now.isoformat()]):
        pred = preds.get(pick["prediction_id"])
        if pred is not None:
            out.append((pred, "head_to_head", pick, f"h2h:{pick['pick_rule']}:{pred['id']}"))
    return [item for item in out if item[3] not in done]


def settle_due(cfg: dict, con, session: date, now: datetime) -> dict:
    """Settle every due trade through the engine and append the rows; a summary for the step's JSON."""
    rows, pending = [], []
    for pred, view, pick, trade_id in due(con, session, now):
        try:
            row = protocol.settle(pred, view, pick, cfg, now)
        except NotImplementedError as error:
            raise EngineUnavailableError(f"settlement engine not available yet ({error})") from error
        if row is None:
            pending.append(trade_id)
        else:
            rows.append(row)
    path = None
    if rows:
        path = day_file(cfg["market"], "paper_trades_settled", now.date())
        append_jsonl(path, rows)
    return {"session_date": str(session), "settled": len(rows), "pending": pending,
            "to": str(path) if path else None}
