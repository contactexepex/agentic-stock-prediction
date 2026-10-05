"""Presentation data: one JSON-ready "view" of a market's day, built only from stored data.

The processing data (append-only JSONL under data/, the context pack, summaries) is what the
next run reads; this module only reads it. charts.py draws the Slack PNGs from the view and
html_report.py embeds it in the HTML report, so both show the same numbers. Every number here
comes from DuckDB views (ranges_latest, features_latest, regime_latest, range_record,
track_record, news, company_events) or the events calendar, never from an agent.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import events as ev
from common import benchmark_key, vol_index_key
from score_predictions import is_late

CURRENCY = {"INR": "₹", "USD": "$"}
HISTORY_DAYS = 20        # trading days of closes shown before the forecast fan
MIN_SAMPLE = 10          # fewer scored ranges/calls than this: "not enough history yet"
NEWS_PER_COMPANY = 3
NEWS_LOOKBACK_DAYS = 4   # calendar days of news shown per company (published before the ranges were made)
MATERIALITY = {"high": 3, "medium": 2, "low": 1}
# market regime (regime.py) in plain words for a novice reader
REGIME_PLAIN = {
    "CALM": "Calm: prices have been moving little and fear (the volatility index) is low.",
    "TRENDING": "Trending: the market has been moving steadily in one direction.",
    "EVENT_HEAVY": "Event-heavy: a big scheduled event or raised fear can move prices more than usual.",
    "UNSTABLE": "Unstable: fear is high and prices swing a lot; ranges are wider and calls rarer.",
}
NEWS_ID = re.compile(r"\b(?:[0-9a-f]{16}|nse-ann-\d+|\d{10}-\d{2}-\d{6})\b")


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name)


def fmt_call(direction, confidence) -> str:
    if direction not in ("up", "down") or confidence is None or pd.isna(confidence):
        return "no call"
    return f"{'▲ up' if direction == 'up' else '▼ down'} {confidence:.0%}"


def money(cur: str, v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return f"{CURRENCY.get(cur, '')}{v:,.2f}"


def day_label(d) -> str:
    """'Mon 12 Oct' for a calendar date."""
    d = pd.Timestamp(d).date()
    return f"{d:%a} {d.day} {d:%b}"


def num(v, digits: int | None = None):
    """JSON-safe float (NaN/NA -> None)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    v = float(v)
    return round(v, digits) if digits is not None else v


