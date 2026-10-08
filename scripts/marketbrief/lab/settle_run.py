"""The post-close settle step (scripts/lab.py settle): every due trade of both views, once (append-only), re-settled
as a new row when its split records change, with the two cost views of each settled trade (cost_views rows,
owner decision 50).

Locking (F1.8): a prediction and, for the head-to-head view, its pick must be made before D's open; when the data
folder is a git repository, the commit that first added each row must be before the open too. A row git cannot
date (added in a shallow clone's boundary commit, whose history is cut) falls back to the made_at check; a row
that no commit added is refused.

Go-live switch (registry.is_live): a prediction, and a pick of it, whose strategy is not live on its D (live_from
null or later than D) is no trade: it is never settled, re-settled or listed as due, now or after the switch (D is
fixed per row, so a rerun after live_from is set never trades a pre-live row)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

from marketbrief.constants.kinds import (KIND_COST_VIEWS, KIND_HEAD_TO_HEAD_PICKS, KIND_PAPER_TRADES_SETTLED,
                                         KIND_STRATEGY_PREDICTIONS)
from marketbrief.core import paths
from marketbrief.lab import reads, registry
from marketbrief.lab.constants import FLAG_RESETTLED, STATUS_SETTLED, VIEW_ACCURACY, VIEW_HEAD_TO_HEAD
from marketbrief.lab.cost_views import settlement_row
from marketbrief.lab.costs import MissingEurUsdError
from marketbrief.lab.run import append_new
from marketbrief.lab.settle import as_date, row_id, settle, trade_id
from marketbrief.lab.timing import first_commit_times, in_git_repo, is_locked

UNDATED = "undated"   # added in a shallow clone's boundary commit: git cannot tell when


def commit_times(market: str, kind: str) -> dict[str, datetime | str] | None:
    """{row id: first commit time, or UNDATED} for a kind's stored files; None when the data root is no git
    repository (no commit check possible)."""
    if not in_git_repo(paths.ROOT):
        return None
    folder = paths.data_dir(market) / kind
    found: dict[str, datetime | str] = {}
    for file in sorted(folder.glob("**/*.jsonl")) if folder.exists() else []:
        for line, when in first_commit_times(paths.ROOT, file).items():
            try:
                found.setdefault(json.loads(line)["id"], UNDATED if when is None else when)
            except (ValueError, KeyError, TypeError):
                continue
    return found


def locked(row: dict, cfg: dict, commits: dict | None) -> bool:
    """F1.8 for a prediction or pick row (made_at and session_date)."""
    if commits is None:
        return is_locked(row, cfg, None)
    if row["id"] not in commits:
        return False                                   # never committed
    when = commits[row["id"]]
    return is_locked(row, cfg, None if when == UNDATED else when)


def live_predictions(preds: list[dict], reg: dict | None = None) -> list[dict]:
    """The predictions whose strategy is live on their D (registry.is_live)."""
    specs = registry.by_id(reg)
    return [p for p in preds if p["strategy_id"] in specs and registry.is_live(specs[p["strategy_id"]],
                                                                               p["session_date"])]


def trades_to_settle(preds: list[dict], picks: list[dict], live_only: bool = True) -> list[tuple[dict, str,
                                                                                            dict | None]]:
    """(prediction, view, pick) of every trade: each qualifying prediction (accuracy) and each picked pick, of
    strategies live on D only (a pick is live when the strategy of the prediction it picked is live on D);
    live_only=False lists them whatever the switch (to count the trades left out)."""
    trading = live_predictions(preds) if live_only else preds
    by_id = {p["id"]: p for p in trading}
    out = [(p, VIEW_ACCURACY, None) for p in trading if p.get("qualifies")]
    for pick in picks:
        if pick["status"] == "picked" and pick["prediction_id"] in by_id:
            out.append((by_id[pick["prediction_id"]], VIEW_HEAD_TO_HEAD, pick))
    return out


def needs_settling(existing: dict | None, data, pred: dict) -> bool:
    """No row yet, or a settled row whose split records inside its window changed since (F1.5)."""
    if existing is None:
        return True
    if existing["status"] != STATUS_SETTLED:
        return False
    _, ids = data.split_factor(pred["ticker"], as_date(pred["session_date"]), as_date(existing["exit_date_actual"]))
    return sorted(existing.get("adjustment_ids") or []) != sorted(ids)


def refusal(pred: dict, pick: dict | None, cfg: dict, commits: dict) -> str | None:
    """The id refused by the lock check (the prediction's or the pick's), or None."""
    if not locked(pred, cfg, commits["predictions"]):
        return pred["id"]
    if pick is not None and not locked(pick, cfg, commits["picks"]):
        return pick["id"]
    return None


def settle_due(con, cfg: dict, now: datetime, betas: dict | None = None) -> dict:
    """Settle every due trade not settled yet (and re-settle on a changed split record); trades of strategies not
    live on D are left out (counted in `not_live`)."""
    preds, picks = reads.predictions(con, now), reads.picks(con, now)
    settled = reads.settlements(con, now)
    newest = {row["trade_id"]: row for row in sorted(settled, key=lambda r: (str(r["settled_at"]), r["id"]))}
    jobs = trades_to_settle(preds, picks)
    not_live = len(trades_to_settle(preds, picks, live_only=False)) - len(jobs)
    start = min((as_date(p["session_date"]) for p, _, _ in jobs), default=now.date()) - timedelta(days=10)
    data = reads.market_data(con, cfg, now, sorted({p["ticker"] for p, _, _ in jobs}), start)
    betas = reads.betas_asof(con, now) if betas is None else betas
    commits = {"predictions": commit_times(cfg["market"], KIND_STRATEGY_PREDICTIONS),
               "picks": commit_times(cfg["market"], KIND_HEAD_TO_HEAD_PICKS)}
    rows, views, refused, waiting = [], [], [], []
    for pred, view, pick in jobs:
        refused_id = refusal(pred, pick, cfg, commits)
        if refused_id:
            refused.append(refused_id)
            continue
        existing = newest.get(trade_id(pred["id"], view, pick["pick_rule"] if pick else None))
        if not needs_settling(existing, data, pred):
            continue
        key = (pred["ticker"], str(pred["as_of_date"]))
        own = replace(data, betas={pred["ticker"]: betas[key]} if key in betas else {})
        try:
            row = settle(pred, view, pick, own, now)
        except MissingEurUsdError:                 # no EUR/USD close stored at all yet: settled on a later run
            waiting.append(pred["id"])
            continue
        if row is None:
            continue
        if existing is not None:
            row["supersedes"], row["flags"] = existing["id"], [*row["flags"], FLAG_RESETTLED]
            row["id"] = row_id(row["trade_id"], now)
        rows.append(row)
        cost_row = settlement_row(row, pred, own)
        if cost_row:
            views.append(cost_row)
    known = {row["id"] for row in settled}
    written = append_new(cfg["market"], KIND_PAPER_TRADES_SETTLED, rows, "settled_at", known)
    known_views = {r["id"] for r in reads.stored(con, KIND_COST_VIEWS, "computed_at", now)}
    return {"due": len(rows), "written": written, "not_live": not_live, "refused_not_locked": sorted(set(refused)),
            "waiting_for_eurusd": sorted(set(waiting)),
            "cost_views": append_new(cfg["market"], KIND_COST_VIEWS, views, "computed_at", known_views),
            "by_status": {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}}
