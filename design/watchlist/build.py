"""Assemble the data for the Watchlist screen (read-only on the repo) and inline it into template.html.

    python design/watchlist/build.py --market india --out design/watchlist

writes <out>/watchlist-<market>.html and <out>/data-<market>.json: one row per watchlist company (price, day and
5-day moves, 20-session sparkline, the model's chance of a rise, verdict, the latest published 5-day range, the
rule replay's 80% coverage over the back-test window, next results date, stored news with its best verification
status, the overnight cue), the market header (regime, vol index, benchmark, flows, session status, run time) and
the sector groups. Nothing under data/, reports/ or summaries/ is written (the rule replay runs into work/design/)."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
sys.path.insert(0, os.path.join(REPO, "design", "decision"))
import pandas as pd  # noqa: E402
from build import CURRENCY, EXCHANGE, SESSIONS_BACK, clean, replay_summary_json  # noqa: E402  (design/decision/build.py)
from marketbrief.core.calendar import next_session, prev_session  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.pipeline.market_status import status as market_session  # noqa: E402
from system import inline_system  # noqa: E402

STATUS_ORDER = ["confirmed_primary", "corroborated", "single_source", "unverified", "rumour", "promotional", "contradicted"]
CALL_THRESHOLD = 0.60   # the cockpit's Paper-candidate line (one of config/model.yaml's backtest thresholds 0.55/0.60/0.65); a reading aid, not a pipeline rule


def build(market: str) -> dict:
    con = connect(market)
    cfg = load_market(market)
    cur = CURRENCY[cfg["currency"]]
    symbols = cfg["symbols"]
    tickers = list(cfg["tickers"])
    bench = next(k for k, v in symbols.items() if v["role"] == "benchmark")
    vol_sym = next(k for k, v in symbols.items() if v["role"] == "vol_index")
    sector_of = {t: s for s, members in cfg["sectors"].items() for t in members}
    sector_sym = {s: k for k, v in symbols.items() if v["role"] == "sector_etf" for s in v.get("sectors", [])}

    def q(sql):
        return con.execute(sql).df()

    end = date.fromisoformat(str(q(f"select max(date) d from ohlc where ticker in ({','.join(repr(t) for t in tickers)})").iloc[0, 0])[:10])
    start = end
    for _ in range(SESSIONS_BACK):
        start = prev_session(cfg, start - timedelta(days=1))
    today = next_session(cfg, end + timedelta(days=1))

    # ---- prices: last 21 closes per symbol (sparkline, day and 5-day moves), plus the market symbols
    syms = tickers + [bench, vol_sym] + sorted(set(sector_sym.values()))
    bars = q(f"""select ticker, date, close from (select ticker, date, close, row_number() over (partition by ticker order by date desc) rn
                 from ohlc where ticker in ({','.join(repr(s) for s in syms)})) where rn <= 21 order by ticker, date""")
    bars["date"] = bars["date"].astype(str)
    closes = {t: g["close"].tolist() for t, g in bars.groupby("ticker")}
    dates = {t: g["date"].tolist() for t, g in bars.groupby("ticker")}

    def move(t, k=1):
        c = closes.get(t, [])
        return None if len(c) <= k or not c[-1 - k] else round((c[-1] / c[-1 - k] - 1) * 100, 2)

    # ---- latest per-ticker rows
    scores = q("select ticker, horizon_days, prob_up, base_rate, news_score, computed_at from model_scores_latest qualify as_of_date = max(as_of_date) over ()").to_dict("records")
    score = {(r["ticker"], r["horizon_days"]): r for r in scores}
    rng = q("select * from ranges_latest qualify as_of_date = max(as_of_date) over (partition by ticker, horizon_days)").to_dict("records")
    rng_by = {(r["ticker"], r["horizon_days"]): r for r in rng}
    feats = q("select * from features_latest qualify as_of_date = max(as_of_date) over (partition by ticker)").to_dict("records")
    feat = {r["ticker"]: r for r in feats}
    reasoning = q("select ticker, decision_1d, decision_5d, made_at from agent_reasoning qualify as_of_date = max(as_of_date) over ()").to_dict("records")
    reas = {r["ticker"]: r for r in reasoning}
    preds = q("select * from predictions where as_of_date = (select max(as_of_date) from predictions)").to_dict("records") if int(q("select count(*) from predictions").iloc[0, 0]) else []
    pred_by = {}
    for p in preds:
        pred_by.setdefault(p["ticker"], []).append(p)
    quotes = {r["symbol"]: r for r in q("select symbol, ts, price, prev_close, change_pct from quotes_latest where day=(select max(day) from quotes_latest)").to_dict("records")}
    news = q("""select t.ticker, count(*) n, sum(case when e.materiality='high' then 1 else 0 end) high, max(t.published_at) latest
                from (select unnest(tickers) ticker, id, published_at from news) t left join enriched_latest e using(id)
                where t.published_at >= (select max(published_at) from news) - interval '3 days' group by 1""").to_dict("records")
    news_by = {r["ticker"]: r for r in news}
    verified = q("select ticker, status, count(*) n from news_verified where level='cluster' group by 1, 2").to_dict("records")
    best_status = {}
    for v in verified:
        cur_best = best_status.get(v["ticker"])
        if cur_best is None or STATUS_ORDER.index(v["status"]) < STATUS_ORDER.index(cur_best):
            best_status[v["ticker"]] = v["status"]
    earn = q(f"select ticker, min(date) d, min_by(timing, date) timing from events where type='earnings' and date >= '{today}' group by 1").to_dict("records")
    earn_by = {r["ticker"]: r for r in earn}
    outcomes = q("select p.ticker, count(*) n, sum(case when o.hit then 1 else 0 end) hits from outcomes o join predictions p on p.id = o.prediction_id group by 1").to_dict("records")
    out_by = {r["ticker"]: r for r in outcomes}
    replay = replay_summary_json(market, start, end)
    cover = {h: replay["horizons"][h]["by_ticker"] for h in ("1", "5")}

    rows = []
    for t in tickers:
        tc = cfg["tickers"][t]
        c = closes.get(t, [])
        f = feat.get(t, {})
        s1, s5 = score.get((t, 1)), score.get((t, 5))
        r5, r1 = rng_by.get((t, 5)), rng_by.get((t, 1))
        calls = pred_by.get(t, [])
        up_calls = [p for p in calls if p["direction"] == "up"]
        if up_calls:
            p = max(up_calls, key=lambda x: x["confidence"])
            final = (p.get("model_prob") or 0) + (p.get("agent_adjustment") or 0)
            verdict = {"word": "YES", "strength": "strong" if p["confidence"] >= 0.75 or final >= 0.65 else "ok", "confidence": p["confidence"], "horizon": p["horizon_days"]}
        elif calls:
            verdict = {"word": "NO", "strength": None, "confidence": calls[0]["confidence"], "horizon": calls[0]["horizon_days"], "direction": "down"}
        else:
            verdict = {"word": "NO", "strength": None, "confidence": None, "horizon": None}
        adr = tc.get("adr")
        cue_sym = f"{t}:ADR" if adr and f"{t}:ADR" in quotes else (t if t in quotes else None)
        cue = quotes.get(cue_sym)
        ne = earn_by.get(t)
        nb = news_by.get(t)
        cov1 = cover["1"].get(t) or {}
        cov5 = cover["5"].get(t) or {}
        rows.append({
            "ticker": t, "name": tc["name"], "sector": sector_of[t], "close": round(c[-1], 2) if c else None, "date": dates[t][-1] if c else None,
            "move": move(t, 1), "move_5": move(t, 5), "move_20": move(t, 20), "spark": [round(v, 2) for v in c],
            "rsi": None if f.get("rsi_14") is None or (isinstance(f.get("rsi_14"), float) and math.isnan(f["rsi_14"])) else round(float(f["rsi_14"])),
            "rel_sector_5d": None if f.get("rel_sector_5d") is None else round(float(f["rel_sector_5d"]) * 100, 2),
            "quality": f.get("quality"), "days_to_earnings": None if f.get("days_to_earnings") is None else int(f["days_to_earnings"]),
            "p1": None if not s1 else round(float(s1["prob_up"]), 4), "p5": None if not s5 else round(float(s5["prob_up"]), 4),
            "news_score": None if not s1 else s1["news_score"],
            "decision_1d": reas.get(t, {}).get("decision_1d"), "decision_5d": reas.get(t, {}).get("decision_5d"),
            "verdict": verdict,
            "range5": None if not r5 else {"lo80": round(float(r5["lo80"]), 2), "hi80": round(float(r5["hi80"]), 2), "lo50": round(float(r5["lo50"]), 2), "hi50": round(float(r5["hi50"]), 2),
                                           "target": str(r5["target_date"])[:10], "as_of": str(r5["as_of_date"])[:10], "base": round(float(r5["base_close"]), 2)},
            "range1": None if not r1 else {"lo80": round(float(r1["lo80"]), 2), "hi80": round(float(r1["hi80"]), 2), "target": str(r1["target_date"])[:10], "as_of": str(r1["as_of_date"])[:10]},
            "cover80_1d": None if cov1.get("cover80") is None else round(float(cov1["cover80"]) * 100), "cover_n": cov1.get("n"),
            "cover80_5d": None if cov5.get("cover80") is None else round(float(cov5["cover80"]) * 100),
            "next_earnings": None if not ne else {"date": str(ne["d"])[:10], "timing": ne["timing"] if isinstance(ne["timing"], str) else None, "days": (date.fromisoformat(str(ne["d"])[:10]) - today).days},
            "news": None if not nb else {"n": int(nb["n"]), "high": int(nb["high"] or 0), "latest": str(nb["latest"])},
            "best_status": best_status.get(t),
            "cue": None if not cue else {"symbol": cue_sym, "change_pct": round(float(cue["change_pct"]) * 100, 2), "ts": str(cue["ts"]), "kind": "ADR" if cue_sym.endswith(":ADR") else "pre-market"},
            "scored": {"n": int(out_by[t]["n"]), "hits": int(out_by[t]["hits"])} if t in out_by else {"n": 0, "hits": 0},
        })

    # ---- market header
    regime = q("select * from regime order by computed_at desc limit 1").to_dict("records")[0]
    run_at = max((r["computed_at"] for r in scores), default=None)
    sess = market_session(cfg, datetime.now(timezone.utc))
    flows = q("select cast(date as varchar) as date, category, net_cr from flows_daily order by date desc, category").to_dict("records")
    fii = next((f for f in flows if f["category"] == "FII/FPI"), None)
    dii = next((f for f in flows if f["category"] == "DII"), None)
    candidates = [r["ticker"] for r in rows if (r["p1"] or 0) >= CALL_THRESHOLD or (r["p5"] or 0) >= CALL_THRESHOLD]
    yes = [r["ticker"] for r in rows if r["verdict"]["word"] == "YES"]
    abstain = sum(1 for r in rows if r["decision_1d"] == "abstain" and r["decision_5d"] == "abstain")
    blocked = [r["ticker"] for r in rows if r["quality"] == "BLOCKED" or (r["days_to_earnings"] is not None and r["days_to_earnings"] <= 1)]
    sectors = []
    for s, members in cfg["sectors"].items():
        sym = sector_sym.get(s)
        sectors.append({"name": s, "members": members, "index": None if not sym else {"symbol": sym, "name": symbols[sym]["name"], "move": move(sym, 1), "move_5": move(sym, 5)}})
    review = q("select week, model_skill from reviews order by computed_at desc limit 1").to_dict("records")
    header = {
        "regime": regime["regime"], "major_event_names": [str(x) for x in (regime.get("major_event_names") if regime.get("major_event_names") is not None else [])], "vol_level": regime["vol_level"],
        "vol_name": symbols[vol_sym]["name"], "vol_move": move(vol_sym, 1), "vol_close": closes.get(vol_sym, [None])[-1],
        "bench_name": symbols[bench]["name"], "bench_close": closes.get(bench, [None])[-1], "bench_move": move(bench, 1), "bench_move_5": move(bench, 5),
        "bench_live": None if bench not in quotes else {"price": quotes[bench]["price"], "change_pct": round(float(quotes[bench]["change_pct"]) * 100, 2), "ts": str(quotes[bench]["ts"])},
        "flows": None if not (fii and dii) else {"date": fii["date"][:10], "fii": fii["net_cr"], "dii": dii["net_cr"]},
        "run_at": str(run_at) if run_at is not None else None, "session": {k: (v if not hasattr(v, "isoformat") else v.isoformat()) for k, v in sess.items()},
        "n": len(rows), "yes": yes, "candidates": candidates, "abstain": abstain, "blocked": blocked,
        "scored_total": sum(r["scored"]["n"] for r in rows), "model_skill": bool(review and review[0]["model_skill"]), "review_week": review[0]["week"] if review else None,
        "up": sum(1 for r in rows if (r["move"] or 0) > 0), "down": sum(1 for r in rows if (r["move"] or 0) < 0),
        "news_total": sum(r["news"]["n"] for r in rows if r["news"]), "news_high": sum(r["news"]["high"] for r in rows if r["news"]),
    }
    return clean({
        "market": market, "market_name": cfg["name"], "exchange": EXCHANGE[market], "currency": cur, "as_of": str(end), "today": str(today),
        "built_at": datetime.now(timezone.utc).date().isoformat(), "window": [replay["start"], replay["end"]], "call_threshold": CALL_THRESHOLD,
        "header": header, "sectors": sectors, "rows": rows,
    })


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--market", default=os.environ.get("MB_MARKET", "india"), choices=["india", "us"])
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = build(a.market)
    json.dump(data, open(os.path.join(a.out, f"data-{a.market}.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    title = f"Watchlist · {data['market_name']}"
    desc = f"The {data['header']['n']} {data['market_name']} watchlist companies: price, the model's chance of a rise, verdict, range, results date and news, as of {data['as_of']}. Research only."
    html = inline_system(tpl.replace("/*__DATA__*/null", payload).replace("__TITLE__", title).replace("__DESC__", desc))
    out = os.path.join(a.out, f"watchlist-{a.market}.html")
    open(out, "w").write(html)
    h = data["header"]
    print(f"{out}: rows {len(data['rows'])} yes {h['yes']} candidates {h['candidates']} abstain {h['abstain']} html bytes {len(html)}")


if __name__ == "__main__":
    main()
