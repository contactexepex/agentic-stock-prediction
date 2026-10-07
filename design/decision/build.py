"""Assemble the data for a stock decision page (read-only on the repo) and inline it into template.html.

    python design/decision/build.py --market india --ticker HDFCBANK --out design/decision

writes <out>/decision-<TICKER>.html and <out>/data-<TICKER>.json. Every number is read from DuckDB, the rule
replay rows and the walk-forward out-of-sample rows (both rebuilt here from the library behind scripts/replay.py
and scripts/model_backtest.py), the market's model back-test JSON (scripts/model_backtest.py, cached under
work/design/bt-<market>/; run here when missing, about 12 minutes) and config/. Nothing under data/, reports/ or
summaries/ is written: the rule replay runs into a scratch root under work/design/.

Data assembly (this file, -> data JSON) and presentation (template.html + the design system in design/system/)
are separate: the template reads one object, D, and renders it."""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
import pandas as pd  # noqa: E402
from marketbrief.core.calendar import market_events, next_session, prev_session, session_open_utc, sessions_ahead  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market, load_ranges_config  # noqa: E402
from marketbrief.model.panel import build_panel  # noqa: E402
from marketbrief.model.panel_inputs import read_inputs  # noqa: E402
from marketbrief.model.settings import load_costs, load_model_config, round_trip_cost  # noqa: E402
from marketbrief.model.walk_forward import walk_forward  # noqa: E402
from marketbrief.replay.rule_replay.inputs import load_inputs  # noqa: E402
from marketbrief.replay.rule_replay.range_rows import replay_rows  # noqa: E402
from system import inline_system  # noqa: E402

SESSIONS_BACK = 34          # back-test window: this many sessions before the as-of date (35 sessions in all)
MARKET_WIDE = 0.75          # % benchmark / sector move, same sign, that counts as market-wide
STAKE = 10000               # the plan's notional, in the market's currency
CURRENCY = {"INR": {"code": "INR", "symbol": "₹", "locale": "en-IN", "unit": "cr"},
            "USD": {"code": "USD", "symbol": "$", "locale": "en-US", "unit": "bn"}}
EXCHANGE = {"india": "NSE", "us": "NYSE/Nasdaq"}
WORK = os.path.join(REPO, "work", "design")
DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_d(d: date, dow: bool = True) -> str:
    return (DOW[d.weekday()][:3] + " " if dow else "") + f"{d.day} {MON[d.month - 1]}"


def sgn(x: float, dec: int = 1, unit: str = "%") -> str:
    return ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.{dec}f}{unit}"


def nan_none(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "tolist"):
        return clean(o.tolist())
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, pd.Timestamp):
        return str(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return o


# ---------------------------------------------------------------------------------------------
# Back-test inputs: rule replay rows and walk-forward out-of-sample rows for the ticker
# ---------------------------------------------------------------------------------------------
def history_rows(market: str, cfg: dict, con, ticker: str, start: date, end: date) -> dict:
    """Per-day rule-replay ranges (1d/5d) and walk-forward OOS probabilities for `ticker` in [start, end]
    (same library calls as scripts/replay.py and scripts/model_backtest.py; nothing is written)."""
    ranges_cfg = load_ranges_config()
    bars, extra = load_inputs(cfg, ranges_cfg, con)
    res, _reg = replay_rows(cfg, ranges_cfg, bars, extra, start, end)
    replay = {}
    for h, frame in res.items():
        f = frame[frame["ticker"] == ticker].copy().sort_values(frame.columns[0])
        replay[str(h)] = json.loads(f.to_json(orient="records", date_format="iso"))
    settings = load_model_config()
    panel = build_panel(cfg, read_inputs(con, market), settings["warmup_bars"])
    oos = {}
    for h in (1, 5):
        o, _fits = walk_forward(panel, (market, "open_to_close", h), settings)
        f = o[(o["ticker"] == ticker) & (o["date"] >= pd.Timestamp(start)) & (o["date"] <= pd.Timestamp(end))].copy()
        oos[str(h)] = json.loads(f.sort_values("date").to_json(orient="records", date_format="iso"))
    return {"replay": replay, "oos": oos}


def replay_summary_json(market: str, start: date, end: date) -> dict:
    """scripts/replay.py's JSON for the window, run into a scratch root (symlinks to the repo's data folders;
    the replay's own outputs land in work/design/)."""
    root = os.path.join(WORK, f"replayroot-{market}")
    path = os.path.join(root, "reports", market, f"replay-{end}.json")
    if not os.path.exists(path):
        os.makedirs(os.path.join(root, "data", market, "replays"), exist_ok=True)
        os.makedirs(os.path.join(root, "reports", market), exist_ok=True)
        for kind in os.listdir(os.path.join(REPO, "data", market)):
            link = os.path.join(root, "data", market, kind)
            if kind != "replays" and not os.path.lexists(link):
                os.symlink(os.path.join(REPO, "data", market, kind), link)
        env = dict(os.environ, MB_ROOT=root)
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "replay.py"), "--market", market,
                        "--start", str(start), "--end", str(end)], check=True, env=env, cwd=REPO,
                       stdout=subprocess.DEVNULL)
    return json.load(open(path))


def backtest_json(market: str) -> tuple[dict, str]:
    """The newest scripts/model_backtest.py JSON under work/design/bt-<market>/ (run when missing)."""
    out = os.path.join(WORK, f"bt-{market}")
    files = sorted(glob.glob(os.path.join(out, f"model-backtest-{market}-*.json")))
    if not files:
        print(f"no back-test JSON in {out}: running scripts/model_backtest.py (about 12 minutes)", file=sys.stderr)
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "model_backtest.py"), "--market", market,
                        "--out", out], check=True, cwd=REPO, stdout=subprocess.DEVNULL)
        files = sorted(glob.glob(os.path.join(out, f"model-backtest-{market}-*.json")))
    return json.load(open(files[-1])), files[-1]


