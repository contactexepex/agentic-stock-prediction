"""Score open predictions and open price ranges whose horizon has passed. Horizons count
trading days (price bars). Prediction base = last close on or before as_of_date; a range is
scored on its target_date close. Writes outcome records; never edits predictions or ranges.
Late records are never scored: a range or call made at or after the open of the first session
after its as_of_date (a mid-session or late run) already knew part of its outcome (CLAUDE.md:
nothing after made_at), whatever its horizon, so it stays out of the track record and is counted
under `late_skipped`.
Splits and bonus issues (issue #31): the bars are read on one basis (views ohlc/bars apply the
adjustments in data/<market>/adjustments/), so a call's return is right across an ex-date; a range,
and the closes stored with a call, are compared and stored in the basis the record was made on
(record_basis), so stored edges and outcomes never mix two bases.
The printed summary adds `scores` (scoring.py) over the whole track record: Brier score, log loss
and a reliability table (confidence bins vs hit rate, Wilson 95%) for calls; coverage, 50%/80%
interval scores and the quantile score (mean pinball loss over q10/q25/q75/q90) for ranges."""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.analytics import price_adjustments
from marketbrief.core import calendar
from marketbrief.analytics import range_math
from marketbrief.analytics import scoring
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file


def is_late(cfg: dict, as_of, made_at) -> bool:
    """True when made_at is at or after the open of the first session after as_of (every
    horizon covers that session, so from its open part of the outcome is public)."""
    if made_at is None or (not isinstance(made_at, str) and pd.isna(made_at)):
        return False
    as_of_day = as_of if isinstance(as_of, date) and not isinstance(as_of, datetime) else pd.Timestamp(as_of).date()
    first = calendar.sessions_ahead(cfg, as_of_day + timedelta(days=1), 1)[-1]
    return pd.Timestamp(made_at).to_pydatetime() >= calendar.session_open_utc(cfg, first)


SQL = """
WITH base AS (
    SELECT p.id, p.ticker, p.horizon_days, p.direction, p.as_of_date, p.made_at,
           b.date AS base_date, b.close AS base_close, b.rn
    FROM open_predictions p
    ASOF JOIN bars b ON p.ticker = b.ticker AND p.as_of_date >= b.date
)
SELECT base.id, base.ticker, base.as_of_date, base.made_at, base.base_date, base.base_close, t.date, t.close,
       t.close / base.base_close - 1 AS ret,
       CASE WHEN base.direction = 'up' THEN t.close > base.base_close
            ELSE t.close < base.base_close END AS hit
FROM base JOIN bars t ON t.ticker = base.ticker AND t.rn = base.rn + base.horizon_days
ORDER BY base.id, base.made_at
"""


RANGE_SQL = """
SELECT r.*, b.close AS actual
FROM open_ranges r JOIN ohlc b ON b.ticker = r.ticker AND b.date = r.target_date
ORDER BY r.id
"""


def load_adjustments(con) -> list[dict]:
    """Recorded splits and bonus issues (view price_adjustments; marketbrief/analytics/price_adjustments.py)."""
    return con.execute("SELECT ticker, ex_date, factor, detected_at FROM price_adjustments").df().to_dict("records")


def record_basis(adjs: list[dict], ticker: str, base_date, made_at) -> float:
    """Factor k that turns a close of the ohlc/bars views (newest basis) into the basis a record
    made at `made_at` on bars up to `base_date` used: view close / k. k is the product of the
    factors of the ticker's adjustments with an ex-date after base_date that were detected after
    made_at (the ones the record did not see); 1 when there are none."""
    return price_adjustments.factor_after(adjs, ticker, pd.Timestamp(base_date).date(), detected_after=made_at)


