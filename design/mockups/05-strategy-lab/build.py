"""Strategy lab mockup (docs/SPEC.md section 6, page 5; F2, F2.8, F7; decisions 42, 50).

    python design/mockups/05-strategy-lab/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/strategies` (read model `rm.strategies`)
for both markets from W1's example files only: the registry, every scoreboard row (both views, every horizon,
per company, per regime, per pick rule), and the settled paper trades the cumulative lines and the reason-code
heatmap are drawn from. Selection and ordering only; no look-ahead; deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "strategy", "scoreboard_row", "paper_trade", "company")
STRATEGY_FIELDS = ("id", "family", "name", "description", "compared_to", "differs_in", "parameters", "threshold",
                   "horizons", "live_from", "live", "settled_trades")
LUCK_FIELDS = ("method", "n", "m", "low_pct", "high_pct", "excludes_zero", "corrected_low_pct", "corrected_high_pct",
               "corrected")
YOUR_FIELDS = ("net_pnl", "mean_return_pct", "win_rate", "worst_losing_streak", "max_drawdown")
ROW_FIELDS = ("scope", "market", "view", "basis", "strategy_id", "family", "pick_rule", "ticker", "regime", "horizon_days",
              "trades", "net_pnl", "mean_return_pct", "win_rate", "target_reached_rate", "median_reached_session",
              "avg_target_error_pct", "range_hit_rate", "worst_losing_streak", "max_drawdown", "sample_badge",
              "first_entry", "last_exit", "as_of")
GO_LIVE_FIELDS = ("proven", "months_forward", "trades_needed", "beats_best_baseline", "best_baseline_net_pnl",
                  "drawdown_limit", "drawdown_within_limit", "holds_in_calm_and_volatile", "cost_view")
TRADE_FIELDS = ("trade_id", "strategy_id", "family", "view", "pick_rule", "ticker", "horizon_days", "entry_date",
                "exit_date", "exit_date_actual", "status", "amount", "currency", "net_pnl", "return_pct",
                "reason_code", "reason_codes", "regime", "settled_at")
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state")
REFERENCE_STRATEGY = "rule.model_news.v1"


def row(r: dict) -> dict:
    out = pick(r, ROW_FIELDS)
    out["luck_test"] = pick(r["luck_test"], LUCK_FIELDS) if r["luck_test"] else None
    yc = r.get("your_cost")
    out["your_cost"] = ({**pick(yc, YOUR_FIELDS), "luck_test": pick(yc["luck_test"], LUCK_FIELDS) if yc.get("luck_test") else None}
                        if yc else None)
    if r.get("go_live"):
        out["go_live"] = pick(r["go_live"], GO_LIVE_FIELDS)
    return out


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    rows = sorted((row(r) for r in files["scoreboard_row"]["records"] if r["market"] == market),
                  key=lambda r: (r["scope"], r["view"], r["basis"], str(r["strategy_id"]), str(r["pick_rule"]),
                                 str(r["ticker"]), str(r["regime"]), str(r["horizon_days"])))
    trades = sorted((pick(r, TRADE_FIELDS) for r in files["paper_trade"]["records"]
                     if r["market"] == market and r["status"] == "settled" and r["settled_at"] <= cutoff),
                    key=lambda r: (r["exit_date_actual"] or r["exit_date"], r["entry_date"], r["trade_id"]))
    reference = next(r for r in rows if r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    companies = [pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market]
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": "all",
        "reference_strategy": REFERENCE_STRATEGY,
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "strategies": strategies, "companies": sorted(companies, key=lambda c: c["ticker"]),
        "rows": rows, "trades": trades,
        "bases": sorted({r["basis"] for r in rows}),
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("strategy-lab", "docs/SPEC.md section 6, page 5; F2, F2.8, F7; decisions 42, 50",
                    "GET /api/v1/markets/{market}/strategies", "rm.strategies", NAMES, cutoff, markets)
    data["_data_requests"] = [
        "scoreboard rows with basis `backtest` (F2.3: the strategies that need no news, on the 15-year history; "
        "never pooled with forward) so the Back-test switch shows numbers instead of its empty state",
        "weekly scoreboard rows (per iso_week) and a per-reason-code scope for the F2.8 heatmaps over time; the "
        "mockup derives the reason-code heatmap and the cumulative lines from the settled trades of the one stored week",
    ]
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"rows {len(p['rows'])} (scopes {sorted({r['scope'] for r in p['rows']})}, bases {p['bases']}), "
                                 f"settled trades {len(p['trades'])}, strategies {len(p['strategies'])}")
