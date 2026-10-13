"""Publish today's 50% and 80% price ranges per ticker and horizon N+k for one market (k from config/strategies.yaml
`horizons`; the range of the close of the k-th session after D, the first session after the as-of close; rows carry
horizon_label n_plus_k, entry_date = D and exit_date = target_date; docs/SPEC.md F2.7).

Run after features.py, calibrate.py and the forecaster. Inputs (all stored, never live APIs):
latest indicator snapshot and regime, latest calibration quantiles, upcoming events, and
today's predictions (AI direction/confidence and optional `range_widen`). Switchable inputs
(config/ranges.yaml per market and horizon, logic in event_history, earnings_reaction, index_cue and
implied_volatility): past earnings-day moves, ex-dividend shift, beta split of the overnight cue, and
option-implied volatility (US; when switched off its horizon sigma is still recorded as the shadow
value `iv_sigma_h`). Appends to data/<market>/ranges/; ids <as_of_date>-<ticker>-<h>d are written once.
Late and mid-session guard: once D has opened at made_at (a manual run after the open, or a late run
after the close), part of every horizon's outcome is public. A range whose target session had already
closed is not published; the other ranges are published for the record, noted "late" (scoring and
the report treat them as late, never scored). Before B10 the 1-day range targeted D itself and was not
published mid-session; no N+k range targets D. For every horizon an overnight
cue or option snapshot quoted after that open is ignored (an intraday quote is not an overnight
cue, it carries part of the session's outcome).
`--evening` (B17's evening run, option C): the same rows from the day's close, before the forecaster and before any
overnight cue (none is applied; the day's stored quotes are its own pre-open cue), written to ranges_evening with the
same ids and `run: "evening"`, once per id there. They preview the pre-open rows, which stay the revision of record in
`ranges`: evening rows are never scored, traded or read by ranges_asof unless asked (run="evening")."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from marketbrief.analytics.range_context import first_target_close, first_target_open, horizon_context, load_context
from marketbrief.analytics.range_row import range_row
from marketbrief.constants.horizons import RUN_EVENING, RUN_KINDS, RUN_PRE_OPEN
from marketbrief.constants.range_publication import HELP_EVENING, HELP_NOW, MSG_NOW_NEEDS_OFFSET, STEP_RANGES
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_ranges_config
from marketbrief.core.storage import append_jsonl, day_file


def build(cfg: dict, ranges_config: dict, con, now: str | None = None, run: str = RUN_PRE_OPEN) -> list[dict]:
    """The range rows of every ticker and horizon that are not stored yet in the run's kind (RUN_KINDS); evening rows
    carry `run`, pre-open rows are unchanged."""
    ctx = load_context(cfg, ranges_config, con, now, run)
    rows = []
    for horizon in ranges_config["horizons"]:
        horizon_info = horizon_context(ctx, horizon)
        if horizon_info is None:
            continue
        for ticker in cfg["tickers"]:
            row = range_row(ctx, horizon_info, ticker)
            if row is not None:
                rows.append(row if run == RUN_PRE_OPEN else {**row, "run": run})
    return rows


def main() -> int:
    """Entry point of scripts/ranges.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--now", help=HELP_NOW)
    parser.add_argument("--evening", action="store_true", help=HELP_EVENING)
    args = parser.parse_args()
    run = RUN_EVENING if args.evening else RUN_PRE_OPEN
    cfg = require_market(args)
    now = args.now or utc_now()
    if datetime.fromisoformat(now).tzinfo is None:
        raise SystemExit(MSG_NOW_NEEDS_OFFSET)
    ranges_config, con = load_ranges_config(cfg["market"]), connect(cfg["market"])
    rows = build(cfg, ranges_config, con, now, run)
    if rows:
        append_jsonl(day_file(cfg["market"], RUN_KINDS[run], pd.Timestamp(rows[0]["as_of_date"]).date()), rows)
    as_of = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    made = datetime.fromisoformat(now)
    late = made >= first_target_close(cfg, as_of)
    in_session = first_target_open(cfg, as_of) <= made and not late  # every range is published late
    print(
        json.dumps(
            {
                "step": STEP_RANGES,
                "market": cfg["market"],
                **({"run": run} if run != RUN_PRE_OPEN else {}),
                "written": len(rows),
                "late": late,
                "in_session": in_session,
                "tickers": sorted({row["ticker"] for row in rows}),
            },
            indent=2,
        )
    )
    return 0
