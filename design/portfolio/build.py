"""Assemble the data for the Paper portfolio screen (both markets) and inline it into template.html.

    python design/portfolio/build.py --out design/portfolio

writes <out>/portfolio.html and <out>/data-portfolio.json. The paper book is a pretend account that follows the
cockpit's plan with 10,000 per trade: buy at the next open when a company shows YES, sell at the close of D+4,
costs from config/costs.yaml. Two books per market: the LIVE book (every live call stored in predictions, with
its outcome once scored: none yet) and the REHEARSAL book (the walk-forward model's out-of-sample rows, exactly
the rows scripts/model_backtest.py scores for its paper strategy, so the totals match the back-test JSON).
Read-only on the repo."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.model.backtest import with_trade_columns  # noqa: E402
from marketbrief.model.panel import build_panel  # noqa: E402
from marketbrief.model.panel_inputs import read_inputs  # noqa: E402
from marketbrief.model.paper import prepare  # noqa: E402
from marketbrief.model.settings import load_costs, load_model_config, round_trip_cost  # noqa: E402
from marketbrief.model.walk_forward import walk_forward  # noqa: E402
from system import inline_system  # noqa: E402

spec = importlib.util.spec_from_file_location("decision_build", os.path.join(REPO, "design", "decision", "build.py"))
decision_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decision_build)
STAKE = 10000
HORIZON = 5


def book_stats(rows: pd.DataFrame, stake: float) -> dict:
    """Per-trade and per-date statistics of a ledger (net = return after costs, fraction)."""
    if rows.empty:
        return {"positions": 0, "dates": 0, "mean_pct": None, "win_rate": None, "pnl_total": 0.0, "best": None, "worst": None, "max_drawdown": None, "curve": []}
    per_date = rows.groupby("date")["net"].mean().sort_index()
    curve = (per_date * stake).cumsum()
    peak = curve.cummax()
    dd = (curve - peak).min()
    best = rows.loc[rows["net"].idxmax()]
    worst = rows.loc[rows["net"].idxmin()]
    return {"positions": int(len(rows)), "dates": int(per_date.notna().sum()), "mean_pct": round(float(per_date.mean()) * 100, 4),
            "mean_trade_pct": round(float(rows["net"].mean()) * 100, 4), "win_rate": round(float((rows["net"] > 0).mean()), 4),
            "pnl_total": round(float(curve.iloc[-1]), 2), "pnl_per_trade": round(float(rows["net"].mean() * stake), 2),
            "best": {"ticker": best["ticker"], "date": str(best["date"])[:10], "pnl": round(float(best["net"] * stake), 2)},
            "worst": {"ticker": worst["ticker"], "date": str(worst["date"])[:10], "pnl": round(float(worst["net"] * stake), 2)},
            "max_drawdown": round(float(dd), 2),
            "curve": [{"date": str(d)[:10], "equity": round(float(v), 2), "n": int(rows[rows["date"] == d].shape[0])} for d, v in curve.items()],
            "by_month": [{"month": str(k), "positions": int(g.shape[0]), "pnl": round(float(g.groupby("date")["net"].mean().sum() * stake), 2),
                          "win_rate": round(float((g["net"] > 0).mean()), 4)} for k, g in rows.groupby(rows["date"].dt.to_period("M"))],
            "by_ticker": sorted([{"ticker": k, "positions": int(g.shape[0]), "win_rate": round(float((g["net"] > 0).mean()), 4),
                                  "pnl": round(float(g["net"].sum() * stake), 2), "mean_pct": round(float(g["net"].mean()) * 100, 3)} for k, g in rows.groupby("ticker")], key=lambda x: -x["pnl"])}


def market_block(market: str) -> dict:
    con = connect(market)
    cfg = load_market(market)
    settings = load_model_config()
    costs = load_costs(market)
    cur = decision_build.CURRENCY[cfg["currency"]]

    def q(sql):
        return con.execute(sql).df()

    # ---- live book: every live call and its outcome
    live = q("""select p.id, p.as_of_date, p.ticker, p.horizon_days, p.direction, p.confidence, p.model_prob, p.agent_adjustment, p.made_at,
                o.entry_date, o.entry_open, o.target_date, o.target_close, o.actual_return, o.hit, o.label_basis, o.scored_at
                from predictions p left join outcomes o on o.prediction_id = p.id order by p.as_of_date, p.ticker""").to_dict("records")
    live_rows = []
    for r in live:
        entry_open = None if r["entry_open"] is None or pd.isna(r["entry_open"]) else float(r["entry_open"])
        ret = None if r["actual_return"] is None or pd.isna(r["actual_return"]) else float(r["actual_return"])
        cost = float(round_trip_cost(market, costs, entry_open if entry_open else 100.0))
        net = None if ret is None else ret - cost
        live_rows.append({"id": r["id"], "as_of": str(r["as_of_date"])[:10], "ticker": r["ticker"], "horizon": int(r["horizon_days"]), "direction": r["direction"],
                          "confidence": r["confidence"], "model_prob": r["model_prob"], "entry_date": None if r["entry_date"] is None else str(r["entry_date"])[:10],
                          "entry_open": entry_open, "exit_date": None if r["target_date"] is None else str(r["target_date"])[:10],
                          "exit_close": None if r["target_close"] is None or pd.isna(r["target_close"]) else float(r["target_close"]),
                          "ret_pct": None if ret is None else round(ret * 100, 3), "cost_pct": round(cost * 100, 4), "net_pct": None if net is None else round(net * 100, 3),
                          "pnl": None if net is None else round(net * STAKE, 2), "hit": None if r["hit"] is None or pd.isna(r["hit"]) else bool(r["hit"]), "status": "closed" if ret is not None else "open"})
    first_live = q("select min(as_of_date) d from ranges").iloc[0, 0]
    n_yes_today = sum(1 for r in live_rows if r["direction"] == "up" and r["status"] == "open")

    # ---- rehearsal book: the walk-forward rows the back-test scores (5-day open-to-close)
    panel = build_panel(cfg, read_inputs(con, market), settings["warmup_bars"])
    oos, fits = walk_forward(panel, (market, LABEL_OPEN_TO_CLOSE, HORIZON), settings)
    done = with_trade_columns(oos[oos["up"].notna()], panel, HORIZON)
    rows = prepare(done, market, costs)
    rows["date"] = pd.to_datetime(rows["date"])
    books = {}
    for t in settings["backtest"]["thresholds"]:
        sel = rows[rows["prob"] >= t].copy()
        key = f"{t:.2f}"
        stats = book_stats(sel, STAKE)
        ledger = sel.sort_values(["date", "ticker"]).tail(400)
        stats["ledger"] = [{"as_of": str(r.date)[:10], "ticker": r.ticker, "prob": round(float(r.prob), 4), "entry_open": round(float(r.entry_open), 2),
                            "exit_close": round(float(r.entry_open * (1 + r.ret)), 2), "exit_date": str(r.end)[:10], "ret_pct": round(float(r.ret) * 100, 3),
                            "cost_pct": round(float(r.cost) * 100, 4), "net_pct": round(float(r.net) * 100, 3), "pnl": round(float(r.net) * STAKE, 2)} for r in ledger.itertuples()]
        stats["ledger_is_tail"] = len(sel) > 400
        books[key] = stats
    always = book_stats(rows, STAKE)
    always.pop("ledger", None); always["by_ticker"] = always["by_ticker"][:5] + always["by_ticker"][-5:]
    bt, bt_path = decision_build.backtest_json(market)
    paper_json = bt["results"][market]["5d open_to_close"].get("paper", {})
    check = {k: {"json_mean_pct": paper_json["thresholds"][k]["long"]["mean_pct"], "json_positions": paper_json["thresholds"][k]["long"]["positions"],
                 "here_mean_pct": round(books[k]["mean_pct"], 4) if books[k]["mean_pct"] is not None else None, "here_positions": books[k]["positions"]} for k in books if k in paper_json.get("thresholds", {})}
    return {"market": market, "market_name": cfg["name"], "exchange": decision_build.EXCHANGE[market], "currency": cur, "n_tickers": len(cfg["tickers"]),
            "as_of": str(rows["date"].max())[:10], "window": [str(rows["date"].min())[:10], str(rows["date"].max())[:10]], "first_live": None if first_live is None else str(first_live)[:10],
            "live": {"rows": live_rows, "open": sum(1 for r in live_rows if r["status"] == "open"), "closed": sum(1 for r in live_rows if r["status"] == "closed"),
                     "pnl": round(sum(r["pnl"] for r in live_rows if r["pnl"] is not None), 2), "wins": sum(1 for r in live_rows if r["net_pct"] is not None and r["net_pct"] > 0), "yes_open": n_yes_today},
            "books": books, "always_up": always, "thresholds": [f"{t:.2f}" for t in settings["backtest"]["thresholds"]], "cost_pct": round(float(rows["cost"].mean()) * 100, 4),
            "check": check, "bt_path": os.path.relpath(bt_path, REPO), "fits": len(fits)}


def build() -> dict:
    return decision_build.clean({"built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "stake": STAKE, "horizon": HORIZON,
                                 "call_line": 0.60, "markets": {m: market_block(m) for m in ("india", "us")}})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = build()
    json.dump(data, open(os.path.join(a.out, "data-portfolio.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    html = inline_system(tpl.replace("/*__DATA__*/null", payload))
    out = os.path.join(a.out, "portfolio.html")
    open(out, "w").write(html)
    for m, b in data["markets"].items():
        print(f"{m}: live rows {len(b['live']['rows'])}; rehearsal books " + "; ".join(f"{k}: {v['positions']} trades mean {v['mean_pct']}% (json {b['check'].get(k, {}).get('json_mean_pct')}, {b['check'].get(k, {}).get('json_positions')} positions)" for k, v in b["books"].items()))
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
