"""The lab's daily steps on stored data (scripts/lab.py): predict (pre-open: rule strategies and baselines, with
the cost-viable rows of their new predictions), pick (pre-open, after every family has predicted: the head-to-head
picks and the cost-viable rows of every prediction and pick not flagged yet, e.g. B3's AI predictions); settle is in
settle_run.py. Predict runs whatever the go-live switch (a rehearsal before a strategy's live_from); pick lets only
strategies live on D contend (registry.is_live). Each appends only new ids (append-only, CLAUDE.md data rules)
and returns a summary."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from marketbrief.constants.kinds import (KIND_COST_VIEWS, KIND_HEAD_TO_HEAD_PICKS, KIND_STRATEGY_ABSTENTIONS,
                                         KIND_STRATEGY_PREDICTIONS)
from marketbrief.core.calendar import session_open_utc
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.lab import picks as lab_picks
from marketbrief.lab import reads, registry, scoreboard
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
    (decision 51) of every qualifying prediction (also before go-live, as predict writes them: a flag, never a
    trade) and every pick. Only strategies live on D (registry.is_live) contend: the ranking (decision 41) holds
    the live strategies of the family and their live settlements; a family with no live strategy gets no row, so
    with nothing live no pick is written (`live_strategies` 0). Refused at or after D's open (F1.8: a later pick
    could rank strategies on settlements stored after the open)."""
    if now >= session_open_utc(cfg, as_date(session_date)):
        return {"ok": False, "message": MSG_PICK_TOO_LATE.format(session=session_date, now=now.isoformat())}
    preds = [p for p in reads.predictions(con, now) if str(p["session_date"]) == session_date]
    live = [s for s in specs if registry.is_live(s, session_date)]
    live_ids = {s["id"] for s in live}
    contenders = [p for p in preds if p["strategy_id"] in live_ids]
    trades = scoreboard.live_settlements(reads.settlements(con, now))
    data = reads.market_data(con, cfg, now, [], as_date(session_date) - timedelta(days=10))
    eurusd = data.eurusd_on(as_date(session_date))
    if data.rates.get("order_fee_eur") and eurusd is None:
        return {"ok": False, "message": MSG_NO_EURUSD.format(when=now.isoformat())}
    rows = []
    for ticker in sorted({p["ticker"] for p in contenders}):
        sample = min((p for p in contenders if p["ticker"] == ticker), key=lambda p: p["id"])
        for family in registry.head_to_head_families():
            family_ids = [s["id"] for s in live if s["family"] == family]
            if not family_ids:
                continue
            context = {"market": cfg["market"], "rate": data.rates, "eurusd": eurusd,
                       "family_ids": family_ids, "made_at": now.isoformat(),
                       "as_of_date": sample["as_of_date"], "session_date": session_date,
                       "base_close": sample["base_close"], "amount": sample["amount"], "currency": sample["currency"],
                       "method_version": LAB_VERSION}
            rows += lab_picks.pick_rows(ticker, family, context, contenders, trades)
    known = {p["id"] for p in reads.picks(con, now)}
    written = append_new(cfg["market"], KIND_HEAD_TO_HEAD_PICKS, rows, "made_at", known)
    by_id = {p["id"]: p for p in preds}
    views = [viability_row(KIND_PREDICTION, p["id"], p, data.rates, eurusd, now) for p in preds if p.get("qualifies")]
    views += [viability_row(KIND_PICK, r["id"], by_id[r["prediction_id"]], data.rates, eurusd, now)
              for r in rows if r["status"] == "picked"]
    known_views = {r["id"] for r in reads.stored(con, KIND_COST_VIEWS, "computed_at", now)}
    return {"session_date": session_date, "live_strategies": len(live), "picks": len(rows), "written": written,
            "no_candidate": sum(r["status"] == "no_candidate" for r in rows),
            "cost_views": append_new(cfg["market"], KIND_COST_VIEWS, views, "computed_at", known_views),
            "cost_viable": sum(bool(v["cost_viable"]) for v in views if v["record_kind"] == KIND_PREDICTION)}


def prediction_views(con, cfg: dict, now: datetime, preds: list[dict]) -> dict:
    """Append the cost-viable rows (decision 51) of the qualifying predictions among `preds` whose
    cv:prediction:<id> is not stored yet (pick_day skips the same ids). US: without any stored EUR/USD close the
    BUX order fee cannot be converted, so no row is written (pick writes them later)."""
    trading = [p for p in preds if p.get("qualifies")]
    if not trading:
        return {"cost_views": 0}
    start = min(as_date(p["session_date"]) for p in trading) - timedelta(days=10)
    data = reads.market_data(con, cfg, now, [], start)
    if data.rates.get("order_fee_eur") and not data.eurusd:
        return {"cost_views": 0, "cost_views_message": MSG_NO_EURUSD.format(when=now.isoformat())}
    views = [viability_row(KIND_PREDICTION, p["id"], p, data.rates, data.eurusd_on(as_date(p["session_date"])), now)
             for p in trading]
    known_views = {r["id"] for r in reads.stored(con, KIND_COST_VIEWS, "computed_at", now)}
    return {"cost_views": append_new(cfg["market"], KIND_COST_VIEWS, views, "computed_at", known_views)}


def write_predictions(cfg: dict, now: datetime, preds: list[dict], abstentions: list[dict], con) -> dict:
    """Append new prediction and abstention rows (abstention ids skipped when already stored) and the cost-viable
    rows of the new qualifying predictions (so they carry the flag even when pick does not run)."""
    known = {p["id"] for p in reads.predictions(con, now)}
    new = [p for p in preds if p["id"] not in known]
    known_abstentions = {a["id"] for a in reads.stored(con, KIND_STRATEGY_ABSTENTIONS, "made_at", now)}
    return {"predictions": append_new(cfg["market"], KIND_STRATEGY_PREDICTIONS, preds, "made_at", known),
            "abstentions": append_new(cfg["market"], KIND_STRATEGY_ABSTENTIONS, abstentions, "made_at",
                                      known_abstentions),
            **prediction_views(con, cfg, now, new)}


def session_of(cfg: dict, now: datetime) -> date:
    """D for a run at `now` (the first session whose open is after now)."""
    return entry_session(cfg, now)
