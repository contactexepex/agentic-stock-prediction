"""Assemble the data for the HDFC Bank decision page (read-only on the repo) and inline it into template.html
-> decision-HDFCBANK.html. Every number is read from DuckDB, the rule replay rows or the walk-forward
out-of-sample rows (hdfcbank_history.json, written by extract.py), or config/costs.yaml."""
import json, os, sys, math
from datetime import date, timedelta
sys.path.insert(0, "/home/user/agentic-stock-prediction/scripts")
import pandas as pd
import yaml
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.core.calendar import sessions_ahead, next_session, market_events
from marketbrief.model.settings import load_costs, round_trip_cost

HERE = os.path.dirname(os.path.abspath(__file__))
T = "HDFCBANK"
START, END = date(2026, 8, 17), date(2026, 10, 6)
con = connect("india")
cfg = load_market("india")
hist = json.load(open(os.path.join(HERE, "hdfcbank_history.json")))


def d(s):
    return str(s)[:10]


def q(sql):
    return con.execute(sql).df()


# ---- prices and index moves (live, stored bars)
bars = q(f"""select date, ticker, open, close from ohlc where ticker in ('{T}','NIFTY50','NIFTYBANK','INDIAVIX')
             and date >= '2026-08-10' order by date, ticker""")
bars["date"] = bars["date"].astype(str)
closes = bars.pivot(index="date", columns="ticker", values="close")
opens = bars.pivot(index="date", columns="ticker", values="open")
moves = (closes / closes.shift(1) - 1) * 100
sessions = [s for s in closes.index if s >= str(START)]
price_rows = []
for s in sessions:
    price_rows.append({
        "date": s, "open": round(float(opens.loc[s, T]), 2), "close": round(float(closes.loc[s, T]), 2),
        "move": round(float(moves.loc[s, T]), 2), "nifty": round(float(moves.loc[s, "NIFTY50"]), 2),
        "bank": round(float(moves.loc[s, "NIFTYBANK"]), 2),
        "vix_move": round(float(moves.loc[s, "INDIAVIX"]), 2),
    })

# ---- stored news per target date (company-news causes); the archive starts 2026-10-04
news_days = q(f"""select cast(published_at + interval '5 hours 30 minutes' as date) as ist_day, count(*) n,
                  sum(case when e.materiality='high' then 1 else 0 end) high
                  from news n left join enriched_latest e using(id) where list_contains(n.tickers,'{T}') group by 1 order by 1""")
news_by_day = {str(r.ist_day): {"n": int(r.n), "high": int(r.high)} for r in news_days.itertuples()}

# ---- back-test rows (rule replay ranges + walk-forward OOS probabilities)
r1 = pd.DataFrame(hist["replay"]["1"]); r5 = pd.DataFrame(hist["replay"]["5"])
o1 = pd.DataFrame(hist["oos"]["1"]); o5 = pd.DataFrame(hist["oos"]["5"])
for f in (r1, r5, o1, o5):
    f["date"] = f["date"].str[:10]
r1["target_date"] = r1["target_date"].str[:10]; r5["target_date"] = r5["target_date"].str[:10]

MARKET_WIDE = 0.75  # % benchmark / sector move, same sign, that counts as market-wide


def cause(target: str, move: float, miss: bool):
    """Deterministic cause of a day's move: results / company news / market-wide / unexplained (mock)."""
    pr = next(p for p in price_rows if p["date"] == target)
    same_sign = lambda x: (x > 0) == (move > 0)
    if abs(pr["bank"]) >= MARKET_WIDE and same_sign(pr["bank"]) or abs(pr["nifty"]) >= MARKET_WIDE and same_sign(pr["nifty"]):
        return {"kind": "market", "label": f"Market-wide: Nifty {pr['nifty']:+.1f}%, Nifty Bank {pr['bank']:+.1f}%",
                "source": "derived"}
    nd = news_by_day.get(target)
    if nd and nd["high"] > 0:
        return {"kind": "company", "label": f"Company news: {nd['n']} stored items, {nd['high']} high materiality",
                "source": "live"}
    if abs(pr["bank"]) >= MARKET_WIDE and not same_sign(pr["bank"]):
        return {"kind": "unexplained", "label": f"Stock-specific: moved against Nifty Bank ({pr['bank']:+.1f}%); no stored news for this day",
                "source": "mock"}
    return {"kind": "unexplained", "label": "Stock-specific; no stored news for this day", "source": "mock"}


