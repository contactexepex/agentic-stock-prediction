"""Score open predictions and open price ranges whose horizon has passed. Horizons count
trading days (price bars). A call is scored on its basis (analytics/call_basis.py, stored as `label_basis`):
close_to_close = the last close on or before as_of_date to the close h bars later (every call made before
config/settings.yaml call_scoring.from; label legacy_cc); open_to_close = the open of the next bar (D) to the close
of the k-th bar after D (N+k, decision 37: k + 1 bars after the as-of bar; label n_plus_k), except a 5-day call made
before call_scoring.n_plus_k_from, which keeps the old close of D+4 (label legacy_5d_d4); with `entry_date` and
`entry_open`; no open, no score (counted under `no_entry_open`). An open-to-close call is scored only when its
entry bar is the market calendar's first session after as_of_date and its exit bar the session of its offset
(issue #45.3, as model/labels.py): a missing session's bar never shifts the window, the call stays open (counted
under `session_gap_open`). Each outcome stores its `horizon_label`. A range is
scored on its target_date close (the exit session of N+k for ranges written by B10's ranges.py). Writes outcome
records; never edits predictions, ranges or stored outcomes.
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

from marketbrief.analytics import call_basis, price_adjustments, range_math, scoring
from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE
from marketbrief.core import calendar
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl, day_file

EARLIEST = pd.Timestamp("1900-01-01", tz="UTC")  # no n_plus_k_from: every open-to-close call is N+k


def is_late(cfg: dict, as_of, made_at) -> bool:
    """True when made_at is at or after the open of the first session after as_of (every
    horizon covers that session, so from its open part of the outcome is public)."""
    if made_at is None or (not isinstance(made_at, str) and pd.isna(made_at)):
        return False
    as_of_day = as_of if isinstance(as_of, date) and not isinstance(as_of, datetime) else pd.Timestamp(as_of).date()
    first = calendar.sessions_ahead(cfg, as_of_day + timedelta(days=1), 1)[-1]
    return pd.Timestamp(made_at).to_pydatetime() >= calendar.session_open_utc(cfg, first)


# every open call with its as-of bar, the entry bar (the next one, with its open) and the bars that close each
# basis: close_to_close at rn + h (legacy_cc); open_to_close at rn + k + 1 (N+k), or rn + 5 for a 5-day call made
# before n_plus_k_from (legacy_5d_d4, the old D+4 close) (call_basis.target_offset)
SQL = """
WITH base AS (
    SELECT p.id, p.ticker, p.horizon_days, p.direction, p.as_of_date, p.made_at,
           b.date AS base_date, b.close AS base_close, b.rn
    FROM open_predictions p
    ASOF JOIN bars b ON p.ticker = b.ticker AND p.as_of_date >= b.date
)
SELECT base.*, e.date AS entry_date, eo.open AS entry_open, c.date AS c2c_date, c.close AS c2c_close,
       o.date AS o2c_date, o.close AS o2c_close
FROM base
LEFT JOIN bars e ON e.ticker = base.ticker AND e.rn = base.rn + 1
LEFT JOIN ohlc eo ON eo.ticker = e.ticker AND eo.date = e.date
LEFT JOIN bars c ON c.ticker = base.ticker AND c.rn = base.rn + base.horizon_days
LEFT JOIN bars o ON o.ticker = base.ticker
     AND o.rn = base.rn + CASE WHEN base.horizon_days = 5 AND base.made_at < ?::TIMESTAMPTZ THEN 5
                               ELSE base.horizon_days + 1 END
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


def on_calendar(cfg: dict, as_of, entry_date, exit_date, offset: int) -> bool:
    """True when the entry bar is the first session after as_of and the exit bar the `offset`-th one, both through
    the market calendar (a missing session's bar would otherwise shift the window to later bars)."""
    if pd.isna(entry_date) or pd.isna(exit_date):
        return False
    sessions = calendar.sessions_ahead(cfg, pd.Timestamp(as_of).date() + timedelta(days=1), offset)
    return (pd.Timestamp(entry_date).date(), pd.Timestamp(exit_date).date()) == (sessions[0], sessions[-1])


def missing(value) -> bool:
    """True for a missing or non-positive price."""
    return value is None or value != value or value <= 0


def score_calls(cfg: dict, con, now: str) -> tuple[list[dict], int, int, int]:
    """(outcome rows, late calls, calls whose entry session has no open, open-to-close calls left open because a
    session of their window has no bar) of the open calls that matured on
    their basis (call_basis.basis_for: close_to_close, or open_to_close from the configured switch). Prices come
    from the bars view (one basis), so the return and the hit hold across a split; the stored prices are put
    back in the basis the call saw (record_basis)."""
    rule, since = call_basis.switch(), call_basis.n_plus_k_from()
    rows, late, no_open, gaps = [], 0, 0, 0
    adjs = load_adjustments(con)
    for row in con.execute(SQL, [since if since is not None else EARLIEST]).df().itertuples():
        basis = call_basis.basis_for(row.made_at, rule)
        horizon_label = call_basis.horizon_label(basis, row.horizon_days, row.made_at, since)
        target_date, target_close = (row.o2c_date, row.o2c_close) if basis == LABEL_OPEN_TO_CLOSE else (
            row.c2c_date, row.c2c_close)
        if missing(target_close):
            continue  # not matured yet
        if is_late(cfg, row.as_of_date, row.made_at):
            late += 1
            continue
        if basis == LABEL_OPEN_TO_CLOSE and not on_calendar(
                cfg, row.as_of_date, row.entry_date, target_date,
                call_basis.target_offset(basis, row.horizon_days, horizon_label)):
            gaps += 1  # a session of the window has no bar: stays open, never scored on a shifted window
            continue
        entry = row.entry_open if basis == LABEL_OPEN_TO_CLOSE else row.base_close
        if missing(entry):
            no_open += 1  # open_to_close needs the entry session's open: no open, no score
            continue
        key = record_basis(adjs, row.ticker, row.base_date, row.made_at)
        out = {"prediction_id": row.id, "scored_at": now, "base_date": str(pd.Timestamp(row.base_date).date()),
               "base_close": row.base_close / key, "target_date": str(pd.Timestamp(target_date).date()),
               "target_close": target_close / key, "actual_return": round(target_close / entry - 1, 6),
               "hit": bool(target_close > entry if row.direction == "up" else target_close < entry),
               "label_basis": basis, "horizon_label": horizon_label}
        if basis == LABEL_OPEN_TO_CLOSE:
            out |= {"entry_date": str(pd.Timestamp(row.entry_date).date()), "entry_open": entry / key}
        rows.append(out)
    return rows, late, no_open, gaps


def main() -> int:
    """Score open calls and ranges and print the summary with the proper scores."""
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg["market"]
    con = connect(market)
    now = utc_now()
    rows, late_calls, no_open, gaps = score_calls(cfg, con, now)
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
                "no_entry_open": no_open,
                "session_gap_open": gaps,
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
