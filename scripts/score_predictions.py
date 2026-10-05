#!/usr/bin/env python3
"""Score open predictions whose horizon has passed. Horizons count trading days (price bars).
Base = last close on or before as_of_date. Writes outcome records; never edits predictions."""
from __future__ import annotations

import json
import sys

from common import append_jsonl, connect, day_file, utc_now, utc_today

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


def main() -> int:
    con = connect()
    now = utc_now()
    rows = [{
        "prediction_id": pid, "scored_at": now, "base_date": str(bd), "base_close": bc,
        "target_date": str(td), "target_close": tc, "actual_return": round(ret, 6), "hit": bool(hit),
    } for pid, bd, bc, td, tc, ret, hit in con.execute(SQL).fetchall()]
    written = append_jsonl(day_file("outcomes", utc_today()), rows)
    open_left = con.execute("SELECT count(*) FROM open_predictions").fetchone()[0] - written
    print(json.dumps({"step": "score", "scored": written, "still_open": open_left}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
