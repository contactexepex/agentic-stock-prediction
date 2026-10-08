"""Stock strategies mockup (docs/SPEC.md section 6, page 4; decisions 30, 39, 41, 42 and the luck guard of section 6).

    python design/mockups/04-stock-strategies/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/stocks/{ticker}/strategies` (read model
`rm.stock_strategies`, page_key = ticker) for the companies whose predictions the catalogue holds (RELIANCE, NVDA),
from W1's example files only, and renders `page.html` through the shared builder. Selection and ordering only;
deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "company", "agreement", "head_to_head_pick", "prediction", "scoreboard_row", "strategy")
COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "amount", "amount_overridden", "currency",
                  "last_close", "last_close_date", "change_pct", "agreement_n1", "open_trades")
STRATEGY_FIELDS = ("id", "family", "name", "description", "compared_to", "differs_in", "parameters", "threshold",
                   "horizons", "live", "settled_trades")
PREDICTION_FIELDS = ("id", "strategy_id", "family", "ticker", "made_at", "as_of_date", "session_date", "exit_date",
                     "horizon_days", "direction", "prob_up", "confidence", "threshold", "qualifies", "base_close",
                     "target_price", "lo50", "hi50", "lo80", "hi80", "range_widen", "model_prob", "agent_adjustment",
                     "adjustment_reason", "evidence_ids", "reason", "regime", "quality", "amount", "currency")
ROW_FIELDS = ("scope", "market", "view", "basis", "strategy_id", "family", "ticker", "horizon_days", "trades", "net_pnl",
              "mean_return_pct", "win_rate", "target_reached_rate", "median_reached_session", "avg_target_error_pct",
              "range_hit_rate", "worst_losing_streak", "max_drawdown", "sample_badge", "first_entry", "last_exit",
              "luck_test", "as_of")
REFERENCE_STRATEGY = "rule.model_news.v1"


def payload(market: str, ticker: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    company = pick(next(r for r in files["company"]["records"] if r["market"] == market and r["ticker"] == ticker), COMPANY_FIELDS)
    agreement = {str(k): [r for r in files["agreement"]["records"] if r["market"] == market and r["ticker"] == ticker and r["horizon_days"] == k]
                 for k in HORIZONS}
    picks = [r for r in files["head_to_head_pick"]["records"]
             if r["market"] == market and r["ticker"] == ticker and r["session_date"] == status["session"]["session_date"]
             and r["made_at"] <= cutoff]
    predictions = sorted((pick(r, PREDICTION_FIELDS) for r in files["prediction"]["records"]
                          if r["market"] == market and r["ticker"] == ticker and r["as_of_date"] == status["as_of"] and r["made_at"] <= cutoff),
                         key=lambda r: (r["strategy_id"], r["horizon_days"]))
    on_company = [pick(r, ROW_FIELDS) for r in files["scoreboard_row"]["records"]
                  if r["market"] == market and r["scope"] == "strategy_company" and r["ticker"] == ticker and r["view"] == "accuracy"]
    overall = [pick(r, ROW_FIELDS) for r in files["scoreboard_row"]["records"]
               if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy" and r["horizon_days"] == "all"]
    reference_full = next(r for r in files["scoreboard_row"]["records"]
                          if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                          and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    return {
        "market": market, "ticker": ticker, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "company": company,
        "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "agreement": agreement, "head_to_head": picks, "predictions": predictions,
        "on_company": sorted(on_company, key=lambda r: (r["strategy_id"], str(r["horizon_days"]))),
        "overall": sorted(overall, key=lambda r: r["strategy_id"]),
        "go_live": pick(reference_full["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")), "strategies": strategies,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    pages = {"india": payload("india", "RELIANCE", files, cutoff), "us": payload("us", "NVDA", files, cutoff)}
    data = envelope("stock-strategies", "docs/SPEC.md section 6, page 4; decisions 30, 39, 41, 42",
                    "GET /api/v1/markets/{market}/stocks/{ticker}/strategies", "rm.stock_strategies", NAMES, cutoff, pages)
    data["_pages"] = "one payload per (market, ticker); the mockup embeds the two companies whose predictions the catalogue holds"
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"{p['ticker']}: predictions {len(p['predictions'])}, picks {len(p['head_to_head'])}, "
                                 f"rows on company {len(p['on_company'])}, overall {len(p['overall'])}")
