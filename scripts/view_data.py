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
from datetime import datetime, timedelta, timezone

import pandas as pd

from marketbrief.core import calendar as ev
from marketbrief.analytics import call_basis, scoring
from marketbrief.constants.horizon_names import BASIS_KEY_SQL, LABEL_ORDER_SQL, NAME_LEGACY_RECORD
from marketbrief.constants.model import LABEL_CLOSE_TO_CLOSE
from marketbrief.constants.scoring import MSG_SCORED_ON
from marketbrief.core.horizons import horizon_key
from marketbrief.core.market_config import benchmark_key, vol_index_key
from marketbrief.constants.formatting import CURRENCY_SYMBOLS
from marketbrief.constants.messages import MSG_NO_PUBLISHED_RANGES
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.presentation.horizon_names import horizon_name, primary_horizon, range_texts
from marketbrief.utils.money import format_money
from marketbrief.utils.numbers import json_safe_float
from marketbrief.pipeline.score_predictions import is_late

CURRENCY = CURRENCY_SYMBOLS
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


SAFE_URL = re.compile(r"^https?://\S+$", re.I)
# issue #48: quote and angle-bracket characters are percent-encoded, so a link can never end an HTML attribute
# (pages escape it as well); the link still opens the same page
URL_ESCAPES = str.maketrans({'"': "%22", "'": "%27", "<": "%3C", ">": "%3E", "`": "%60"})


