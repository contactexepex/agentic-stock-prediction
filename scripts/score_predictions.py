#!/usr/bin/env python3
"""Score open predictions and open price ranges whose horizon has passed. Horizons count
trading days (price bars). Prediction base = last close on or before as_of_date; a range is
scored on its target_date close. Writes outcome records; never edits predictions or ranges.
Late records are never scored: a range or call made at or after the open of the first session
after its as_of_date (a mid-session or late run) already knew part of its outcome (CLAUDE.md:
nothing after made_at), whatever its horizon, so it stays out of the track record and is counted
under `late_skipped`.
The printed summary adds `scores` (scoring.py) over the whole track record: Brier score, log loss
and a reliability table (confidence bins vs hit rate, Wilson 95%) for calls; coverage, 50%/80%
interval scores and the quantile score (mean pinball loss over q10/q25/q75/q90) for ranges."""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta

import pandas as pd

import events as ev
import rangelib as rl
import scoring
from common import append_jsonl, connect, day_file, market_arg, require_market, utc_now, utc_today


def is_late(cfg: dict, as_of, made_at) -> bool:
    """True when made_at is at or after the open of the first session after as_of (every
    horizon covers that session, so from its open part of the outcome is public)."""
    if made_at is None or (not isinstance(made_at, str) and pd.isna(made_at)):
        return False
    d = as_of if isinstance(as_of, date) and not isinstance(as_of, datetime) else pd.Timestamp(as_of).date()
    first = ev.sessions_ahead(cfg, d + timedelta(days=1), 1)[-1]
    return pd.Timestamp(made_at).to_pydatetime() >= ev.session_open_utc(cfg, first)

SQL = """
WITH base AS (
    SELECT p.id, p.ticker, p.horizon_days, p.direction, p.as_of_date, p.made_at,
           b.date AS base_date, b.close AS base_close, b.rn
    FROM open_predictions p
    ASOF JOIN bars b ON p.ticker = b.ticker AND p.as_of_date >= b.date
)
SELECT base.id, base.as_of_date, base.made_at, base.base_date, base.base_close, t.date, t.close,
       t.close / base.base_close - 1 AS ret,
       CASE WHEN base.direction = 'up' THEN t.close > base.base_close
            ELSE t.close < base.base_close END AS hit
FROM base JOIN bars t ON t.ticker = base.ticker AND t.rn = base.rn + base.horizon_days
"""


RANGE_SQL = """
SELECT r.*, b.close AS actual
FROM open_ranges r JOIN ohlc b ON b.ticker = r.ticker AND b.date = r.target_date
"""


def score_ranges(cfg: dict, con, now: str) -> tuple[list[dict], int]:
    out, late = [], 0
    for r in con.execute(RANGE_SQL).df().itertuples():
        if is_late(cfg, r.as_of_date, r.made_at):
            late += 1
            continue
        y, base = float(r.actual), float(r.base_close)
        pct = lambda v: round(100 * v / base, 4)  # noqa: E731
        naive = r.naive_lo80 is not None and not math.isnan(r.naive_lo80)
        out.append({
            "range_id": r.id, "scored_at": now, "target_date": str(r.target_date)[:10], "actual_close": y,
            "z": round((math.log(y / base) - r.center) / r.sigma_h, 6) if r.sigma_h else None,
            "hit50": bool(r.lo50 <= y <= r.hi50), "hit80": bool(r.lo80 <= y <= r.hi80),
            "naive_hit50": bool(r.naive_lo50 <= y <= r.naive_hi50) if naive else None,
            "naive_hit80": bool(r.naive_lo80 <= y <= r.naive_hi80) if naive else None,
            "is80_pct": pct(rl.interval_score(r.lo80, r.hi80, y, 0.8)),
            "naive_is80_pct": pct(rl.interval_score(r.naive_lo80, r.naive_hi80, y, 0.8)) if naive else None,
            "width80_pct": pct(r.hi80 - r.lo80),
            "naive_width80_pct": pct(r.naive_hi80 - r.naive_lo80) if naive else None,
            "center_err_pct": round(100 * abs(y / (base * math.exp(r.center)) - 1), 4),
            "naive_center_err_pct": round(100 * abs(y / base - 1), 4),
        })
    return out, late


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg["market"]
    con = connect(market)
    now = utc_now()
    rows, late_calls = [], 0
    for pid, as_of, made_at, bd, bc, td, tc, ret, hit in con.execute(SQL).fetchall():
        if is_late(cfg, as_of, made_at):
            late_calls += 1
            continue
        rows.append({"prediction_id": pid, "scored_at": now, "base_date": str(bd), "base_close": bc,
                     "target_date": str(td), "target_close": tc, "actual_return": round(ret, 6), "hit": bool(hit)})
    written = append_jsonl(day_file(market, "outcomes", utc_today()), rows)
    open_left = con.execute("SELECT count(*) FROM open_predictions").fetchone()[0] - written - late_calls
    ranges, late_ranges = score_ranges(cfg, con, now)
    r_written = append_jsonl(day_file(market, "range_outcomes", utc_today()), ranges)
    r_open = con.execute("SELECT count(*) FROM open_ranges").fetchone()[0] - r_written - late_ranges
    # proper scores over the whole track record, including what was just scored (fresh connection)
    scores = scoring.summary(connect(market))
    print(json.dumps({"step": "score", "market": market, "scored": written, "still_open": open_left,
                      "late_skipped": {"calls": late_calls, "ranges": late_ranges},
                      "ranges_scored": r_written, "ranges_open": r_open,
                      "hit80": sum(r["hit80"] for r in ranges), "hit50": sum(r["hit50"] for r in ranges),
                      "scores": scores},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
