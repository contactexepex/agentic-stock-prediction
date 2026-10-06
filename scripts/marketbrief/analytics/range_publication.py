"""Publish today's 50% and 80% price ranges per ticker and horizon for one market.

Run after features.py, calibrate.py and the forecaster. Inputs (all stored, never live APIs):
latest indicator snapshot and regime, latest calibration quantiles, upcoming events, and
today's predictions (AI direction/confidence and optional `range_widen`). Switchable inputs
(config/ranges.yaml per market and horizon, logic in event_history, earnings_reaction, index_cue and
implied_volatility): past earnings-day moves, ex-dividend shift, beta split of the overnight cue, and
option-implied volatility (US; when switched off its horizon sigma is still recorded as the shadow
value `iv_sigma_h`). Appends to data/<market>/ranges/; ids <as_of_date>-<ticker>-<h>d are written once.
Late and mid-session guard: once the first target session has opened at made_at (a manual run
after the open, or a late run after the close), part of every horizon's outcome is public. The
1-day range (its target is that session) is not published; a range whose target session had
already closed is not published either; the other ranges are published for the record, noted
"late" (scoring and the report treat them as late, never scored). For every horizon an overnight
cue or option snapshot quoted after that open is ignored (an intraday quote is not an overnight
cue, it carries part of the session's outcome)."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from marketbrief.analytics.range_context import first_target_close, first_target_open, horizon_context, load_context
from marketbrief.analytics.range_row import range_row
from marketbrief.constants.range_publication import HELP_NOW, MSG_NOW_NEEDS_OFFSET, STEP_RANGES
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_ranges_config
from marketbrief.core.storage import append_jsonl, day_file


def build(cfg: dict, rc: dict, con, now: str | None = None) -> list[dict]:
    """The range rows of every ticker and horizon that are not stored yet."""
    ctx = load_context(cfg, rc, con, now)
    rows = []
    for h in rc["horizons"]:
        hc = horizon_context(ctx, h)
        if hc is None:
            continue
        for t in cfg["tickers"]:
            row = range_row(ctx, hc, t)
            if row is not None:
                rows.append(row)
    return rows


def main() -> int:
    """Entry point of scripts/ranges.py."""
    ap = market_arg(__doc__)
    ap.add_argument("--now", help=HELP_NOW)
    args = ap.parse_args()
    cfg = require_market(args)
    now = args.now or utc_now()
    if datetime.fromisoformat(now).tzinfo is None:
        raise SystemExit(MSG_NOW_NEEDS_OFFSET)
    rc, con = load_ranges_config(cfg["market"]), connect(cfg["market"])
    rows = build(cfg, rc, con, now)
    if rows:
        append_jsonl(day_file(cfg["market"], "ranges", pd.Timestamp(rows[0]["as_of_date"]).date()), rows)
    as_of = con.execute("SELECT max(as_of_date) FROM regime_latest").fetchone()[0]
    made = datetime.fromisoformat(now)
    late = made >= first_target_close(cfg, as_of)
    in_session = first_target_open(cfg, as_of) <= made and not late   # no 1-day ranges; 5-day ones late
    print(json.dumps({"step": STEP_RANGES, "market": cfg["market"], "written": len(rows), "late": late,
                      "in_session": in_session, "tickers": sorted({r["ticker"] for r in rows})}, indent=2))
    return 0
