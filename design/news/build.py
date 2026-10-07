"""Assemble the data for the News and events screen (both markets) and inline it into template.html.

    python design/news/build.py --out design/news

writes <out>/news.html and <out>/data-news.json: per market the stories (news clusters per company with their
verification status, items, outlets, independent origins, primary sources and the claims the claim-checker
extracted), every stored headline with its enrichment and status, the counts behind the filters, and the
next eight weeks of events (market calendar plus the watchlist's results and ex-dividend dates). Read-only."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "design", "system"))
from marketbrief.core.calendar import market_events, next_session  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from system import inline_system  # noqa: E402

spec = importlib.util.spec_from_file_location("decision_build", os.path.join(REPO, "design", "decision", "build.py"))
decision_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decision_build)
STATUS_ORDER = ["confirmed_primary", "corroborated", "single_source", "unverified", "rumour", "promotional", "contradicted"]
MAT = {"high": 3, "medium": 2, "low": 1}


def lst(v):
    return [] if v is None else [str(x) for x in (v.tolist() if hasattr(v, "tolist") else v)]


def market_block(market: str) -> dict:
    con = connect(market)
    cfg = load_market(market)

    def q(sql):
        return con.execute(sql).df()

    tickers = list(cfg["tickers"])
    names = {t: cfg["tickers"][t]["name"] for t in tickers}
    end = date.fromisoformat(str(q(f"select max(date) d from ohlc where ticker in ({','.join(repr(t) for t in tickers)})").iloc[0, 0])[:10])
    today = next_session(cfg, end + timedelta(days=1))

    # ---- headlines with enrichment
    news = q("""select n.id, n.title, n.url, n.source, n.source_domain, n.published_at, n.tickers, n.primary_tickers, n.feed,
                e.sentiment, e.materiality, e.event_type, e.priced_in, e.summary, e.relevance
                from news n left join enriched_latest e using(id) order by n.published_at desc""").to_dict("records")
    verified = q("select cluster_id, ticker, status, status_ids, independent_origins, unread_vetted_origins, origins, primary_ids, flags, first_reported_at, confirmed_at from news_verified where level='cluster' and as_of=(select max(as_of) from news_verified)").to_dict("records")
    status_by_cluster = {v["cluster_id"]: v for v in verified}
    status_by_news = {}
    for v in verified:
        for nid in lst(v["status_ids"]):
            prev = status_by_news.get(nid)
            if prev is None or STATUS_ORDER.index(v["status"]) < STATUS_ORDER.index(prev):
                status_by_news[nid] = v["status"]
    headlines = []
    for n in news:
        tk = [t for t in lst(n["tickers"]) if t in names]
        headlines.append({"id": n["id"], "title": n["title"], "url": n["url"], "source": n["source"], "domain": n["source_domain"], "at": str(n["published_at"])[:16],
                          "tickers": tk, "sentiment": None if n["sentiment"] is None or pd.isna(n["sentiment"]) else round(float(n["sentiment"]), 2),
                          "materiality": n["materiality"], "event_type": n["event_type"], "priced_in": bool(n["priced_in"]) if n["priced_in"] is not None and not pd.isna(n["priced_in"]) else None,
                          "summary": (n["summary"][:200] if isinstance(n["summary"], str) and n["materiality"] in ("high", "medium") else None),
                          "status": status_by_news.get(n["id"], "not assessed")})
    by_id = {h["id"]: h for h in headlines}
    # the page embeds the newest 800 headlines plus every high-materiality one (the full archive stays in data/)
    keep = set(h["id"] for h in headlines[:800]) | set(h["id"] for h in headlines if h["materiality"] == "high")
    headlines_page = [dict(h, summary=None) for h in headlines if h["id"] in keep]

    # ---- stories: clusters with their status, items and claims
    clusters = q("select * from news_clusters_latest order by n_items desc").to_dict("records")
    claims = q("select cluster_id, ticker, claim_type, subject, predicate, stance, value_text, value_num, unit, period, quote, quote_field, source_kind, attribution, news_ids, source_published_at from news_claims order by extracted_at").to_dict("records")
    claims_by = {}
    for c in claims:
        claims_by.setdefault(c["cluster_id"], []).append({"type": c["claim_type"], "subject": c["subject"], "predicate": c["predicate"], "stance": c["stance"], "value": c["value_text"],
                                                           "quote": c["quote"], "quote_field": c["quote_field"], "source_kind": c["source_kind"], "attribution": c["attribution"],
                                                           "at": str(c["source_published_at"])[:16]})
    stories = []
    for c in clusters:
        v = status_by_cluster.get(c["cluster_id"], {})
        ids = lst(c["news_ids"])
        items = [by_id[i] for i in ids if i in by_id]
        items.sort(key=lambda h: (-MAT.get(h["materiality"], 0), h["at"]), reverse=False)
        items.sort(key=lambda h: -MAT.get(h["materiality"], 0))
        lead = items[0] if items else None
        if not lead:
            continue
        sents = [h["sentiment"] for h in items if h["sentiment"] is not None]
        stories.append({"cluster_id": c["cluster_id"], "ticker": c["ticker"], "name": names.get(c["ticker"], c["ticker"]), "status": v.get("status", "not assessed"),
                        "lead": {"id": lead["id"], "title": lead["title"], "url": lead["url"], "source": lead["source"], "at": lead["at"]},
                        "items": [{"id": h["id"], "title": h["title"], "source": h["source"], "at": h["at"], "materiality": h["materiality"], "url": h["url"]} for h in items[:6]],
                        "n_items": int(c["n_items"]), "n_duplicates": len(lst(c["duplicate_ids"])), "outlets": lst(c["outlets"]), "tiers": lst(c["tiers"]),
                        "independent_origins": int(c["independent_origins"]), "unread_vetted_origins": int(c["unread_vetted_origins"]), "origins": lst(c["origins"]),
                        "primary_ids": lst(c["primary_ids"]), "flags": lst(c["flags"]), "first": str(c["first_reported_at"])[:16], "last": str(c["last_reported_at"])[:16],
                        "materiality": max((h["materiality"] for h in items if h["materiality"]), key=lambda m: MAT.get(m, 0), default=None),
                        "sentiment": round(sum(sents) / len(sents), 2) if sents else None, "event_type": lead["event_type"],
                        "claims": claims_by.get(c["cluster_id"], []), "confirmed_at": None if v.get("confirmed_at") is None or pd.isna(v.get("confirmed_at")) else str(v["confirmed_at"])[:16]})
    stories.sort(key=lambda s: (-MAT.get(s["materiality"], 0), STATUS_ORDER.index(s["status"]) if s["status"] in STATUS_ORDER else 9, -s["n_items"]))

    # ---- counts
    status_counts = {}
    for s in stories:
        status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1
    mat_counts = {}
    for h in headlines:
        mat_counts[h["materiality"] or "not scored"] = mat_counts.get(h["materiality"] or "not scored", 0) + 1
    sources = q("select source, count(*) n from news group by 1 order by 2 desc limit 10").to_dict("records")
    access = {r["access"]: int(r["n"]) for r in q("select access, count(*) n from news_articles group by 1").to_dict("records")}
    span = q("select min(published_at) a, max(published_at) b from news").to_dict("records")[0]
    per_ticker = {}
    for h in headlines:
        for t in h["tickers"]:
            per_ticker[t] = per_ticker.get(t, 0) + 1

    # ---- events: next 8 weeks
    window_end = today + timedelta(days=56)
    events = [{"date": str(e["date"]), "type": e["type"], "name": e["name"], "major": bool(e["major"]), "ticker": None} for e in market_events(cfg, today, window_end)]
    rows = q(f"select ticker, date, type, timing, name from events where date >= '{today}' and date <= '{window_end}' and type in ('earnings', 'ex_dividend') order by date, ticker").to_dict("records")
    for e in rows:
        if e["ticker"] not in names:
            continue
        d = date.fromisoformat(str(e["date"])[:10])
        timing = e["timing"] if isinstance(e["timing"], str) else None
        reaction = next_session(cfg, d + timedelta(days=1)) if timing == "after_close" else next_session(cfg, d)
        events.append({"date": str(d), "type": e["type"], "name": f"{names[e['ticker']]} {'results' if e['type'] == 'earnings' else 'ex-dividend'}", "major": e["type"] == "earnings",
                       "ticker": e["ticker"], "timing": timing, "reaction_session": str(reaction)})
    events.sort(key=lambda e: (e["date"], e["type"] != "earnings", e["name"]))
    return {"market": market, "market_name": cfg["name"], "exchange": decision_build.EXCHANGE[market], "tickers": tickers, "names": names, "as_of": str(end), "today": str(today),
            "span": [str(span["a"])[:16], str(span["b"])[:16]], "n_headlines": len(headlines), "n_stories": len(stories), "status_counts": status_counts, "mat_counts": mat_counts,
            "n_claims": len(claims), "sources": sources, "access": access, "per_ticker": per_ticker,
            "stories": stories, "headlines": headlines_page, "n_embedded": len(headlines_page), "events": events, "events_until": str(window_end)}


def build() -> dict:
    return decision_build.clean({"built_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "status_order": STATUS_ORDER, "markets": {m: market_block(m) for m in ("india", "us")}})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    data = build()
    json.dump(data, open(os.path.join(a.out, "data-news.json"), "w"), indent=1, default=str)
    tpl = open(os.path.join(HERE, "template.html")).read()
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    html = inline_system(tpl.replace("/*__DATA__*/null", payload))
    out = os.path.join(a.out, "news.html")
    open(out, "w").write(html)
    for m, b in data["markets"].items():
        print(f"{m}: headlines {b['n_headlines']} (embedded {b['n_embedded']}) stories {b['n_stories']} statuses {b['status_counts']} claims {b['n_claims']} events {len(b['events'])}")
    print(out, len(html), "bytes")


if __name__ == "__main__":
    main()
