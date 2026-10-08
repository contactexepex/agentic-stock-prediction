"""The entity files of design/catalogue/ built from make_examples.py's predictions and settlement (EXAMPLES only)."""
from __future__ import annotations

import statistics

from marketbrief.lab import costs as lab_costs
from marketbrief.lab import picks as lab_picks
from marketbrief.lab import scoreboard as lab_scoreboard
from marketbrief.lab.constants import LAB_VERSION

from make_examples import (
    BARS,
    CIK,
    COMPANIES,
    CURRENCY,
    DEFAULT_AMOUNT,
    EURUSD,
    TODAY_CLOSE,
    r2,
    r4,
)


SETTLED_UNTIL = "2026-10-06"   # the newest stored close the examples settle on
ACCURACY_STRATEGIES = ("rule.model_news.v1", "rule.model_news_strict.v1", "base.always_up.v1", "base.model_only.v1",
                       "ai.combined.opus.v1", "ai.news_results.sonnet.v1")
SETTLED_TICKERS = ("NVDA", "JPM", "AAPL", "RELIANCE", "HDFCBANK", "MARUTI")
INACTIVE = {"india": ("INDIGO", "InterGlobe Aviation (IndiGo)", "Transport", "INDIGO.NS", 5050.5),
            "us": ("DAL", "Delta Air Lines", "Airlines", "DAL", 83.66)}


def head_to_head(preds: list[dict], settled: list[dict], specs: list[dict], ticker: str) -> list[dict]:
    """The head_to_head_picks rows of one company, both families, built by B2's engine (marketbrief/lab/picks.py
    pick_rows: the corrected decision-41 ranking, gain per session held, every horizon's candidate with `eligible`
    and the cost-viable fields) from the settled example trades of the company's market."""
    market = "india" if ticker in COMPANIES["india"] else "us"
    mine = [p for p in preds if p["ticker"] == ticker]
    sample = min(mine, key=lambda p: p["id"])
    trades = [t for t in settled if t["market"] == market]
    rows = []
    for family in ("rule", "ai"):
        context = {"market": market, "rate": lab_costs.rates(market), "eurusd": EURUSD if market == "us" else None,
                   "family_ids": [s["id"] for s in specs if s["family"] == family], "made_at": sample["made_at"],
                   "as_of_date": sample["as_of_date"], "session_date": sample["session_date"],
                   "base_close": sample["base_close"], "amount": sample["amount"], "currency": sample["currency"],
                   "method_version": LAB_VERSION}
        rows += lab_picks.pick_rows(ticker, family, context, preds, trades)
    return rows


def agreement(preds: list[dict]) -> list[dict]:
    out = []
    for market in ("india", "us"):
        for k in (1, 2, 3, 4, 5):
            rows = []
            for ticker in COMPANIES[market]:
                mine = [p for p in preds if p["ticker"] == ticker and p["horizon_days"] == k]
                buys = [p for p in mine if p["qualifies"]]
                probs = [p["prob_up"] for p in buys if p["prob_up"] is not None]
                by_family = {f: {"buy": sum(p["family"] == f for p in buys), "of": sum(p["family"] == f for p in mine)}
                             for f in ("rule", "baseline", "ai")}
                rows.append({"ticker": ticker, "name": COMPANIES[market][ticker][0], "horizon_days": k,
                             "buy": len(buys), "of": len(mine), "by_family": by_family,
                             "avg_prob_up": r4(statistics.mean(probs)) if probs else None,
                             "label": f"{COMPANIES[market][ticker][0]}: {len(buys)} of {len(mine)} strategies "
                                      f"buy at N+{k}"})
            rows.sort(key=lambda r: (-r["buy"], -(r["avg_prob_up"] or 0), r["ticker"]))
            for rank, row in enumerate(rows, 1):
                out.append({"market": market, "as_of_date": "2026-10-06", "session_date": "2026-10-07", "rank": rank,
                            **row, "paper": True})
    return out


def scoreboard(settled: list[dict], costs: list[dict]) -> list[dict]:
    """F7 rows built by B2's engine (marketbrief/lab/scoreboard.py: scopes strategy, strategy_company, pick_rule and
    strategy_regime; the luck test with its correction; the your-cost block and the go-live bar), from the example
    trades joined to their your-cost numbers in cost_view.json."""
    your = {r["record_id"]: r for r in costs if r["record_kind"] == "settlement"}
    trades = [{**t, "net_pnl_your": your[t["id"]]["net_pnl_your"], "return_pct_your": your[t["id"]]["return_pct_your"]}
              if t["id"] in your else t for t in settled]
    return lab_scoreboard.scoreboard(trades, "forward", SETTLED_UNTIL)


