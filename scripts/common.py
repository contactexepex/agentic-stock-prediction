"""Shared paths, schemas and DuckDB setup for the market-brief pipeline.

Each market (config/markets/<market>.yaml) has its own data tree: append-only,
date-partitioned files under data/<market>/<kind>/YYYY/MM/. DuckDB reads those files
directly, so any time window is just a SQL query. Scripts take --market (or MB_MARKET).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import yaml

CODE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("MB_ROOT", CODE))
CONFIG = Path(os.environ.get("MB_CONFIG", CODE / "config"))
# Yahoo collectors report a series as stale when its newest data is older than this many calendar
# days (cues and factors on other exchanges; the market's own symbols use its previous session).
STALE_DAYS = 7

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

# kind -> (file extension, column types). This is the single source of truth for schemas.
SCHEMAS: dict[str, tuple[str, dict[str, str]]] = {
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
        "actual_return": "DOUBLE", "hit": "BOOLEAN", "range_id": "VARCHAR", "range_target_date": "DATE",
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
        # They date each quarter's results release among the 2.02 filings (range_inputs.results_filter).
        "period_end": "DATE",
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
        # ACI (aci.py), only when switched on in config/ranges.yaml: effective miss rates used for
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

# Relationships (docs/DESIGN.md phase 5), US from SEC EDGAR: one row per Form 4 transaction
# line (insiders), per Schedule 13D/13G filing (stakes), per 13F filing x watchlist ticker (holdings).
SCHEMAS.update({
    "insiders": ("jsonl", {
        "id": "VARCHAR", "accession": "VARCHAR", "line": "INTEGER", "ticker": "VARCHAR",
        "issuer_cik": "VARCHAR", "form": "VARCHAR", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ",
        "insider_name": "VARCHAR", "insider_cik": "VARCHAR", "role": "VARCHAR",
        "is_director": "BOOLEAN", "is_officer": "BOOLEAN", "is_ten_pct_owner": "BOOLEAN",
        "derivative": "BOOLEAN", "security": "VARCHAR", "transaction_date": "DATE", "code": "VARCHAR",
        "acquired_disposed": "VARCHAR", "shares": "DOUBLE", "price": "DOUBLE", "value": "DOUBLE",
        "shares_after": "DOUBLE", "ownership": "VARCHAR", "plan_10b5_1": "BOOLEAN",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "stakes": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "issuer_cik": "VARCHAR", "form": "VARCHAR",
        "kind": "VARCHAR", "amendment": "BOOLEAN", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ",
        "event_date": "DATE", "filer_name": "VARCHAR", "filer_cik": "VARCHAR",
        "reporting_persons": "VARCHAR[]", "percent": "DOUBLE", "shares": "DOUBLE",
        "purpose": "VARCHAR", "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "holdings": ("jsonl", {
        "id": "VARCHAR", "accession": "VARCHAR", "filer_cik": "VARCHAR", "filer_name": "VARCHAR",
        "period": "DATE", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ", "ticker": "VARCHAR",
        "cusip": "VARCHAR", "issuer_name": "VARCHAR", "shares": "DOUBLE", "value_usd": "DOUBLE",
        "put_call": "VARCHAR", "n_lines": "INTEGER", "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "report_type": "VARCHAR", "complete": "BOOLEAN", "note": "VARCHAR",
    }),
})

# SEC acceptance-time checks (scripts/check_sec_times.py; see sec.py): one row per stored accession
# checked against its SGML header. accepted_at = the header's time (authoritative, UTC),
# json_accepted_at = the value stored from the submissions JSON. connect() reads accepted_at of
# filings, insiders, stakes, holdings and fundamentals through it (ACCEPTED_KEYS), so a value
# stored from a shifted submissions file is corrected on read without editing data/.
SCHEMAS["sec_times"] = ("jsonl", {
    "accession": "VARCHAR", "cik": "VARCHAR", "accepted_at": "TIMESTAMPTZ",
    "json_accepted_at": "TIMESTAMPTZ", "source": "VARCHAR", "checked_at": "TIMESTAMPTZ",
})
# kind -> its accession column, for the sec_times correction in connect()
ACCEPTED_KEYS = {"filings": "id", "insiders": "accession", "stakes": "id", "holdings": "accession",
                 "fundamentals": "accession"}

# Fundamentals, US from SEC XBRL company facts (collect_fundamentals.py): one row per ticker x
# tag x period x filing that first reported the value or changed it (prev_value = earlier value).
SCHEMAS["fundamentals"] = ("jsonl", {
    "id": "VARCHAR", "ticker": "VARCHAR", "cik": "VARCHAR", "concept": "VARCHAR", "tag": "VARCHAR",
    "tag_rank": "INTEGER", "unit": "VARCHAR", "period_start": "DATE", "period_end": "DATE",
    "period": "VARCHAR", "fiscal_year": "INTEGER", "fiscal_period": "VARCHAR", "form": "VARCHAR",
    "accession": "VARCHAR", "filing_date": "DATE", "accepted_at": "TIMESTAMPTZ", "value": "DOUBLE",
    "prev_value": "DOUBLE", "first_seen_at": "TIMESTAMPTZ",
})

# Free market-wide sources (issue #9; HTTP and storage in sources.py). A revised value is a new
# row with the same id; the *_daily/_series views keep a complete row over an incomplete one,
# then the newest first_seen_at. A per-session file stored incomplete (`complete` false) is
# fetched again on the next run while it is in the lookback.
SCHEMAS.update({
    # US macro (collect_macro.py): one row per series and observation date. unit: pct | ratio | index.
    "macro": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "series": "VARCHAR", "name": "VARCHAR", "value": "DOUBLE",
        "unit": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "complete": "BOOLEAN",  # Cboe: the session file had every configured ratio (Treasury, FRED: true)
    }),
    # US FINRA Reg SHO daily short-sale volume (collect_shorts.py); short_pct in percent of the
    # FINRA-reported (off-exchange) volume, not of all trading.
    "shorts": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "short_volume": "DOUBLE",
        "short_exempt_volume": "DOUBLE", "total_volume": "DOUBLE", "short_pct": "DOUBLE",
        "markets": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "complete": "BOOLEAN",  # the day file was whole (trailer count matched) and had every watchlist ticker
    }),
    # US FINRA consolidated short interest, twice a month (collect_shorts.py); change_pct in percent.
    "short_interest": ("jsonl", {
        "id": "VARCHAR", "settlement_date": "DATE", "ticker": "VARCHAR", "short_interest": "DOUBLE",
        "prev_short_interest": "DOUBLE", "change_pct": "DOUBLE", "avg_daily_volume": "DOUBLE",
        "days_to_cover": "DOUBLE", "revised": "BOOLEAN", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    # India NSDL daily FPI investment by asset class and route, INR crore (collect_flows_india.py).
    "fpi": ("jsonl", {
        "id": "VARCHAR", "reporting_date": "DATE", "asset_class": "VARCHAR", "route": "VARCHAR",
        "gross_purchases_cr": "DOUBLE", "gross_sales_cr": "DOUBLE", "net_cr": "DOUBLE",
        "net_usd_mn": "DOUBLE", "usd_inr": "DOUBLE", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    # India NSE index closes with valuation (collect_flows_india.py); sector = watchlist sector it stands for.
    "indices": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "index_name": "VARCHAR", "sector": "VARCHAR", "open": "DOUBLE",
        "high": "DOUBLE", "low": "DOUBLE", "close": "DOUBLE", "change_pct": "DOUBLE", "volume": "DOUBLE",
        "turnover_cr": "DOUBLE", "pe": "DOUBLE", "pb": "DOUBLE", "div_yield": "DOUBLE",
        "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        "complete": "BOOLEAN",  # the session file had every configured index for the right date
    }),
})

# Relationships (DESIGN.md phase 5): India insider/promoter trades (SEBI PIT), bulk and block
# deals, shareholding incl. promoter pledges (collect_relations_india.py), and the per-company
# connection map for both markets (graph-builder agent, graph.py). Merged as a column union so a
# market-specific collector can share a kind (e.g. US Form 4 rows in `insiders`): read_json fills
# columns a row does not have with NULL, and an existing column keeps its type.
RELATION_SCHEMAS: dict[str, tuple[str, dict[str, str]]] = {
    "insiders": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "source": "VARCHAR", "person": "VARCHAR",
        "person_category": "VARCHAR", "security_type": "VARCHAR", "transaction": "VARCHAR",
        "mode": "VARCHAR", "shares": "DOUBLE", "value": "DOUBLE",
        "holding_before_pct": "DOUBLE", "holding_after_pct": "DOUBLE",
        "trade_from": "DATE", "trade_to": "DATE", "disclosed_at": "TIMESTAMPTZ",
        "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "deals": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "deal_type": "VARCHAR",
        "client": "VARCHAR", "side": "VARCHAR", "shares": "DOUBLE", "price": "DOUBLE",
        "value": "DOUBLE", "remarks": "VARCHAR", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "holdings": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "period_end": "DATE", "source": "VARCHAR",
        "promoter_pct": "DOUBLE", "public_pct": "DOUBLE", "employee_trust_pct": "DOUBLE",
        "pledged_pct_of_promoter": "DOUBLE", "pledged_pct_of_total": "DOUBLE",
        "filed_at": "TIMESTAMPTZ", "url": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
        # nse_pledge rows (depository system-driven disclosures; see collect_relations_india.py)
        "sdd_promoter_pct": "DOUBLE", "promoter_shares": "DOUBLE", "total_shares": "DOUBLE",
        "promoter_encumbered_shares": "DOUBLE", "depository_pledged_shares": "DOUBLE",
        "depository_pledged_pct": "DOUBLE",
    }),
    # India primary sources from NSE (collect_nse_india.py).
    "announcements": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "company": "VARCHAR", "published_at": "TIMESTAMPTZ",
        "category": "VARCHAR", "subject": "VARCHAR", "url": "VARCHAR", "source": "VARCHAR",
        "first_seen_at": "TIMESTAMPTZ",
    }),
    "financials": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "basis": "VARCHAR", "period_type": "VARCHAR",
        "period_start": "DATE", "period_end": "DATE", "revenue": "DOUBLE", "revenue_item": "VARCHAR",
        "total_income": "DOUBLE", "profit_before_tax": "DOUBLE", "net_profit": "DOUBLE",
        "profit_to_owners": "DOUBLE", "eps_basic": "DOUBLE", "eps_diluted": "DOUBLE",
        "audited": "VARCHAR", "taxonomy": "VARCHAR", "filing_type": "VARCHAR", "filed_at": "TIMESTAMPTZ",
        "url": "VARCHAR", "seq_id": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "flows": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "category": "VARCHAR", "buy_cr": "DOUBLE", "sell_cr": "DOUBLE",
        "net_cr": "DOUBLE", "provisional": "BOOLEAN", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "delivery": ("jsonl", {
        "id": "VARCHAR", "date": "DATE", "ticker": "VARCHAR", "series": "VARCHAR", "close": "DOUBLE",
        "volume": "DOUBLE", "delivery_qty": "DOUBLE", "delivery_pct": "DOUBLE", "trades": "DOUBLE",
        "turnover_lacs": "DOUBLE", "source": "VARCHAR", "first_seen_at": "TIMESTAMPTZ",
    }),
    "graph": ("jsonl", {
        "id": "VARCHAR", "ticker": "VARCHAR", "relation": "VARCHAR", "target": "VARCHAR",
        "target_kind": "VARCHAR", "target_ticker": "VARCHAR", "aliases": "VARCHAR[]",
        "detail": "VARCHAR", "weight": "DOUBLE", "status": "VARCHAR", "as_of": "DATE",
        "source_url": "VARCHAR", "added_at": "TIMESTAMPTZ", "prompt_version": "VARCHAR",
    }),
    # One row per connection-map refresh attempt (graph.py attempt), even when no edge changed.
    "graph_runs": ("jsonl", {
        "id": "VARCHAR", "run_at": "TIMESTAMPTZ", "month": "VARCHAR", "edges": "INTEGER",
        "tickers_without_edges": "INTEGER", "note": "VARCHAR",
    }),
}
for _kind, (_ext, _cols) in RELATION_SCHEMAS.items():
    SCHEMAS[_kind] = (SCHEMAS[_kind][0], {**_cols, **SCHEMAS[_kind][1]}) if _kind in SCHEMAS else (_ext, _cols)


def clock() -> datetime:
    """Now as an aware UTC datetime. MB_NOW (ISO 8601 with a UTC offset) freezes it, so an as-of
    replay (scripts/ai_replay.py) runs features, calibrate, context and ranges as of that time;
    connect() then also freezes DuckDB's current_date. Unset in live runs."""
    fixed = os.environ.get("MB_NOW")
    if not fixed:
        return datetime.now(timezone.utc)
    t = datetime.fromisoformat(fixed.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise SystemExit(f"MB_NOW needs a UTC offset, e.g. 2026-07-02T12:15:00+00:00 (got {fixed!r})")
    return t.astimezone(timezone.utc)


def utc_now() -> str:
    return clock().replace(microsecond=0).isoformat()


def utc_today() -> date:
    return clock().date()


# ---------- markets ----------

def load_ranges_config(market: str | None = None) -> dict:
    """config/ranges.yaml. With a market, a setting `<key>_by_market: {market: value}` replaces
    `<key>` for that market (e.g. earnings_vol_multiple_by_market)."""
    rc = yaml.safe_load((CONFIG / "ranges.yaml").read_text())
    if market:
        for key in [k for k in rc if k.endswith("_by_market")]:
            if market in (rc[key] or {}):
                rc[key.removesuffix("_by_market")] = rc[key][market]
    return rc


def market_names() -> list[str]:
    return sorted(p.stem for p in (CONFIG / "markets").glob("*.yaml"))


def load_market(name: str) -> dict:
    path = CONFIG / "markets" / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"unknown market {name!r}; available: {market_names()}")
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault("market", name)
    cfg.setdefault("symbols", {})
    for key, meta in cfg["tickers"].items():
        meta.setdefault("yahoo", key)
    for key, meta in cfg["symbols"].items():
        meta.setdefault("yahoo", key)
    sector_of = {t: s for s, ts in cfg.get("sectors", {}).items() for t in ts}
    for key, meta in cfg["tickers"].items():
        meta.setdefault("sector", sector_of.get(key))
    cfg["sector_etfs"] = sector_etf_map(cfg)
    for key, meta in cfg["tickers"].items():
        meta.setdefault("sector_etf", cfg["sector_etfs"].get(meta.get("sector")))
    return cfg


