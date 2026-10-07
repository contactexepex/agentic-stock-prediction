"""Per-horizon model scores and ranges as of a time (marketbrief/contracts/horizons.py; docs/SPEC.md F2.7, B10).

The records B2 (strategy lab), B3 (AI traders) and B9 (monitoring) read: today's `model_scores` and `ranges`
columns plus `horizon_label`, `entry_date` and `exit_date`. Only N+k rows (horizon_label n_plus_k, written by
model_scores.py and ranges.py from B10 on; old open-to-close 1-day scores count as N+1, the same window) are
returned: a legacy row is never offered as an N+k one. Nothing computed after `as_of` is used (no look-ahead)."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from marketbrief.constants.model import (KIND_MODEL_SCORES, KIND_MODEL_VARIANT_SCORES, MODEL_VARIANTS,
                                         MSG_UNKNOWN_VARIANT, VARIANT_BASE)
from marketbrief.constants.horizons import LABEL_N_PLUS_K, SQL_LABEL_MODEL_SCORES, SQL_LABEL_RANGES
from marketbrief.core.database import connect
from marketbrief.core.horizons import entry_exit
from marketbrief.core.market_config import load_market

# The newest score per id computed by the time; then per ticker and horizon the newest as-of date. {source}: the base
# model's model_scores, or another variant's rows of model_variant_scores.
SCORES_SQL = f"""
WITH known AS (
    SELECT DISTINCT ON (id) * REPLACE ({SQL_LABEL_MODEL_SCORES} AS horizon_label)
    FROM {{source}} WHERE computed_at <= ?::TIMESTAMPTZ
    ORDER BY id, computed_at DESC, prob_up, model_id
)
SELECT DISTINCT ON (ticker, horizon_days) * FROM known
WHERE horizon_label = '{LABEL_N_PLUS_K}' AND (? IS NULL OR horizon_days = ?)
ORDER BY ticker, horizon_days, as_of_date DESC"""

# The first published range per id made by the time, of the newest as-of date with any N+k range by then.
RANGES_SQL = f"""
WITH known AS (
    SELECT DISTINCT ON (id) * REPLACE ({SQL_LABEL_RANGES} AS horizon_label)
    FROM ranges WHERE made_at <= ?::TIMESTAMPTZ ORDER BY id, made_at
), current AS (
    SELECT * FROM known WHERE horizon_label = '{LABEL_N_PLUS_K}'
)
SELECT * FROM current
WHERE as_of_date = (SELECT max(as_of_date) FROM current) AND (? IS NULL OR horizon_days = ?)
ORDER BY ticker, horizon_days"""


def as_timestamp(as_of) -> pd.Timestamp:
    """A timezone-aware time (a naive one is read as UTC)."""
    stamp = pd.Timestamp(as_of)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp


def plain(value):
    """A DuckDB/pandas cell as a plain Python value (dates as date, timestamps as datetime, NaN and NaT as None)."""
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, float) and value != value:
        return None
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        return value.tolist()
    return value


def with_window(cfg: dict, rec: dict) -> dict:
    """Fill entry_date (D) and exit_date (the k-th session after D) from the market calendar when a row lacks them
    (old open-to-close 1-day scores, which are N+1)."""
    if rec.get("entry_date") is None or rec.get("exit_date") is None:
        entry, exit_day = entry_exit(cfg, pd.Timestamp(rec["as_of_date"]).date(), int(rec["horizon_days"]))
        rec["entry_date"], rec["exit_date"] = entry, exit_day
    for key in ("as_of_date", "session_date", "target_date", "entry_date", "exit_date", "trained_until"):
        if isinstance(rec.get(key), datetime):
            rec[key] = rec[key].date()
    return rec


def variant_name(variant: str) -> str:
    """A known model variant's name (constants/model.py MODEL_VARIANTS), else exit with a message."""
    if variant not in MODEL_VARIANTS:
        raise SystemExit(MSG_UNKNOWN_VARIANT.format(variant=variant, known=", ".join(MODEL_VARIANTS)))
    return variant


def scores_asof(market: str, as_of, horizon_days: int | None = None, con=None,
                variant: str = VARIANT_BASE) -> list[dict]:
    """The newest N+k model score per ticker and horizon computed by `as_of` (HorizonScore records) of one model
    variant: base (config/model.yaml as written) or cross_market (every cross-market group on)."""
    con = con or connect(market)
    cfg = load_market(market)
    source = KIND_MODEL_SCORES if variant == VARIANT_BASE else (
        f"(SELECT * FROM {KIND_MODEL_VARIANT_SCORES} WHERE model_variant = '{variant_name(variant)}')")
    frame = con.execute(SCORES_SQL.format(source=source), [as_timestamp(as_of), horizon_days, horizon_days]).df()
    out = []
    for rec in frame.to_dict("records"):
        rec = {key: plain(value) for key, value in rec.items()}
        if isinstance(rec.get("contributions"), str):
            rec["contributions"] = json.loads(rec["contributions"])
        out.append(with_window(cfg, rec))
    return out


def ranges_asof(market: str, as_of, horizon_days: int | None = None, con=None) -> list[dict]:
    """The first published N+k range per ticker and horizon of the newest as-of date ranged by `as_of`
    (HorizonRange records; the range a strategy prediction copies)."""
    con = con or connect(market)
    cfg = load_market(market)
    frame = con.execute(RANGES_SQL, [as_timestamp(as_of), horizon_days, horizon_days]).df()
    return [with_window(cfg, {key: plain(value) for key, value in rec.items()}) for rec in frame.to_dict("records")]

