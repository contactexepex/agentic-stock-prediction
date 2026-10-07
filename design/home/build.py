"""Assemble the data for the Home (Today) screen, both markets, and inline it into template.html.

    python design/home/build.py --out design/home

writes <out>/home.html and <out>/data-home.json. Reuses the watchlist builder (design/watchlist/build.py) for
each market's rows and header, then adds what the morning screen needs: yesterday's biggest movers with a
deterministic cause (market-wide / company news / stock-specific), the next seven days of events (market
calendar plus watchlist results dates), pipeline status (what the latest run stored) and a track-record snapshot
(live calls scored, the rule replay's coverage, the weekly review's skill verdict). Read-only on the repo."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from marketbrief.core.calendar import market_events, next_session, session_open_utc  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from system import inline_system  # noqa: E402

spec = importlib.util.spec_from_file_location("watchlist_build", os.path.join(REPO, "design", "watchlist", "build.py"))
watchlist_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchlist_build)
MARKET_WIDE = 0.75   # % benchmark / sector move, same sign, that counts as market-wide (as on the decision page)


def market_block(market: str) -> dict:
    wl = watchlist_build.build(market)
    cfg = load_market(market)
    con = connect(market)

    def q(sql):
        return con.execute(sql).df()

    end = date.fromisoformat(wl["as_of"])
    today = date.fromisoformat(wl["today"])
    rows = {r["ticker"]: r for r in wl["rows"]}
    sector_move = {s["name"]: (s["index"]["move"] if s["index"] else None) for s in wl["sectors"]}
    sector_name = {s["name"]: (s["index"]["name"] if s["index"] else None) for s in wl["sectors"]}
    bench_move = wl["header"]["bench_move"]
    # high-materiality headlines on the last session's local day, per ticker
    hi = q(f"""select t.ticker, count(*) n, sum(case when e.materiality='high' then 1 else 0 end) high
               from (select unnest(tickers) ticker, id, published_at from news) t left join enriched_latest e using(id)
               where cast(timezone('{cfg["timezone"]}', t.published_at) as date) = '{end}' group by 1""").to_dict("records")
    news_day = {r["ticker"]: {"n": int(r["n"]), "high": int(r["high"] or 0)} for r in hi}

    def cause(t: str, mv: float) -> dict:
        sm = sector_move.get(rows[t]["sector"])
        same = lambda x: x is not None and (x > 0) == (mv > 0)  # noqa: E731
        if (sm is not None and abs(sm) >= MARKET_WIDE and same(sm)) or (bench_move is not None and abs(bench_move) >= MARKET_WIDE and same(bench_move)):
            parts = [f"{wl['header']['bench_name']} {bench_move:+.1f}%"] + ([f"{sector_name[rows[t]['sector']]} {sm:+.1f}%"] if sm is not None else [])
            return {"kind": "market", "label": "Market-wide: " + ", ".join(parts), "source": "derived"}
        nd = news_day.get(t)
        if nd and nd["high"] > 0:
            return {"kind": "company", "label": f"Company news: {nd['n']} stored items, {nd['high']} high materiality", "source": "live"}
        if sm is not None and abs(sm) >= MARKET_WIDE and not same(sm):
            return {"kind": "unexplained", "label": f"Stock-specific: moved against {sector_name[rows[t]['sector']]} ({sm:+.1f}%); no stored high-materiality news", "source": "mock"}
        return {"kind": "unexplained", "label": "Stock-specific; no stored high-materiality news for the day", "source": "mock"}

    moved = sorted((r for r in wl["rows"] if r["move"] is not None), key=lambda r: r["move"])
    movers = {"up": [dict(ticker=r["ticker"], name=r["name"], move=r["move"], close=r["close"], cause=cause(r["ticker"], r["move"])) for r in reversed(moved[-3:]) if r["move"] > 0],
              "down": [dict(ticker=r["ticker"], name=r["name"], move=r["move"], close=r["close"], cause=cause(r["ticker"], r["move"])) for r in moved[:3] if r["move"] < 0]}
    # events: next 7 days, market calendar plus watchlist results
    window_end = today + timedelta(days=7)
    events = [{"date": str(e["date"]), "type": e["type"], "name": e["name"], "major": e["major"], "ticker": None} for e in market_events(cfg, today, window_end)]
    earn = q(f"select ticker, date, timing from events where type='earnings' and date >= '{today}' and date <= '{window_end}' order by date, ticker").to_dict("records")
    for e in earn:
        if e["ticker"] in cfg["tickers"]:
            d = date.fromisoformat(str(e["date"])[:10])
            timing = e["timing"] if isinstance(e["timing"], str) else None
            reaction = next_session(cfg, d + timedelta(days=1)) if timing == "after_close" else next_session(cfg, d)
            events.append({"date": str(d), "type": "earnings", "name": f"{cfg['tickers'][e['ticker']]['name']} results", "major": True, "ticker": e["ticker"],
                           "timing": timing, "reaction_session": str(reaction)})
    events.sort(key=lambda e: (e["date"], e["type"] != "earnings", e["name"]))
    # pipeline status: what the latest run stored
    latest_scores = q("select max(as_of_date) d, max(computed_at) t, count(*) n from model_scores_latest").to_dict("records")[0]
    ranges_today = q(f"select horizon_days, count(*) n from ranges where as_of_date = '{end}' group by 1").to_dict("records")
    n_news_today = int(q(f"select count(*) from news where cast(published_at as date) >= '{end}'").iloc[0, 0])
    n_verified = int(q("select count(distinct cluster_id) from news_verified where level='cluster' and as_of = (select max(as_of) from news_verified)").iloc[0, 0])
    n_reasoning = int(q(f"select count(*) from agent_reasoning where as_of_date = '{end}'").iloc[0, 0])
    n_prices = int(q(f"select count(*) from ohlc where date = '{end}' and ticker in ({','.join(repr(t) for t in cfg['tickers'])})").iloc[0, 0])
    lessons = int(q("select count(*) from lessons").iloc[0, 0])
    replay = watchlist_build.replay_summary_json(market, date.fromisoformat(wl["window"][0]), end)
    overall = {h: replay["horizons"][h]["overall"] for h in ("1", "5")}
    h = wl["header"]
    status = {"as_of": wl["as_of"], "today": wl["today"], "session": h["session"], "run_at": h["run_at"], "run_before_open": None,
              "prices_stored": n_prices, "scores_stored": int(latest_scores["n"]), "ranges_1d": next((int(r["n"]) for r in ranges_today if r["horizon_days"] == 1), 0),
              "ranges_5d": next((int(r["n"]) for r in ranges_today if r["horizon_days"] == 5), 0), "reasoning_stored": n_reasoning,
              "news_since_asof": n_news_today, "clusters_verified": n_verified, "lessons": lessons}
    if h["run_at"]:   # against the open of the session the run predicts (the one after the as-of date), not tomorrow's
        status["run_before_open"] = datetime.fromisoformat(h["run_at"]) < session_open_utc(cfg, today)
        status["open_utc"] = session_open_utc(cfg, today).isoformat()
    return {"market": market, "market_name": wl["market_name"], "exchange": wl["exchange"], "currency": wl["currency"], "as_of": wl["as_of"], "today": wl["today"],
            "window": wl["window"], "call_threshold": wl["call_threshold"], "header": h, "sectors": wl["sectors"], "rows": wl["rows"],
            "movers": movers, "events": events, "status": status, "replay_overall": overall}


def build() -> dict:
    markets = {m: market_block(m) for m in ("india", "us")}
    return watchlist_build.clean({"built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "markets": markets})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = build()
    json.dump(data, open(os.path.join(a.out, "data-home.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    html = inline_system(tpl.replace("/*__DATA__*/null", payload))
    out = os.path.join(a.out, "home.html")
    open(out, "w").write(html)
    for m, b in data["markets"].items():
        print(f"{m}: as of {b['as_of']} yes {b['header']['yes']} candidates {b['header']['candidates']} movers up {[x['ticker'] for x in b['movers']['up']]} down {[x['ticker'] for x in b['movers']['down']]} events {len(b['events'])}")
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