def sector_etf_map(cfg: dict) -> dict[str, str]:
    """Watchlist sector -> the sector_etf symbol that stands for it (the symbol's `sectors` list).
    A sector named by no symbol is absent. Config mistakes (see sector_etf_problems) are skipped
    here, so a typo never stops a daily run; tests/test_signals.py checks the real configs."""
    known, out = set(cfg.get("sectors") or {}), {}
    for key, meta in cfg["symbols"].items():
        if meta.get("role") != "sector_etf":
            continue
        for sector in meta.get("sectors") or []:
            if sector in known:
                out.setdefault(sector, key)  # the first symbol listed wins
    return out


def sector_etf_problems(cfg: dict) -> list[str]:
    """Mistakes in the symbols' `sectors` lists: an unknown sector, a sector claimed by two
    symbols, or `sectors` on a symbol whose role is not sector_etf."""
    known, seen, out = set(cfg.get("sectors") or {}), {}, []
    for key, meta in cfg["symbols"].items():
        if meta.get("sectors") and meta.get("role") != "sector_etf":
            out.append(f"symbol {key}: `sectors` is only for role sector_etf")
        for sector in meta.get("sectors") or []:
            if sector not in known:
                out.append(f"symbol {key}: unknown sector {sector!r}")
            elif sector in seen:
                out.append(f"sector {sector!r} is mapped to both {seen[sector]} and {key}")
            else:
                seen[sector] = key
    return out


