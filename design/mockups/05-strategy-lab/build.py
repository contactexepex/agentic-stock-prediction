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

NAMES = ("market_status", "strategy", "scoreboard_row", "scoreboard_backtest_row", "heatmap_cell", "cumulative_line", "company")
CELL_FIELDS = ("market", "view", "basis", "strategy_id", "dimension", "column", "week", "trades", "wins", "win_rate", "net_pnl")
LINE_FIELDS = ("market", "view", "basis", "series", "date", "net_pnl", "cumulative_net_pnl")
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
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state")
REFERENCE_STRATEGY = "rule.model_news.v1"


# A back-test row (scope strategy only) has no as_of, go_live, pick_rule, ticker or regime; its your_cost holds net_pnl
# and mean_return_pct only. The three scope keys are set to null so the page's filters treat the row like any other.
BACKTEST_ROW_FIELDS = tuple(f for f in ROW_FIELDS if f not in ("as_of", "pick_rule", "ticker", "regime"))
BACKTEST_YOUR_FIELDS = ("net_pnl", "mean_return_pct")
BACKTEST_RUN_FIELDS = ("history", "first_date", "last_date", "eurusd", "note")


def row(r: dict) -> dict:
    backtest = r["basis"] == "backtest"
    out = pick(r, BACKTEST_ROW_FIELDS if backtest else ROW_FIELDS)
    if backtest:
        out.update({"pick_rule": None, "ticker": None, "regime": None})
    out["luck_test"] = pick(r["luck_test"], LUCK_FIELDS) if r["luck_test"] else None
    yc = r.get("your_cost")
    if yc is None:
        out["your_cost"] = None
    elif backtest:
        out["your_cost"] = pick(yc, BACKTEST_YOUR_FIELDS)            # no luck test stored for the your-cost view
    else:
        out["your_cost"] = {**pick(yc, YOUR_FIELDS),
                            "luck_test": pick(yc["luck_test"], LUCK_FIELDS) if yc.get("luck_test") else None}
    if r.get("go_live"):
        out["go_live"] = pick(r["go_live"], GO_LIVE_FIELDS)
    return out


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    # forward rows (the scoreboard) and the back-test rows (basis `backtest`, F2.3, W1's answer to the track's data
    # request): the same fields, never pooled (every row carries its basis; the page filters on it)
    rows = sorted((row(r) for name in ("scoreboard_row", "scoreboard_backtest_row")
                   for r in files[name]["records"] if r["market"] == market),
                  key=lambda r: (r["scope"], r["view"], r["basis"], str(r["strategy_id"]), str(r["pick_rule"]),
                                 str(r["ticker"]), str(r["regime"]), str(r["horizon_days"])))
    backtest_run = pick(files["scoreboard_backtest_row"]["runs"][market], BACKTEST_RUN_FIELDS)
    # F2.8 heatmap cells (per strategy, dimension horizon / company / reason_code, per ISO week of exit or all) and
    # cumulative-profit points (per strategy in the accuracy view, per family:pick_rule in the head-to-head view),
    # W1's answer to the track's data request; both built by B2's code from the example trades, forward basis
    cells = sorted((pick(r, CELL_FIELDS) for r in files["heatmap_cell"]["records"] if r["market"] == market),
                   key=lambda r: (r["view"], r["basis"], r["dimension"], r["week"], r["strategy_id"], r["column"]))
    lines = sorted((pick(r, LINE_FIELDS) for r in files["cumulative_line"]["records"] if r["market"] == market),
                   key=lambda r: (r["view"], r["basis"], r["series"], r["date"]))
    assert all(r["date"] <= cutoff[:10] for r in lines), "a cumulative point after the cut-off"
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
        "rows": rows, "cells": cells, "lines": lines,
        "bases": sorted({r["basis"] for r in rows}),
        "backtest_run": backtest_run,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    data = envelope("strategy-lab", "docs/SPEC.md section 6, page 5; F2, F2.8, F7; decisions 42, 50",
                    "GET /api/v1/markets/{market}/strategies", "rm.strategies", NAMES, cutoff, markets)
    data["_data_requests"] = [
        "scoreboard rows with basis `backtest` (F2.3, never pooled with forward): answered by W1 with "
        "scoreboard_backtest_row.json (always-up and momentum on the stored bars, without the 15-year history cache; "
        "model-only and the rule strategies are not run; the US BUX fee at an ASSUMED EUR/USD), shown on the Back-test "
        "basis with the run's facts; a run on the history cache and the model-only rows stay open",
        "weekly scoreboard rows (per iso_week) and a per-reason-code scope for the F2.8 heatmaps over time: answered by "
        "W1 with heatmap_cell.json (per strategy, by horizon / company / reason code, per ISO week of exit or all weeks) and "
        "cumulative_line.json (per strategy, or per family and pick rule in the head-to-head view); both are read now: the "
        "heatmaps have a week picker and the lines are the stored running totals",
    ]
    return data


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"rows {len(p['rows'])} (scopes {sorted({r['scope'] for r in p['rows']})}, bases {p['bases']}), "
                                 f"cells {len(p['cells'])}, line points {len(p['lines'])}, strategies {len(p['strategies'])}")
