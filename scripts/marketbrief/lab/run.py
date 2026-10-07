"""The lab's daily steps on stored data (scripts/lab.py): predict (pre-open: rule strategies and baselines),
pick (pre-open, after every family has predicted: the head-to-head picks and the cost-viable rows); settle is in
settle_run.py. Each appends only new ids (append-only, CLAUDE.md data rules) and returns a summary."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.constants.kinds import (KIND_COST_VIEWS, KIND_HEAD_TO_HEAD_PICKS, KIND_STRATEGY_ABSTENTIONS,
                                         KIND_STRATEGY_PREDICTIONS)
from marketbrief.core.calendar import session_open_utc
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.lab import picks as lab_picks
from marketbrief.lab import reads, registry
from marketbrief.lab.constants import LAB_VERSION, MSG_NO_EURUSD, MSG_PICK_TOO_LATE
from marketbrief.lab.cost_views import KIND_PICK, KIND_PREDICTION, viability_row
from marketbrief.lab.settle import as_date
from marketbrief.lab.timing import entry_session
from marketbrief.utils.timefmt import as_utc_timestamp


def append_new(market: str, kind: str, rows: list[dict], time_column: str, known: set[str]) -> int:
    """Append the rows whose id is new, each to the day file of its time column (UTC date)."""
    written = 0
    for row in rows:
        if row["id"] in known:
            continue
        known.add(row["id"])
        written += append_jsonl(day_file(market, kind, as_utc_timestamp(row[time_column]).date()), [row])
    return written


def pick_day(con, cfg: dict, now: datetime, specs: list[dict], session_date: str) -> dict:
    """Write the head-to-head picks of every company predicted for `session_date` (D), and the cost-viable rows
    (decision 51) of every prediction that would trade and every pick. Refused at or after D's open (F1.8: a
    later pick could rank strategies on settlements stored after the open)."""
    if now >= session_open_utc(cfg, as_date(session_date)):
        return {"ok": False, "message": MSG_PICK_TOO_LATE.format(session=session_date, now=now.isoformat())}
    preds = [p for p in reads.predictions(con, now) if str(p["session_date"]) == session_date]
    trades = reads.settlements(con, now)
    data = reads.market_data(con, cfg, now, [], as_date(session_date) - timedelta(days=10))
    eurusd = data.eurusd_on(as_date(session_date))
    if data.rates.get("order_fee_eur") and eurusd is None:
        return {"ok": False, "message": MSG_NO_EURUSD.format(when=now.isoformat())}
    rows = []
    for ticker in sorted({p["ticker"] for p in preds}):
        sample = min((p for p in preds if p["ticker"] == ticker), key=lambda p: p["id"])
        for family in registry.head_to_head_families():
            context = {"market": cfg["market"], "rate": data.rates, "eurusd": eurusd,
                       "family_ids": [s["id"] for s in specs if s["family"] == family], "made_at": now.isoformat(),
                       "as_of_date": sample["as_of_date"], "session_date": session_date,
                       "base_close": sample["base_close"], "amount": sample["amount"], "currency": sample["currency"],
                       "method_version": LAB_VERSION}
            rows += lab_picks.pick_rows(ticker, family, context, preds, trades)
    known = {p["id"] for p in reads.picks(con, now)}
    written = append_new(cfg["market"], KIND_HEAD_TO_HEAD_PICKS, rows, "made_at", known)
    by_id = {p["id"]: p for p in preds}
    views = [viability_row(KIND_PREDICTION, p["id"], p, data.rates, eurusd, now) for p in preds if p.get("qualifies")]
    views += [viability_row(KIND_PICK, r["id"], by_id[r["prediction_id"]], data.rates, eurusd, now)
              for r in rows if r["status"] == "picked"]
    known_views = {r["id"] for r in reads.stored(con, KIND_COST_VIEWS, "computed_at", now)}
    return {"session_date": session_date, "picks": len(rows), "written": written,
            "no_candidate": sum(r["status"] == "no_candidate" for r in rows),
            "cost_views": append_new(cfg["market"], KIND_COST_VIEWS, views, "computed_at", known_views),
            "cost_viable": sum(bool(v["cost_viable"]) for v in views if v["record_kind"] == KIND_PREDICTION)}


def write_predictions(cfg: dict, now: datetime, preds: list[dict], abstentions: list[dict], con) -> dict:
    """Append new prediction and abstention rows (abstention ids skipped when already stored)."""
    known = {p["id"] for p in reads.predictions(con, now)}
    known_abstentions = {a["id"] for a in reads.stored(con, KIND_STRATEGY_ABSTENTIONS, "made_at", now)}
    return {"predictions": append_new(cfg["market"], KIND_STRATEGY_PREDICTIONS, preds, "made_at", known),
            "abstentions": append_new(cfg["market"], KIND_STRATEGY_ABSTENTIONS, abstentions, "made_at",
                                      known_abstentions)}


def session_of(cfg: dict, now: datetime) -> date:
    """D for a run at `now` (the first session whose open is after now)."""
    return entry_session(cfg, now)
