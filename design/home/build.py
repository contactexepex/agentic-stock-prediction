"""Assemble the data for the Home (Today) screen, both markets, and inline it into template.html.

    python design/home/build.py --out design/home

writes <out>/home.html and <out>/data-home.json. Reuses the watchlist builder (design/watchlist/build.py) for
each market's rows and header, then adds what the morning screen needs: yesterday's biggest movers with a
deterministic cause (market-wide / company news / stock-specific), the news card (the last 24 hours of the
archive: market-wide stories grouped by the news-analyst's summary, the company stories that can carry a call,
and what was set aside and why), the next seven days of events with the eight weeks behind them (market calendar
plus watchlist results and ex-dividend dates), pipeline status (what the latest run stored) and a track-record
snapshot (live calls scored, the rule replay's coverage, the weekly review's skill verdict). Read-only on the repo."""
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
NEWS_HOURS = 24      # the news card covers the last 24 hours of the stored archive
CAN_CARRY = ("confirmed_primary", "corroborated")   # the only statuses that may be a call's main evidence (DESIGN.md 3b)
MAT_RANK = {"high": 3, "medium": 2, "low": 1}


def lst(v):
    return [str(x) for x in (v if v is not None else [])]


def news_card(q, cfg: dict) -> dict:
    """The last NEWS_HOURS hours of the stored archive, in three parts: market-wide stories (macro items with no
    company tag, medium or high materiality, grouped by the news-analyst's summary, which is identical across the
    copies of one story), the company stories whose newest verification row marks them fit to carry a call, and the
    stories set aside with their status. Nothing is fetched; everything comes from news, enriched_latest,
    news_clusters_latest and news_verified."""
    newest = q("select max(published_at) t from news").iloc[0, 0]
    newest = newest.to_pydatetime() if hasattr(newest, "to_pydatetime") else newest
    since = newest - timedelta(hours=NEWS_HOURS)
    since_sql = since.isoformat()
    names = {t: cfg["tickers"][t]["name"] for t in cfg["tickers"]}
    # market-wide
    mw = q(f"""select n.id, n.title, n.url, n.source, n.published_at, e.materiality, e.sentiment, e.summary
               from news n join enriched_latest e using(id)
               where len(n.tickers) = 0 and e.event_type = 'macro' and e.materiality in ('medium', 'high') and n.published_at >= '{since_sql}'
               order by n.published_at desc, n.id""").to_dict("records")
    groups: dict[str, dict] = {}
    for r in mw:
        key = (r["summary"] or r["title"]).strip()
        g = groups.setdefault(key, {"headline": r["title"], "url": r["url"], "source": r["source"], "latest": r["published_at"].isoformat(), "outlets": set(), "n": 0,
                                    "sentiments": [], "materiality": "medium", "summary": r["summary"]})
        g["n"] += 1
        g["outlets"].add(r["source"])
        if r["sentiment"] is not None:
            g["sentiments"].append(float(r["sentiment"]))
        if MAT_RANK.get(r["materiality"], 0) > MAT_RANK[g["materiality"]]:
            g["materiality"] = r["materiality"]
    market_wide = []
    for g in groups.values():
        market_wide.append({"headline": g["headline"], "url": g["url"], "source": g["source"], "latest": g["latest"], "outlets": len(g["outlets"]), "n": g["n"],
                            "sentiment": round(sum(g["sentiments"]) / len(g["sentiments"]), 2) if g["sentiments"] else None, "materiality": g["materiality"],
                            "summary": g["summary"] if g["summary"] and not g["summary"].startswith("Macro") else None})
    market_wide.sort(key=lambda g: (-MAT_RANK[g["materiality"]], -g["outlets"], -g["n"]))
    n_macro = int(q(f"select count(*) from news n join enriched_latest e using(id) where len(n.tickers) = 0 and e.event_type = 'macro' and n.published_at >= '{since_sql}'").iloc[0, 0])
    # company stories of the window, each with its newest verification row (a pass covers the clusters of its run)
    clusters = q(f"""select c.cluster_id, c.ticker, c.news_ids, c.n_items, c.outlets, c.independent_origins, c.primary_ids, c.first_reported_at, c.last_reported_at, v.status
                     from news_clusters_latest c
                     left join (select cluster_id, status from news_verified where level = 'cluster' qualify row_number() over (partition by cluster_id order by as_of desc) = 1) v using(cluster_id)
                     where c.last_reported_at >= '{since_sql}' order by c.last_reported_at desc, c.cluster_id""").to_dict("records")
    ids = sorted({i for c in clusters for i in lst(c["news_ids"])})
    items = {}
    if ids:
        items = {r["id"]: r for r in q(f"""select n.id, n.title, n.url, n.source, n.published_at, e.materiality, e.sentiment, e.event_type
                                           from news n left join enriched_latest e using(id) where n.id in ({','.join(repr(i) for i in ids)})""").to_dict("records")}
    stories = []
    for c in clusters:
        if c["ticker"] not in names:
            continue
        its = [items[i] for i in lst(c["news_ids"]) if i in items]
        if not its:
            continue
        its.sort(key=lambda r: (MAT_RANK.get(r["materiality"], 0), r["published_at"]), reverse=True)
        lead = its[0]
        status = c["status"] if isinstance(c["status"], str) else "not assessed"
        stories.append({"cluster_id": c["cluster_id"], "ticker": c["ticker"], "name": names[c["ticker"]], "headline": lead["title"], "url": lead["url"], "source": lead["source"],
                        "status": status, "materiality": max((r["materiality"] for r in its if r["materiality"]), key=lambda m: MAT_RANK.get(m, 0), default=None),
                        "event_type": lead["event_type"], "sentiment": None if lead["sentiment"] is None else float(lead["sentiment"]), "n": int(c["n_items"]),
                        "outlets": len(lst(c["outlets"])), "independent": int(c["independent_origins"] or 0), "filings": len(lst(c["primary_ids"])),
                        "last": c["last_reported_at"].isoformat()})
    can_carry = [s for s in stories if s["status"] in CAN_CARRY]
    set_aside = [s for s in stories if s["status"] not in CAN_CARRY]
    order = {"high": 0, "medium": 1, "low": 2, None: 3}
    can_carry.sort(key=lambda s: (order.get(s["materiality"], 3), s["last"]), reverse=False)
    set_aside.sort(key=lambda s: (order.get(s["materiality"], 3), -s["n"]))
    counts: dict[str, int] = {}
    for s in set_aside:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    n_company = int(q(f"select count(*) from news where len(tickers) > 0 and published_at >= '{since_sql}'").iloc[0, 0])
    return {"since": since.isoformat(), "until": newest.isoformat(), "hours": NEWS_HOURS, "market_wide": market_wide[:6], "market_wide_groups": len(market_wide), "macro_headlines": n_macro,
            "company_headlines": n_company, "can_carry": can_carry, "set_aside": set_aside, "set_aside_counts": counts}


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
    # events: the next 8 weeks (the first 7 days shown, the rest behind a click), market calendar plus watchlist results and ex-dividend dates
    week_end, window_end = today + timedelta(days=7), today + timedelta(days=56)
    events = [{"date": str(e["date"]), "type": e["type"], "name": e["name"], "major": bool(e["major"]), "ticker": None} for e in market_events(cfg, today, window_end)]
    earn = q(f"select ticker, date, type, timing from events where type in ('earnings', 'ex_dividend') and date >= '{today}' and date <= '{window_end}' order by date, ticker").to_dict("records")
    for e in earn:
        if e["ticker"] in cfg["tickers"]:
            d = date.fromisoformat(str(e["date"])[:10])
            timing = e["timing"] if isinstance(e["timing"], str) else None
            reaction = next_session(cfg, d + timedelta(days=1)) if timing == "after_close" else next_session(cfg, d)
            events.append({"date": str(d), "type": e["type"], "name": f"{cfg['tickers'][e['ticker']]['name']} {'results' if e['type'] == 'earnings' else 'ex-dividend'}",
                           "major": e["type"] == "earnings", "ticker": e["ticker"], "timing": timing, "reaction_session": str(reaction)})
    events.sort(key=lambda e: (e["date"], e["type"] != "earnings", e["name"]))
    for e in events:
        e["this_week"] = date.fromisoformat(e["date"]) <= week_end
    news = news_card(q, cfg)
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
            "movers": movers, "events": events, "news": news, "status": status, "replay_overall": overall}


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
        print(f"{m}: as of {b['as_of']} yes {b['header']['yes']} candidates {b['header']['candidates']} movers up {[x['ticker'] for x in b['movers']['up']]} down {[x['ticker'] for x in b['movers']['down']]} events {len(b['events'])} "
              f"news: market-wide {len(b['news']['market_wide'])} of {b['news']['market_wide_groups']} groups, can carry {len(b['news']['can_carry'])}, set aside {b['news']['set_aside_counts']}")
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
