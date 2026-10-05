#!/usr/bin/env python3
"""Score open predictions and open price ranges whose horizon has passed. Horizons count
trading days (price bars). Prediction base = last close on or before as_of_date; a range is
scored on its target_date close. Writes outcome records; never edits predictions or ranges."""
from __future__ import annotations

import json
import math
import sys

import rangelib as rl
from common import append_jsonl, connect, day_file, market_arg, require_market, utc_now, utc_today

SQL = """
WITH base AS (
    SELECT p.id, p.ticker, p.horizon_days, p.direction,
           b.date AS base_date, b.close AS base_close, b.rn
    FROM open_predictions p
    ASOF JOIN bars b ON p.ticker = b.ticker AND p.as_of_date >= b.date
)
SELECT base.id, base.base_date, base.base_close, t.date, t.close,
       t.close / base.base_close - 1 AS ret,
       CASE WHEN base.direction = 'up' THEN t.close > base.base_close
            ELSE t.close < base.base_close END AS hit
FROM base JOIN bars t ON t.ticker = base.ticker AND t.rn = base.rn + base.horizon_days
"""


RANGE_SQL = """
SELECT r.*, b.close AS actual
FROM open_ranges r JOIN ohlc b ON b.ticker = r.ticker AND b.date = r.target_date
"""


def score_ranges(con, now: str) -> list[dict]:
    out = []
    for r in con.execute(RANGE_SQL).df().itertuples():
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
    return out


def main() -> int:
    market = require_market(market_arg(__doc__).parse_args())["market"]
    con = connect(market)
    now = utc_now()
    rows = [{
        "prediction_id": pid, "scored_at": now, "base_date": str(bd), "base_close": bc,
        "target_date": str(td), "target_close": tc, "actual_return": round(ret, 6), "hit": bool(hit),
    } for pid, bd, bc, td, tc, ret, hit in con.execute(SQL).fetchall()]
    written = append_jsonl(day_file(market, "outcomes", utc_today()), rows)
    open_left = con.execute("SELECT count(*) FROM open_predictions").fetchone()[0] - written
    ranges = score_ranges(con, now)
    r_written = append_jsonl(day_file(market, "range_outcomes", utc_today()), ranges)
    r_open = con.execute("SELECT count(*) FROM open_ranges").fetchone()[0] - r_written
    print(json.dumps({"step": "score", "market": market, "scored": written, "still_open": open_left,
                      "ranges_scored": r_written, "ranges_open": r_open,
                      "hit80": sum(r["hit80"] for r in ranges), "hit50": sum(r["hit50"] for r in ranges)},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
