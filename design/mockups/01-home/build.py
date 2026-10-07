"""Home mockup (docs/SPEC.md section 6, page 1; design track, decision 48).

    python design/mockups/01-home/build.py [--out DIR]

Composes `data.json`, the example payload of `GET /api/v1/markets/{market}/home` (read model `rm.home`) for
both markets, from W1's example files in design/catalogue/ only, then inlines it into `template.html` and writes
`page.html` (self-contained: the design system of design/system/ is inlined, no request leaves the page).

Every value in data.json is a catalogue field (docs/DATA_CATALOGUE.md) copied from the example records; nothing
is invented here. The build is deterministic: `cutoff` is the example files' as_of clock and `built_at` is the
market status example's freshness.built_at, so two builds give the same bytes. The template holds no number.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
CATALOGUE = os.path.join(REPO, "design", "catalogue")
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from system import inline_system  # noqa: E402

MARKETS = ("india", "us")
HORIZONS = (1, 2, 3, 4, 5)       # config/strategies.yaml horizons (decision 37); N+1 opens (decision 39)
TOP = 5                           # decision 30: top 5 by agreement
NOTE = ("EXAMPLE DATA for page design only: every value is copied from W1's example files in design/catalogue/ "
        "(docs/DATA_CATALOGUE.md). Predictions, trades, reasons and scores are invented there and consistent "
        "with each other. Not a forecast, not advice. Paper only.")
COMPANY_FIELDS = ("market", "ticker", "name", "exchange", "sector", "state", "amount", "amount_overridden",
                  "currency", "last_close", "last_close_date", "change_pct", "agreement_n1", "open_trades")
STRATEGY_FIELDS = ("id", "family", "name", "threshold", "horizons", "live", "settled_trades")
PICK_RULE_ROW_FIELDS = ("scope", "market", "view", "family", "pick_rule", "horizon_days", "trades", "net_pnl",
                        "currency", "mean_return_pct", "win_rate", "sample_badge", "basis", "as_of")


def catalogue(name: str) -> dict:
    with open(os.path.join(CATALOGUE, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


def pick(record: dict, fields: tuple) -> dict:
    return {field: record[field] for field in fields}


def market_payload(market: str, files: dict, cutoff: str) -> dict:
    status = next(r for r in files["market_status"]["records"] if r["market"] == market)
    session_date = status["session"]["session_date"]
    companies = [pick(r, COMPANY_FIELDS) for r in files["company"]["records"] if r["market"] == market]
    active = {c["ticker"] for c in companies if c["state"] == "active"}
    agreement = {}
    for k in HORIZONS:
        rows = [r for r in files["agreement"]["records"]
                if r["market"] == market and r["horizon_days"] == k and r["ticker"] in active]
        agreement[str(k)] = sorted(rows, key=lambda r: r["rank"])[:TOP]
    picks = [r for r in files["head_to_head_pick"]["records"]
             if r["market"] == market and r["session_date"] == session_date]
    open_trades = [r for r in files["open_trade"]["records"] if r["market"] == market]
    # intraday checks stored by the cut-off only (no look-ahead; ARCHITECTURE.md 4.3)
    checks = [r for r in files["trade_check"]["records"] if r["market"] == market and r["check_at"] <= cutoff]
    latest_check = max((r["check_at"] for r in checks), default=None)
    checks = [r for r in checks if r["check_at"] == latest_check]
    eod = max((r for r in files["eod_analysis"]["records"] if r["market"] == market),
              key=lambda r: r["session_date"], default=None)
    to_date = [pick(r, PICK_RULE_ROW_FIELDS) for r in files["scoreboard_row"]["records"]
               if r["market"] == market and r["scope"] == "pick_rule" and r["horizon_days"] == "all"]
    reference = next(r for r in files["scoreboard_row"]["records"]
                     if r["market"] == market and r["scope"] == "strategy" and r["view"] == "accuracy"
                     and r["strategy_id"] == "rule.model_news.v1" and r["horizon_days"] == "all")
    strategies = {r["id"]: pick(r, STRATEGY_FIELDS) for r in files["strategy"]["records"]}
    return {
        "market": market, "name": status["name"], "currency": status["currency"],
        "as_of": status["as_of"], "cutoff": cutoff, "built_at": status["freshness"]["built_at"],
        "status": status,
        "horizons": list(HORIZONS), "default_horizon": HORIZONS[0],
        "companies": sorted(companies, key=lambda c: c["ticker"]),
        "agreement": agreement,
        "head_to_head": picks,
        "open_trades": open_trades,
        "trade_checks": checks,
        "eod": eod,
        "to_date": to_date,
        "go_live": reference["go_live"],
        "strategies": strategies,
    }


def build() -> dict:
    names = ("market_status", "company", "agreement", "head_to_head_pick", "open_trade", "trade_check",
             "eod_analysis", "scoreboard_row", "strategy")
    files = {name: catalogue(name) for name in names}
    cutoffs = {files[name]["as_of"] for name in names}
    assert len(cutoffs) == 1, cutoffs
    cutoff = cutoffs.pop()
    markets = {m: market_payload(m, files, cutoff) for m in MARKETS}
    return {
        "_example": True, "_note": NOTE,
        "page": "home", "spec": "docs/SPEC.md section 6, page 1; decisions 30, 39",
        "endpoint": "GET /api/v1/markets/{market}/home", "read_model": "rm.home",
        "sources": [f"design/catalogue/{name}.json" for name in names],
        "as_of": min(p["as_of"] for p in markets.values()), "cutoff": cutoff,
        "built_at": max(p["built_at"] for p in markets.values()),
        "markets": markets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=HERE)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    data = build()
    with open(os.path.join(args.out, "data.json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as handle:
        template = handle.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = inline_system(template.replace("/*__DATA__*/null", payload))
    out = os.path.join(args.out, "page.html")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(html)
    for market, p in data["markets"].items():
        print(f"{market}: as of {p['as_of']}, session {p['status']['session']['session_date']}, "
              f"agreement N+1 {[(r['ticker'], r['buy'], r['of']) for r in p['agreement']['1']]}, "
              f"picks {len(p['head_to_head'])}, open trades {len(p['open_trades'])}, "
              f"checks at cut-off {len(p['trade_checks'])}, to-date rows {len(p['to_date'])}")
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