def iso(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return pd.Timestamp(v).date().isoformat()


def _list(v) -> list:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return []
    return [x for x in list(v) if x is not None]


def record_text(n: int, hits: int, what: str) -> str:
    """Plain-language track record: a share once there is enough history, else a sample note."""
    if n == 0:
        return f"No {what} checked yet."
    if n < MIN_SAMPLE:
        return f"Not enough history yet: {hits} of {n} {what} were right so far."
    return f"Right {hits} of {n} times ({hits / n:.0%})."


def gather_view(cfg: dict, con, now: datetime | None = None) -> dict:
    q = lambda sql, p=None: con.execute(sql, p or []).df()  # noqa: E731
    cur = cfg.get("currency", "")
    ranges = q("SELECT * FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)")
    if ranges.empty:
        raise SystemExit("no published ranges; run ranges.py first")
    as_of = pd.Timestamp(ranges["as_of_date"].iloc[0]).date()
    session = pd.Timestamp(ranges["session_date"].iloc[0]).date()
    made_at = pd.to_datetime(ranges["made_at"], utc=True).max()

    regime = q("SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1")
    feats = q("SELECT * FROM features_latest WHERE as_of_date = ?", [as_of]).set_index("ticker")
    tickers = list(cfg["tickers"])
    hist = q(f"""SELECT ticker, date, close FROM (
                   SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY date DESC) AS k
                   FROM bars WHERE date <= ?) WHERE k <= {HISTORY_DAYS} ORDER BY ticker, date""", [as_of])
    rr = q("""SELECT ticker, horizon_days AS h, count(*) AS n, sum(hit80::INT) AS h80, sum(hit50::INT) AS h50
              FROM range_record GROUP BY ALL""")
    tr = q("SELECT ticker, count(*) AS n, sum(hit::INT) AS hits FROM track_record GROUP BY ALL")
    preds = q("SELECT DISTINCT ON (id) * FROM predictions WHERE as_of_date = ? ORDER BY id, made_at", [as_of]) \
        if _has_rows(con, "predictions") else pd.DataFrame()
    news = q("""SELECT n.id, n.title, n.url, n.source, coalesce(n.published_at, n.first_seen_at) AS ts, n.tickers,
                       e.materiality, e.relevance, e.summary
                FROM (SELECT DISTINCT ON (id) * FROM news ORDER BY id, first_seen_at) n
                LEFT JOIN enriched_latest e USING (id)""")
    filings = q("SELECT DISTINCT ON (id) id, ticker, form, url, accepted_at, description FROM filings ORDER BY id") \
        if _has_rows(con, "filings") else pd.DataFrame()
    anns = q("SELECT id, ticker, subject, url, published_at, source FROM announcements_latest") \
        if _has_rows(con, "announcements") else pd.DataFrame()
    cevents = q("SELECT date, type, ticker, name, amount FROM company_events WHERE date BETWEEN ? AND ? ORDER BY date",
                [as_of, as_of + timedelta(days=21)])

    # every source an agent may cite: news, SEC filings, NSE announcements -> headline + link
    sources: dict[str, dict] = {}
    for x in news.itertuples():
        sources[x.id] = {"title": x.title, "url": x.url, "source": x.source, "ts": _ts(x.ts)}
    for x in filings.itertuples():
        sources[x.id] = {"title": f"{x.ticker} {x.form} filing", "url": x.url, "source": "SEC EDGAR", "ts": _ts(x.accepted_at)}
    for x in anns.itertuples():
        sources[x.id] = {"title": f"{x.ticker}: {x.subject}", "url": x.url, "source": x.source or "NSE",
                         "ts": _ts(x.published_at)}

    mevents = ev.market_events(cfg, as_of + timedelta(days=1), as_of + timedelta(days=21))
    by = {(r.ticker, int(r.horizon_days)): r for r in ranges.itertuples()}
    pred_by = {(p.ticker, int(p.horizon_days)): p for p in preds.itertuples()} if len(preds) else {}
    window_start = (made_at - pd.Timedelta(days=NEWS_LOOKBACK_DAYS)) if not pd.isna(made_at) else None

    companies, sector_rows = [], []
    sectors = cfg.get("sectors") or {"": tickers}
    for sector, members in sectors.items():
        moves = []
        for t in members:
            meta = cfg["tickers"].get(t, {})
            f = feats.loc[t] if t in feats.index else None
            h = hist[hist["ticker"] == t]
            ret1 = num(f["ret_1d"]) if f is not None else None
            if ret1 is not None:
                moves.append((t, ret1))
            rows = []
            for hz in (1, 5):
                r = by.get((t, hz))
                if r is None:
                    continue
                late = is_late(cfg, getattr(r, "as_of_date", None), getattr(r, "made_at", None))
                rows.append({
                    "h": hz, "target_date": iso(r.target_date), "target_label": day_label(r.target_date),
                    "base_close": num(r.base_close), "center_price": num(r.base_close * math.exp(r.center)),
                    "lo50": num(r.lo50), "hi50": num(r.hi50), "lo80": num(r.lo80), "hi80": num(r.hi80),
                    "direction": r.direction if r.direction in ("up", "down") else None,
                    "confidence": num(r.confidence) if r.direction in ("up", "down") else None,
                    "late": bool(late), "notes": _list(r.notes),
                })
            calls = []
            for x in rows:
                if x["direction"] and not x["late"]:
                    p = pred_by.get((t, x["h"]))
                    ids = _list(p.evidence_ids) if p is not None else []
                    calls.append({"h": x["h"], "direction": x["direction"], "confidence": x["confidence"],
                                  "target_label": x["target_label"],
                                  "rationale": (p.rationale if p is not None else None),
                                  "evidence": [{"id": i, **sources[i]} if i in sources else {"id": i} for i in ids]})
            cited = {e["id"] for c in calls for e in c["evidence"]}
            items = []
            for x in news.itertuples():
                tick = _list(x.tickers)
                if t not in tick:
                    continue
                ts = pd.Timestamp(x.ts) if x.ts is not None and not pd.isna(x.ts) else None
                if ts is None or (window_start is not None and not (window_start <= ts <= made_at)):
                    continue
                items.append({"id": x.id, "title": x.title, "url": x.url, "source": x.source, "ts": _ts(ts),
                              "cited": x.id in cited, "rank": (x.id in cited, MATERIALITY.get(x.materiality or "", 0),
                                                               num(x.relevance) or 0.0, ts.isoformat())})
            items.sort(key=lambda i: i["rank"], reverse=True)
            seen, unique = set(), []
            for i in items:  # the same story from two feeds is shown once
                i.pop("rank")
                key = re.sub(r"\W+", " ", (i["title"] or "").lower()).strip()
                if key not in seen:
                    seen.add(key)
                    unique.append(i)
            items = unique
            evs = []
            for e in cevents[cevents["ticker"] == t].itertuples():
                d = pd.Timestamp(e.date).date()
                label = e.name
                if e.type == "ex_dividend" and e.amount is not None and not pd.isna(e.amount):
                    label = f"{e.name} ({money(cur, e.amount)} per share)"
                evs.append({"date": d.isoformat(), "label": label, "type": e.type, "day": day_label(d)})
            last_target = max((pd.Timestamp(x["target_date"]).date() for x in rows), default=as_of)
            for e in mevents:
                if e["date"] <= last_target:
                    evs.append({"date": e["date"].isoformat(), "label": e["name"], "type": e["type"],
                                "day": day_label(e["date"]), "market": True})
            evs.sort(key=lambda e: e["date"])
            rec_r = {}
            for x in rr[rr["ticker"] == t].itertuples():
                rec_r[int(x.h)] = {"n": int(x.n), "hit80": int(x.h80), "hit50": int(x.h50),
                                   "text": record_text(int(x.n), int(x.h80), "80% ranges")}
            trow = tr[tr["ticker"] == t]
            nc, hc = (int(trow["n"].iloc[0]), int(trow["hits"].iloc[0])) if len(trow) else (0, 0)
            companies.append({
                "ticker": t, "name": meta.get("name", t), "sector": sector,
                "close": num(f["close"]) if f is not None else (num(h["close"].iloc[-1]) if len(h) else None),
                "ret_1d": ret1, "quality": (f["quality"] if f is not None else "no data"),
                "days_to_earnings": (int(f["days_to_earnings"]) if f is not None and not pd.isna(f["days_to_earnings"]) else None),
                "history": [{"d": iso(x.date), "c": num(x.close, 4)} for x in h.itertuples()],
                "ranges": rows, "calls": calls, "events": evs,
                "news": items[:NEWS_PER_COMPANY],
                "record": {"ranges": rec_r, "calls": {"n": nc, "hits": hc, "text": record_text(nc, hc, "up/down calls")}},
            })
        sector_rows.append({"sector": sector, "tickers": members,
                            "move_1d": (sum(m for _, m in moves) / len(moves)) if moves else None,
                            "moves": [{"ticker": a, "ret_1d": b} for a, b in moves]})

    reg = regime.iloc[0] if not regime.empty else None
    vol_name = cfg["symbols"].get(vol_index_key(cfg) or "", {}).get("name", "volatility index")
    bench = cfg["symbols"].get(benchmark_key(cfg) or "", {}).get("name", "benchmark")
    regime_view = None
    if reg is not None:
        regime_view = {
            "code": reg["regime"], "plain": REGIME_PLAIN.get(reg["regime"], reg["regime"]),
            "stress": bool(reg["stress"]), "vol_name": vol_name, "vol_level": num(reg["vol_level"], 2),
            "vol_change_1d": num(reg["vol_change_1d"]), "bench_name": bench, "bench_ret_5d": num(reg["bench_ret_5d"]),
            "major_events": _list(reg["major_event_names"]), "notes": _list(reg["notes"]),
        }

    # track record, market-wide: stated vs actual hit rate (ranges by band, calls by confidence)
    cal = q("""SELECT horizon_days AS h, count(*) AS n, avg(hit50::INT) AS c50, avg(hit80::INT) AS c80
               FROM range_record GROUP BY ALL ORDER BY h""")
    bands = q("""SELECT CASE WHEN confidence < 0.6 THEN '50-59%' WHEN confidence < 0.7 THEN '60-69%'
                             WHEN confidence < 0.8 THEN '70-79%' ELSE '80-90%' END AS band,
                        count(*) AS n, avg(confidence) AS conf, avg(hit::INT) AS hit
                 FROM track_record GROUP BY band ORDER BY band""")
    points = []
    for x in cal.itertuples():
        for stated, actual in ((0.5, x.c50), (0.8, x.c80)):
            points.append({"kind": "range", "label": f"{int(stated * 100)}% ranges, {int(x.h)}-day",
                           "stated": stated, "actual": num(actual), "n": int(x.n)})
    for x in bands.itertuples():
        points.append({"kind": "call", "label": f"Calls at {x.band} confidence", "stated": num(x.conf),
                       "actual": num(x.hit), "n": int(x.n)})

    n_calls = sum(len(c["calls"]) for c in companies)
    late = sum(1 for c in companies for r in c["ranges"] if r["late"])
    partial = sorted(feats.index[feats["quality"] == "PARTIAL"]) if len(feats) else []
    blocked = sorted(feats.index[feats["quality"] == "BLOCKED"]) if len(feats) else []
    upcoming = [{"date": e["date"].isoformat(), "day": day_label(e["date"]), "label": e["name"],
                 "major": bool(e["major"])} for e in mevents]
    upcoming += [{"date": pd.Timestamp(x.date).date().isoformat(), "day": day_label(x.date), "label": x.name,
                  "major": False} for x in cevents.itertuples()]
    upcoming.sort(key=lambda e: e["date"])
    return {
        "market": cfg["market"], "name": cfg["name"], "currency": cur, "symbol": CURRENCY.get(cur, ""),
        "session": session.isoformat(), "session_label": day_label(session), "as_of": as_of.isoformat(),
        "as_of_label": day_label(as_of), "made_at": made_at.isoformat() if not pd.isna(made_at) else None,
        "generated_at": (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(),
        "regime": regime_view, "sectors": sector_rows, "companies": companies,
        "calibration": points, "min_sample": MIN_SAMPLE,
        "counts": {"calls": n_calls, "companies": len(companies),
                   "with_ranges": sum(1 for c in companies if c["ranges"]), "late_ranges": late,
                   "scored_ranges": int(cal["n"].sum()) if len(cal) else 0,
                   "scored_calls": int(bands["n"].sum()) if len(bands) else 0},
        "quality": {"partial": partial, "blocked": blocked, "regime_notes": regime_view["notes"] if regime_view else []},
        "upcoming": upcoming, "sources": sources,
    }


def _ts(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return pd.Timestamp(v).isoformat()


def _has_rows(con, view: str) -> bool:
    try:
        return con.execute(f"SELECT count(*) FROM {view}").fetchone()[0] > 0
    except Exception:  # view absent when the market has no such files yet
        return False


def primary_horizon(view: dict) -> int:
    """The horizon the overview shows: next day when non-late 1-day ranges exist, else 5 days."""
    ok1 = any(r["h"] == 1 and not r["late"] for c in view["companies"] for r in c["ranges"])
    return 1 if ok1 else 5
