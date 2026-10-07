"""Column types of the strategy-lab kinds (W1; docs/SPEC.md F1-F7 and section 4; field meanings, sources and
examples in docs/DATA_CATALOGUE.md). Research only: a paper trade is a record, never an order.

Conventions for every kind here: horizon_days = k of N+k (1-5; the exit is the close of the k-th session after
D, the entry session; decision 37); prices are raw (unadjusted, `ohlc_raw`) in the market currency (INR for
india, USD for us); money columns (amount, pnl, costs) are in that currency too; columns ending in `_pct` are
percent points (1.25 = +1.25%); probabilities are fractions 0-1. strategy_id as in config/strategies.yaml."""
from __future__ import annotations

from marketbrief.constants.kinds import (
    KIND_EOD_ANALYSES,
    KIND_HEAD_TO_HEAD_PICKS,
    KIND_NEWS_IMPACT,
    KIND_PAPER_TRADES_SETTLED,
    KIND_RESEARCH_REVIEWS,
    KIND_STRATEGY_ABSTENTIONS,
    KIND_STRATEGY_PREDICTIONS,
    KIND_TRADE_CHECKS,
    KIND_TRADE_REASONS_AI,
)
from marketbrief.core.schema_base import Schemas
from marketbrief.core.schema_lifecycle import LIFECYCLE_SCHEMAS