def band_rows(rep: pd.DataFrame, oos: pd.DataFrame, horizon: int):
    out = []
    for r in rep.itertuples():
        o = oos[oos["date"] == r.date]
        o = o.iloc[0] if len(o) else None
        actual = None if (r.actual is None or (isinstance(r.actual, float) and math.isnan(r.actual))) else float(r.actual)
        hit80 = None if actual is None else bool(r.lo80 <= actual <= r.hi80)
        hit50 = None if actual is None else bool(r.lo50 <= actual <= r.hi50)
        row = {
            "as_of": r.date, "target": r.target_date, "regime": r.regime, "base": round(float(r.base), 2), "center": float(r.center),
            "lo50": round(float(r.lo50), 2), "hi50": round(float(r.hi50), 2),
            "lo80": round(float(r.lo80), 2), "hi80": round(float(r.hi80), 2),
            "actual": None if actual is None else round(actual, 2), "hit80": hit80, "hit50": hit50,
            "major": bool(r.major), "earn": bool(r.earn),
            "p": None if o is None else round(float(o.prob), 4),
            "p_raw": None if o is None else round(float(o.prob_raw), 4),
            "oc_ret": None if o is None or pd.isna(o.ret) else round(float(o.ret) * 100, 2),
            "lean_hit": None if o is None or pd.isna(o.up) else bool((o.prob > 0.5) == (o.up > 0)),
        }
        if actual is not None:
            mv = (actual / float(r.base) - 1) * 100
            # which session moved it: for 1d the target day itself; for 5d the largest day in the window
            if horizon == 1:
                row["cause"] = cause(r.target_date, mv, not hit80)
            else:
                window = [p for p in price_rows if r.date < p["date"] <= r.target_date]
                big = max(window, key=lambda p: abs(p["move"])) if window else None
                row["cause"] = cause(big["date"], big["move"], not hit80) if big else None
                if big: row["cause"]["label"] = f"Biggest day {big['date'][5:]} ({big['move']:+.1f}%): " + row["cause"]["label"]
        out.append(row)
    return out

bands1 = band_rows(r1, o1, 1)
bands5 = band_rows(r5, o5, 5)

def summary(rows):
    scored = [r for r in rows if r["actual"] is not None]
    leans = [r for r in rows if r["lean_hit"] is not None]
    return {"n": len(scored), "hit80": sum(r["hit80"] for r in scored), "hit50": sum(r["hit50"] for r in scored),
            "lean_n": len(leans), "lean_hit": sum(r["lean_hit"] for r in leans),
            "p_min": min(r["p"] for r in rows if r["p"] is not None), "p_max": max(r["p"] for r in rows if r["p"] is not None)}

# ---- live rows
live_scores = q(f"select * from model_scores where ticker='{T}' order by computed_at").to_dict("records")
live_latest = q(f"select * from model_scores_latest where ticker='{T}' order by horizon_days").to_dict("records")
live_ranges = q(f"select * from ranges where ticker='{T}' order by made_at, horizon_days").to_dict("records")
reasoning = q(f"select * from agent_reasoning where ticker='{T}' order by made_at").to_dict("records")
features = q(f"select * from features_latest where ticker='{T}'").to_dict("records")[0]
regime = q("select * from regime order by computed_at desc limit 1").to_dict("records")[0]
quotes = q("select symbol, ts, price, prev_close, change_pct from quotes_latest where day='2026-10-07' order by symbol").to_dict("records")
flows = q("select cast(date as varchar) as date, category, net_cr from flows_daily order by date desc, category").to_dict("records")
fpi = q("select cast(reporting_date as varchar) as reporting_date, asset_class, route, net_cr from fpi_latest where route in ('Sub-total','Total') order by asset_class").to_dict("records")
indices = q("select date, index_name, close, change_pct, ret_5_pct, pe, pb from indices_latest where index_name in ('Nifty Bank','Nifty 50')").to_dict("records")
delivery = q(f"select date, delivery_pct, delivery_pct_avg20 from delivery_stats where ticker='{T}' order by date desc limit 1").to_dict("records")
estimates = q(f"select report_date, eps_estimate, reported_eps, surprise_pct from earnings_estimates where ticker='{T}' order by report_date desc limit 2").to_dict("records")
news = q(f"""select n.id, n.published_at, n.source, n.title, n.url, e.sentiment, e.materiality, e.event_type, e.priced_in, e.summary
             from news n left join enriched_latest e using(id) where list_contains(n.tickers,'{T}') order by n.published_at desc""").to_dict("records")
verified = q(f"select id, status, level, independent_origins, origins from news_verified where ticker='{T}' and level='cluster'").to_dict("records")
status_by_id = {}
for v in verified:
    nid = v["id"].split("|")[0].split("-", 1)[1]
    status_by_id[nid] = v["status"]
for n in news:
    n["status"] = status_by_id.get(n["id"], "not assessed")
    n["published_at"] = str(n["published_at"])
    n["origins"] = next((list(v["origins"]) for v in verified if v["id"].split("|")[0].split("-", 1)[1] == n["id"]), [])

