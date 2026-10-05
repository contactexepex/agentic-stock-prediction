#!/usr/bin/env python3
"""Compute the daily indicator snapshot and market regime for one market.

Reads stored bars, quotes and events (never live APIs), then appends:
- data/<market>/features/YYYY/MM/<as_of_date>.jsonl: one row per watchlist ticker
- data/<market>/regime/YYYY/MM/<as_of_date>.jsonl: one row for the market
and prints a JSON summary. as_of_date = latest benchmark bar; session_date = the trading day
being predicted (today in the exchange's timezone if it is a session, else the next one)."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import events as ev
import indicators as ind
import regime as rg
from common import (FEATURE_COLS, append_jsonl, benchmark_key, clock, connect, day_file, market_arg,
                    require_market, utc_now, utc_today, vol_index_key)


def local_today(cfg: dict) -> date:
    return clock().astimezone(ZoneInfo(cfg["timezone"])).date()


def load_bars(con) -> dict[str, pd.DataFrame]:
    df = con.execute("SELECT ticker, date, open, high, low, close, volume FROM ohlc ORDER BY ticker, date").df()
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    return {t: g.set_index("date").drop(columns="ticker") for t, g in df.groupby("ticker")}


def quotes_today(con, day: date) -> dict[str, dict]:
    rows = con.execute("SELECT symbol, price, prev_close, change_pct, ts FROM quotes_latest WHERE day = ?",
                       [day]).fetchall()
    return {r[0]: {"price": r[1], "prev_close": r[2], "change_pct": r[3], "ts": r[4]} for r in rows}


def company_events(con, start: date) -> dict[tuple[str, str], date]:
    rows = con.execute("SELECT ticker, type, date FROM company_events WHERE date >= ?", [start]).fetchall()
    return {(t, k): d for t, k, d in rows}


def run(cfg: dict, today_local: date | None = None, utc_day: date | None = None) -> dict:
    market = cfg["market"]
    con = connect(market)
    bars = load_bars(con)
    today_local = today_local or local_today(cfg)
    session = ev.next_session(cfg, today_local)
    bench_key, vol_key = benchmark_key(cfg), vol_index_key(cfg)
    bench = bars.get(bench_key)
    if bench is None or bench.empty:
        raise SystemExit(f"no benchmark bars for {bench_key}; run collect_prices.py first")
    as_of = bench.index[-1].date()
    quotes = quotes_today(con, utc_day or utc_today())
    cevents = company_events(con, session)
    now = utc_now()

    # per-ticker indicators
    rows = {}
    for key, meta in cfg["tickers"].items():
        df = bars.get(key)
        df = df[df.index <= pd.Timestamp(as_of)] if df is not None else None
        if df is None or df.empty:
            vals = {"bars": 0, "quality": "BLOCKED", "warnings": ["no price data"]}
        else:
            vals = ind.compute(df, bench["close"])
            if df.index[-1].date() < as_of:
                vals["warnings"].append(f"stale: last bar {df.index[-1].date()}")
                vals["quality"] = "PARTIAL" if vals["quality"] == "OK" else vals["quality"]
        q = quotes.get(f"{key}:ADR") or quotes.get(key)
        vals["cue_change_pct"] = q["change_pct"] if q else None
        earn = cevents.get((key, "earnings"))
        vals["days_to_earnings"] = (earn - session).days if earn else None
        exdiv = cevents.get((key, "ex_dividend"))
        vals["ex_dividend_date"] = exdiv.isoformat() if exdiv and (exdiv - session).days <= 10 else None
        rows[key] = vals

    # relative strength vs sector peers (5-day return minus peers' average)
    for sector, members in cfg.get("sectors", {}).items():
        for key in members:
            peers = [rows[p]["ret_5d"] for p in members if p != key and rows.get(p, {}).get("ret_5d") is not None]
            own = rows.get(key, {}).get("ret_5d")
            rows[key]["rel_sector_5d"] = own - sum(peers) / len(peers) if own is not None and peers else None

    feature_rows = [{"id": f"{as_of}-{k}", "as_of_date": as_of.isoformat(), "ticker": k,
                     "computed_at": now, **{c: v.get(c) for c in FEATURE_COLS}} for k, v in rows.items()]

    # market regime
    vol = bars.get(vol_key)
    vol_level = vol_change = None
    if vol is not None and not vol.empty:
        vol_level = float(vol["close"].iloc[-1])
        prev = float(vol["close"].iloc[-2]) if len(vol) > 1 else None
        vq = quotes.get(vol_key)
        if vq and vq.get("price"):
            vol_level, prev = vq["price"], vq["prev_close"] or prev
        vol_change = vol_level / prev - 1 if prev else None
    bench_ret_5d = ind.ret(bench["close"], 5)
    bench_vol_10d = ind.realized_vol(bench["close"])
    upcoming = ev.market_events(cfg, today_local, session + timedelta(days=14))
    near = ev.major_events_near(upcoming, session)
    regime, stress, notes = rg.classify(cfg["regime"], vol_level, bench_ret_5d, bench_vol_10d,
                                        bool(near), vol_change)
    if not ev.calendar_covers(cfg, session):
        notes.append(f"exchange calendar does not cover {session}: assuming Mon-Fri sessions")
    regime_row = {"id": str(as_of), "as_of_date": as_of.isoformat(), "session_date": session.isoformat(),
                  "computed_at": now, "regime": regime,
                  "vol_level": round(vol_level, 4) if vol_level is not None else None,
                  "vol_change_1d": round(vol_change, 6) if vol_change is not None else None,
                  "bench_ret_5d": bench_ret_5d, "bench_vol_10d": bench_vol_10d,
                  "major_event": bool(near), "major_event_names": [e["name"] for e in near],
                  "stress": stress, "notes": notes}

    append_jsonl(day_file(market, "features", as_of), feature_rows)
    append_jsonl(day_file(market, "regime", as_of), [regime_row])
    quality = {q: sorted(k for k, v in rows.items() if v["quality"] == q) for q in ("OK", "PARTIAL", "BLOCKED")}
    return {"step": "features", "market": market, "as_of_date": str(as_of), "session_date": str(session),
            "regime": regime, "stress": stress, "notes": notes,
            "tickers": {q: len(v) for q, v in quality.items()},
            "partial": quality["PARTIAL"], "blocked": quality["BLOCKED"],
            "upcoming_events": [f"{e['date']} {e['name']}" for e in upcoming]}


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    print(json.dumps(run(cfg), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