def score_ranges(cfg: dict, con, now: str) -> tuple[list[dict], int]:
    """Each range is scored in its own price basis: a split or bonus detected after it was made
    (ex-date after its as_of_date) re-bases the ohlc view, so the target close is put back by
    record_basis before it is compared with the stored edges; actual_close is stored in that basis."""
    out, late = [], 0
    adjs = load_adjustments(con)
    for row in con.execute(RANGE_SQL).df().itertuples():
        if is_late(cfg, row.as_of_date, row.made_at):
            late += 1
            continue
        key = record_basis(adjs, row.ticker, row.as_of_date, row.made_at)
        actual_close, base = float(row.actual) / key, float(row.base_close)
        pct = lambda volume: round(100 * volume / base, 4)  # noqa: E731
        naive = row.naive_lo80 is not None and not math.isnan(row.naive_lo80)
        out.append(
            {
                "range_id": row.id,
                "scored_at": now,
                "target_date": str(row.target_date)[:10],
                "actual_close": actual_close,
                "z": round((math.log(actual_close / base) - row.center) / row.sigma_h, 6) if row.sigma_h else None,
                "hit50": bool(row.lo50 <= actual_close <= row.hi50),
                "hit80": bool(row.lo80 <= actual_close <= row.hi80),
                "naive_hit50": bool(row.naive_lo50 <= actual_close <= row.naive_hi50) if naive else None,
                "naive_hit80": bool(row.naive_lo80 <= actual_close <= row.naive_hi80) if naive else None,
                "is80_pct": pct(range_math.interval_score(row.lo80, row.hi80, actual_close, 0.8)),
                "naive_is80_pct": pct(range_math.interval_score(row.naive_lo80, row.naive_hi80, actual_close, 0.8))
                if naive
                else None,
                "width80_pct": pct(row.hi80 - row.lo80),
                "naive_width80_pct": pct(row.naive_hi80 - row.naive_lo80) if naive else None,
                "center_err_pct": round(100 * abs(actual_close / (base * math.exp(row.center)) - 1), 4),
                "naive_center_err_pct": round(100 * abs(actual_close / base - 1), 4),
            }
        )
    return out, late


def main() -> int:
    """Score open calls and ranges and print the summary with the proper scores."""
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg["market"]
    con = connect(market)
    now = utc_now()
    rows, late_calls = [], 0
    adjs = load_adjustments(con)
    for pid, ticker, as_of, made_at, base_date, base_close, target_date, target_close, ret, hit in con.execute(
        SQL
    ).fetchall():
        if is_late(cfg, as_of, made_at):
            late_calls += 1
            continue
        # base and target both come from the bars view (one basis), so the return and the hit hold
        # across a split; the two closes are stored in the basis the call saw (record_basis)
        key = record_basis(adjs, ticker, base_date, made_at)
        if key != 1:
            base_close, target_close = base_close / key, target_close / key
        rows.append(
            {
                "prediction_id": pid,
                "scored_at": now,
                "base_date": str(base_date),
                "base_close": base_close,
                "target_date": str(target_date),
                "target_close": target_close,
                "actual_return": round(ret, 6),
                "hit": bool(hit),
            }
        )
    written = append_jsonl(day_file(market, "outcomes", utc_today()), rows)
    open_left = con.execute("SELECT count(*) FROM open_predictions").fetchone()[0] - written - late_calls
    ranges, late_ranges = score_ranges(cfg, con, now)
    r_written = append_jsonl(day_file(market, "range_outcomes", utc_today()), ranges)
    r_open = con.execute("SELECT count(*) FROM open_ranges").fetchone()[0] - r_written - late_ranges
    # proper scores over the whole track record, including what was just scored (fresh connection)
    scores = scoring.summary(connect(market))
    print(
        json.dumps(
            {
                "step": "score",
                "market": market,
                "scored": written,
                "still_open": open_left,
                "late_skipped": {"calls": late_calls, "ranges": late_ranges},
                "ranges_scored": r_written,
                "ranges_open": r_open,
                "hit80": sum(row["hit80"] for row in ranges),
                "hit50": sum(row["hit50"] for row in ranges),
                "scores": scores,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
