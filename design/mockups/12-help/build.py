"""Help mockup (docs/SPEC.md section 6, page 12; decision 35): how to read the cockpit in plain words.

    python design/mockups/12-help/build.py [--out DIR]

The Help page is static content (SPEC section 6: "static content"). Its `data.json` carries only what the shared
shell needs (the market status and the go-live state) and the strategy registry, so the strategy list and the
go-live wording come from the catalogue rather than from typed text. Deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "strategy", "scoreboard_row", "portfolio")
STRATEGY_FIELDS = ("id", "family", "name", "description", "compared_to", "differs_in", "threshold", "horizons", "live")
GO_LIVE_FIELDS = ("proven", "months_forward", "trades_needed", "beats_best_baseline", "best_baseline_net_pnl",
                  "drawdown_limit", "drawdown_within_limit", "holds_in_calm_and_volatile", "cost_view")
REFERENCE_STRATEGY = "rule.model_news.v1"


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "go_live_detail": pick(reference["go_live"], GO_LIVE_FIELDS),
        "default_amount": files["portfolio"]["records"][0]["default_amounts"][market],
        "strategies": strategies,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    return envelope("help", "docs/SPEC.md section 6, page 12; decision 35", "(static content; no endpoint)", "(none)",
                    NAMES, cutoff, markets)


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"strategies {len(p['strategies'])}, go-live {p['go_live_detail']}")
