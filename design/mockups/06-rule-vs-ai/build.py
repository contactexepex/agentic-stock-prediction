"""Rule vs AI mockup (docs/SPEC.md section 6, page 6; F1 head-to-head view, F6, F7.1; decisions 41-43, 50).

    python design/mockups/06-rule-vs-ai/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/compare` (read models `rm.compare` and
`rm.review`) for both markets from W1's example files only: the head-to-head scoreboard rows (per strategy, per pick
rule, per regime), the settled head-to-head trades (the matches on identical company-days), today's picks, the
EOD analyst's head-to-head reasons and day summaries, and the weekly research review. Selection and ordering only;
no look-ahead; deterministic.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "strategy", "scoreboard_row", "paper_trade", "head_to_head_pick", "reason_ai", "eod_analysis",
         "research_review", "company", "cost_view")
STRATEGY_FIELDS = ("id", "family", "name", "description", "compared_to", "differs_in", "threshold", "horizons", "live",
                   "settled_trades")
LUCK_FIELDS = ("method", "n", "m", "low_pct", "high_pct", "excludes_zero", "corrected_low_pct", "corrected_high_pct",
               "corrected")
YOUR_FIELDS = ("net_pnl", "mean_return_pct", "win_rate", "worst_losing_streak", "max_drawdown")
ROW_FIELDS = ("scope", "market", "view", "basis", "strategy_id", "family", "pick_rule", "ticker", "regime", "horizon_days",
              "trades", "net_pnl", "mean_return_pct", "win_rate", "target_reached_rate", "median_reached_session",
              "avg_target_error_pct", "range_hit_rate", "worst_losing_streak", "max_drawdown", "sample_badge",
              "first_entry", "last_exit", "as_of")
TRADE_FIELDS = ("trade_id", "prediction_id", "strategy_id", "family", "view", "pick_rule", "ticker", "horizon_days",
                "made_at", "entry_date", "exit_date", "exit_date_actual", "status", "amount", "currency", "entry_price",
                "exit_price", "net_pnl", "return_pct", "prob_up", "target_price", "target_error_pct", "target_reached",
                "range_hit", "move_pct", "market_pct", "sector_pct", "news_pct", "company_pct", "reason_code",
                "reason_codes", "regime", "settled_at")
PICK_FIELDS = ("id", "market", "ticker", "made_at", "as_of_date", "session_date", "family", "pick_rule", "status",
               "strategy_id", "strongest_basis", "horizon_days", "prediction_id", "prob_up", "move_pct", "loss_pct",
               "costs_pct", "expected_gain_pct", "candidates", "amount", "currency")
REASON_FIELDS = ("id", "trade_id", "market", "ticker", "strategy_id", "session_date", "kind", "rank", "text", "cited_ids",
                 "reason_codes", "created_at")
EOD_FIELDS = ("id", "market", "session_date", "settled_trades", "results", "summary", "cited_ids", "reason_ids", "created_at")
REVIEW_FIELDS = ("id", "market", "iso_week", "period_start", "period_end", "leaders", "findings", "proposals",
                 "report_path", "written_at")
COST_FIELDS = ("trade_id", "record_id", "net_pnl_market", "return_pct_market", "net_pnl_your", "return_pct_your",
               "market_costs", "your_costs", "your_cost_pct", "computed_at")
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state", "amount", "amount_overridden", "currency")
REFERENCE_STRATEGY = "rule.model_news.v1"


def row(r: dict) -> dict:
    out = pick(r, ROW_FIELDS)
    out["luck_test"] = pick(r["luck_test"], LUCK_FIELDS) if r["luck_test"] else None
    yc = r.get("your_cost")
    out["your_cost"] = ({**pick(yc, YOUR_FIELDS), "luck_test": pick(yc["luck_test"], LUCK_FIELDS) if yc.get("luck_test") else None}
                        if yc else None)
    return out


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    session_date = status["session"]["session_date"]
    rows = sorted((row(r) for r in files["scoreboard_row"]["records"] if r["market"] == market and r["view"] == "head_to_head"),
                  key=lambda r: (r["scope"], r["basis"], str(r["strategy_id"]), str(r["pick_rule"]), str(r["regime"]), str(r["horizon_days"])))
    trades = sorted((pick(r, TRADE_FIELDS) for r in files["paper_trade"]["records"]
                     if r["market"] == market and r["view"] == "head_to_head" and r["settled_at"] <= cutoff),
                    key=lambda r: (r["entry_date"], r["ticker"], str(r["pick_rule"]), r["family"]))
    picks = sorted((pick(r, PICK_FIELDS) for r in files["head_to_head_pick"]["records"]
                    if r["market"] == market and r["made_at"] <= cutoff),
                   key=lambda r: (r["session_date"], r["ticker"], r["family"], r["pick_rule"]))
    trade_ids = {t["trade_id"] for t in trades}
    your_costs = sorted((pick(r, COST_FIELDS) for r in files["cost_view"]["records"]
                         if r["market"] == market and r["record_kind"] == "settlement" and r["trade_id"] in trade_ids
                         and r["computed_at"] <= cutoff), key=lambda r: r["record_id"])
    reasons = sorted((pick(r, REASON_FIELDS) for r in files["reason_ai"]["records"]
                      if r["market"] == market and r["kind"] == "head_to_head" and r["created_at"] <= cutoff),
                     key=lambda r: (r["session_date"], r["ticker"], r["strategy_id"]), reverse=True)
    eod = sorted((pick(r, EOD_FIELDS) for r in files["eod_analysis"]["records"] if r["market"] == market and r["created_at"] <= cutoff),
                 key=lambda r: r["session_date"], reverse=True)
    reviews = sorted((pick(r, REVIEW_FIELDS) for r in files["research_review"]["records"]
                      if r["market"] == market and r["written_at"] <= cutoff), key=lambda r: r["iso_week"], reverse=True)
    cutoff_day = date.fromisoformat(cutoff[:10])
    saturday = cutoff_day + timedelta(days=(5 - cutoff_day.weekday()) % 7)   # the weekly review runs on Saturday (F6.2)
    review_due = {"date": saturday.isoformat(), "iso_week": f"{saturday.isocalendar()[0]}-W{saturday.isocalendar()[1]:02d}"}
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    companies = [pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market]
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": "all",
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "strategies": strategies, "companies": sorted(companies, key=lambda c: c["ticker"]),
        "session_date": session_date,
        "rows": rows, "trades": trades, "your_costs": your_costs, "picks": picks, "reasons": reasons, "eod": eod,
        "reviews": reviews, "review_due": review_due,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("rule-vs-ai", "docs/SPEC.md section 6, page 6; F1 head-to-head view, F6, F7.1; decisions 41-43, 50",
                    "GET /api/v1/markets/{market}/compare", "rm.compare + rm.review", NAMES, cutoff, markets)
    data["_data_requests"] = [
        "head-to-head scoreboard rows per company (scope strategy_company with view head_to_head) so the per-company "
        "comparison reads from the scoreboard instead of being summed from the settled trades",
        "a research review written before the catalogue's as_of (e.g. 2026-W40, written Saturday 3 Oct) for both markets: "
        "both stored reviews are written on 10 Oct, after the cut-off, so the weekly-review card is an empty state",
    ]
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"h2h rows {len(p['rows'])}, h2h trades {len(p['trades'])}, picks {len(p['picks'])}, "
                                 f"your-cost rows {len(p['your_costs'])}, reasons {len(p['reasons'])}, eod {len(p['eod'])}, reviews {len(p['reviews'])} "
                                 f"(next due {p['review_due']['date']})")
