"""Column types of the base data kinds (prices, news, predictions, ranges, outcomes, replays ...)."""
from __future__ import annotations

# Indicator columns written by features.py (formulas in indicators.py).
FEATURE_COLS: dict[str, str] = {
    "close": "DOUBLE", "bars": "INTEGER",
    "ret_1d": "DOUBLE", "ret_3d": "DOUBLE", "ret_5d": "DOUBLE", "ret_20d": "DOUBLE",
    "ema_ratio": "DOUBLE", "rsi_14": "DOUBLE", "roc_10": "DOUBLE", "price_vs_20d_high": "DOUBLE",
    "atr_14": "DOUBLE", "atr_pct": "DOUBLE", "realized_vol_10d": "DOUBLE", "ewma_vol": "DOUBLE",
    "bb_width": "DOUBLE", "obv_trend": "DOUBLE", "volume_ratio_20d": "DOUBLE",
    "beta_1y": "DOUBLE", "rel_sector_5d": "DOUBLE", "cue_change_pct": "DOUBLE",
    "days_to_earnings": "INTEGER", "ex_dividend_date": "DATE",
    "quality": "VARCHAR", "warnings": "VARCHAR[]",
}

Schemas = dict[str, tuple[str, dict[str, str]]]

# kind -> (file extension, column types). This is the single source of truth for schemas.
BASE_SCHEMAS: Schemas = {
    "news": ("jsonl", {
        "id": "VARCHAR", "title": "VARCHAR", "url": "VARCHAR", "source": "VARCHAR",
        "published_at": "TIMESTAMPTZ", "first_seen_at": "TIMESTAMPTZ",
        "feed": "VARCHAR", "category": "VARCHAR", "tickers": "VARCHAR[]",
        # tickers = primary_tickers (the item is about them) + mentioned_tickers (named in passing);
        # tag_confidence high|low|null (low: several title companies, comparison/list, summary-only).
        # source_domain: the RSS <source url> host (Google News), part of the id; tag_version:
        # the news_tags.py tagger that set the tags (missing on older rows: re-tagged on read)
        "primary_tickers": "VARCHAR[]", "mentioned_tickers": "VARCHAR[]", "tag_confidence": "VARCHAR",
        "source_domain": "VARCHAR", "tag_version": "INTEGER",
    }),
    "news_enriched": ("jsonl", {
        "id": "VARCHAR", "analyzed_at": "TIMESTAMPTZ", "relevance": "DOUBLE",
        "sentiment": "DOUBLE", "novelty": "DOUBLE", "materiality": "VARCHAR",
        "event_type": "VARCHAR", "urgency": "VARCHAR", "geopolitical": "BOOLEAN",
        "priced_in": "BOOLEAN", "summary": "VARCHAR", "prompt_version": "VARCHAR",
    }),
    # News verification phase A (docs/DESIGN.md 3a; config/news_sources.yaml). One row per news id
    # (collect_articles.py): the article page behind a material watchlist headline. access: full |
    # partial | paywalled (isAccessibleForFree false: description only) | blocked (refused, or an
    # outlet that refuses cloud traffic) | undecoded (Google News link not resolved) | skipped_unlisted
    # (not an allowlisted HTTPS host: never requested). No article text: extract = at most 3 key
    # sentences of <= 40 words; numbers normalised ('3.8e+09 usd', '24.7 pct'); minhash = hex MinHash
    # (128 x 32-bit) of the 6-word shingles, shingle_count their number (copy detection).
    "news_articles": ("jsonl", {
        "id": "VARCHAR", "fetched_at": "TIMESTAMPTZ", "ticker": "VARCHAR", "source_url": "VARCHAR",
        "final_url": "VARCHAR", "domain": "VARCHAR", "tier": "VARCHAR", "http_status": "INTEGER",
        "access": "VARCHAR", "extractor": "VARCHAR", "chars": "INTEGER", "date_published": "TIMESTAMPTZ",
        "date_modified": "TIMESTAMPTZ", "byline": "VARCHAR", "provider": "VARCHAR", "origin_wire": "VARCHAR",
        "origin_evidence": "VARCHAR", "sources_say": "BOOLEAN", "promotional": "VARCHAR",
        "extract": "VARCHAR[]", "numbers": "VARCHAR[]", "content_hash": "VARCHAR", "shingle_count": "INTEGER",
        "minhash": "VARCHAR", "note": "VARCHAR", "method_version": "VARCHAR",
    }),
    # Same-event clusters per ticker (news_clusters.py), appended per run when a cluster is new or
    # changed: as_of = the run time; every input (item first_seen_at, article fetched_at, primary
    # accepted/published time) is <= inputs_until <= as_of. Read through news_clusters_asof(ts).
    # origin_groups: JSON list of {origin, news_ids, promotional, vetted, opinion, verified,
    # unread_vetted}; outlets/tiers are parallel lists. independent_origins counts verified groups
    # (a vetted, non-promotional, non-opinion item that was read or carries agency evidence) and
    # origins lists them; unread_vetted_origins counts vetted groups with only unread headlines;
    # unvetted_ids are items from outlets not on the allowlist (informational, never counted).
    "news_clusters": ("jsonl", {
        "id": "VARCHAR", "as_of": "TIMESTAMPTZ", "cluster_id": "VARCHAR", "ticker": "VARCHAR",
        "news_ids": "VARCHAR[]", "duplicate_ids": "VARCHAR[]", "n_items": "INTEGER",
        "outlets": "VARCHAR[]", "tiers": "VARCHAR[]", "independent_origins": "INTEGER",
        "unread_vetted_origins": "INTEGER",
        "unvetted_ids": "VARCHAR[]", "origins": "VARCHAR[]", "origin_groups": "JSON",
        "primary_ids": "VARCHAR[]", "first_reported_at": "TIMESTAMPTZ", "last_reported_at": "TIMESTAMPTZ",
        "inputs_until": "TIMESTAMPTZ", "flags": "VARCHAR[]", "state_hash": "VARCHAR", "method_version": "VARCHAR",
    }),
    "filings": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "cik": "VARCHAR", "form": "VARCHAR",
        "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ", "description": "VARCHAR",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "predictions": ("jsonl", {
        "id": "VARCHAR", "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "ticker": "VARCHAR",
        "horizon_days": "INTEGER", "direction": "VARCHAR", "confidence": "DOUBLE",
        "rationale": "VARCHAR", "evidence_ids": "VARCHAR[]", "prompt_version": "VARCHAR",
        "range_widen": "DOUBLE",
        # signal model anchor (forecast-v11; null on older rows): the stored model_scores prob_up, the
        # forecaster's adjustment (|x| <= 0.10, final = model_prob + x) and its written reason
        "model_prob": "DOUBLE", "agent_adjustment": "DOUBLE", "adjustment_reason": "VARCHAR",
    }),
    # Reflection log (lessons.py; pattern from TauricResearch/TradingAgents): one lesson per settled call.
    # Facts are copied deterministically from predictions/outcomes/ranges/range_outcomes; only `lesson`
    # (<= 60 words) is written by the reflector agent. settled_at = the outcome's scored_at; available_from
    # = the latest scored_at among the facts cited (context.py shows a lesson only from then on).
    "lessons": ("jsonl", {
        "id": "VARCHAR", "prediction_id": "VARCHAR", "ticker": "VARCHAR", "horizon_days": "INTEGER",
        "as_of_date": "DATE", "made_at": "TIMESTAMPTZ", "direction": "VARCHAR", "confidence": "DOUBLE",
        "rationale": "VARCHAR", "evidence_ids": "VARCHAR[]", "call_prompt_version": "VARCHAR",
        "base_date": "DATE", "base_close": "DOUBLE", "target_date": "DATE", "target_close": "DOUBLE",
        "actual_return": "DOUBLE", "hit": "BOOLEAN", "label_basis": "VARCHAR", "entry_date": "DATE",
        "entry_open": "DOUBLE", "range_id": "VARCHAR", "range_target_date": "DATE",
        "range_actual_close": "DOUBLE", "lo80": "DOUBLE", "lo50": "DOUBLE", "hi50": "DOUBLE", "hi80": "DOUBLE",
        "hit50": "BOOLEAN", "hit80": "BOOLEAN", "range_position": "VARCHAR",
        "settled_at": "TIMESTAMPTZ", "available_from": "TIMESTAMPTZ",
        "lesson": "VARCHAR", "prompt_version": "VARCHAR", "written_at": "TIMESTAMPTZ",
    }),
    # One row per judge verdict in a daily run (routine/PROMPT.md); build verdicts are in judgments/log.jsonl.
    "judgments": ("jsonl", {
        "id": "VARCHAR", "run_date": "DATE", "agent": "VARCHAR", "round": "INTEGER",
        "verdict": "VARCHAR", "summary": "VARCHAR", "dropped": "VARCHAR", "recorded_at": "TIMESTAMPTZ",
    }),
    "outcomes": ("jsonl", {
        "prediction_id": "VARCHAR", "scored_at": "TIMESTAMPTZ", "base_date": "DATE",
        "base_close": "DOUBLE", "target_date": "DATE", "target_close": "DOUBLE",
        "actual_return": "DOUBLE", "hit": "BOOLEAN",
        # the scoring basis (analytics/call_basis.py): close_to_close (also every row stored without it) or
        # open_to_close, whose return starts at entry_open, the open of entry_date (the session after as-of)
        "label_basis": "VARCHAR", "entry_date": "DATE", "entry_open": "DOUBLE",
    }),
    "prices": ("csv", {
        "date": "DATE", "ticker": "VARCHAR", "open": "DOUBLE", "high": "DOUBLE",
        "low": "DOUBLE", "close": "DOUBLE", "adj_close": "DOUBLE", "volume": "BIGINT",
        "collected_at": "TIMESTAMPTZ",
    }),
    # One row per bar collect_prices.py wrote from a source other than Yahoo (India: the NSE
    # bhavcopy fallback); files dated by the bar's trading date, like prices. View `bar_sources`.
    "price_sources": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "source": "VARCHAR", "url": "VARCHAR",
        "filled_at": "TIMESTAMPTZ",
    }),
    # Splits and bonus issues (issue #31; analytics/price_adjustments.py, detected by collect_prices.py), one row
    # per corporate action, files dated by the ex-date. factor = price multiplier for every bar
    # before ex_date (0.5 for a 1:1 bonus or a 2:1 split), volume_factor = 1/factor; the ohlc and
    # bars views apply them on read (ohlc_raw, bars_raw: as stored). source: yahoo_splits (a
    # `Stock Splits` row in Yahoo's frame) or nse_prev_close (NSE's bhavcopy; India). Evidence:
    # check_date = the stored bar compared, stored_close and yahoo_close its two closes,
    # measured_factor = yahoo_close / stored_close, yahoo_ratio = Yahoo's split value,
    # nse_prev_close / nse_ex_close = the bhavcopy's PREV_CLOSE and close on the ex-date.
    "adjustments": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "ex_date": "DATE", "factor": "DOUBLE",
        "volume_factor": "DOUBLE", "source": "VARCHAR", "yahoo_ratio": "DOUBLE", "check_date": "DATE",
        "stored_close": "DOUBLE", "yahoo_close": "DOUBLE", "measured_factor": "DOUBLE",
        "nse_prev_close": "DOUBLE", "nse_ex_close": "DOUBLE", "url": "VARCHAR", "detected_at": "TIMESTAMPTZ",
        # correction of a wrong record (appended by hand; see adjust.load): the id it replaces
        "supersedes": "VARCHAR", "note": "VARCHAR",
    }),
    "quotes": ("jsonl", {
        "symbol": "VARCHAR", "yahoo": "VARCHAR", "ts": "TIMESTAMPTZ", "price": "DOUBLE",
        "prev_close": "DOUBLE", "change_pct": "DOUBLE", "collected_at": "TIMESTAMPTZ",
    }),
    "events": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "type": "VARCHAR", "ticker": "VARCHAR",
        "name": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        # amount: dividend per share (ex_dividend); timing: before_open | during | after_close
        # (earnings, when the source has a time). Past events carry a source ending in "_history".
        "amount": "DOUBLE", "timing": "VARCHAR",
        # periodic_report rows (SEC 10-Q/10-K acceptance, source sec_history): the fiscal period end.
        # They date each quarter's results release among the 2.02 filings (event_history.results_filter).
        "period_end": "DATE",
        # periodic_report rows stored from issue #24 on: the acceptance time (UTC), so the live ranges count a
        # report only once accepted by made_at (earnings_events(made_at=...)); older rows have none.
        "accepted_at": "TIMESTAMPTZ",
    }),
    # Yahoo consensus EPS per report (collect_events.py, issue #17): a row per (ticker, report) when first seen or
    # changed; collected_at is when we saw it, so a value is usable only from then (earnings_estimates_asof).
    "earnings_estimates": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "report_date": "DATE", "report_at": "TIMESTAMPTZ",
        "eps_estimate": "DOUBLE", "reported_eps": "DOUBLE", "surprise_pct": "DOUBLE", "source": "VARCHAR",
        "collected_at": "TIMESTAMPTZ",
    }),
    # Near-the-money implied volatility per ticker and expiry (collect_options.py, US only).
    "options": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "collected_at": "TIMESTAMPTZ", "expiry": "DATE",
        "days_to_expiry": "INTEGER", "spot": "DOUBLE", "strike": "DOUBLE", "call_iv": "DOUBLE",
        "put_iv": "DOUBLE", "atm_iv": "DOUBLE", "straddle": "DOUBLE", "straddle_pct": "DOUBLE",
        "source": "VARCHAR",
    }),
    "features": ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "ticker": "VARCHAR", "computed_at": "TIMESTAMPTZ",
        **FEATURE_COLS,
    }),
    "ranges": ("jsonl", {
        "id": "VARCHAR", "made_at": "TIMESTAMPTZ", "as_of_date": "DATE", "session_date": "DATE",
        "target_date": "DATE", "ticker": "VARCHAR", "horizon_days": "INTEGER",
        "base_close": "DOUBLE", "center": "DOUBLE", "sigma_h": "DOUBLE",
        "lo50": "DOUBLE", "hi50": "DOUBLE", "lo80": "DOUBLE", "hi80": "DOUBLE",
        "naive_lo50": "DOUBLE", "naive_hi50": "DOUBLE", "naive_lo80": "DOUBLE", "naive_hi80": "DOUBLE",
        "direction": "VARCHAR", "confidence": "DOUBLE", "regime": "VARCHAR",
        "calibration_id": "VARCHAR", "notes": "VARCHAR[]",
        "inputs": "VARCHAR[]",  # range inputs applied: earnings_history, ex_dividend, beta_split, implied_vol
        "iv_sigma_h": "DOUBLE",  # shadow: sigma_h with option-implied vol applied (same centre)
    }),
    "range_outcomes": ("jsonl", {
        "range_id": "VARCHAR", "scored_at": "TIMESTAMPTZ", "target_date": "DATE",
        "actual_close": "DOUBLE", "z": "DOUBLE", "hit50": "BOOLEAN", "hit80": "BOOLEAN",
        "naive_hit50": "BOOLEAN", "naive_hit80": "BOOLEAN", "is80_pct": "DOUBLE",
        "naive_is80_pct": "DOUBLE", "width80_pct": "DOUBLE", "naive_width80_pct": "DOUBLE",
        "center_err_pct": "DOUBLE", "naive_center_err_pct": "DOUBLE",
    }),
    "calibration": ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "computed_at": "TIMESTAMPTZ", "horizon_days": "INTEGER",
        "q10": "DOUBLE", "q25": "DOUBLE", "q75": "DOUBLE", "q90": "DOUBLE",
        "n_history": "INTEGER", "n_live": "INTEGER", "source": "VARCHAR",
        # ACI (adaptive_conformal.py), only when switched on in config/ranges.yaml: effective miss rates used for
        # the 50% and 80% bands and the scored target dates behind them
        "aci_alpha50": "DOUBLE", "aci_alpha80": "DOUBLE", "aci_steps": "INTEGER",
    }),
    "regime": ("jsonl", {
        "id": "VARCHAR", "as_of_date": "DATE", "session_date": "DATE", "computed_at": "TIMESTAMPTZ",
        "regime": "VARCHAR",
        "vol_level": "DOUBLE", "vol_change_1d": "DOUBLE", "bench_ret_5d": "DOUBLE",
        "bench_vol_10d": "DOUBLE", "major_event": "BOOLEAN", "major_event_names": "VARCHAR[]",
        "stress": "BOOLEAN", "notes": "VARCHAR[]",
    }),
    # Weekly review (review.py): headline numbers as columns, tables and proposals as JSON.
    "reviews": ("jsonl", {
        "id": "VARCHAR", "week": "VARCHAR", "week_start": "DATE", "week_end": "DATE",
        "computed_at": "TIMESTAMPTZ", "report": "VARCHAR",
        "n_ranges_week": "INTEGER", "n_ranges_30d": "INTEGER", "n_ranges_all": "INTEGER",
        "n_calls_week": "INTEGER", "n_calls_all": "INTEGER",
        "cover50_all": "DOUBLE", "cover80_all": "DOUBLE", "score80_all": "DOUBLE",
        "naive_score80_all": "DOUBLE", "call_hit_all": "DOUBLE", "always_up_all": "DOUBLE",
        "call_basis_all": "VARCHAR",  # the scoring basis of call_hit_all / always_up_all (call_basis.py)
        "low_sample": "BOOLEAN", "n_proposals": "INTEGER", "proposals": "JSON", "detail": "JSON",
    }),
    # Historical replay of the rule-based parts (replay.py): headline numbers as columns (scores are
    # the 80% interval score in % of price on rows with a naive range), the full results as JSON.
    "replays": ("jsonl", {
        "id": "VARCHAR", "market": "VARCHAR", "start_date": "DATE", "end_date": "DATE",
        "computed_at": "TIMESTAMPTZ", "report": "VARCHAR", "n_days": "INTEGER", "n_ranges": "INTEGER",
        "cover50_1d": "DOUBLE", "cover80_1d": "DOUBLE", "cover50_5d": "DOUBLE", "cover80_5d": "DOUBLE",
        "score80_1d": "DOUBLE", "naive_score80_1d": "DOUBLE", "score80_5d": "DOUBLE", "naive_score80_5d": "DOUBLE",
        "always_up_1d": "DOUBLE", "always_up_5d": "DOUBLE", "runtime_s": "DOUBLE",
        "settings": "JSON", "detail": "JSON",
    }),
}
