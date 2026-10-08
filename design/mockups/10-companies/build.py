"""Companies mockup (docs/SPEC.md section 6, page 10; F8, F10; decisions 12-15, 20, 26, 33, 44).

    python design/mockups/10-companies/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/companies` (read model `rm.companies`)
for both markets from W1's example files only: every company (active and inactive; a deleted company is never
shown, decision 12), its lifecycle events, the recent commands of the governed tool layer (accepted, refused,
pending), the inactive companies' news since they went inactive, and the market's default amount. Selection and
ordering only; no look-ahead; deterministic.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_shared"))
from mockup import HORIZONS, MARKETS, envelope, load, pick, run  # noqa: E402

NAMES = ("market_status", "company", "lifecycle_event", "command_log", "news_item", "portfolio", "scoreboard_row")
COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "state_since", "added_at", "amount",
                  "amount_overridden", "currency", "yahoo", "nse_symbol", "cik", "last_close", "last_close_date",
                  "change_pct", "agreement_n1", "open_trades")
LIFECYCLE_FIELDS = ("id", "event", "ticker", "market", "effective_from", "recorded_at", "name", "exchange", "sector",
                    "amount", "reason", "requested_by", "channel", "command_id", "idempotency_key", "onboarding",
                    "supersedes")
COMMAND_FIELDS = ("id", "market", "received_at", "channel", "actor", "agent", "tool", "kind", "arguments",
                  "idempotency_key", "result", "refusal_code", "message", "record_ids", "budget_left", "completed_at")
NEWS_FIELDS = ("id", "market", "tickers", "primary_tickers", "title", "source", "published_at", "first_seen_at", "status",
               "enrichment")
REFERENCE_STRATEGY = "rule.model_news.v1"


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    companies = sorted((pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market),
                       key=lambda c: (c["state"] != "active", c["ticker"]))
    shown = {c["ticker"] for c in companies}
    events = [r for r in files["lifecycle_event"]["records"] if r["market"] == market and r["recorded_at"] <= cutoff]
    deleted = {r["ticker"] for r in events if r["event"] == "delete"}
    lifecycle = sorted((pick(r, LIFECYCLE_FIELDS) for r in events if r["ticker"] in shown and r["ticker"] not in deleted),
                       key=lambda r: (r["recorded_at"], r["id"]), reverse=True)
    commands = sorted((pick(r, COMMAND_FIELDS) for r in files["command_log"]["records"]
                       if r["market"] == market and r["received_at"] <= cutoff
                       and r["tool"] in ("add_company", "deactivate_company", "reactivate_company", "set_paper_amount", "delete_company")),
                      key=lambda r: r["received_at"], reverse=True)
    for c in commands:   # a deleted company is never shown (decision 12): every echo of it in the command is masked
        for t in deleted:
            if t in (c["message"] or "") or t == c["arguments"].get("symbol") or t == c["arguments"].get("ticker") \
                    or t.lower() in (c["idempotency_key"] or "").lower() or any(t in rid for rid in (c["record_ids"] or [])):
                c["arguments"] = {k: ("(deleted company)" if v == t else v) for k, v in c["arguments"].items()}
                c["message"] = "(this company was deleted later; its records are excluded on read)"
                c["idempotency_key"] = "(masked)" if c["idempotency_key"] else None
                c["record_ids"] = ["(masked)"] * len(c["record_ids"] or [])
    inactive = {c["ticker"]: c["state_since"] for c in companies if c["state"] == "inactive"}
    news = sorted((pick(r, NEWS_FIELDS) for r in files["news_item"]["records"]
                   if r["market"] == market and r["first_seen_at"] <= cutoff
                   and any(t in inactive and r["first_seen_at"] >= inactive[t] for t in r["tickers"])),
                  key=lambda r: r["first_seen_at"], reverse=True)
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == REFERENCE_STRATEGY and r["horizon_days"] == "all")
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status, "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "go_live": pick(reference["go_live"], ("proven", "months_forward", "trades_needed", "beats_best_baseline")),
        "default_amount": files["portfolio"]["records"][0]["default_amounts"][market],
        "companies": companies, "lifecycle": lifecycle, "commands": commands, "news_inactive": news,
        "deleted_count": len(deleted),
    }


def compose() -> dict:
    files, cutoff = load(NAMES)
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    return envelope("companies", "docs/SPEC.md section 6, page 10; F8, F10; decisions 12-15, 20, 26, 33, 44",
                    "GET /api/v1/markets/{market}/companies", "rm.companies", NAMES, cutoff, markets)


if __name__ == "__main__":
    run(compose, HERE, lambda p: f"companies {len(p['companies'])} ({sum(c['state'] == 'active' for c in p['companies'])} active), "
                                 f"events {len(p['lifecycle'])}, commands {len(p['commands'])}, news of inactive {len(p['news_inactive'])}, "
                                 f"deleted {p['deleted_count']}")