LAB_SCHEMAS: Schemas = {
    # One row per strategy x company x horizon x as-of day (pre-open run), in the day file of made_at.
    # id = <strategy_id>:<as_of_date>-<ticker>-<horizon_days>d (F2.6), skipped if it exists. family rule |
    # baseline | ai. session_date = D (entry session), exit_date = the k-th session after D. prob_up = the
    # probability that the exit close is above the entry open (null for always_up and momentum, which carry no
    # probability); confidence = the probability of `direction`. qualifies = direction up and prob_up >=
    # threshold (baselines: direction up), i.e. the prediction becomes an accuracy-view trade (F1.2). base_close
    # = C, the latest stored close at made_at; target_price = the expected exit close; lo50..hi80 = the range for
    # this horizon (ranges.py, widened only by range_widen); range_id = that ranges row. model_score_id /
    # model_prob / agent_adjustment / adjustment_reason: the forecast-v11 anchor (combined AI traders and
    # model-based rule strategies). evidence_ids: news/filing ids, or for strategies citing no news the feature
    # snapshot and model score ids (F2.6). reason: the AI trader's <= 60 words (null for rule strategies).
    # amount: the company's paper amount at made_at (F1.3). config_hash: sha256 of the strategy's registry entry.
    KIND_STRATEGY_PREDICTIONS: ("jsonl", {
        "id": "VARCHAR", "strategy_id": "VARCHAR", "family": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR",
        "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "session_date": "DATE", "exit_date": "DATE",
        "horizon_days": "INTEGER", "direction": "VARCHAR", "prob_up": "DOUBLE", "confidence": "DOUBLE",
        "threshold": "DOUBLE", "qualifies": "BOOLEAN", "base_close": "DOUBLE", "target_price": "DOUBLE",
        "range_id": "VARCHAR", "lo50": "DOUBLE", "hi50": "DOUBLE", "lo80": "DOUBLE", "hi80": "DOUBLE",
        "range_widen": "DOUBLE", "model_score_id": "VARCHAR", "model_prob": "DOUBLE", "agent_adjustment": "DOUBLE",
        "adjustment_reason": "VARCHAR", "evidence_ids": "VARCHAR[]", "reason": "VARCHAR", "regime": "VARCHAR",
        "quality": "VARCHAR", "amount": "DOUBLE", "currency": "VARCHAR", "config_hash": "VARCHAR",
        "prompt_version": "VARCHAR", "method_version": "VARCHAR",
    }),
    # One row per AI trader (or a rule strategy refused by the shared gate) x company x as-of day without a
    # prediction (F4.3): id = <strategy_id>:<as_of_date>-<ticker>. reason_code abstained | gate_failed |
    # timeout | blocked_quality | earnings_window | killed; horizons: the horizons it did not predict; gate_codes:
    # the gate's failure codes after the retry; reason: the trader's own words when it abstained (<= 60 words).
    KIND_STRATEGY_ABSTENTIONS: ("jsonl", {
        "id": "VARCHAR", "strategy_id": "VARCHAR", "family": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR",
        "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "session_date": "DATE", "horizons": "INTEGER[]",
        "reason_code": "VARCHAR", "reason": "VARCHAR", "gate_codes": "VARCHAR[]", "attempts": "INTEGER",
        "prompt_version": "VARCHAR",
    }),
    # One row per settled trade x view (post-close run, F1 engine), in the day file of settled_at. trade_id =
    # acc:<prediction_id> (accuracy view) or h2h:<pick_rule>:<prediction_id> (head-to-head view); id =
    # <trade_id>@<settled_at as YYYYMMDDTHHMMSSZ>, so a re-settlement (adjustment corrected) is a new row whose
    # supersedes names the old id. pick_rule best_expected_gain | highest_probability (head-to-head only).
    # status settled | no_entry | skipped_price_above_amount; flags: exit_delayed, split_in_window, resettled.
    # quantity: from D's raw open (India whole shares, US 6 decimals), never recomputed; exit_quantity: times the
    # split ratio of adjustment_ids. costs: the round trip (F1.6), cost_lines JSON {charge: amount}. return_pct
    # = net_pnl / amount x 100. target_error_pct = (exit_price / target_price - 1) x 100. range_hit: exit close
    # inside lo80..hi80. target_reached*: highs from D to the exit session on adjusted bars (session 1 = D).
    # The automatic reason (F1.10): move_pct = exit vs entry; market_pct / sector_pct / news_pct / company_pct
    # its parts (they add up to move_pct); reason_code the main one, reason_codes all; news_ids the verified
    # news inside the window; reason_detail JSON (benchmark, sector source, beta, statuses).
    KIND_PAPER_TRADES_SETTLED: ("jsonl", {
        "id": "VARCHAR", "trade_id": "VARCHAR", "prediction_id": "VARCHAR", "strategy_id": "VARCHAR",
        "family": "VARCHAR", "view": "VARCHAR", "pick_rule": "VARCHAR", "pick_id": "VARCHAR", "market": "VARCHAR",
        "ticker": "VARCHAR", "horizon_days": "INTEGER", "made_at": "TIMESTAMPTZ", "entry_date": "DATE",
        "exit_date": "DATE", "exit_date_actual": "DATE", "status": "VARCHAR", "flags": "VARCHAR[]",
        "amount": "DOUBLE", "currency": "VARCHAR", "entry_price": "DOUBLE", "exit_price": "DOUBLE",
        "quantity": "DOUBLE", "exit_quantity": "DOUBLE", "adjustment_ids": "VARCHAR[]", "entry_value": "DOUBLE",
        "exit_value": "DOUBLE", "gross_pnl": "DOUBLE", "costs": "DOUBLE", "cost_lines": "JSON", "net_pnl": "DOUBLE",
        "return_pct": "DOUBLE", "prob_up": "DOUBLE", "target_price": "DOUBLE", "target_error_pct": "DOUBLE",
        "lo80": "DOUBLE", "hi80": "DOUBLE", "range_hit": "BOOLEAN", "target_reached": "BOOLEAN",
        "target_reached_session": "INTEGER", "max_favourable_pct": "DOUBLE", "max_adverse_pct": "DOUBLE",
        "move_pct": "DOUBLE", "market_pct": "DOUBLE", "sector_pct": "DOUBLE", "news_pct": "DOUBLE",
        "company_pct": "DOUBLE", "reason_code": "VARCHAR", "reason_codes": "VARCHAR[]", "news_ids": "VARCHAR[]",
        "reason_detail": "JSON", "regime": "VARCHAR", "supersedes": "VARCHAR", "settled_at": "TIMESTAMPTZ",
        "method_version": "VARCHAR",
    }),
    # One row per company x as-of day x family (rule | ai) x pick rule (pre-open run, F1.7): id =
    # h2h:<as_of_date>-<ticker>-<family>-<pick_rule>. status picked | no_candidate. strongest_basis per_company
    # (>= 20 settled trades on it) | all_companies; ranking: JSON [{strategy_id, rank, basis, settled_trades,
    # net_pnl}] the strongest strategy came from. candidates: JSON per candidate horizon [{horizon_days,
    # prediction_id, prob_up, move_pct, loss_pct, costs_pct, expected_gain_pct}]; the chosen one is repeated in
    # the flat columns. Both pick rules are recorded even when they name the same horizon (F1.7.4).
    KIND_HEAD_TO_HEAD_PICKS: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "ticker": "VARCHAR", "made_at": "TIMESTAMPTZ", "as_of_date": "DATE",
        "session_date": "DATE", "family": "VARCHAR", "pick_rule": "VARCHAR", "status": "VARCHAR",
        "strategy_id": "VARCHAR", "strongest_basis": "VARCHAR", "ranking": "JSON", "horizon_days": "INTEGER",
        "prediction_id": "VARCHAR", "base_close": "DOUBLE", "prob_up": "DOUBLE", "move_pct": "DOUBLE",
        "loss_pct": "DOUBLE", "costs_pct": "DOUBLE", "expected_gain_pct": "DOUBLE", "candidates": "JSON",
        "amount": "DOUBLE", "currency": "VARCHAR", "method_version": "VARCHAR",
    }),
    # The EOD analyst's reason per head-to-head trade settled today and per day's 5 biggest wins and misses
    # (F6.1, decision 43), gated: id = tra:<trade_id> (head_to_head) or tra:<trade_id>:<kind> (a biggest win or
    # miss, so a head-to-head trade that is also among the biggest gets both). kind head_to_head | biggest_win |
    # biggest_miss; rank 1-5 for the biggest (null for head_to_head). text <= 60 words grounded in the trade's
    # automatic reason; cited_ids: the trade id plus news/filing ids it names.
    KIND_TRADE_REASONS_AI: ("jsonl", {
        "id": "VARCHAR", "trade_id": "VARCHAR", "settlement_id": "VARCHAR", "market": "VARCHAR",
        "ticker": "VARCHAR", "strategy_id": "VARCHAR", "session_date": "DATE", "kind": "VARCHAR", "rank": "INTEGER",
        "text": "VARCHAR", "cited_ids": "VARCHAR[]", "reason_codes": "VARCHAR[]", "prompt_version": "VARCHAR",
        "created_at": "TIMESTAMPTZ",
    }),
    # One row per open paper trade x intraday check (F5; extends WS5 intraday_checks; written by B9): id =
    # <check_id>-<trade_id>, check_id as in intraday_checks (ic-<market>-<check_at to the minute as
    # YYYY-MM-DDTHH:MMZ>, e.g. ic-us-2026-10-07T16:27Z); check_row_id = that ticker's intraday_checks row (market,
    # sector, news candidates live there), null for a ticker not on the watchlist (no such row). session_number:
    # which session of the holding window today is (1 = D). entry_price, target_price and lo80..hi80 are stored as
    # predicted (raw); every measure is on today's price basis: ret_since_entry_pct = (last / entry_adj - 1) x 100;
    # to_target_pct = (target_adj / last - 1) x 100; band below80 | below50 | inside50 | above50 | above80 against
    # the adjusted range; target_z = (target_adj / last - 1) / (sigma_1d x sqrt(sessions_left)). flags outside_range
    # | far_from_target | against_prediction.
    # Added for B9 (issue #78, additive; rows written before it hold them in B9's trade_check_details, joined by the
    # view trade_check_rows): family, pick_rule (head-to-head trades); quality ok | stale_quote | no_quote |
    # no_entry_price (no measures and no flags unless ok); entry_source intraday_open (D is today) | stored_open;
    # basis_factor = the split/bonus factor from the prediction's as-of date to today's basis (adjustments detected
    # by check_at), entry_adj, target_adj, lo80_adj..hi80_adj the trade's prices on that basis; last_time = the
    # 5-minute bar of last_price; sigma_1d, elapsed_fraction (share of today's session elapsed), sessions_held =
    # session_number - 1 + elapsed_fraction, sessions_left = sessions to the exit close (the rest of today
    # included), z_since_entry = return since entry / (sigma_1d x sqrt(sessions_held)); target_reached /
    # target_reached_session (F1.9 so far: a session high from D up to the check at or above target_adj; 1 = D; null
    # = unknown); high_since_entry_pct / low_since_entry_pct vs entry_adj; notes no_bar_<date> | no_sigma |
    # not_on_watchlist.
    KIND_TRADE_CHECKS: ("jsonl", {
        "id": "VARCHAR", "check_id": "VARCHAR", "check_row_id": "VARCHAR", "check_at": "TIMESTAMPTZ",
        "session_date": "DATE", "market": "VARCHAR", "ticker": "VARCHAR", "trade_id": "VARCHAR",
        "prediction_id": "VARCHAR", "strategy_id": "VARCHAR", "view": "VARCHAR", "horizon_days": "INTEGER",
        "entry_date": "DATE", "exit_date": "DATE", "session_number": "INTEGER", "entry_price": "DOUBLE",
        "last_price": "DOUBLE", "ret_since_entry_pct": "DOUBLE", "target_price": "DOUBLE", "to_target_pct": "DOUBLE",
        "lo80": "DOUBLE", "lo50": "DOUBLE", "hi50": "DOUBLE", "hi80": "DOUBLE", "band": "VARCHAR",
        "target_z": "DOUBLE", "flags": "VARCHAR[]", "flagged": "BOOLEAN", "method_version": "VARCHAR",
        "computed_at": "TIMESTAMPTZ",
        "family": "VARCHAR", "pick_rule": "VARCHAR", "quality": "VARCHAR", "entry_source": "VARCHAR",
        "basis_factor": "DOUBLE", "entry_adj": "DOUBLE", "target_adj": "DOUBLE", "lo80_adj": "DOUBLE",
        "lo50_adj": "DOUBLE", "hi50_adj": "DOUBLE", "hi80_adj": "DOUBLE", "last_time": "TIMESTAMPTZ",
        "sigma_1d": "DOUBLE", "elapsed_fraction": "DOUBLE", "sessions_held": "DOUBLE", "sessions_left": "DOUBLE",
        "z_since_entry": "DOUBLE", "target_reached": "BOOLEAN", "target_reached_session": "INTEGER",
        "high_since_entry_pct": "DOUBLE", "low_since_entry_pct": "DOUBLE", "notes": "VARCHAR[]",
    }),
    # The EOD analyst's day summary per market (F6.1), gated: id = eod-<market>-<session_date>. results: JSON of
    # the day's deterministic numbers it was given ({family: {trades, wins, net_pnl, return_pct}}, per pick rule);
    # summary <= 150 words citing ids; reason_ids: the trade_reasons_ai rows written with it.
    KIND_EOD_ANALYSES: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "session_date": "DATE", "settled_trades": "INTEGER",
        "results": "JSON", "summary": "VARCHAR", "cited_ids": "VARCHAR[]", "reason_ids": "VARCHAR[]",
        "prompt_version": "VARCHAR", "created_at": "TIMESTAMPTZ",
    }),
    # The weekly research director's report per market (F6.2): id = rr-<market>-<iso_week> (e.g. 2026-W41).
    # leaders: JSON list of {scope, strategy_id, net_pnl, trades}; findings: JSON list of {text, cited_ids};
    # proposals: JSON list of {proposal_id, kind: new_strategy_version | weight | threshold, file, diff, rationale,
    # cited_ids, status: proposed} for the owner to approve (it changes nothing itself). report_path: the markdown.
    KIND_RESEARCH_REVIEWS: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "iso_week": "VARCHAR", "period_start": "DATE", "period_end": "DATE",
        "leaders": "JSON", "findings": "JSON", "proposals": "JSON", "report_path": "VARCHAR",
        "prompt_version": "VARCHAR", "written_at": "TIMESTAMPTZ",
    }),
    # The news-impact study (F3), weekly, as of the review date (inputs <= as_of): one row per market x week x
    # event_type x status x materiality x horizon. id = ni-<market>-<iso_week>-<event_type>-<status>-<materiality>-
    # <horizon_days>. abnormal return = the stock's return over N+k minus beta x its benchmark's (benchmark_pct)
    # and its sector's (sector_pct) where available; mean and 95% interval in percent points; enough false when
    # n_events < the minimum (shown as "not enough events yet").
    KIND_NEWS_IMPACT: ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "iso_week": "VARCHAR", "as_of": "TIMESTAMPTZ", "event_type": "VARCHAR",
        "status": "VARCHAR", "materiality": "VARCHAR", "horizon_days": "INTEGER", "n_events": "INTEGER",
        "mean_abnormal_pct": "DOUBLE", "ci_low_pct": "DOUBLE", "ci_high_pct": "DOUBLE",
        "mean_benchmark_pct": "DOUBLE", "mean_sector_pct": "DOUBLE", "enough": "BOOLEAN", "news_ids": "VARCHAR[]",
        "method_version": "VARCHAR", "computed_at": "TIMESTAMPTZ",
    }),
}

# Every W1 kind (registered in core/schemas.py with one spread line): the lab kinds and the lifecycle kinds.
W1_SCHEMAS: Schemas = {**LAB_SCHEMAS, **LIFECYCLE_SCHEMAS}