# ---- events and earnings-day moves
earn = q(f"select date, timing from events where ticker='{T}' and type='earnings' order by date").to_dict("records")
all_close = q(f"select date, close from ohlc where ticker='{T}' order by date")
all_close["date"] = all_close["date"].astype(str)
cl = dict(zip(all_close["date"], all_close["close"]))
dates_sorted = list(all_close["date"])
earn_moves = []
for e in earn:
    ed = str(e["date"])[:10]
    if ed > str(END): continue
    # reaction session: before_open/during -> the day itself if a session else the next; after_close -> next session
    nxt = [x for x in dates_sorted if x >= ed]
    if not nxt or dates_sorted[0] > ed: continue
    if e["timing"] == "after_close":
        nxt = [x for x in dates_sorted if x > ed]
    react = nxt[0]
    prev = [x for x in dates_sorted if x < react][-1]
    if (date.fromisoformat(react) - date.fromisoformat(ed)).days > 4: continue
    earn_moves.append({"date": ed, "timing": e["timing"], "session": react,
                       "move": round((cl[react] / cl[prev] - 1) * 100, 2)})
upcoming = [e for e in market_events(cfg, date(2026, 10, 7), date(2026, 12, 15)) if e["type"] != "weekly_expiry" or e["date"] <= date(2026, 10, 13)]
upcoming = [{"date": str(e["date"]), "type": e["type"], "name": e["name"], "major": e["major"]} for e in upcoming]
upcoming.append({"date": "2026-10-17", "type": "earnings", "name": "HDFC Bank Q2 FY27 results (Saturday; reaction on Mon 19 Oct)",
                 "major": True, "reaction_session": str(next_session(cfg, date(2026, 10, 17)))})
upcoming.sort(key=lambda e: e["date"])
next_sessions = [str(s) for s in sessions_ahead(cfg, END, 6)[1:]]

# ---- costs
costs = load_costs("india")
rt = round_trip_cost("india", costs)
costs_yaml = open("/home/user/agentic-stock-prediction/config/costs.yaml").read()

# ---- backtest aggregates (model skill) from the run in bt/
bt = json.load(open(os.path.join(HERE, "bt", "model-backtest-india-2026-10-06.json")))
res = bt["results"]["india"]
skill = {k: {"n": v["n"], "brier": v["brier"], "brier_base": v["brier_base_rate"], "skill": v["brier_skill"], "auc": v["auc"],
             "auc95": v["auc95"], "last_platt": v["model"]["last_platt"], "dates": v["dates"],
             "paper": v.get("paper", {}).get("thresholds", {}), "always_up": v.get("paper", {}).get("baselines", {}).get("always_up")}
         for k, v in res.items()}
model_cfg = yaml.safe_load(open("/home/user/agentic-stock-prediction/config/model.yaml"))
replay_summary = json.load(open(os.path.join(HERE, "replayroot", "reports", "india", "replay-2026-10-06.json")))
replay_tick = {h: replay_summary["horizons"][h]["by_ticker"].get(T) for h in ("1", "5")}
replay_overall = {h: replay_summary["horizons"][h]["overall"] for h in ("1", "5")}

data = {
    "ticker": T, "name": "HDFC Bank", "as_of": str(END), "today": "2026-10-07", "built_at": "2026-10-07",
    "prices": price_rows, "bands": {"1": bands1, "5": bands5},
    "band_summary": {"1": summary(bands1), "5": summary(bands5)},
    "next_sessions": next_sessions,
    "live": {"scores": live_scores, "latest": live_latest, "ranges": live_ranges, "reasoning": reasoning,
             "features": features, "regime": regime, "quotes": quotes, "flows": flows, "fpi": fpi, "indices": indices,
             "delivery": delivery, "estimates": estimates},
    "news": news, "earn_moves": earn_moves, "upcoming": upcoming,
    "costs": {"rates": costs, "round_trip": rt, "yaml": costs_yaml},
    "skill": skill, "model_cfg": {"thresholds": model_cfg["backtest"]["thresholds"], "news": model_cfg["news"]},
    "replay": {"ticker": replay_tick, "overall": replay_overall, "window": [replay_summary["start"], replay_summary["end"]]},
    "verdict_text": next((v for v in bt["verdicts"] if "5d open_to_close" in v and "Brier" in v), ""),
}


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if hasattr(o, "tolist"): return clean(o.tolist())
    if isinstance(o, float) and math.isnan(o): return None
    if isinstance(o, (pd.Timestamp,)): return str(o)
    if hasattr(o, "isoformat"): return o.isoformat()
    return o

data = clean(data)
json.dump(data, open(os.path.join(HERE, "data.json"), "w"), indent=1, default=str)
tpl = open(os.path.join(HERE, "template.html")).read()
payload = json.dumps(data, default=str).replace("</", "<\\/")
html = tpl.replace("/*__DATA__*/null", payload)
open(os.path.join(HERE, "decision-HDFCBANK.html"), "w").write(html)
print("bands1", len(bands1), "bands5", len(bands5), "news", len(news), "earn moves", len(earn_moves), "html bytes", len(html))
print(json.dumps(data["band_summary"]))
print("round trip", rt, "next sessions", next_sessions)
print([ (e['date'], e['move']) for e in earn_moves])
