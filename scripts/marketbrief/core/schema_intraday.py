"""Column types of the intraday kinds (WS5; scripts/intraday_check.py, docs/ws/ws5.md; B9 additions: docs/ws/b9.md).
The trade_checks kind itself is W1's (core/schema_lab.py); B9 writes it and adds the two kinds at the end."""
from __future__ import annotations

from marketbrief.core.schema_base import Schemas
from marketbrief.intraday.constants import (
    KIND_INTRADAY_ALERTS,
    KIND_INTRADAY_CHECKS,
    KIND_INTRADAY_EXPLANATIONS,
    KIND_INTRADAY_RUNS,
    KIND_TRADE_CHECK_DETAILS,
)

INTRADAY_SCHEMAS: Schemas = {
    # One row per ticker per check (intraday_check.py), files dated by check_at's UTC date. id =
    # <check_id>-<ticker>, check_id = ic-<market>-<check_at to the minute>. Prices are the newest complete
    # 5-minute Yahoo bar by check_at; returns are fractions. quality ok | stale_quote | no_quote (no
    # measures then). band_1d / band_5d: below80 | below50 | inside50 | above50 | above80 against the
    # session's first published range. move_z = ret_since_open / (sigma_1d * sqrt(elapsed_fraction));
    # residual = ret_since_open - beta x bench_ret. calls: JSON [{source, id, horizon_days, direction,
    # prob_up, entry_date, entry_open, ret, z, against}]. candidates: JSON [{id, kind, ...}] (the ids the
    # explainer may cite; news status as of check_at).
    # B9 (additive): bands = JSON {"<k>": {range_id, lo80, lo50, hi50, hi80, sigma_h, band}} for every horizon k with
    # a published range for the session (the _1d / _5d columns repeat k = 1 and 5, kept for older readers);
    # open_trades = the ticker's open paper trades at the check (each one a trade_checks row with this row's id
    # as check_row_id); flag open_trade_flagged when at least one of them is flagged.
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
        "bands": "JSON", "open_trades": "INTEGER",
    }),
    # One row per check time (id = check_id): status ok | market_closed | stale; counts of the rows written. No
    # session open/close columns: a future close time would trip validate's future-timestamp check. B9 (additive):
    # open_trades, trades_flagged = trade_checks rows written / flagged; alerts = intraday_alerts rows written.
    KIND_INTRADAY_RUNS: ("jsonl", {
        "id": "VARCHAR", "check_at": "TIMESTAMPTZ", "session_date": "DATE", "status": "VARCHAR",
        "tickers": "INTEGER",
        "written": "INTEGER", "flagged": "INTEGER", "stale": "VARCHAR[]", "failed": "JSON",
        "note": "VARCHAR", "method_version": "VARCHAR", "computed_at": "TIMESTAMPTZ",
        "open_trades": "INTEGER", "trades_flagged": "INTEGER", "alerts": "INTEGER",
    }),
    # The deviation explainer's note per flagged check row (intraday_check.py validate|add): id = ix-<row id>;
    # text <= 60 words citing only cited_ids (each one of the row's candidate_ids); attribution = the kind of
    # cause named (or idiosyncratic | unexplained). Never a prediction or a trade instruction.
    KIND_INTRADAY_EXPLANATIONS: ("jsonl", {
        "id": "VARCHAR", "check_row_id": "VARCHAR", "check_id": "VARCHAR", "check_at": "TIMESTAMPTZ",
        "session_date": "DATE", "ticker": "VARCHAR", "flags": "VARCHAR[]", "attribution": "VARCHAR",
        "text": "VARCHAR", "cited_ids": "VARCHAR[]", "prompt_version": "VARCHAR", "created_at": "TIMESTAMPTZ",
    }),
    # B9: the measures of a trade check that W1's trade_checks columns do not hold, one row per trade_checks row
    # (same id = <check_id>-<trade_id>). quality ok | stale_quote | no_quote | no_entry_price (no measures then).
    # entry_source intraday_open (D is today) | stored_open (D's stored raw open). basis_factor = the split/bonus
    # factor from the prediction's as-of date to today's basis (adjustments detected by check_at); the *_adj
    # columns are the trade's prices on today's basis, the basis of last_price and of every measure (trade_checks
    # stores the raw entry, target and range as predicted). target_reached: a session high from D up to the
    # check (today: complete 5-minute bars only) at or above the adjusted target (F1.9); target_reached_session
    # 1 = D; null = unknown (today's quote missing and not reached before). high_since_entry_pct /
    # low_since_entry_pct: the highest high and lowest low so far vs the adjusted entry (percent points).
    # sessions_held = session_number - 1 + the elapsed share of today; sessions_left = sessions to the exit close
    # (the rest of today included); z_since_entry = return since entry / (sigma_1d x sqrt(sessions_held));
    # target_z (trade_checks) = (target_adj / last - 1) / (sigma_1d x sqrt(sessions_left)).
    KIND_TRADE_CHECK_DETAILS: ("jsonl", {
        "id": "VARCHAR", "check_id": "VARCHAR", "check_at": "TIMESTAMPTZ", "session_date": "DATE",
        "ticker": "VARCHAR", "trade_id": "VARCHAR", "family": "VARCHAR", "pick_rule": "VARCHAR",
        "quality": "VARCHAR", "entry_source": "VARCHAR", "basis_factor": "DOUBLE", "entry_adj": "DOUBLE",
        "target_adj": "DOUBLE", "lo80_adj": "DOUBLE", "lo50_adj": "DOUBLE", "hi50_adj": "DOUBLE",
        "hi80_adj": "DOUBLE", "last_time": "TIMESTAMPTZ", "sigma_1d": "DOUBLE", "elapsed_fraction": "DOUBLE",
        "sessions_held": "DOUBLE", "sessions_left": "DOUBLE", "z_since_entry": "DOUBLE",
        "target_reached": "BOOLEAN", "target_reached_session": "INTEGER", "high_since_entry_pct": "DOUBLE",
        "low_since_entry_pct": "DOUBLE", "notes": "VARCHAR[]", "method_version": "VARCHAR",
        "computed_at": "TIMESTAMPTZ",
    }),
    # B9: the intraday alerts feed for the Slack alerts (session B6), written by each check. alert_type
    # open_trade_flagged (one row per ticker with flagged open trades: id = <check_id>-<ticker>-trades; repeat =
    # every one of those trades was alerted with the same flags earlier this session) | material_news_open_trade
    # (one row per news id per ticker with an open trade, first alerted check only: id =
    # <check_id>-<ticker>-news-<news_id>). trades: JSON [{trade_id, strategy_id, view, horizon_days, flags, band,
    # ret_since_entry_pct, to_target_pct, target_reached}]; news_*: the item, its status and materiality as of
    # check_at. check_row_id: the ticker's intraday_checks row (its explainer note joins on it). Never advice.
    KIND_INTRADAY_ALERTS: ("jsonl", {
        "id": "VARCHAR", "check_id": "VARCHAR", "check_at": "TIMESTAMPTZ", "session_date": "DATE",
        "market": "VARCHAR", "ticker": "VARCHAR", "alert_type": "VARCHAR", "check_row_id": "VARCHAR",
        "trade_ids": "VARCHAR[]", "trades": "JSON", "flags": "VARCHAR[]", "repeat": "BOOLEAN",
        "news_id": "VARCHAR", "news_title": "VARCHAR", "news_source": "VARCHAR", "news_status": "VARCHAR",
        "news_materiality": "VARCHAR", "news_first_seen_at": "TIMESTAMPTZ", "method_version": "VARCHAR",
        "computed_at": "TIMESTAMPTZ",
    }),
}
