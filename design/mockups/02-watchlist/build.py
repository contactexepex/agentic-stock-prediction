"""Watchlist mockup (docs/SPEC.md section 6, page 2; decisions 13, 30, 39).

    python design/mockups/02-watchlist/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/watchlist` (read model `rm.watchlist`)
for both markets from W1's example files in design/catalogue/ only, and renders `page.html` from `template.html`
with the design system and the shared shell inlined (design/mockups/_shared/mockup.py). Every value is a catalogue
field; the only logic here is selection and ordering. Deterministic: no wall clock.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "company", "agreement", "open_trade", "trade_check", "prediction", "scoreboard_row", "strategy")
COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "state_since", "amount", "amount_overridden",
                  "currency", "last_close", "last_close_date", "change_pct", "agreement_n1", "open_trades")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
CHECK_FIELDS = ("id", "check_id", "check_row_id", "check_at", "session_date", "market", "ticker", "trade_id", "prediction_id",
                "strategy_id", "view", "horizon_days", "entry_date", "exit_date", "session_number", "entry_price", "last_price",
                "ret_since_entry_pct", "target_price", "to_target_pct", "lo80", "lo50", "hi50", "hi80", "band", "target_z",
                "flags", "flagged", "method_version", "computed_at")
GO_LIVE_FIELDS = ("proven", "months_forward", "trades_needed", "beats_best_baseline")
PREDICTION_FIELDS = ("id", "strategy_id", "family", "ticker", "made_at", "as_of_date", "session_date", "exit_date",
                     "horizon_days", "direction", "prob_up", "qualifies", "base_close", "target_price",
                     "lo50", "hi50", "lo80", "hi80", "range_widen", "regime", "quality")
REFERENCE_STRATEGY = "rule.model_news.v1"   # the registry's reference rule strategy (config/strategies.yaml)


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    companies = [pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market]
    active = {c["ticker"] for c in companies if c["state"] == "active"}
    agreement = {str(k): sorted((r for r in files["agreement"]["records"]
                                 if r["market"] == market and r["horizon_days"] == k and r["ticker"] in active),
                                key=lambda r: r["rank"]) for k in HORIZONS}
    open_trades = [r for r in files["open_trade"]["records"] if r["market"] == market]
    checks = [r for r in files["trade_check"]["records"] if r["market"] == market and r["check_at"] <= cutoff]
    latest = max((r["check_at"] for r in checks), default=None)
    checks = [pick(r, CHECK_FIELDS) for r in checks if r["check_at"] == latest]
    # today's published range per company and horizon: the reference strategy's prediction, where the example holds one
    ranges = [pick(r, PREDICTION_FIELDS) for r in files["prediction"]["records"]
              if r["market"] == market and r["as_of_date"] == status["as_of"] and r["strategy_id"] == REFERENCE_STRATEGY
              and r["made_at"] <= cutoff]
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status,
        "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "companies": sorted(companies, key=lambda c: c["ticker"]),
        "agreement": agreement,
        "open_trades": open_trades,
        "trade_checks": checks,
        "ranges": sorted(ranges, key=lambda r: (r["ticker"], r["horizon_days"])),
        "go_live": pick(reference["go_live"], GO_LIVE_FIELDS),
        "strategies": strategies,
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    return envelope("watchlist", "docs/SPEC.md section 6, page 2; decisions 13, 30, 39",
                    "GET /api/v1/markets/{market}/watchlist", "rm.watchlist", NAMES, cutoff, markets)


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"as of {p['as_of']}, {sum(c['state'] == 'active' for c in p['companies'])} active of "
                                 f"{len(p['companies'])} companies, agreement N+1 {[(r['ticker'], r['buy']) for r in p['agreement']['1']]}, "
                                 f"open trades {len(p['open_trades'])}, checks {len(p['trade_checks'])}, ranges {len(p['ranges'])}")