def company_rows(agree: list[dict], open_trades: list[dict]) -> list[dict]:
    rows = []
    for market in ("india", "us"):
        for ticker, (name, sector, yahoo, *_rest) in COMPANIES[market].items():
            bars = BARS[ticker]
            n1 = next(a for a in agree if a["ticker"] == ticker and a["horizon_days"] == 1)
            rows.append({
                "market": market, "ticker": ticker, "name": name, "exchange": "NSE" if market == "india" else (
                    "NYSE" if ticker == "JPM" else "NASDAQ"), "sector": sector, "state": "active",
                "amount": 10000.0 if ticker == "MARUTI" else DEFAULT_AMOUNT[market],
                "amount_overridden": ticker == "MARUTI", "currency": CURRENCY[market], "yahoo": yahoo,
                "nse_symbol": ticker if market == "india" else None, "cik": CIK.get(ticker),
                "added_at": "2011-01-03T00:00:00Z", "state_since": "2011-01-03T00:00:00Z",
                "last_close": TODAY_CLOSE[ticker], "last_close_date": "2026-10-06",
                "change_pct": r2((bars["2026-10-06"][3] / bars["2026-10-05"][3] - 1) * 100),
                "agreement_n1": {"buy": n1["buy"], "of": n1["of"]},
                "open_trades": sum(t["ticker"] == ticker for t in open_trades)})
        ticker, name, sector, yahoo, close = INACTIVE[market]
        rows.append({"market": market, "ticker": ticker, "name": name,
                     "exchange": "NSE" if market == "india" else "NYSE", "sector": sector, "state": "inactive",
                     "amount": DEFAULT_AMOUNT[market], "amount_overridden": False, "currency": CURRENCY[market],
                     "yahoo": yahoo, "nse_symbol": ticker if market == "india" else None,
                     "cik": "0000027904" if ticker == "DAL" else None, "added_at": "2011-01-03T00:00:00Z",
                     "state_since": "2026-10-05T02:10:00Z" if market == "india" else "2026-10-05T11:45:00Z",
                     "last_close": close, "last_close_date": "2026-10-06",
                     "change_pct": None, "agreement_n1": None, "open_trades": 0})
    return rows


def open_trade_rows(past: list[dict], picks: list[dict]) -> list[dict]:
    """Accuracy-view trades of the settled strategies and head-to-head picks still open after the newest close."""
    by_id = {p["id"]: p for p in past}
    entries = [(f"acc:{p['id']}", "accuracy", p) for p in past
               if p["qualifies"] and p["strategy_id"] in ACCURACY_STRATEGIES and p["ticker"] in SETTLED_TICKERS]
    entries += [(f"h2h:{r['pick_rule']}:{r['prediction_id']}", "head_to_head", by_id[r["prediction_id"]])
                for r in picks if r["status"] == "picked"]
    rows = []
    for trade_id, view, pred in entries:
        if pred["exit_date"] > SETTLED_UNTIL:
            entry = BARS[pred["ticker"]][pred["session_date"]][0]
            quantity = int(pred["amount"] // entry) if pred["market"] == "india" else round(pred["amount"] / entry, 6)
            if not quantity:
                continue
            last = TODAY_CLOSE[pred["ticker"]]
            rows.append({"trade_id": trade_id, "view": view, "prediction_id": pred["id"],
                         "strategy_id": pred["strategy_id"], "family": pred["family"], "market": pred["market"],
                         "ticker": pred["ticker"], "horizon_days": pred["horizon_days"],
                         "entry_date": pred["session_date"], "exit_date": pred["exit_date"], "entry_price": entry,
                         "quantity": float(quantity), "amount": pred["amount"], "currency": pred["currency"],
                         "target_price": pred["target_price"], "lo80": pred["lo80"], "lo50": pred["lo50"],
                         "hi50": pred["hi50"], "hi80": pred["hi80"],
                         "last_price": last, "last_price_date": SETTLED_UNTIL,
                         "unrealised_pnl": r2(quantity * (last - entry)),
                         "unrealised_pct": r2((last / entry - 1) * 100),
                         "to_target_pct": r2((pred["target_price"] / last - 1) * 100), "paper": True})
    return rows


def build_all(write, settle, today: list[dict], past: list[dict], specs: list[dict]) -> None:
    from catalogue_costs import cost_rows
    from catalogue_more import build_rest

    accuracy = [settle(p, "accuracy", None, None) for p in past
                if p["qualifies"] and p["exit_date"] <= SETTLED_UNTIL and p["strategy_id"] in ACCURACY_STRATEGIES
                and p["ticker"] in SETTLED_TICKERS]
    picks_past = [r for t in ("NVDA", "RELIANCE") for r in head_to_head(past, [], specs, t)]
    by_id = {p["id"]: p for p in past}
    h2h = [settle(by_id[r["prediction_id"]], "head_to_head", r["pick_rule"], r["id"]) for r in picks_past
           if r["status"] == "picked" and by_id[r["prediction_id"]]["exit_date"] <= SETTLED_UNTIL]
    settled = accuracy + h2h
    picks_today = [r for t in ("NVDA", "RELIANCE", "HDFCBANK") for r in head_to_head(today, settled, specs, t)]
    agree = agreement(today)
    opens = open_trade_rows(past, picks_past)
    shown = [p for p in today if p["ticker"] in ("NVDA", "RELIANCE")]
    costs = cost_rows(shown, picks_past + picks_today, settled, past)
    write("cost_view.json", "cost_view", "cost_views", costs)
    write("prediction.json", "prediction", "strategy_predictions", shown)
    write("agreement.json", "agreement", None, agree)
    write("head_to_head_pick.json", "head_to_head_pick", "head_to_head_picks", picks_past + picks_today)
    write("paper_trade.json", "paper_trade", "paper_trades_settled", settled)
    write("open_trade.json", "open_trade", None, opens)
    write("scoreboard_row.json", "scoreboard_row", None, scoreboard(settled, costs))
    write("company.json", "company", None, company_rows(agree, opens))
    write("strategy.json", "strategy", None, [
        {**s, "live": s["live_from"] is not None,
         "settled_trades": sum(t["strategy_id"] == s["id"] and t["status"] == "settled" for t in accuracy),
         "status_note": "not live yet: switched on in Wave 5"} for s in specs])
    build_rest(write, settled, opens, EURUSD, r2)
