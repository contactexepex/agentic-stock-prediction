"""Split and bonus adjustments of stored price bars (issue #31): helpers shared by the prices collector
(detection), score_predictions.py (scoring across an ex-date) and the tests.

Why: yfinance's `Close` (auto_adjust=False) is not dividend-adjusted but IS split/bonus-adjusted
as of the collection time, and bars in data/<market>/prices/ are written once. After a split or
bonus the stored bars before its ex-date stay on the old basis while new bars come on the new
one. Each confirmed corporate action is therefore recorded once in
data/<market>/adjustments/YYYY/MM/<ex-date>.jsonl (schema `adjustments` in marketbrief/core/schemas.py) and applied
on read: the `ohlc` and `bars` views (sql/views.sql) multiply the prices of every bar before an
ex-date by that action's `factor` (0.5 for a 1:1 bonus or a 2:1 split) and divide its volume by it,
cumulatively over all later actions; `ohlc_raw` and `bars_raw` keep the bars as stored.
Dividends are never adjusted."""

from __future__ import annotations

import json
from datetime import date, datetime
from fractions import Fraction

import pandas as pd

from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.kinds import KIND_ADJUSTMENTS
from marketbrief.constants.price_adjustments import (
    FRACTION_TOLERANCE,
    KEY_DETECTED_AT,
    KEY_EX_DATE,
    KEY_FACTOR,
    KEY_SUPERSEDES,
    MAX_SPLIT_TERM,
)
from marketbrief.core.paths import data_dir

ISO_DATE_LENGTH = 10


def as_date(value) -> date:
    """A date from a date, a datetime (also a pandas Timestamp) or an ISO string."""
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:ISO_DATE_LENGTH])


def load_adjustments(market: str, include_superseded: bool = False) -> list[dict]:
    """The stored adjustments of a market, one per id (the first detected wins), ex_date as a date.
    A wrong record is corrected by appending a new one (own id, e.g. `<ticker>-<ex_date>-fix1`,
    `supersedes` = the wrong id, `factor` 1.0 to cancel it or the right factor, a `note`): a
    superseded record is left out (as by the price_adjustments view) unless include_superseded."""
    rows: dict[str, dict] = {}
    for file in sorted((data_dir(market) / KIND_ADJUSTMENTS).glob(JSONL_GLOB)):
        for line in file.read_text(encoding=ENCODING_UTF8).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            known = rows.get(row[COL_ID])
            if known is None or str(row.get(KEY_DETECTED_AT)) < str(known.get(KEY_DETECTED_AT)):
                rows[row[COL_ID]] = {**row, KEY_EX_DATE: as_date(row[KEY_EX_DATE])}
    if include_superseded:
        return list(rows.values())
    superseded = {row.get(KEY_SUPERSEDES) for row in rows.values() if row.get(KEY_SUPERSEDES)}
    return [row for row_id, row in rows.items() if row_id not in superseded]


def factor_after(adjustments, ticker: str, day, detected_after=None) -> float:
    """Price multiplier that puts a stored bar of `ticker` dated `day` on the newest basis: the
    product of the factors of every adjustment with ex_date > day. With `detected_after` (a time),
    only adjustments detected after it count (the part a record made at that time did not see)."""
    day, product = as_date(day), 1.0
    for adjustment in adjustments:
        if adjustment[COL_TICKER] != ticker or as_date(adjustment[KEY_EX_DATE]) <= day:
            continue
        if detected_after is not None and not _later(adjustment.get(KEY_DETECTED_AT), detected_after):
            continue
        product *= float(adjustment[KEY_FACTOR])
    return product


def _utc(moment):
    """A pandas UTC timestamp (naive times are UTC)."""
    stamp = pd.Timestamp(moment)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _later(moment, reference) -> bool:
    """True when time `moment` is after time `reference` (naive times are UTC); a missing one never is."""
    if moment is None or (isinstance(moment, float) and moment != moment):
        return False
    return _utc(moment) > _utc(reference)


def split_fraction(ratio: float) -> Fraction | None:
    """The simple fraction p/q (p, q <= MAX_SPLIT_TERM, not 1) within FRACTION_TOLERANCE of `ratio`, or
    None: a price ratio a split, bonus or consolidation can produce."""
    if not ratio or ratio <= 0:
        return None
    fraction = Fraction(ratio).limit_denominator(MAX_SPLIT_TERM)
    too_large = fraction.numerator > MAX_SPLIT_TERM or fraction.denominator > MAX_SPLIT_TERM
    if fraction == 1 or too_large or abs(float(fraction) / ratio - 1) > FRACTION_TOLERANCE:
        return None
    return fraction


def adjustment_record(ticker: str, ex_date: date, factor: float, source: str, now: str, **evidence) -> dict:
    """One adjustments row (schema `adjustments` in marketbrief/core/schemas.py)."""
    return {
        "id": f"{ticker}-{ex_date}",
        "ticker": ticker,
        "ex_date": str(ex_date),
        "factor": factor,
        "volume_factor": 1 / factor,
        "source": source,
        **evidence,
        "detected_at": now,
    }