# ---------------------------------------------------------------------------------------------
def build(market: str, ticker: str) -> dict:
    con = connect(market)
    cfg = load_market(market)
    tcfg = cfg["tickers"][ticker]
    company = tcfg["name"]
    sector = next(s for s, members in cfg["sectors"].items() if ticker in members)
    peers = [t for t in cfg["sectors"][sector] if t != ticker]
    cur = CURRENCY[cfg["currency"]]
    symbols = cfg["symbols"]
    bench = next(k for k, v in symbols.items() if v["role"] == "benchmark")
    vol_sym = next(k for k, v in symbols.items() if v["role"] == "vol_index")
    sector_sym = next((k for k, v in symbols.items() if v["role"] == "sector_etf" and sector in v.get("sectors", [])), None)

    def q(sql):
        return con.execute(sql).df()

    end = date.fromisoformat(str(q(f"select max(date) d from ohlc where ticker='{ticker}'").iloc[0, 0])[:10])
    start = end
    for _ in range(SESSIONS_BACK):
        start = prev_session(cfg, start - timedelta(days=1))
    today = next_session(cfg, end + timedelta(days=1))
    built_at = datetime.now(timezone.utc).date().isoformat()

    # ---- prices and index moves (live, stored bars)
    syms = [ticker, bench, vol_sym] + ([sector_sym] if sector_sym else [])
    bars = q(f"""select date, ticker, open, close from ohlc where ticker in ({",".join(repr(s) for s in syms)})
                 and date >= '{start - timedelta(days=7)}' order by date, ticker""")
    bars["date"] = bars["date"].astype(str)
    closes = bars.pivot(index="date", columns="ticker", values="close")
    opens = bars.pivot(index="date", columns="ticker", values="open")
    moves = (closes / closes.shift(1) - 1) * 100
    sessions = [s for s in closes.index if s >= str(start)]
    price_rows = []
    for s in sessions:
        price_rows.append({
            "date": s, "open": round(float(opens.loc[s, ticker]), 2), "close": round(float(closes.loc[s, ticker]), 2),
            "move": round(float(moves.loc[s, ticker]), 2), "nifty": round(float(moves.loc[s, bench]), 2),
            "bank": round(float(moves.loc[s, sector_sym]), 2) if sector_sym else None,
            "vix_move": round(float(moves.loc[s, vol_sym]), 2),
        })
    last = price_rows[-1]

    # ---- stored news per target date (company-news causes), local market day
    news_days = q(f"""select cast(timezone('{cfg["timezone"]}', published_at) as date) as local_day, count(*) n,
                      sum(case when e.materiality='high' then 1 else 0 end) high
                      from news n left join enriched_latest e using(id) where list_contains(n.tickers,'{ticker}') group by 1 order by 1""")
    news_by_day = {str(r.local_day): {"n": int(r.n), "high": int(r.high)} for r in news_days.itertuples()}

    # ---- back-test rows (rule replay ranges + walk-forward OOS probabilities)
    hist = history_rows(market, cfg, con, ticker, start, end)
    r1, r5 = pd.DataFrame(hist["replay"]["1"]), pd.DataFrame(hist["replay"]["5"])
    o1, o5 = pd.DataFrame(hist["oos"]["1"]), pd.DataFrame(hist["oos"]["5"])
    for f in (r1, r5, o1, o5):
        f["date"] = f["date"].str[:10]
    for f in (r1, r5):
        f["target_date"] = f["target_date"].str[:10]
    bench_name, sector_name = symbols[bench]["name"], symbols[sector_sym]["name"] if sector_sym else None

    def cause(target: str, move: float):
        """Deterministic cause of a day's move: market-wide / company news / stock-specific (mock)."""
        pr = next(p for p in price_rows if p["date"] == target)
        same_sign = lambda x: (x > 0) == (move > 0)  # noqa: E731
        sec = pr["bank"] if pr["bank"] is not None else 0.0
        if abs(sec) >= MARKET_WIDE and same_sign(sec) or abs(pr["nifty"]) >= MARKET_WIDE and same_sign(pr["nifty"]):
            label = f"Market-wide: {bench_name} {pr['nifty']:+.1f}%" + (f", {sector_name} {sec:+.1f}%" if sector_sym else "")
            return {"kind": "market", "label": label, "source": "derived"}
        nd = news_by_day.get(target)
        if nd and nd["high"] > 0:
            return {"kind": "company", "label": f"Company news: {nd['n']} stored items, {nd['high']} high materiality", "source": "live"}
        if sector_sym and abs(sec) >= MARKET_WIDE and not same_sign(sec):
            return {"kind": "unexplained", "label": f"Stock-specific: moved against {sector_name} ({sec:+.1f}%); no stored news for this day", "source": "mock"}
        return {"kind": "unexplained", "label": "Stock-specific; no stored news for this day", "source": "mock"}

    def band_rows(rep: pd.DataFrame, oos: pd.DataFrame, horizon: int):
        out = []
        for r in rep.itertuples():
            o = oos[oos["date"] == r.date]
            o = o.iloc[0] if len(o) else None
            actual = nan_none(r.actual)
            actual = None if actual is None else float(actual)
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
                if horizon == 1:
                    row["cause"] = cause(r.target_date, mv)
                else:
                    window = [p for p in price_rows if r.date < p["date"] <= r.target_date]
                    big = max(window, key=lambda p: abs(p["move"])) if window else None
                    row["cause"] = cause(big["date"], big["move"]) if big else None
                    if big:
                        row["cause"]["label"] = f"Biggest day {big['date'][5:]} ({big['move']:+.1f}%): " + row["cause"]["label"]
            out.append(row)
        return out

    bands1 = band_rows(r1, o1, 1)
    bands5 = band_rows(r5, o5, 5)

    def summary(rows):
        scored = [r for r in rows if r["actual"] is not None]
        leans = [r for r in rows if r["lean_hit"] is not None]
        ps = [r["p"] for r in rows if r["p"] is not None]
        return {"n": len(scored), "hit80": sum(r["hit80"] for r in scored), "hit50": sum(r["hit50"] for r in scored),
                "lean_n": len(leans), "lean_hit": sum(r["lean_hit"] for r in leans),
                "p_min": min(ps) if ps else None, "p_max": max(ps) if ps else None}

    # ---- live rows
    live_scores = q(f"select * from model_scores where ticker='{ticker}' order by computed_at").to_dict("records")
    live_latest = q(f"select * from model_scores_latest where ticker='{ticker}' order by horizon_days").to_dict("records")
    live_ranges = q(f"select * from ranges where ticker='{ticker}' order by made_at, horizon_days").to_dict("records")
    reasoning = q(f"select * from agent_reasoning where ticker='{ticker}' order by made_at").to_dict("records")
    features = q(f"select * from features_latest where ticker='{ticker}'").to_dict("records")[0]
    regime = q("select * from regime order by computed_at desc limit 1").to_dict("records")[0]
    quotes = q("select symbol, ts, price, prev_close, change_pct from quotes_latest where day=(select max(day) from quotes_latest) order by symbol").to_dict("records")
    flows = q("select cast(date as varchar) as date, category, net_cr from flows_daily order by date desc, category").to_dict("records")
    fpi = q("select cast(reporting_date as varchar) as reporting_date, asset_class, route, net_cr from fpi_latest where route in ('Sub-total','Total') order by asset_class").to_dict("records")
    index_names = [n for n in (sector_name, bench_name) if n]
    indices = q(f"select date, index_name, close, change_pct, ret_5_pct, pe, pb from indices_latest where index_name in ({','.join(repr(n) for n in index_names)}) order by index_name").to_dict("records")
    delivery = q(f"select date, delivery_pct, delivery_pct_avg20 from delivery_stats where ticker='{ticker}' order by date desc limit 1").to_dict("records")
    estimates = q(f"select report_date, eps_estimate, reported_eps, surprise_pct from earnings_estimates where ticker='{ticker}' order by report_date desc limit 2").to_dict("records")
    news = q(f"""select n.id, n.published_at, n.source, n.title, n.url, e.sentiment, e.materiality, e.event_type, e.priced_in, e.summary
                 from news n left join enriched_latest e using(id) where list_contains(n.tickers,'{ticker}') order by n.published_at desc""").to_dict("records")
    verified = q(f"select id, status, level, independent_origins, origins from news_verified where ticker='{ticker}' and level='cluster'").to_dict("records")
    status_by_id, origins_by_id = {}, {}
    for v in verified:
        nid = v["id"].split("|")[0].split("-", 1)[1]
        status_by_id[nid] = v["status"]
        origins_by_id[nid] = list(v["origins"])
    for n in news:
        n["status"] = status_by_id.get(n["id"], "not assessed")
        n["published_at"] = str(n["published_at"])
        n["origins"] = origins_by_id.get(n["id"], [])
    outcomes_n = int(q(f"select count(*) from outcomes o join predictions p on p.id = o.prediction_id where p.ticker='{ticker}'").iloc[0, 0])
    predictions = q(f"select * from predictions where ticker='{ticker}' order by made_at").to_dict("records")

    # ---- events and earnings-day moves
    earn = q(f"select date, timing from events where ticker='{ticker}' and type='earnings' order by date").to_dict("records")
    all_close = q(f"select date, close from ohlc where ticker='{ticker}' order by date")
    all_close["date"] = all_close["date"].astype(str)
    cl = dict(zip(all_close["date"], all_close["close"]))
    dates_sorted = list(all_close["date"])
    earn_moves = []
    for e in earn:
        ed = str(e["date"])[:10]
        if ed > str(end):
            continue
        nxt = [x for x in dates_sorted if x >= ed]
        if not nxt or dates_sorted[0] > ed:
            continue
        if e["timing"] == "after_close":
            nxt = [x for x in dates_sorted if x > ed]
        react = nxt[0]
        prev = [x for x in dates_sorted if x < react][-1]
        if (date.fromisoformat(react) - date.fromisoformat(ed)).days > 4:
            continue
        earn_moves.append({"date": ed, "timing": e["timing"], "session": react, "move": round((cl[react] / cl[prev] - 1) * 100, 2)})
    window_end = today + timedelta(days=69)
    upcoming = [e for e in market_events(cfg, today, window_end) if e["type"] != "weekly_expiry" or e["date"] <= today + timedelta(days=6)]
    upcoming = [{"date": str(e["date"]), "type": e["type"], "name": e["name"], "major": e["major"]} for e in upcoming]
    next_earnings = None
    for e in earn:
        ed = date.fromisoformat(str(e["date"])[:10])
        if ed < today or ed > window_end:
            continue
        timing = e["timing"] if isinstance(e["timing"], str) else None
        reaction = next_session(cfg, ed + timedelta(days=1)) if timing == "after_close" else next_session(cfg, ed)
        when = DOW[ed.weekday()] + (f", {timing.replace('_', ' ')}" if timing else "")
        row = {"date": str(ed), "type": "earnings", "major": True, "reaction_session": str(reaction),
               "name": f"{company} results ({when}; reaction on {fmt_d(reaction)})" if reaction != ed else f"{company} results ({when})"}
        upcoming.append(row)
        if next_earnings is None:
            next_earnings = {"date": str(ed), "timing": timing, "reaction_session": str(reaction), "days": (ed - today).days}
    upcoming.sort(key=lambda e: e["date"])
    next_sessions = [str(s) for s in sessions_ahead(cfg, end, 6)[1:]]

    # ---- costs
    costs = load_costs(market)
    rt = round_trip_cost(market, costs, price=last["close"])
    costs_yaml = open(os.path.join(REPO, "config", "costs.yaml")).read()

    # ---- backtest aggregates (model skill) and the rule replay's market-wide coverage
    bt, bt_path = backtest_json(market)
    res = bt["results"][market]
    skill = {k: {"n": v["n"], "brier": v["brier"], "brier_base": v["brier_base_rate"], "skill": v["brier_skill"], "auc": v["auc"],
                 "auc95": v["auc95"], "last_platt": v["model"]["last_platt"], "dates": v["dates"],
                 "paper": v.get("paper", {}).get("thresholds", {}), "always_up": v.get("paper", {}).get("baselines", {}).get("always_up")}
             for k, v in res.items()}
    model_cfg = load_model_config()
    replay_summary = replay_summary_json(market, start, end)
    replay_tick = {h: replay_summary["horizons"][h]["by_ticker"].get(ticker) for h in ("1", "5")}
    replay_overall = {h: replay_summary["horizons"][h]["overall"] for h in ("1", "5")}

    data = {
        "ticker": ticker, "name": company, "as_of": str(end), "today": str(today), "built_at": built_at,
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
    data = clean(data)
    data["page"] = clean(page_block(market, cfg, con, ticker, company, sector, peers, cur, data, today, end, bench, vol_sym,
                                    sector_sym, next_earnings, outcomes_n, predictions, bt_path))
    return data


# ---------------------------------------------------------------------------------------------
# Presentation inputs that depend on config, the calendar or market conventions (-> D.page)
# ---------------------------------------------------------------------------------------------
def page_block(market, cfg, con, ticker, company, sector, peers, cur, D, today, end, bench, vol_sym, sector_sym,
               next_earnings, outcomes_n, predictions, bt_path) -> dict:
    symbols = cfg["symbols"]
    live = D["live"]
    last = D["prices"][-1]
    quotes = {r["symbol"]: r for r in live["quotes"]}
    latest = {r["horizon_days"]: r for r in live["latest"]}
    p1 = latest[1]["prob_up"] if 1 in latest else None
    p5 = latest[5]["prob_up"] if 5 in latest else None
    reasoning = live["reasoning"][-1] if live["reasoning"] else None
    feats = live["features"]
    regime = live["regime"]

    def q(sql):
        return con.execute(sql).df()

    # 52-week position
    yr = q(f"select min(low) lo, max(high) hi from ohlc where ticker='{ticker}' and date > '{end - timedelta(days=365)}'").iloc[0]
    lo52, hi52 = float(yr["lo"]), float(yr["hi"])
    close = last["close"]
    if close <= lo52 * 1.05:
        pos52 = "52-week low area"
    elif close >= hi52 * 0.95:
        pos52 = "52-week high area"
    else:
        pos52 = f"{(1 - close / hi52) * 100:.0f}% below the 52-week high"

    # run time vs the open of today's session
    run_at = max(r["computed_at"] for r in live["latest"]) if live["latest"] else None
    run_dt = datetime.fromisoformat(run_at) if run_at else None
    open_dt = session_open_utc(cfg, today)
    run_before_open = bool(run_dt and run_dt < open_dt)
    hm = lambda dt: dt.astimezone(timezone.utc).strftime("%H:%M")  # noqa: E731

    # weekly review verdict on model skill
    review = q("select week, model_skill, computed_at from reviews order by computed_at desc limit 1").to_dict("records")
    review = review[0] if review else None

    # evidence quality as of the run
    order = ["confirmed_primary", "corroborated", "single_source", "unverified", "rumour", "promotional", "contradicted", "not assessed"]
    counts = {}
    for n in D["news"]:
        counts[n["status"]] = counts.get(n["status"], 0) + 1
    assessed = [s for s in order if counts.get(s) and s != "not assessed"]
    best_status = assessed[0] if assessed else "none assessed"
    evidence_ok = best_status in ("confirmed_primary", "corroborated")

    # plan sources per horizon: the live range for the as-of date, else the rule replay's row
    plan = {}
    for h in (1, 5):
        rid = f"{end}-{ticker}-{h}d"
        row = next((r for r in live["ranges"] if r["id"] == rid), None)
        if row:
            plan[str(h)] = {"kind": "live", "id": rid, "made_at": row["made_at"], "base": row["base_close"], "center": row["center"],
                            "lo50": row["lo50"], "hi50": row["hi50"], "lo80": row["lo80"], "hi80": row["hi80"], "notes": list(row["notes"] or []),
                            "regime": row["regime"], "target": str(row["target_date"])[:10]}
        else:
            b = next((b for b in D["bands"][str(h)] if b["as_of"] == str(end)), None)
            plan[str(h)] = None if b is None else {"kind": "bt", "id": rid, "made_at": None, "base": b["base"], "center": b["center"],
                                                   "lo50": b["lo50"], "hi50": b["hi50"], "lo80": b["lo80"], "hi80": b["hi80"],
                                                   "notes": ["major event x1.15"] if b["major"] else [], "regime": b["regime"], "target": b["target"]}

    # verdict: a live call for today, else NO (no edge)
    call = next((p for p in predictions if str(p.get("as_of_date"))[:10] == str(end)), None)
    if call:
        # strength of a YES (owner's rule: darker green when strong, lighter when okay): strong when the
        # forecaster's confidence is at least 0.75 or the anchored probability (model_prob + adjustment)
        # is at least 0.65; else okay
        final = (call.get("model_prob") or 0) + (call.get("agent_adjustment") or 0)
        strong = call["confidence"] >= 0.75 or final >= 0.65
        verdict = {"word": "YES" if call["direction"] == "up" else "NO", "small": f"call: {call['direction']}, confidence {call['confidence']}"
                   + (f" \u00b7 {'strong' if strong else 'okay'} signal" if call["direction"] == "up" else ""),
                   "kind": "call", "direction": call["direction"], "strength": ("strong" if strong else "ok") if call["direction"] == "up" else None}
    else:
        verdict = {"word": "NO", "small": "No edge today", "kind": "no_call", "direction": None, "strength": None}

    # why sentence pieces
    coin = p1 is not None and p5 is not None and all(0.45 <= p <= 0.55 for p in (p1, p5))
    abstained = bool(reasoning and reasoning.get("decision_1d") == "abstain" and reasoning.get("decision_5d") == "abstain")
    skill_true = bool(review and review["model_skill"])
    earnings_sentence = ""
    if next_earnings:
        d = date.fromisoformat(next_earnings["date"])
        earnings_sentence = f"Results on {fmt_d(d, False)} are {next_earnings['days']} days away."
    forecaster_quote = (reasoning["verdict"].split(".")[0] + ".") if reasoning and reasoning.get("verdict") else ""

    # the five checks
    sk5, sk1 = D["skill"].get("5d open_to_close", {}), D["skill"].get("1d open_to_close", {})
    th = D["model_cfg"]["thresholds"]
    paper60 = (sk5.get("paper") or {}).get("0.60", {}).get("long")
    pct = lambda x, dec=0: round(x * 100, dec) if dec else round(x * 100)  # noqa: E731
    checks = [
        {"ok": bool(p1 is not None and max(p1, p5 or 0) >= 0.60), "text": "Model chance of a rise at or above 60%",
         "now": f"{pct(p1)}% / {pct(p5)}% now" if p1 is not None and p5 is not None else "no live score",
         "tip": f"config/model.yaml backtest thresholds are {'/'.join(str(int(t * 100)) for t in th)}%. "
                + (f"In the back-test the 5-day long at >=60% held {paper60['positions']} positions on {paper60['dates']} dates and "
                   f"{'lost' if paper60['mean_pct'] < 0 else 'made'} {abs(paper60['mean_pct']):.2f}% per trade after costs on average "
                   f"(95% interval {paper60['ci95_pct'][0]} to {paper60['ci95_pct'][1]})." if paper60 else "")},
        {"ok": skill_true, "text": "Model shows skill in the walk-forward back-test",
         "now": f"AUC {sk5['auc']:.2f} (95%: {sk5['auc95'][0]:.2f}–{sk5['auc95'][1]:.2f})" if sk5 else "no back-test",
         "tip": "Weekly review rule: at least 500 out-of-sample rows with Brier skill above 0 and an AUC 95% interval above 0.5. "
                + (f"Today: 5d open-to-close Brier {sk5['brier']} vs base rate {sk5['brier_base']} (skill {sk5['skill']}), AUC {sk5['auc']}. " if sk5 else "")
                + (f"1d: AUC {sk1['auc']}. " if sk1 else "")
                + (f"Verdict of review {review['week']}: model_skill {'true' if skill_true else 'false'}." if review else "No weekly review stored yet.")},
        {"ok": run_before_open, "text": f"Run finished before the {EXCHANGE[market]} open",
         "now": (f"today {hm(run_dt)} UTC, open {hm(open_dt)}" if run_dt else "no run stored"),
         "tip": f"The forecaster abstains when the first session of the call is already partly public (mid-session run). "
                f"The {cfg['name']} routine's latest model score was computed at {hm(run_dt) if run_dt else '?'} UTC; the session of {fmt_d(today)} opens at {hm(open_dt)} UTC."
                + ("" if run_before_open else " A 1-day range is withheld for the same reason.")},
        {"ok": evidence_ok, "text": "Main evidence confirmed by a primary source or two outlets",
         "now": f"best: {best_status.replace('_', ' ')}",
         "tip": "Prediction rule: the first evidence id must be confirmed_primary or corroborated as of made_at. Stored headlines for "
                f"{company} by verification status: " + ", ".join(f"{s.replace('_', ' ')} {counts[s]}" for s in order if counts.get(s)) + "."},
        {"ok": bool(feats.get("days_to_earnings") is None or feats["days_to_earnings"] > 1), "text": "More than 1 session to results",
         "now": (f"{next_earnings['days']} days ({fmt_d(date.fromisoformat(next_earnings['date']), False)})" if next_earnings
                 else "none stored in the window"),
         "tip": "No new call with earnings within 1 day (days_to_earnings <= 1). "
                + (f"Results are due {fmt_d(date.fromisoformat(next_earnings['date']))}; the reaction session is {fmt_d(date.fromisoformat(next_earnings['reaction_session']))}."
                   if next_earnings else "No results date is stored inside the next ten weeks.")},
    ]

    # ---- drivers (Company / Sector / Market) with direction, strength 1-3 and a tooltip
    def str_news(s, m):
        w = {"high": 1, "medium": .5, "low": .2}.get(m, .2)
        v = abs(s) * w
        return 3 if v >= .4 else 2 if v >= .15 else 1

    def str_move(v):
        return 3 if abs(v) >= 1 else 2 if abs(v) >= .5 else 1

    def dir_of(v, eps=0.0):
        return "up" if v > eps else "dn" if v < -eps else "flat"

    def qpct(sym):
        return quotes[sym]["change_pct"] * 100

    def quote_name(sym):
        return symbols.get(sym, {}).get("name", sym)

    comp = []
    seen = set()
    scored_news = [n for n in D["news"] if n.get("sentiment") is not None and n.get("materiality")]
    scored_news.sort(key=lambda n: -abs(n["sentiment"]) * {"high": 1, "medium": .5, "low": .2}.get(n["materiality"], .2))
    for n in scored_news:
        key = n["title"][:40].lower()
        if key in seen:
            continue
        seen.add(key)
        s = n["sentiment"]
        d = date.fromisoformat(n["published_at"][:10])
        comp.append({"name": n["title"][:72] + ("…" if len(n["title"]) > 72 else ""), "dir": dir_of(s, 0.05), "str": str_news(s, n["materiality"]),
                     "sub": f"{n['source']}, {fmt_d(d, False)} · sentiment {s:+.2f} · {n['materiality']} · {n['status'].replace('_', ' ')}", "k": "live",
                     "tip": f"Stored headline {n['id']}: “{n['title']}”. Enrichment: sentiment {s:+.2f}, materiality {n['materiality']}"
                            + (f", {n['event_type']}" if n.get("event_type") else "") + (", priced in" if n.get("priced_in") else "") + ". "
                            + (n["summary"] + " " if n.get("summary") else "")
                            + f"Verification: {n['status'].replace('_', ' ')}" + (f", origins {', '.join(n['origins'])}" if n["origins"] else "") + "."})
        if len(comp) >= 5:
            break
    if live["delivery"]:
        dv = live["delivery"][0]
        comp.append({"name": f"Delivery share {dv['delivery_pct']}% vs {dv['delivery_pct_avg20']}% 20-day average", "dir": "flat", "str": 1,
                     "sub": f"NSE bhavcopy, {fmt_d(date.fromisoformat(str(dv['date'])[:10]), False)}", "k": "live",
                     "tip": f"Delivery percentage of traded volume (delivery_stats): {dv['delivery_pct']}% against a 20-day average of {dv['delivery_pct_avg20']}%. "
                            "Lower delivery = more intraday trading, less investor accumulation."})
    if market == "us":
        si = q(f"select settlement_date, short_interest, change_pct, days_to_cover from short_interest_latest where ticker='{ticker}'").to_dict("records")
        sv = q(f"select date, short_pct, short_pct_5d, short_pct_prior_avg from shorts_latest where ticker='{ticker}'").to_dict("records")
        if si:
            s0 = si[0]
            comp.append({"name": f"Short interest {s0['short_interest'] / 1e6:.1f}m shares ({sgn(s0['change_pct'], 1)} vs prior), {s0['days_to_cover']:.1f} days to cover",
                         "dir": "flat", "str": 1, "sub": f"FINRA, settlement {fmt_d(date.fromisoformat(str(s0['settlement_date'])[:10]), False)}"
                         + (f" · daily short volume {sv[0]['short_pct']}% of volume" if sv else ""), "k": "live",
                         "tip": "FINRA short interest (twice a month) and Reg SHO daily short-sale volume (short_interest_latest, shorts_latest). Context only; no model input."})
    sc1 = [s for s in live["scores"] if s["horizon_days"] == 1]
    tech_pts = None
    contrib = None
    if sc1:
        contrib = sc1[-1]["contributions"]
        contrib = json.loads(contrib) if isinstance(contrib, str) else contrib
        groups = (contrib or {}).get("groups", {})
        tech_pts = sum(float(v) for k, v in groups.items() if k not in ("news", "baseline"))
    comp.append({"name": f"Model's technical read: {tech_pts:+.2f} points" if tech_pts is not None else "Model's technical read: no live score",
                 "dir": dir_of(tech_pts or 0, 0.05), "str": 1 if tech_pts is None or abs(tech_pts) < .1 else 2 if abs(tech_pts) < .3 else 3,
                 "sub": f"RSI {round(feats['rsi_14'])}, 20-day {sgn(feats['ret_20d'] * 100, 1)}, vs sector 5d {sgn(feats['rel_sector_5d'] * 100, 1)}" if feats.get("rsi_14") is not None else "",
                 "k": "live", "tip": ("model_scores " + str(sc1[-1]["as_of_date"])[:10] + ": points by group " + ", ".join(f"{k} {v}" for k, v in (contrib or {}).get("groups", {}).items())
                                      + f"; base rate {sc1[-1]['base_rate']}." if sc1 else "No live model score for this ticker.")
                 + " Technical, volume, volatility and regime features together; the news group is listed apart."})

    sect = []
    ib = next((i for i in live["indices"] if sector_sym and i["index_name"] == symbols[sector_sym]["name"]), None)
    i50 = next((i for i in live["indices"] if i["index_name"] == symbols[bench]["name"]), None)
    if sector_sym:
        sname = symbols[sector_sym]["name"]
        if ib:
            day, five = ib["change_pct"], ib["ret_5_pct"]
            src = f"NSE index close (indices_latest) {fmt_d(date.fromisoformat(str(ib['date'])[:10]), False)}: {sname} {ib['close']:,} ({sgn(day, 2)}; 5-day {sgn(five, 2)})."
        else:
            day, five = last["bank"], (D["prices"][-1]["close"] and None)
            sec_closes = q(f"select close from ohlc where ticker='{sector_sym}' order by date desc limit 6")["close"].tolist()
            five = (sec_closes[0] / sec_closes[5] - 1) * 100 if len(sec_closes) == 6 else 0.0
            src = f"Stored bars of {sname} ({sector_sym}, Yahoo): {fmt_d(date.fromisoformat(last['date']), False)} {sgn(day, 2)}, 5-day {sgn(five, 2)}."
        sect.append({"name": f"{sname} {sgn(day, 2)} {DOW[date.fromisoformat(last['date']).weekday()]}, {sgn(five, 2)} over 5 days", "dir": dir_of(day), "str": str_move(day),
                     "sub": f"{company} {sgn(feats['ret_5d'] * 100, 2)} over the same 5 days", "k": "live",
                     "tip": src + f" {company}'s 5-day return {sgn(feats['ret_5d'] * 100, 2)}: {'lagged' if feats['rel_sector_5d'] < 0 else 'led'} its sector by {sgn(feats['rel_sector_5d'] * 100, 1)} points (features.rel_sector_5d)."})
    for peer in peers:
        pname = cfg["tickers"][peer]["name"]
        padr = cfg["tickers"][peer].get("adr")
        if padr and f"{peer}:ADR" in quotes:
            qq = quotes[f"{peer}:ADR"]
            sect.append({"name": f"{pname} ADR {sgn(qpct(f'{peer}:ADR'), 1)} overnight", "dir": dir_of(qq["change_pct"]), "str": str_move(qpct(f"{peer}:ADR")),
                         "sub": f"peer cue, NYSE close {fmt_d(date.fromisoformat(str(qq['ts'])[:10]), False)}", "k": "live",
                         "tip": f"quotes_latest {padr} {qq['price']} vs {qq['prev_close']} ({sgn(qpct(f'{peer}:ADR'), 2)}). The peer's US listing traded overnight."})
        elif peer in quotes:
            qq = quotes[peer]
            sect.append({"name": f"{pname} pre-market {sgn(qpct(peer), 1)}", "dir": dir_of(qq["change_pct"]), "str": str_move(qpct(peer)),
                         "sub": f"peer cue, {str(qq['ts'])[11:16]} UTC", "k": "live",
                         "tip": f"quotes_latest {peer} {qq['price']} vs previous close {qq['prev_close']} ({sgn(qpct(peer), 2)})."})
        else:
            pm = q(f"select date, close, lag(close) over (order by date) prev from ohlc where ticker='{peer}' order by date desc limit 1").to_dict("records")
            if pm and pm[0]["prev"]:
                mv = (pm[0]["close"] / pm[0]["prev"] - 1) * 100
                sect.append({"name": f"{pname} {sgn(mv, 1)} on {fmt_d(date.fromisoformat(str(pm[0]['date'])[:10]), False)}", "dir": dir_of(mv), "str": str_move(mv),
                             "sub": "peer, stored close", "k": "live", "tip": f"ohlc {peer}: close {pm[0]['close']} vs {pm[0]['prev']}."})
    if ib and ib.get("pb") is not None:
        sect.append({"name": f"Sector valuation: {symbols[sector_sym]['name']} P/B {ib['pb']}, P/E {ib['pe']}", "dir": "flat", "str": 1,
                     "sub": f"{symbols[bench]['name']} P/E {i50['pe']}, P/B {i50['pb']}" if i50 else "", "k": "live",
                     "tip": "NSE daily index valuation (indices_latest). Context only; no model input."})
    for peer in peers:
        pn = q(f"""select n.id, n.source, n.title, n.published_at, e.sentiment, e.materiality from news n left join enriched_latest e using(id)
                   where list_contains(n.tickers,'{peer}') and e.materiality in ('high','medium') and e.sentiment is not null
                   order by case e.materiality when 'high' then 0 else 1 end, abs(e.sentiment) desc, n.published_at desc limit 1""").to_dict("records")
        if pn:
            n = pn[0]
            st = status_of(con, peer, n["id"])
            sect.append({"name": f"Peer news: {n['title'][:80]}{'…' if len(n['title']) > 80 else ''}", "dir": dir_of(n["sentiment"], 0.05), "str": str_news(n["sentiment"], n["materiality"]),
                         "sub": f"{n['source']}, {fmt_d(date.fromisoformat(str(n['published_at'])[:10]), False)} · {n['materiality']} · {st.replace('_', ' ')}", "k": "live",
                         "tip": f"Headline {n['id']} tagged to {cfg['tickers'][peer]['name']}: sentiment {n['sentiment']:+.2f}, materiality {n['materiality']}; verification {st.replace('_', ' ')}."})

    mkt = []
    names = list(regime.get("major_event_names") or [])
    if names:
        mkt.append({"name": f"{', '.join(names)} today", "dir": "unk", "str": 3, "sub": f"regime {regime['regime']}; ranges ×{load_ranges_config()['major_event_factor']}", "k": "live",
                    "tip": f"config/events.yaml: a major market-wide event inside the horizon raises the regime to EVENT_HEAVY and widens every range "
                           f"×{load_ranges_config()['major_event_factor']}. Direction for the stock: unclear until the outcome is known."})
    adr = cfg["tickers"][ticker].get("adr")
    own = f"{ticker}:ADR" if adr and f"{ticker}:ADR" in quotes else (ticker if ticker in quotes else None)
    if own:
        qq = quotes[own]
        label = f"{company} ADR {sgn(qpct(own), 1)} overnight" if own.endswith(":ADR") else f"{company} pre-market {sgn(qpct(own), 1)}"
        mkt.append({"name": label, "dir": dir_of(qq["change_pct"]), "str": str_move(qpct(own)),
                    "sub": (f"NYSE: {adr}, " if own.endswith(":ADR") else "gap vs previous close, ") + f"half applied to the range centre (cue weight {load_ranges_config()['cue_weight']})", "k": "live",
                    "tip": f"quotes_latest {own} {qq['price']} vs {qq['prev_close']} ({sgn(qpct(own), 2)}) at {str(qq['ts'])[11:16]} UTC. ranges.py applies cue_weight {load_ranges_config()['cue_weight']} of this to the range centre."})
    if live["flows"]:
        fii = next((f for f in live["flows"] if f["category"] == "FII/FPI"), None)
        dii = next((f for f in live["flows"] if f["category"] == "DII"), None)
        fpi_eq = next((f for f in live["fpi"] if f["asset_class"] == "Equity" and f["route"] == "Sub-total"), None)
        if fii and dii:
            str_flow = lambda v: 3 if abs(v) >= 3000 else 2 if abs(v) >= 1000 else 1  # noqa: E731
            mkt.append({"name": f"FII {'sold' if fii['net_cr'] < 0 else 'bought'} ₹{abs(fii['net_cr']):,.0f} cr, DII {'bought' if dii['net_cr'] > 0 else 'sold'} ₹{abs(dii['net_cr']):,.0f} cr",
                        "dir": dir_of(fii["net_cr"]), "str": str_flow(fii["net_cr"]),
                        "sub": f"NSE provisional, {fmt_d(date.fromisoformat(fii['date'][:10]))}" + (f" · FPI equity {sgn(fpi_eq['net_cr'], 0, ' cr')} (NSDL)" if fpi_eq else ""), "k": "live",
                        "tip": f"flows_daily {fii['date'][:10]}: FII/FPI net {fii['net_cr']} cr, DII net {dii['net_cr']} cr (provisional)."
                               + (f" NSDL FPI equity sub-total {fpi_eq['net_cr']} cr on {fpi_eq['reporting_date']}." if fpi_eq else "")
                               + " Foreign selling is the conventional negative for large caps; direction is the conventional reading."})
    cues = [s for s, v in symbols.items() if v["role"] == "cue" and s in quotes]
    if cues:
        lead = cues[0]
        mkt.append({"name": ", ".join(f"{quote_name(s).split(' (')[0]} {sgn(qpct(s), 1)}" for s in cues[:2]), "dir": dir_of(quotes[lead]["change_pct"]), "str": str_move(qpct(lead)),
                    "sub": (" · ".join(f"{quote_name(s).split(' (')[0]} {sgn(qpct(s), 1)}" for s in cues[2:]) + (" · " if len(cues) > 2 else "")
                            + (f"{quote_name(bench)} {sgn(qpct(bench), 1)} at {str(quotes[bench]['ts'])[11:16]} UTC" if bench in quotes else f"{str(quotes[lead]['ts'])[11:16]} UTC")), "k": "live",
                    "tip": "quotes_latest: " + "; ".join(f"{quote_name(s)} {quotes[s]['price']} ({sgn(qpct(s), 2)})" for s in cues + ([bench] if bench in quotes else [])) + ". Overnight and pre-open cues; same-sign reading."})
    if "US10Y" in quotes:
        y = quotes["US10Y"]
        mkt.append({"name": f"US 10-year {y['price']:.2f}% ({sgn((y['price'] - y['prev_close']) * 100, 0, ' bp')})", "dir": "dn" if y["change_pct"] > 0 else "up" if y["change_pct"] < 0 else "flat", "str": str_move(qpct("US10Y")),
                    "sub": f"dollar index {quotes['DXY']['price']:.1f} ({sgn(qpct('DXY'), 2)})" if "DXY" in quotes else "", "k": "live",
                    "tip": f"quotes_latest ^TNX {y['price']} vs {y['prev_close']}" + (f"; DXY {quotes['DXY']['price']}" if "DXY" in quotes else "")
                           + ". Lower yields are the conventional positive for equities, a firmer dollar the opposite; direction is the conventional reading, not a model output."})
    oil = "BRENT" if "BRENT" in quotes else "WTI" if "WTI" in quotes else None
    if oil:
        fx = "USDINR" if "USDINR" in quotes else None
        energy = sector.lower() == "energy"
        o_dir = dir_of(quotes[oil]["change_pct"]) if energy else ("dn" if quotes[oil]["change_pct"] > 0 else "up" if quotes[oil]["change_pct"] < 0 else "flat") if market == "india" else "flat"
        mkt.append({"name": f"{quote_name(oil)} ${quotes[oil]['price']:.1f} ({sgn(qpct(oil), 1)})" + (f", rupee {quotes[fx]['price']:.2f}/$ ({sgn(qpct(fx), 2)})" if fx else (f", gold ${quotes['GOLD']['price']:,.0f} ({sgn(qpct('GOLD'), 1)})" if "GOLD" in quotes else "")),
                    "dir": o_dir, "str": str_move(qpct(oil)) if o_dir != "flat" else 1,
                    "sub": ("energy producer: oil up is the conventional positive" if energy else "costly oil and a weak rupee: conventional negatives for India" if market == "india" else "context only for this sector"), "k": "live",
                    "tip": f"quotes_latest {oil} {quotes[oil]['price']}" + (f", {fx} {quotes[fx]['price']}" if fx else "") + ". Direction is the conventional reading for the sector, not a model output."})
    if vol_sym in quotes:
        vq = quotes[vol_sym]
        rcfg = cfg["regime"]
        mkt.append({"name": f"{quote_name(vol_sym)} {vq['price']:.1f} ({sgn(qpct(vol_sym), 1)})", "dir": "flat", "str": 1,
                    "sub": f"regime: {regime['regime']} (vol < {rcfg['calm_vol']} would be CALM)", "k": "live",
                    "tip": f"regime_latest: {regime['regime']}, vol level {regime['vol_level']}, benchmark 5-day {sgn(regime['bench_ret_5d'] * 100, 2)}, major event: {', '.join(names) or 'none'}. "
                           f"Thresholds (config/markets/{market}.yaml): calm below {rcfg['calm_vol']}, event above {rcfg['event_vol']}, unstable above {rcfg['unstable_vol']}."})

    def net(rows):
        s = sum(r["str"] if r["dir"] == "up" else -r["str"] if r["dir"] == "dn" else 0 for r in rows)
        unk = any(r["dir"] == "unk" for r in rows)
        if unk and abs(s) < 2:
            return "net: event day, mixed"
        return "net: leaning up" if s >= 2 else "net: leaning down" if s <= -2 else "net: mixed"

    # the pipeline's own conclusion (drivers note)
    news_n = len(((contrib or {}).get("news") or {}).get("ids") or [])
    note = ""
    if latest.get(1):
        note = f"What the pipeline itself concluded: model news score {latest[1]['news_score']:+g} ({news_n} items in the 72-hour window, fixed prior weights), " \
               f"technicals {tech_pts:+.2f} points" if tech_pts is not None else ""
    if reasoning:
        bull = (reasoning.get("bull_case") or "").split(". ")[0]
        bear = (reasoning.get("bear_case") or "").split(". ")[0]
        note += (f"; forecaster bull case “{bull[:160]}” vs bear case “{bear[:160]}” → {reasoning['decision_1d']} (1d), {reasoning['decision_5d']} (5d)."
                 if note else f"Forecaster: {reasoning['decision_1d']} (1d), {reasoning['decision_5d']} (5d).")

    nd = [date.fromisoformat(n["published_at"][:10]) for n in D["news"]]
    news_span = (f"{min(nd).day}–{fmt_d(max(nd), False)}" if nd and min(nd).month == max(nd).month else f"{fmt_d(min(nd), False)} – {fmt_d(max(nd), False)}") if nd else "none stored"
    bt_run = datetime.fromtimestamp(os.path.getmtime(bt_path), timezone.utc).strftime("%-d %b %H:%M UTC")
    kinds = {"india": "prices (Yahoo, NSE bhavcopy), quotes, model_scores and ranges, agent_reasoning, features, regime, news with enrichment and verification status (news_verified), events, earnings_estimates (Yahoo), flows (NSE FII/DII), fpi (NSDL), indices (NSE), delivery (NSE)",
             "us": "prices (Yahoo), pre-market quotes, model_scores and ranges, agent_reasoning, features, regime, news with enrichment and verification status (news_verified), events (incl. SEC 8-K results days), earnings_estimates (Yahoo), FINRA short interest and short volume"}[market]

    return {
        "market": market, "market_name": cfg["name"], "exchange": EXCHANGE[market], "company": company, "sector": sector, "logo": ticker[:4],
        "currency": cur, "stake": STAKE, "n_tickers": len(cfg["tickers"]), "timezone": cfg["timezone"],
        "position_52w": pos52, "lo52": round(lo52, 2), "hi52": round(hi52, 2),
        "today": str(today), "run_at": run_at, "run_hm": hm(run_dt) if run_dt else None, "open_hm": hm(open_dt), "run_before_open": run_before_open,
        "review": review, "best_status": best_status, "status_counts": counts, "evidence_ok": evidence_ok,
        "next_earnings": next_earnings, "outcomes_n": outcomes_n, "verdict": verdict,
        "why": {"coin_flip": coin, "abstained": abstained, "skill": skill_true, "earnings_sentence": earnings_sentence,
                "forecaster_quote": forecaster_quote, "forecaster_time": reasoning["made_at"][11:16] if reasoning else None,
                "decision_1d": reasoning["decision_1d"] if reasoning else None, "decision_5d": reasoning["decision_5d"] if reasoning else None},
        "checks": checks, "plan": plan,
        "drivers": {"company": comp, "sector": sect, "market": mkt}, "nets": {"company": net(comp), "sector": net(sect), "market": net(mkt)},
        "drivers_note": note, "news_span": news_span, "bt_run": bt_run, "major_event_factor": load_ranges_config()["major_event_factor"],
        "regime_factor": load_ranges_config()["regime_factor"], "live_kinds": kinds,
        "bench_name": symbols[bench]["name"], "sector_index_name": symbols[sector_sym]["name"] if sector_sym else None, "sector_index": sector_sym,
        "replay_cmd": f"scripts/replay.py --market {market} --start {D['replay']['window'][0]} --end {D['replay']['window'][1]}",
    }


def status_of(con, ticker: str, news_id: str) -> str:
    rows = con.execute(f"select status from news_verified where ticker='{ticker}' and level='cluster' and id like '{ticker}-{news_id}|%'").fetchall()
    return rows[0][0] if rows else "not assessed"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--market", default=os.environ.get("MB_MARKET", "india"), choices=["india", "us"])
    ap.add_argument("--ticker", default=None, help="watchlist ticker (default HDFCBANK for india, AAPL for us)")
    ap.add_argument("--out", default=HERE, help="output folder (default: this folder)")
    a = ap.parse_args()
    ticker = a.ticker or {"india": "HDFCBANK", "us": "AAPL"}[a.market]
    cfg = load_market(a.market)
    if ticker not in cfg["tickers"]:
        raise SystemExit(f"{ticker} is not on the {a.market} watchlist: {', '.join(cfg['tickers'])}")
    os.makedirs(a.out, exist_ok=True)
    data = build(a.market, ticker)
    json.dump(data, open(os.path.join(a.out, f"data-{ticker}.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    company = data["page"]["company"]
    title = f"{company} decision"
    desc = (f"Buy today? One screen for {company} ({data['page']['exchange']}: {ticker}): the decision, the forecast against reality, "
            "what moves it and what comes next. Research only.")
    html = inline_system(tpl.replace("/*__DATA__*/null", payload).replace("__TITLE__", title).replace("__DESC__", desc))
    out = os.path.join(a.out, f"decision-{ticker}.html")
    open(out, "w").write(html)
    bs = data["band_summary"]
    print(f"{out}: bands1 {len(data['bands']['1'])} bands5 {len(data['bands']['5'])} news {len(data['news'])} earn moves {len(data['earn_moves'])} html bytes {len(html)}")
    print(json.dumps(bs))
    print("round trip", data["costs"]["round_trip"], "next sessions", data["next_sessions"], "window", data["replay"]["window"])


if __name__ == "__main__":
    main()
