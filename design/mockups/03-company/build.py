"""Company mockup (docs/SPEC.md section 6, page 3; decisions 13, 26, 39, 43, 44; F1.9-F1.10, F5, F6.1, F8, WS6).

    python design/mockups/03-company/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/stocks/{ticker}` (read models `rm.stock`,
`rm.bars`, `rm.lifecycle`, `rm.trades`), for every company the catalogue holds bars for (India: RELIANCE, HDFCBANK,
MARUTI; US: NVDA, AAPL, JPM), from W1's example files only. Selection and ordering only; no look-ahead: every record
with a time is kept only when that time is at or before the cut-off. Deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "company", "lifecycle_event", "agreement", "head_to_head_pick", "prediction", "open_trade",
         "trade_check", "paper_trade", "reason_ai", "news_item", "results_digest", "calendar_event", "bar",
         "scoreboard_row", "strategy")
COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "state_since", "added_at", "amount",
                  "amount_overridden", "currency", "yahoo", "nse_symbol", "cik", "last_close", "last_close_date",
                  "change_pct", "agreement_n1", "open_trades")
LIFECYCLE_FIELDS = ("id", "event", "ticker", "market", "effective_from", "recorded_at", "amount", "reason",
                    "requested_by", "channel", "supersedes")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
PREDICTION_FIELDS = ("id", "strategy_id", "family", "ticker", "made_at", "as_of_date", "session_date", "exit_date",
                     "horizon_days", "direction", "prob_up", "qualifies", "base_close", "target_price", "lo50", "hi50",
                     "lo80", "hi80", "range_widen", "regime", "quality")
PICK_FIELDS = ("id", "market", "ticker", "made_at", "as_of_date", "session_date", "family", "pick_rule", "status",
               "strategy_id", "strongest_basis", "ranking", "horizon_days", "prediction_id", "base_close", "prob_up",
               "move_pct", "loss_pct", "costs_pct", "expected_gain_pct", "candidates", "amount", "currency")
OPEN_TRADE_FIELDS = ("trade_id", "view", "prediction_id", "strategy_id", "family", "market", "ticker", "horizon_days",
                     "entry_date", "exit_date", "entry_price", "quantity", "amount", "currency", "target_price", "lo80",
                     "lo50", "hi50", "hi80", "last_price", "last_price_date", "unrealised_pnl", "unrealised_pct",
                     "to_target_pct", "paper")
CHECK_FIELDS = ("id", "check_id", "check_row_id", "check_at", "session_date", "market", "ticker", "trade_id",
                "prediction_id", "strategy_id", "view", "horizon_days", "entry_date", "exit_date", "session_number",
                "entry_price", "last_price", "ret_since_entry_pct", "target_price", "to_target_pct", "lo80", "lo50",
                "hi50", "hi80", "band", "target_z", "flags", "flagged", "quality", "target_reached",
                "target_reached_session", "high_since_entry_pct", "low_since_entry_pct", "sessions_left", "last_time")
TRADE_FIELDS = ("id", "trade_id", "prediction_id", "strategy_id", "family", "view", "pick_rule", "market", "ticker",
                "horizon_days", "made_at", "entry_date", "exit_date", "exit_date_actual", "status", "flags", "amount",
                "currency", "entry_price", "exit_price", "quantity", "gross_pnl", "costs", "net_pnl", "return_pct",
                "prob_up", "target_price", "lo80", "hi80", "range_hit", "target_reached", "target_reached_session",
                "max_favourable_pct", "max_adverse_pct", "move_pct", "market_pct", "sector_pct", "news_pct",
                "company_pct", "reason_code", "reason_codes", "news_ids", "reason_detail", "regime", "settled_at")
REASON_FIELDS = ("id", "trade_id", "market", "ticker", "strategy_id", "session_date", "kind", "rank", "text",
                 "cited_ids", "reason_codes", "created_at")
NEWS_FIELDS = ("id", "market", "tickers", "primary_tickers", "title", "source", "source_domain", "url", "published_at",
               "first_seen_at", "enrichment", "status", "status_as_of", "cluster_id", "independent_origins",
               "primary_ids", "headline_history")
DIGEST_FIELDS = ("id", "release_kind", "ticker", "release_at", "release_date", "release_timing", "period_end",
                 "fiscal_label", "basis", "currency", "status", "numbers_status", "numbers_as_of", "numbers",
                 "consensus", "reaction", "bullets", "sources", "created_at")
CALENDAR_FIELDS = ("market", "date", "type", "name", "ticker", "timing", "reaction_sessions", "major", "widens",
                   "provisional", "release", "source", "event_id")
BAR_FIELDS = ("date", "open", "high", "low", "close", "volume", "adjusted")
ROW_FIELDS = ("scope", "market", "view", "strategy_id", "family", "ticker", "horizon_days", "trades", "net_pnl",
              "win_rate", "sample_badge")
REFERENCE_STRATEGY = "rule.model_news.v1"   # the registry's reference rule strategy (config/strategies.yaml)


def company_payload(market: str, ticker: str, files: dict, status: dict, cutoff: str) -> dict:
    session_date = status["session"]["session_date"]
    mine = lambda name: [r for r in files[name]["records"] if r.get("market", market) == market and r.get("ticker") == ticker]  # noqa: E731
    company = pick(next(r for r in mine("company")), COMPANY_FIELDS)
    lifecycle = sorted((pick(r, LIFECYCLE_FIELDS) for r in mine("lifecycle_event") if r["recorded_at"] <= cutoff),
                       key=lambda r: (r["recorded_at"], r["id"]))
    agreement = {str(k): [r for r in mine("agreement") if r["horizon_days"] == k] for k in HORIZONS}
    picks = sorted((pick(r, PICK_FIELDS) for r in mine("head_to_head_pick") if r["session_date"] == session_date and r["made_at"] <= cutoff),
                   key=lambda r: (r["family"], r["pick_rule"]))
    predictions = sorted((pick(r, PREDICTION_FIELDS) for r in mine("prediction")
                          if r["as_of_date"] == status["as_of"] and r["made_at"] <= cutoff),
                         key=lambda r: (r["strategy_id"], r["horizon_days"]))
    open_trades = sorted((pick(r, OPEN_TRADE_FIELDS) for r in mine("open_trade")), key=lambda r: (r["horizon_days"], r["trade_id"]))
    checks = [r for r in mine("trade_check") if r["check_at"] <= cutoff]
    latest = max((r["check_at"] for r in checks), default=None)
    checks = sorted((pick(r, CHECK_FIELDS) for r in checks if r["check_at"] == latest), key=lambda r: r["trade_id"])
    trades = sorted((pick(r, TRADE_FIELDS) for r in mine("paper_trade") if r["settled_at"] <= cutoff),
                    key=lambda r: (r["exit_date_actual"] or r["exit_date"], r["entry_date"], r["trade_id"]), reverse=True)
    reasons = sorted((pick(r, REASON_FIELDS) for r in mine("reason_ai") if r["created_at"] <= cutoff),
                     key=lambda r: (r["session_date"], r["kind"], r["rank"] or 0, r["id"]), reverse=True)
    news = sorted((pick(r, NEWS_FIELDS) for r in files["news_item"]["records"]
                   if r["market"] == market and ticker in r["tickers"] and r["first_seen_at"] <= cutoff),
                  key=lambda r: r["published_at"], reverse=True)
    digests = sorted((pick(r, DIGEST_FIELDS) for r in files["results_digest"]["records"]
                      if r["ticker"] == ticker and r["created_at"] <= cutoff), key=lambda r: r["release_at"], reverse=True)
    events = sorted((pick(r, CALENDAR_FIELDS) for r in files["calendar_event"]["records"]
                     if r["market"] == market and r["date"] >= session_date
                     and (r["ticker"] == ticker or (r["ticker"] is None and (r["major"] or r["type"] == "holiday")))),
                    key=lambda r: (r["date"], r["type"], r["name"]))
    bars = sorted((pick(r, BAR_FIELDS) for r in mine("bar") if r["date"] <= status["as_of"]), key=lambda r: r["date"])
    on_company = sorted((pick(r, ROW_FIELDS) for r in files["scoreboard_row"]["records"]
                         if r["market"] == market and r["scope"] == "strategy_company" and r["ticker"] == ticker
                         and r["view"] == "accuracy" and r["horizon_days"] == "all"),
                        key=lambda r: r["strategy_id"])
    return {
        "ticker": ticker, "company": company, "lifecycle": lifecycle, "agreement": agreement, "head_to_head": picks,
        "predictions": predictions, "open_trades": open_trades, "trade_checks": checks, "settled": trades,
        "reasons": reasons, "news": news, "results": digests, "events": events, "bars": bars, "on_company": on_company,
    }


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    tickers = sorted({r["ticker"] for r in files["bar"]["records"] if r["market"] == market})
    companies = [pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market]
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "reference_strategy": REFERENCE_STRATEGY,
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "strategies": strategies,
        "companies": sorted(companies, key=lambda c: c["ticker"]),
        "default_ticker": {"india": "RELIANCE", "us": "NVDA"}[market],
        "pages": {t: company_payload(market, t, files, status, cutoff) for t in tickers},
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("company", "docs/SPEC.md section 6, page 3; decisions 13, 26, 39, 43, 44",
                    "GET /api/v1/markets/{market}/stocks/{ticker}", "rm.stock + rm.bars + rm.lifecycle + rm.trades",
                    NAMES, cutoff, markets)
    data["_pages"] = ("one payload per (market, ticker) = markets.<market>.pages.<ticker>; the market-level keys "
                      "(status, strategies, go_live, companies) are shared; the mockup embeds every company the "
                      "catalogue holds bars for")
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: ", ".join(
        f"{t}: bars {len(c['bars'])}, predictions {len(c['predictions'])}, open {len(c['open_trades'])}, "
        f"checks {len(c['trade_checks'])}, settled {len(c['settled'])}, reasons {len(c['reasons'])}, news {len(c['news'])}, "
        f"results {len(c['results'])}, events {len(c['events'])}" for t, c in p["pages"].items()))