def safe_url(url) -> str | None:
    """The URL if it is plain http(s), else None, with quote and angle-bracket characters percent-encoded. Feed
    links are stored unchecked, and a javascript: or data: link must never become a clickable href in the report."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    return u.translate(URL_ESCAPES) if SAFE_URL.match(u) else None


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name)


def fmt_call(direction, confidence) -> str:
    if direction not in ("up", "down") or confidence is None or pd.isna(confidence):
        return "no call"
    return f"{'▲ up' if direction == 'up' else '▼ down'} {scoring.percent(confidence)}"


def day_label(d) -> str:
    """'Mon 12 Oct' for a calendar date."""
    d = pd.Timestamp(d).date()
    return f"{d:%a} {d.day} {d:%b}"


def iso(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return pd.Timestamp(v).date().isoformat()


def _list(v) -> list:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return []
    return [x for x in list(v) if x is not None]


# calls by stated-confidence band (exact decimal average: no dependence on row order) and the scored
# calls in a fixed order for scoring.call_scores / reliability (docs/REFACTOR_PLAN.md, nondeterminism)
# (per scoring basis key, never pooled: analytics/call_basis.py; {src} = the track record as of the day's made_at)
BANDS_SQL = f"""SELECT CASE WHEN confidence < 0.6 THEN '50-59%' WHEN confidence < 0.7 THEN '60-69%'
                          WHEN confidence < 0.8 THEN '70-79%' ELSE '80-90%' END AS band, {BASIS_KEY_SQL} AS label_basis,
                     count(*) AS n, avg(TRY_CAST(confidence AS DECIMAL(38,10))) AS conf, avg(hit::INT) AS hit
              FROM {{src}} GROUP BY ALL ORDER BY band, label_basis"""
SCORED_CALLS_SQL = ("SELECT confidence, hit FROM {src} WHERE confidence IS NOT NULL AND hit IS NOT NULL "
                    f"AND {BASIS_KEY_SQL} = ? ORDER BY id, scored_at")
# the same for report.py: its confidence bands, and range_record with the averaged % columns as exact decimals
CONF_BANDS_SQL = f"""SELECT CASE WHEN confidence < 0.6 THEN '0.50-0.59' WHEN confidence < 0.7 THEN '0.60-0.69'
                               WHEN confidence < 0.8 THEN '0.70-0.79' ELSE '0.80-0.90' END AS band,
                          {BASIS_KEY_SQL} AS label_basis, count(*) AS n,
                          avg(TRY_CAST(confidence AS DECIMAL(38,10))) AS conf, avg(hit::INT) AS hit
                   FROM track_record GROUP BY ALL ORDER BY band, label_basis"""
EXACT_COLUMNS = ("width80_pct", "naive_width80_pct", "is80_pct", "naive_is80_pct", "center_err_pct",
                 "naive_center_err_pct")
RANGE_RECORD_EXACT = ("(SELECT * REPLACE ("
                      + ", ".join(f"TRY_CAST({c} AS DECIMAL(38,10)) AS {c}" for c in EXACT_COLUMNS)
                      + ") FROM range_record)")


def record_text(n: int, hits: int, what: str) -> str:
    """Plain-language track record: a share once there is enough history, else a sample note."""
    if n == 0:
        return f"No {what} checked yet."
    if n < MIN_SAMPLE:
        return f"Not enough history yet: {hits} of {n} {what} were right so far."
    return f"Right {hits} of {n} times ({scoring.percent(hits / n)})."


def asof_source(con, view: str, cutoff) -> str:
    """A temp view of `view` with only the outcomes scored by `cutoff` (issue #26: rebuilding an old day's page
    later shows the track record as it was that day); the view itself when there is no cutoff."""
    if cutoff is None or pd.isna(cutoff):
        return view
    con.execute(f"CREATE OR REPLACE TEMP VIEW {view}_asof AS SELECT * FROM {view} "
                f"WHERE scored_at <= TIMESTAMPTZ '{pd.Timestamp(cutoff).isoformat()}'")
    return f"{view}_asof"


def gather_view(cfg: dict, con, now: datetime | None = None) -> dict:
    q = lambda sql, p=None: con.execute(sql, p or []).df()  # noqa: E731
    cur = cfg.get("currency", "")
    ranges = q("SELECT * FROM ranges_latest WHERE as_of_date = (SELECT max(as_of_date) FROM ranges_latest)")
    if ranges.empty:
        raise SystemExit(MSG_NO_PUBLISHED_RANGES)
    as_of = pd.Timestamp(ranges["as_of_date"].iloc[0]).date()
    session = pd.Timestamp(ranges["session_date"].iloc[0]).date()
    made_at = pd.to_datetime(ranges["made_at"], utc=True).max()
    trs, rrs = asof_source(con, "track_record", made_at), asof_source(con, "range_record", made_at)
    calls_seen = q(f"SELECT id, made_at, {BASIS_KEY_SQL} AS label_basis FROM {trs}")
    basis = call_basis.current(calls_seen) or LABEL_CLOSE_TO_CLOSE  # per-company and proper scores: this basis

    regime = q("SELECT * FROM regime_latest ORDER BY as_of_date DESC LIMIT 1")
    feats = q("SELECT * FROM features_latest WHERE as_of_date = ?", [as_of]).set_index("ticker")
    tickers = list(cfg["tickers"])
    hist = q(f"""SELECT ticker, date, close FROM (
                   SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY date DESC) AS k
                   FROM bars WHERE date <= ?) WHERE k <= {HISTORY_DAYS} ORDER BY ticker, date""", [as_of])
    rr = q(f"""SELECT ticker, horizon_days AS h, horizon_label AS label, count(*) AS n, sum(hit80::INT) AS h80,
               sum(hit50::INT) AS h50 FROM {rrs} GROUP BY ticker, h, label ORDER BY ticker, h, {LABEL_ORDER_SQL}""")
    tr = q(f"SELECT ticker, count(*) AS n, sum(hit::INT) AS hits FROM {trs} WHERE {BASIS_KEY_SQL} = ? "
           "GROUP BY ALL ORDER BY ticker", [basis])
    preds = q("SELECT DISTINCT ON (id) * FROM predictions WHERE as_of_date = ? ORDER BY id, made_at", [as_of]) \
        if _has_rows(con, "predictions") else pd.DataFrame()
    news = q("""SELECT n.id, n.title, n.url, n.source, coalesce(n.published_at, n.first_seen_at) AS ts, n.tickers,
                       e.materiality, e.relevance, e.summary
                FROM (SELECT DISTINCT ON (id) * FROM news_asof(coalesce($at, now())) ORDER BY id, first_seen_at) n
                LEFT JOIN news_enriched_asof(coalesce($at, now())) e USING (id) ORDER BY id""", {"at": now})
    filings = q("SELECT DISTINCT ON (id) id, ticker, form, url, accepted_at, description FROM filings "
                "ORDER BY id, first_seen_at, ticker, form, url, accepted_at, description") \
        if _has_rows(con, "filings") else pd.DataFrame()
    anns = q("SELECT id, ticker, subject, url, published_at, source FROM announcements_latest ORDER BY id") \
        if _has_rows(con, "announcements") else pd.DataFrame()
    cevents = q("SELECT date, type, ticker, name, amount FROM company_events WHERE date BETWEEN ? AND ? "
                "ORDER BY date, ticker, type, name",
                [as_of, as_of + timedelta(days=21)])

    # every source an agent may cite: news, SEC filings, NSE announcements -> headline + link
    sources: dict[str, dict] = {}
    for x in news.itertuples():
        sources[x.id] = {"title": x.title, "url": safe_url(x.url), "source": x.source, "ts": _ts(x.ts)}
    for x in filings.itertuples():
        sources[x.id] = {"title": f"{x.ticker} {x.form} filing", "url": safe_url(x.url), "source": "SEC EDGAR", "ts": _ts(x.accepted_at)}
    for x in anns.itertuples():
        sources[x.id] = {"title": f"{x.ticker}: {x.subject}", "url": safe_url(x.url), "source": x.source or "NSE",
                         "ts": _ts(x.published_at)}

    statuses = EvidenceStatuses(con)   # news verification status of cited and listed news (evidence_status.py)
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
            ret1 = json_safe_float(f["ret_1d"]) if f is not None else None
            if ret1 is not None:
                moves.append((t, ret1))
            rows = []
            for hz in sorted(h for tk, h in by if tk == t):   # every published horizon (config/strategies.yaml)
                r = by[(t, hz)]
                late = is_late(cfg, getattr(r, "as_of_date", None), getattr(r, "made_at", None))
                rows.append({  # name, trading days to the target (ahead), card text (when), chart phrase
                    "h": hz, "horizon_label": r.horizon_label, **range_texts(hz, r.horizon_label),
                    "target_date": iso(r.target_date), "target_label": day_label(r.target_date),
                    "base_close": json_safe_float(r.base_close),
                    "center_price": json_safe_float(r.base_close * math.exp(r.center)),
                    "lo50": json_safe_float(r.lo50), "hi50": json_safe_float(r.hi50), "lo80": json_safe_float(r.lo80),
                    "hi80": json_safe_float(r.hi80),
                    "direction": r.direction if r.direction in ("up", "down") else None,
                    "confidence": json_safe_float(r.confidence) if r.direction in ("up", "down") else None,
                    "late": bool(late), "notes": _list(r.notes),
                })
            calls = []
            for x in rows:
                if x["direction"] and not x["late"]:
                    p = pred_by.get((t, x["h"]))
                    ids = _list(p.evidence_ids) if p is not None else []
                    calls.append({"h": x["h"], "when": x["when"], "direction": x["direction"],
                                  "confidence": x["confidence"], "target_label": x["target_label"],
                                  "rationale": (p.rationale if p is not None else None),
                                  "evidence": [{"id": i, **sources.get(i, {}),   # status as of the call's made_at
                                                "verification": statuses.of(i, t, p.made_at)} for i in ids]})
            cited = {e["id"] for c in calls for e in c["evidence"]}
            items = []
            for x in news.itertuples():
                tick = _list(x.tickers)
                if t not in tick:
                    continue
                ts = pd.Timestamp(x.ts) if x.ts is not None and not pd.isna(x.ts) else None
                if ts is None or (window_start is not None and not (window_start <= ts <= made_at)):
                    continue
                items.append({"id": x.id, "title": x.title, "url": safe_url(x.url), "source": x.source, "ts": _ts(ts),
                              "verification": statuses.of(x.id, t, made_at),
                              "cited": x.id in cited, "rank": (x.id in cited, MATERIALITY.get(x.materiality or "", 0),
                                                               json_safe_float(x.relevance) or 0.0, ts.isoformat())})
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
                    label = f"{e.name} ({format_money(cur, e.amount)} per share)"
                evs.append({"date": d.isoformat(), "label": label, "type": e.type, "day": day_label(d)})
            last_target = max((pd.Timestamp(x["target_date"]).date() for x in rows), default=as_of)
            for e in mevents:
                if e["date"] <= last_target:
                    evs.append({"date": e["date"].isoformat(), "label": e["name"], "type": e["type"],
                                "day": day_label(e["date"]), "market": True})
            evs.sort(key=lambda e: e["date"])
            rec_r = {}   # per horizon and label (core.horizons.horizon_key): old windows never pooled with N+k
            for x in rr[rr["ticker"] == t].itertuples():
                rec_r[horizon_key(x.h, x.label)] = {
                    "h": int(x.h), "name": horizon_name(x.h, x.label, legacy=NAME_LEGACY_RECORD), "n": int(x.n),
                    "hit80": int(x.h80), "hit50": int(x.h50), "text": record_text(int(x.n), int(x.h80), "80% ranges")}
            trow = tr[tr["ticker"] == t]
            nc, hc = (int(trow["n"].iloc[0]), int(trow["hits"].iloc[0])) if len(trow) else (0, 0)
            companies.append({
                "ticker": t, "name": meta.get("name", t), "sector": sector,
                "close": json_safe_float(f["close"]) if f is not None else (
                    json_safe_float(h["close"].iloc[-1]) if len(h) else None),
                "ret_1d": ret1, "quality": (f["quality"] if f is not None else "no data"),
                "days_to_earnings": (int(f["days_to_earnings"]) if f is not None and not pd.isna(f["days_to_earnings"]) else None),
                "history": [{"d": iso(x.date), "c": json_safe_float(x.close, 4)} for x in h.itertuples()],
                "ranges": rows, "calls": calls, "events": evs,
                "news": items[:NEWS_PER_COMPANY],
                "record": {"ranges": rec_r, "calls": {"n": nc, "hits": hc, "text": record_text(
                    nc, hc, f"up/down calls (scored {call_basis.label(basis)})")}},
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
            "stress": bool(reg["stress"]), "vol_name": vol_name, "vol_level": json_safe_float(reg["vol_level"], 2),
            "vol_change_1d": json_safe_float(reg["vol_change_1d"]), "bench_name": bench,
            "bench_ret_5d": json_safe_float(reg["bench_ret_5d"]),
            "major_events": _list(reg["major_event_names"]), "notes": _list(reg["notes"]),
        }

    # track record, market-wide: stated vs actual hit rate (ranges by band, calls by confidence)
    cal = q(f"""SELECT horizon_days AS h, horizon_label AS label, count(*) AS n, avg(hit50::INT) AS c50,
                avg(hit80::INT) AS c80 FROM {rrs} GROUP BY h, label ORDER BY h, {LABEL_ORDER_SQL}""")
    bands = q(BANDS_SQL.format(src=trs))
    points = []
    for x in cal.itertuples():
        for stated, actual in ((0.5, x.c50), (0.8, x.c80)):
            points.append({"kind": "range", "label": f"{int(stated * 100)}% ranges, {horizon_name(x.h, x.label)}",
                           "stated": stated, "actual": json_safe_float(actual), "n": int(x.n)})
    for x in bands.itertuples():
        points.append({"kind": "call", "label": f"Calls at {x.band} confidence ({call_basis.label(x.label_basis)})",
                       "stated": json_safe_float(x.conf),
                       "actual": json_safe_float(x.hit), "n": int(x.n)})

    # proper scores of the scored calls (scoring.py): Brier, log loss, reliability with Wilson 95%
    sc_calls = q(SCORED_CALLS_SQL.format(src=trs), [basis])
    call_scores = {**scoring.call_scores(sc_calls), "basis_note": MSG_SCORED_ON.format(basis=call_basis.label(basis))}
    reliability = [{**r, "mean_conf": json_safe_float(r["mean_conf"]), "hit_rate": json_safe_float(r["hit_rate"]),
                    "wilson_lo": json_safe_float(r["wilson_lo"]), "wilson_hi": json_safe_float(r["wilson_hi"])}
                   for r in scoring.reliability(sc_calls["confidence"], sc_calls["hit"])] if len(sc_calls) else []

    n_calls = sum(len(c["calls"]) for c in companies)
    late = sum(1 for c in companies for r in c["ranges"] if r["late"])
    partial = sorted(feats.index[feats["quality"] == "PARTIAL"]) if len(feats) else []
    blocked = sorted(feats.index[feats["quality"] == "BLOCKED"]) if len(feats) else []
    upcoming = [{"date": e["date"].isoformat(), "day": day_label(e["date"]), "label": e["name"],
                 "major": bool(e["major"])} for e in mevents]
    upcoming += [{"date": pd.Timestamp(x.date).date().isoformat(), "day": day_label(x.date), "label": x.name,
                  "major": False} for x in cevents.itertuples()]
    upcoming.sort(key=lambda e: e["date"])
    view = {
        "market": cfg["market"], "name": cfg["name"], "currency": cur, "symbol": CURRENCY.get(cur, ""),
        "session": session.isoformat(), "session_label": day_label(session), "as_of": as_of.isoformat(),
        "as_of_label": day_label(as_of), "made_at": made_at.isoformat() if not pd.isna(made_at) else None,
        "generated_at": (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(),
        "regime": regime_view, "sectors": sector_rows, "companies": companies,
        "calibration": points, "min_sample": MIN_SAMPLE,
        "call_scores": call_scores, "reliability": reliability,
        "counts": {"calls": n_calls, "companies": len(companies),
                   "with_ranges": sum(1 for c in companies if c["ranges"]), "late_ranges": late,
                   "scored_ranges": int(cal["n"].sum()) if len(cal) else 0,
                   "scored_calls": int(bands["n"].sum()) if len(bands) else 0},
        "quality": {"partial": partial, "blocked": blocked, "regime_notes": regime_view["notes"] if regime_view else []},
        "upcoming": upcoming, "sources": sources,
    }
    view["primary_horizon"] = primary_horizon(view)
    return view


def _ts(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return pd.Timestamp(v).isoformat()


def _has_rows(con, view: str) -> bool:
    try:
        return con.execute(f"SELECT count(*) FROM {view}").fetchone()[0] > 0
    except Exception:  # view absent when the market has no such files yet
        return False