def market_arg(description: str | None = None) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--market", default=os.environ.get("MB_MARKET"),
                    help="market config name, e.g. india or us (default: $MB_MARKET)")
    return ap


def require_market(args) -> dict:
    if not args.market:
        raise SystemExit(f"--market is required; available: {market_names()}")
    return load_market(args.market)


def symbols_by_role(cfg: dict, role: str) -> dict[str, dict]:
    return {k: v for k, v in cfg["symbols"].items() if v.get("role") == role}


def benchmark_key(cfg: dict) -> str | None:
    return next(iter(symbols_by_role(cfg, "benchmark")), None)


def vol_index_key(cfg: dict) -> str | None:
    return next(iter(symbols_by_role(cfg, "vol_index")), None)


# ---------- files ----------

def data_dir(market: str) -> Path:
    return ROOT / "data" / market


def day_file(market: str, kind: str, day: date, ext: str | None = None) -> Path:
    ext = ext or SCHEMAS[kind][0]
    path = data_dir(market) / kind / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, rows) -> int:
    """Append rows; never rewrites existing lines."""
    rows = list(rows)
    if rows:
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows)


def recent_ids(market: str, kind: str, days: int, key: str = "id") -> set[str]:
    """Ids seen in the last `days` daily files of a kind (for de-duplication)."""
    ids: set[str] = set()
    files = sorted((data_dir(market) / kind).glob("**/*.jsonl"))[-days:]
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)[key])
    return ids


