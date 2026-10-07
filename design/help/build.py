"""Assemble the data for the Help screen and inline it into template.html.

    python design/help/build.py --out design/help

writes <out>/help.html and <out>/data-help.json. The Help screen explains the cockpit to a retail reader in plain
words: what it is, the five-minute morning, what each page answers, how a call is made and the rules it never
breaks, the colours and badges, when it can be trusted with money, a glossary, where the numbers come from and
the questions people ask. Every number on it is read from the repo's configuration (config/model.yaml,
config/ranges.yaml, config/review.yaml, config/settings.yaml, config/costs.yaml, config/markets/*.yaml) or the
stored data (latest as-of dates, data kinds), never typed in. Read-only on the repo."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from marketbrief.core.calendar import next_session, session_close_utc, session_open_utc  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.model.settings import load_costs, round_trip_cost  # noqa: E402
from system import inline_system  # noqa: E402

spec = importlib.util.spec_from_file_location("decision_build", os.path.join(REPO, "design", "decision", "build.py"))
decision_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decision_build)
spec = importlib.util.spec_from_file_location("watchlist_build", os.path.join(REPO, "design", "watchlist", "build.py"))
watchlist_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchlist_build)
spec = importlib.util.spec_from_file_location("portfolio_build", os.path.join(REPO, "design", "portfolio", "build.py"))
portfolio_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portfolio_build)

# the YES strength rule of the decision page (design/decision/build.py, owner's rule): strong when the forecaster's
# confidence is at least STRONG_CONFIDENCE or the anchored probability is at least STRONG_PROB
STRONG_CONFIDENCE, STRONG_PROB = 0.75, 0.65
# prediction rules (CLAUDE.md "Prediction rules"; checked by scripts/validate.py --stage forecast)
CONFIDENCE_RANGE = (0.50, 0.90)
AGENT_ADJUSTMENT_MAX = 0.10
EARNINGS_BLOCK_DAYS = 1
UNVERIFIED_PENALTY, UNVERIFIED_CAP = 0.05, 0.85
MOVER_MARKET_WIDE = 0.75   # % benchmark or sector move counted as market-wide on Home and the company page


def load_yaml(name: str) -> dict:
    with open(os.path.join(REPO, "config", name)) as f:
        return yaml.safe_load(f)


def market_block(market: str) -> dict:
    cfg = load_market(market)
    con = connect(market)
    tickers = {t: cfg["tickers"][t] for t in cfg["tickers"]}
    as_of = con.execute(f"select max(date) from ohlc where ticker in ({','.join(repr(t) for t in tickers)})").fetchone()[0]
    as_of = date.fromisoformat(str(as_of)[:10])
    today = next_session(cfg, as_of, include=False)
    tz = ZoneInfo(cfg["timezone"])
    open_local = session_open_utc(cfg, today).astimezone(tz)
    close_local = session_close_utc(cfg, today).astimezone(tz)
    costs = load_costs(market)
    probe = 100.0
    rt = float(round_trip_cost(market, costs, probe))
    sectors = {}
    for t, c in tickers.items():
        sectors.setdefault(c["sector"], []).append({"ticker": t, "name": c["name"], "page": os.path.exists(os.path.join(REPO, "design", "decision", f"decision-{t}.html"))})
    symbols = {role: [{"id": k, "name": v["name"]} for k, v in cfg["symbols"].items() if v.get("role") == role] for role in ("benchmark", "vol_index", "cue", "factor")}
    news = cfg.get("news", {}) or {}
    data_kinds = sorted(d for d in os.listdir(os.path.join(REPO, "data", market)) if os.path.isdir(os.path.join(REPO, "data", market, d)))
    counts = {k: int(con.execute(f"select count(*) from {k}").fetchone()[0]) for k in ("news", "predictions", "ranges", "lessons")}
    first_bar = con.execute(f"select min(date) from ohlc where ticker in ({','.join(repr(t) for t in tickers)})").fetchone()[0]
    return {"market": market, "market_name": cfg["name"], "exchange": decision_build.EXCHANGE[market], "timezone": cfg["timezone"], "currency": decision_build.CURRENCY[cfg["currency"]],
            "as_of": str(as_of), "next_session": str(today), "open_local": open_local.strftime("%H:%M"), "close_local": close_local.strftime("%H:%M"),
            "open_utc": session_open_utc(cfg, today).strftime("%H:%M"), "close_utc": session_close_utc(cfg, today).strftime("%H:%M"),
            "n_tickers": len(tickers), "sectors": [{"name": s, "companies": v} for s, v in sectors.items()], "symbols": symbols,
            "regime": cfg["regime"], "round_trip_cost_pct": round(rt * 100, 4), "round_trip_cost_per_stake": round(rt * portfolio_build.STAKE, 2),
            "news_feeds": {"google_news": len(news.get("google_news", []) or []), "outlets": len(news.get("outlets", []) or []), "categories": len(news.get("categories", []) or [])},
            "filings": cfg.get("filings"), "premarket_quotes": bool(cfg.get("premarket_quotes")), "price_fallback": cfg.get("price_fallback"),
            "data_kinds": data_kinds, "counts": counts, "first_bar": str(first_bar)[:10]}


def build() -> dict:
    model = load_yaml("model.yaml")
    ranges = load_yaml("ranges.yaml")
    review = load_yaml("review.yaml")
    settings = load_yaml("settings.yaml")
    rules = {"call_threshold": watchlist_build.CALL_THRESHOLD, "strong_confidence": STRONG_CONFIDENCE, "strong_prob": STRONG_PROB,
             "confidence_min": CONFIDENCE_RANGE[0], "confidence_max": CONFIDENCE_RANGE[1], "agent_adjustment_max": AGENT_ADJUSTMENT_MAX,
             "earnings_block_days": EARNINGS_BLOCK_DAYS, "unverified_penalty": UNVERIFIED_PENALTY, "unverified_cap": UNVERIFIED_CAP,
             "horizons": ranges["horizons"], "bands": [0.5, 0.8], "max_ai_widen": ranges["max_ai_widen"], "major_event_factor": ranges["major_event_factor"],
             "regime_factor": ranges["regime_factor"], "earnings_vol_multiple": ranges["earnings_vol_multiple"], "earnings_vol_multiple_by_market": ranges.get("earnings_vol_multiple_by_market", {}),
             "news_lookback_hours": model["news"]["lookback_hours"], "news_status_weights": model["news"]["status_weights"], "news_materiality_weights": model["news"]["materiality_weights"],
             "model_refit": model["refit"], "model_version": model["model_version"], "mover_market_wide": MOVER_MARKET_WIDE,
             "stake": portfolio_build.STAKE, "label_basis": settings["call_scoring"]["label_basis"], "label_basis_from": settings["call_scoring"]["from"][:10],
             "training_cutoff": str(settings["model_training_cutoff"])}
    gate = {"ranges_needed": review["min_n_recommend"], "calls_needed": review["min_n_calls"], "tolerance": review["calibration_tolerance"],
            "confidence_bands": review["confidence_bands"], "model_skill": review["model_skill"], "rolling_days": review["rolling_days"]}
    markets = {m: market_block(m) for m in ("india", "us")}
    pages = [
        {"id": "home", "name": "Home", "href": "../home/home.html", "icon": "home", "question": "Is there anything worth doing today?",
         "what": "Both markets on one screen: the signals banner, each market's regime and big numbers, what moved yesterday and why, the news of the last 24 hours (what moved the whole market, which company stories can carry a call, what was set aside), this week's events and whether the latest run finished cleanly."},
        {"id": "watchlist", "name": "Watchlist", "href": "../watchlist/watchlist-india.html", "icon": "format_list_bulleted", "question": "Which of the 20 companies is closest to a call?",
         "what": "One row per company, grouped by sector: price and move, the model's chance of a rise for 1 and 5 days, the published ranges, news count and verification status, results date, and the call line at 60%. Sort by any column."},
        {"id": "decision", "name": "Company page", "href": "../decision/decision-HDFCBANK.html", "icon": "description", "question": "Buy this one or not, and if so, exactly how?",
         "what": "The verdict (NO in red, YES in green, darker when strong) with the five checks behind it, the plan (buy at the next open, sell at the close of the fifth session), the price range on the chart, the drivers, the bull and bear cases, the company's news with status, and its own track record."},
        {"id": "track", "name": "Record", "href": "../track/track.html", "icon": "query_stats", "question": "Has it earned trust, or is it still paper?",
         "what": "The four tests the system must pass before its signals may be followed with money, each in plain words with today's number and the date it could turn green; then the live record and the rehearsal results underneath."},
        {"id": "portfolio", "name": "Portfolio", "href": "../portfolio/portfolio.html", "icon": "account_balance_wallet", "question": "Would following it have made money?",
         "what": "A pretend account that follows the plan to the letter with 10,000 per trade after real trading costs: the live book (every real call once it settles) and the rehearsal book on past prices, month by month and company by company."},
        {"id": "help", "name": "Help", "href": "help.html", "icon": "help", "question": "How do I read all this?", "what": "This page."},
    ]
    return watchlist_build.clean({"built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "rules": rules, "gate": gate, "markets": markets, "pages": pages})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = build()
    json.dump(data, open(os.path.join(a.out, "data-help.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    html = inline_system(tpl.replace("/*__DATA__*/null", payload))
    out = os.path.join(a.out, "help.html")
    open(out, "w").write(html)
    for m, b in data["markets"].items():
        print(f"{m}: as of {b['as_of']} next session {b['next_session']} {b['open_local']}-{b['close_local']} local, round trip {b['round_trip_cost_pct']}% "
              f"({b['currency']['symbol'] if isinstance(b['currency'], dict) else ''}{b['round_trip_cost_per_stake']} on {data['rules']['stake']}), {len(b['data_kinds'])} data kinds, counts {b['counts']}")
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
