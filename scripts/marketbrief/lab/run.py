"""The lab's daily steps on stored data (scripts/lab.py): predict (pre-open: rule strategies and baselines),
pick (pre-open, after every family has predicted: the head-to-head picks), settle (post-close: every due trade of
both views). Each appends only new ids (append-only, CLAUDE.md data rules) and returns a summary."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta

from marketbrief.constants.kinds import (KIND_HEAD_TO_HEAD_PICKS, KIND_PAPER_TRADES_SETTLED, KIND_STRATEGY_ABSTENTIONS,
                                         KIND_STRATEGY_PREDICTIONS)
from marketbrief.core import paths
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.lab import picks as lab_picks
from marketbrief.lab import reads, registry
from marketbrief.lab.constants import (FLAG_RESETTLED, LAB_VERSION, MSG_NO_EURUSD, STATUS_SETTLED, VIEW_ACCURACY,
                                       VIEW_HEAD_TO_HEAD)
from marketbrief.lab.settle import as_date, row_id, settle, trade_id
from marketbrief.lab.timing import entry_session, first_commit_times, is_locked
from marketbrief.utils.timefmt import as_utc_timestamp

SETTLE_LOOKBACK_DAYS = 60   # bars read back from the oldest open trade's entry


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
    """Write the head-to-head picks of every company predicted for `session_date` (D)."""
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
    return {"session_date": session_date, "picks": len(rows), "written": written,
            "no_candidate": sum(r["status"] == "no_candidate" for r in rows)}


def commit_times(market: str) -> dict[str, datetime]:
    """{prediction id: first commit time} from git for the stored prediction files (empty without git)."""
    folder = paths.data_dir(market) / KIND_STRATEGY_PREDICTIONS
    found: dict[str, datetime] = {}
    for file in sorted(folder.glob("**/*.jsonl")) if folder.exists() else []:
        for line, when in first_commit_times(paths.ROOT, file).items():
            try:
                found.setdefault(json.loads(line)["id"], when)
            except (ValueError, KeyError, TypeError):
                continue
    return found


def trades_to_settle(preds: list[dict], picks: list[dict]) -> list[tuple[dict, str, dict | None]]:
    """(prediction, view, pick) of every trade: each qualifying prediction (accuracy) and each picked pick."""
    by_id = {p["id"]: p for p in preds}
    out = [(p, VIEW_ACCURACY, None) for p in preds if p.get("qualifies")]
    for pick in picks:
        if pick["status"] == "picked" and pick["prediction_id"] in by_id:
            out.append((by_id[pick["prediction_id"]], VIEW_HEAD_TO_HEAD, pick))
    return out


def needs_settling(existing: dict | None, data, pred: dict) -> bool:
    """No row yet, or a settled row whose split records inside its window changed since (F1.5: a correction
    re-settles the trade as a new row)."""
    if existing is None:
        return True
    if existing["status"] != STATUS_SETTLED:
        return False
    _, ids = data.split_factor(pred["ticker"], as_date(pred["session_date"]), as_date(existing["exit_date_actual"]))
    return sorted(existing.get("adjustment_ids") or []) != sorted(ids)


def settle_due(con, cfg: dict, now: datetime, betas: dict | None = None, commits: dict | None = None) -> dict:
    """Settle every due trade not settled yet (and re-settle on a changed split record)."""
    preds, picks = reads.predictions(con, now), reads.picks(con, now)
    settled = reads.settlements(con, now)
    newest = {row["trade_id"]: row for row in sorted(settled, key=lambda r: (str(r["settled_at"]), r["id"]))}
    jobs = trades_to_settle(preds, picks)
    start = min((as_date(p["session_date"]) for p, _, _ in jobs), default=now.date()) - timedelta(days=10)
    data = reads.market_data(con, cfg, now, sorted({p["ticker"] for p, _, _ in jobs}), start)
    betas = reads.betas_asof(con, now) if betas is None else betas
    commits = commit_times(cfg["market"]) if commits is None else commits
    rows, refused, waiting = [], [], []
    for pred, view, pick in jobs:
        if not is_locked(pred, cfg, commits.get(pred["id"])):
            refused.append(pred["id"])
            continue
        existing = newest.get(trade_id(pred["id"], view, pick["pick_rule"] if pick else None))
        if not needs_settling(existing, data, pred):
            continue
        own = replace(data, betas={pred["ticker"]: betas[(pred["ticker"], str(pred["as_of_date"]))]}
                      if (pred["ticker"], str(pred["as_of_date"])) in betas else {})
        try:
            row = settle(pred, view, pick, own, now)
        except ValueError:                     # no EUR/USD close stored at all yet: settled on a later run
            waiting.append(pred["id"])
            continue
        if row is None:
            continue
        if existing is not None:
            row["supersedes"], row["flags"] = existing["id"], [*row["flags"], FLAG_RESETTLED]
            row["id"] = row_id(row["trade_id"], now)
        rows.append(row)
    known = {row["id"] for row in settled}
    written = append_new(cfg["market"], KIND_PAPER_TRADES_SETTLED, rows, "settled_at", known)
    return {"due": len(rows), "written": written, "refused_not_locked": sorted(set(refused)),
            "waiting_for_eurusd": sorted(set(waiting)),
            "by_status": {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}}


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