_CLOCK_SQL = [(re.compile(r"\bcurrent_date\b(\s*\(\s*\))?", re.I), "DATE '{d}'"),
              (re.compile(r"\b(?:now|get_current_timestamp|current_timestamp)\s*\(\s*\)|\bcurrent_timestamp\b", re.I),
               "TIMESTAMPTZ '{t}'")]


def freeze_sql(sql: str, at: datetime) -> str:
    """SQL with DuckDB's clock functions replaced by the literal time `at` (UTC)."""
    for pattern, lit in _CLOCK_SQL:
        sql = pattern.sub(lit.format(d=at.date().isoformat(), t=at.isoformat()), sql)
    return sql


class FrozenClockConnection:
    """A DuckDB connection whose SQL sees `at` as the current date and time (MB_NOW). Every other
    attribute is the wrapped connection's; execute() returns that connection, as DuckDB's does."""

    def __init__(self, con: duckdb.DuckDBPyConnection, at: datetime):
        self._con, self._at = con, at

    def execute(self, query: str, *args, **kwargs):
        return self._con.execute(freeze_sql(query, self._at), *args, **kwargs)

    def sql(self, query: str, *args, **kwargs):
        return self._con.sql(freeze_sql(query, self._at), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._con, name)


def connect(market: str) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with one view per data kind plus the derived views in sql/views.sql.
    With MB_NOW set, the connection's SQL sees that time as now (FrozenClockConnection).
    News is the exception: the stored rows are `news_stored`, and the `news` view (views.sql)
    re-tags rows from before the current tagger with `news_retag` (scripts/news_tags.py)."""
    from news_tags import RETAG_TYPE, Tagger
    con = duckdb.connect()
    try:
        retag = Tagger(load_market(market)).retag_stored
    except SystemExit:   # no market config (some tests): tags stay as stored
        def retag(feed, title, tickers, primary, mentioned, confidence, tag_version):
            return {"tickers": list(tickers or []), "primary_tickers": list(primary or []),
                    "mentioned_tickers": list(mentioned or []), "tag_confidence": confidence}
    con.create_function("news_retag", retag,
                        ["VARCHAR", "VARCHAR", "VARCHAR[]", "VARCHAR[]", "VARCHAR[]", "VARCHAR", "INTEGER"],
                        duckdb.struct_type(RETAG_TYPE), null_handling="special", side_effects=False)
    if os.environ.get("MB_NOW"):
        con = FrozenClockConnection(con, clock())
    con.execute("SET TimeZone = 'UTC'")
    base = data_dir(market)
    for kind, (ext, cols) in SCHEMAS.items():
        name = "news_stored" if kind == "news" else kind
        has_files = any((base / kind).glob(f"**/*.{ext}"))
        col_spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"
        if has_files:
            pattern = (base / kind).as_posix() + f"/**/*.{ext}"
            if ext == "jsonl":
                src = f"read_json('{pattern}', format='newline_delimited', columns={col_spec})"
            else:
                src = f"read_csv('{pattern}', header=true, columns={col_spec})"
            if name in ACCEPTED_KEYS and any((base / "sec_times").glob("**/*.jsonl")):
                # accepted_at corrected to the SGML header's time where one was checked (sec_times)
                tpat = (base / "sec_times").as_posix() + "/**/*.jsonl"
                tspec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in SCHEMAS["sec_times"][1].items()) + "}"
                fix = (f"(SELECT DISTINCT ON (accession) accession AS _acc, accepted_at AS _true FROM "
                       f"read_json('{tpat}', format='newline_delimited', columns={tspec}) "
                       f"WHERE accepted_at IS NOT NULL ORDER BY accession, checked_at DESC)")
                con.execute(f"CREATE VIEW {name} AS SELECT s.* REPLACE (coalesce(f._true, s.accepted_at) AS accepted_at) "
                            f"FROM {src} s LEFT JOIN {fix} f ON f._acc = s.{ACCEPTED_KEYS[name]}")
            else:
                con.execute(f"CREATE VIEW {name} AS SELECT * FROM {src}")
        else:
            con.execute(f"CREATE TABLE {name} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
    con.execute((CODE / "sql" / "views.sql").read_text())
    return con


def md_table(cursor) -> str:
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out) + "\n"
