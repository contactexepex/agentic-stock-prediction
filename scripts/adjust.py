"""Split and bonus adjustments of stored price bars (issue #31): helpers shared by
collect_prices.py (detection), score_predictions.py (scoring across an ex-date) and the tests.

Why: yfinance's `Close` (auto_adjust=False) is not dividend-adjusted but IS split/bonus-adjusted
as of the collection time, and bars in data/<market>/prices/ are written once. After a split or
bonus the stored bars before its ex-date stay on the old basis while new bars come on the new
one. Each confirmed corporate action is therefore recorded once in
data/<market>/adjustments/YYYY/MM/<ex-date>.jsonl (schema `adjustments` in common.py) and applied
on read: the `ohlc` and `bars` views (sql/views.sql) multiply the prices of every bar before an
ex-date by that action's `factor` (0.5 for a 1:1 bonus or a 2:1 split) and divide its volume by it,
cumulatively over all later actions; `ohlc_raw` and `bars_raw` keep the bars as stored.
Dividends are never adjusted."""
from __future__ import annotations

import json
from datetime import date, datetime
from fractions import Fraction

from common import data_dir

SPLIT_TOL = 0.01     # a measured price ratio vs a split factor (Yahoo rounds closes)
MATCH_TOL = 0.02     # |Yahoo close / stored close - 1| above this: the stored bar is on another basis
MAX_TERM = 20        # a split factor is p/q with p, q <= MAX_TERM (1:1 bonus 1/2, 1:10 bonus 10/11, 3:2 split 2/3)
FRACTION_TOL = 0.001  # a re-based close is the old one x factor up to Yahoo's rounding


def _day(v) -> date:
    if isinstance(v, datetime):     # also pandas Timestamps
        return v.date()
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def load(market: str, include_superseded: bool = False) -> list[dict]:
    """The stored adjustments of a market, one per id (the first detected wins), ex_date as a date.
    A wrong record is corrected by appending a new one (own id, e.g. `<ticker>-<ex_date>-fix1`,
    `supersedes` = the wrong id, `factor` 1.0 to cancel it or the right factor, a `note`): a
    superseded record is left out (as by the price_adjustments view) unless include_superseded."""
    rows: dict[str, dict] = {}
    for f in sorted((data_dir(market) / "adjustments").glob("**/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["id"] not in rows or str(r.get("detected_at")) < str(rows[r["id"]].get("detected_at")):
                rows[r["id"]] = {**r, "ex_date": _day(r["ex_date"])}
    if include_superseded:
        return list(rows.values())
    gone = {r.get("supersedes") for r in rows.values() if r.get("supersedes")}
    return [r for i, r in rows.items() if i not in gone]


def factor_after(adjs, ticker: str, d, detected_after=None) -> float:
    """Price multiplier that puts a stored bar of `ticker` dated `d` on the newest basis: the
    product of the factors of every adjustment with ex_date > d. With `detected_after` (a time),
    only adjustments detected after it count (the part a record made at that time did not see)."""
    d, out = _day(d), 1.0
    for a in adjs:
        if a["ticker"] != ticker or _day(a["ex_date"]) <= d:
            continue
        if detected_after is not None and not _later(a.get("detected_at"), detected_after):
            continue
        out *= float(a["factor"])
    return out


def _utc(t):
    import pandas as pd
    ts = pd.Timestamp(t)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _later(t, ref) -> bool:
    """True when time t is after time ref (naive times are UTC); a missing t never is."""
    if t is None or (isinstance(t, float) and t != t):
        return False
    return _utc(t) > _utc(ref)


def split_fraction(x: float) -> Fraction | None:
    """The simple fraction p/q (p, q <= MAX_TERM, not 1) within FRACTION_TOL of x, or None:
    a price ratio a split, bonus or consolidation can produce."""
    if not x or x <= 0:
        return None
    fr = Fraction(x).limit_denominator(MAX_TERM)
    if fr == 1 or fr.numerator > MAX_TERM or fr.denominator > MAX_TERM or abs(float(fr) / x - 1) > FRACTION_TOL:
        return None
    return fr


def record(ticker: str, ex_date: date, factor: float, source: str, now: str, **evidence) -> dict:
    """One adjustments row (schema `adjustments` in common.py)."""
    return {"id": f"{ticker}-{ex_date}", "ticker": ticker, "ex_date": str(ex_date), "factor": factor,
            "volume_factor": 1 / factor, "source": source, **evidence, "detected_at": now}
