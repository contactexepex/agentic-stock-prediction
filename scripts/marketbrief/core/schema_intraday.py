"""Column types of the intraday kinds (WS5; scripts/intraday_check.py, docs/ws/ws5.md)."""
from __future__ import annotations

from marketbrief.core.schema_base import Schemas
from marketbrief.intraday.constants import KIND_INTRADAY_CHECKS, KIND_INTRADAY_EXPLANATIONS, KIND_INTRADAY_RUNS

INTRADAY_SCHEMAS: Schemas = {
    # One row per ticker per check (intraday_check.py), files dated by check_at's UTC date. id =
    # <check_id>-<ticker>, check_id = ic-<market>-<check_at to the minute>. Prices are the newest complete
    # 5-minute Yahoo bar by check_at; returns are fractions. quality ok | stale_quote | no_quote (no
    # measures then). band_1d / band_5d: below80 | below50 | inside50 | above50 | above80 against the
    # session's first published range. move_z = ret_since_open / (sigma_1d * sqrt(elapsed_fraction));
    # residual = ret_since_open - beta x bench_ret. calls: JSON [{source, id, horizon_days, direction,
    # prob_up, entry_date, entry_open, ret, z, against}]. candidates: JSON [{id, kind, ...}] (the ids the
    # explainer may cite; news status as of check_at).
    KIND_INTRADAY_CHECKS: ("jsonl", {
        "id": "VARCHAR", "check_id": "VARCHAR", "check_at": "TIMESTAMPTZ", "session_date": "DATE",
        "ticker": "VARCHAR", "yahoo": "VARCHAR", "quality": "VARCHAR", "last_price": "DOUBLE",
        "last_time": "TIMESTAMPTZ", "open_price": "DOUBLE", "prev_close": "DOUBLE", "gap": "DOUBLE",
        "ret_since_open": "DOUBLE", "elapsed_fraction": "DOUBLE", "sigma_1d": "DOUBLE", "move_z": "DOUBLE",
        "range_id_1d": "VARCHAR", "lo80_1d": "DOUBLE", "lo50_1d": "DOUBLE", "hi50_1d": "DOUBLE",
        "hi80_1d": "DOUBLE", "band_1d": "VARCHAR", "range_id_5d": "VARCHAR", "lo80_5d": "DOUBLE",
        "hi80_5d": "DOUBLE", "band_5d": "VARCHAR", "bench_ret": "DOUBLE", "sector_ret": "DOUBLE",
        "sector_source": "VARCHAR", "beta": "DOUBLE", "residual": "DOUBLE", "residual_z": "DOUBLE",
        "sector_residual": "DOUBLE", "calls": "JSON", "flags": "VARCHAR[]", "flagged": "BOOLEAN",
        "candidates": "JSON", "candidate_ids": "VARCHAR[]", "notes": "VARCHAR[]",
        "method_version": "VARCHAR", "computed_at": "TIMESTAMPTZ",
    }),
    # One row per check time (id = check_id): status ok | market_closed | stale; counts of the rows written. No
    # session open/close columns: a future close time would trip validate's future-timestamp check.
    KIND_INTRADAY_RUNS: ("jsonl", {
        "id": "VARCHAR", "check_at": "TIMESTAMPTZ", "session_date": "DATE", "status": "VARCHAR",
        "tickers": "INTEGER",
        "written": "INTEGER", "flagged": "INTEGER", "stale": "VARCHAR[]", "failed": "JSON",
        "note": "VARCHAR", "method_version": "VARCHAR", "computed_at": "TIMESTAMPTZ",
    }),
    # The deviation explainer's note per flagged check row (intraday_check.py validate|add): id = ix-<row id>;
    # text <= 60 words citing only cited_ids (each one of the row's candidate_ids); attribution = the kind of
    # cause named (or idiosyncratic | unexplained). Never a prediction or a trade instruction.
    KIND_INTRADAY_EXPLANATIONS: ("jsonl", {
        "id": "VARCHAR", "check_row_id": "VARCHAR", "check_id": "VARCHAR", "check_at": "TIMESTAMPTZ",
        "session_date": "DATE", "ticker": "VARCHAR", "flags": "VARCHAR[]", "attribution": "VARCHAR",
        "text": "VARCHAR", "cited_ids": "VARCHAR[]", "prompt_version": "VARCHAR", "created_at": "TIMESTAMPTZ",
    }),
}
