"""Paper portfolios mockup (docs/SPEC.md section 6, page 7; F1.11, F7.1, F10; decisions 11, 26, 41-42, 44, 50).

    python design/mockups/07-paper-portfolios/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/portfolios` (read models `rm.portfolio`
and `rm.trades`) for both markets from W1's example files only: the head-to-head portfolios (scoreboard rows per
family and per pick rule), every open paper trade with its latest intraday check, and the owner's own paper trades
and positions with the EUR view of US positions. Selection and ordering only; no look-ahead; deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "strategy", "scoreboard_row", "open_trade", "trade_check", "portfolio", "company")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
LUCK_FIELDS = ("method", "n", "m", "low_pct", "high_pct", "excludes_zero", "corrected_low_pct", "corrected_high_pct",
               "corrected")
YOUR_FIELDS = ("net_pnl", "mean_return_pct", "win_rate", "worst_losing_streak", "max_drawdown")
ROW_FIELDS = ("scope", "market", "view", "basis", "strategy_id", "family", "pick_rule", "horizon_days", "trades", "net_pnl",
              "mean_return_pct", "win_rate", "target_reached_rate", "avg_target_error_pct", "range_hit_rate",
              "worst_losing_streak", "max_drawdown", "sample_badge", "first_entry", "last_exit", "as_of")
OPEN_TRADE_FIELDS = ("trade_id", "view", "prediction_id", "strategy_id", "family", "market", "ticker", "horizon_days",
                     "entry_date", "exit_date", "entry_price", "quantity", "amount", "currency", "target_price", "lo80",
                     "lo50", "hi50", "hi80", "last_price", "last_price_date", "unrealised_pnl", "unrealised_pct",
                     "to_target_pct", "paper")
CHECK_FIELDS = ("id", "check_at", "session_date", "market", "ticker", "trade_id", "strategy_id", "view", "horizon_days",
                "session_number", "entry_price", "last_price", "ret_since_entry_pct", "target_price", "to_target_pct",
                "band", "flags", "flagged", "quality", "high_since_entry_pct", "low_since_entry_pct")
OWNER_TRADE_FIELDS = ("id", "market", "ticker", "side", "quantity", "price", "price_basis", "trade_date", "source",
                      "idempotency_key", "entered_at", "note", "supersedes")
POSITION_FIELDS = ("market", "ticker", "quantity", "avg_price", "last_close", "last_close_date", "currency", "cost", "value",
                   "pnl", "pnl_pct", "eur_view")
EUR_FIELDS = ("ticker", "quantity", "mark_date", "eurusd_at_buy", "eurusd_now", "fx_fee_rate", "cost_usd", "value_usd",
              "cost_eur", "value_eur", "fx_effect_eur", "pnl_eur", "note")
COMPANY_FIELDS = ("market", "ticker", "name", "sector", "state", "amount", "amount_overridden", "currency", "last_close",
                  "last_close_date")
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
    rows = sorted((row(r) for r in files["scoreboard_row"]["records"]
                   if r["market"] == market and r["view"] == "head_to_head" and r["scope"] in ("strategy", "pick_rule")),
                  key=lambda r: (r["scope"], str(r["family"]), str(r["pick_rule"]), str(r["strategy_id"]), str(r["horizon_days"])))
    open_trades = sorted((pick(r, OPEN_TRADE_FIELDS) for r in files["open_trade"]["records"] if r["market"] == market),
                         key=lambda r: (r["strategy_id"], r["ticker"], r["horizon_days"], r["trade_id"]))
    checks = [r for r in files["trade_check"]["records"] if r["market"] == market and r["check_at"] <= cutoff]
    latest = max((r["check_at"] for r in checks), default=None)
    checks = sorted((pick(r, CHECK_FIELDS) for r in checks if r["check_at"] == latest), key=lambda r: r["trade_id"])
    portfolio = files["portfolio"]["records"][0]
    owner_trades = sorted((pick(r, OWNER_TRADE_FIELDS) for r in portfolio["owner_trades"]
                           if r["market"] == market and r["entered_at"] <= cutoff), key=lambda r: (r["trade_date"], r["id"]))
    positions = []
    for r in portfolio["positions"]:
        if r["market"] != market:
            continue
        p = pick(r, POSITION_FIELDS)
        p["eur_view"] = pick(r["eur_view"], EUR_FIELDS) if r["eur_view"] else None
        positions.append(p)
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    companies = [pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market]
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "strategies": strategies, "companies": sorted(companies, key=lambda c: c["ticker"]),
        "h2h_rows": rows, "open_trades": open_trades, "trade_checks": checks,
        "owner": {"trades": owner_trades, "positions": sorted(positions, key=lambda p: p["ticker"]),
                  "default_amount": portfolio["default_amounts"][market], "paper": portfolio["paper"]},
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    return envelope("paper-portfolios", "docs/SPEC.md section 6, page 7; F1.11, F7.1, F10; decisions 11, 26, 41-42, 44, 50",
                    "GET /api/v1/markets/{market}/portfolios", "rm.portfolio + rm.trades", NAMES, cutoff, markets)


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"h2h rows {len(p['h2h_rows'])}, open trades {len(p['open_trades'])}, checks {len(p['trade_checks'])}, "
                                 f"owner trades {len(p['owner']['trades'])}, positions {len(p['owner']['positions'])}")
