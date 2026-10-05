#!/usr/bin/env python3
"""Collect US market-wide macro series (the `macro:` section of the market config; markets
without one print `skipped`) into data/<market>/macro/YYYY/MM/<UTC today>.jsonl, one row per
series and observation date:
  treasury  daily par yield curve (home.treasury.gov CSV), series UST_<tenor>, in percent
  fred      FRED series by id (fredgraph.csv, no API key), e.g. high-yield and investment-grade
            credit spreads and the 10-year breakeven, units as configured
  cboe      Cboe daily options statistics (cdn.cboe.com JSON per session): put/call ratios,
            series CBOE_PC_<name>; sessions in the lookback not yet stored are fetched
Append-only: a row is written when its id (<series>-<date>) is new or its value changed (a
revision is a new row; the view macro_series keeps the newest). A Cboe session file missing a
configured ratio is stored with `complete` false and fetched again on the next run. Prints a JSON summary: `failed`
lists every source or session that could not be read (HTTP status, or the host to allowlist),
a per-session file missing before the latest completed session is a failure, the latest one a
note (publishing lag). Exit code 1 only if every source failed."""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import date, datetime, timedelta

from common import market_arg, require_market, utc_now, utc_today
from sources import (Client, FetchError, complete_days, not_published, num, recent_sessions, stale_cutoff,
                     store_changed, summary)

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
CBOE_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{day}_daily_options"
VALUE_COLS = ["value", "complete"]


def row(series: str, day: date, value: float, unit: str, name: str, source: str, now: str,
        complete: bool = True) -> dict:
    return {"id": f"{series}-{day}", "date": str(day), "series": series, "name": name, "value": value,
            "unit": unit, "source": source, "first_seen_at": now, "complete": complete}


# ---------- Treasury ----------

def tenor_series(col: str) -> str | None:
    """'3 Mo' -> UST_3M, '1.5 Month' -> UST_1.5M, '10 Yr' -> UST_10Y; other columns -> None."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(Mo|Month|Months|Yr|Year|Years)\s*", col)
    if not m:
        return None
    return f"UST_{m.group(1)}{'M' if m.group(2).startswith('Mo') else 'Y'}"


def parse_treasury(text: str, since: date, now: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            day = datetime.strptime((r.get("Date") or "").strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if day < since:
            continue
        for col, val in r.items():
            series, v = tenor_series(col or ""), num(val)
            if series and v is not None:
                rows.append(row(series, day, v, "pct", f"Treasury par yield {col.strip()}", "treasury", now))
    return rows


def treasury(client, today: date, lookback: int, now: str) -> list[dict]:
    since = today - timedelta(days=lookback)
    rows = []
    for year in sorted({since.year, today.year}):
        text = client.get(TREASURY_URL.format(year=year), headers={"Accept": "text/csv"}).decode("utf-8-sig")
        if not text.lstrip().startswith("Date"):
            raise FetchError(TREASURY_URL.format(year=year), f"not the yield-curve CSV: {text[:80]!r}")
        rows += parse_treasury(text, since, now)
    return rows


# ---------- FRED ----------

def parse_fred(text: str, sid: str, since: date, unit: str, name: str, now: str) -> list[dict]:
    """fredgraph.csv: a date column (observation_date, formerly DATE) and one column per id;
    '.' marks a day without a value."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        d = r.get("observation_date") or r.get("DATE")
        try:
            day = date.fromisoformat((d or "").strip())
        except ValueError:
            continue
        v = num(r.get(sid))
        if day >= since and v is not None:
            rows.append(row(sid, day, v, unit, name, "fred", now))
    return rows


# ---------- Cboe ----------

def parse_cboe(payload: dict, day: date, wanted: dict[str, str], now: str) -> tuple[list[dict], list[str]]:
    """`ratios` list -> (rows for the configured ratio names ({name in Cboe's file: series}),
    configured names absent or without a number). Rows are `complete` only when none is missing."""
    by_name = {(r.get("name") or "").strip().upper(): num(r.get("value")) for r in payload.get("ratios") or []}
    found = {n: by_name.get(n.upper()) for n in wanted}
    missing = sorted(n for n, v in found.items() if v is None)
    rows = [row(series, day, found[n], "ratio", f"Cboe {n}", "cboe", now, complete=not missing)
            for n, series in wanted.items() if found[n] is not None]
    return rows, missing


def cboe(client, cfg: dict, today: date, conf: dict, market: str, now: str, failed: list, notes: list) -> tuple[list, int]:
    wanted = conf.get("ratios") or {}
    have = complete_days(market, "macro", "series", set(wanted.values()))
    cutoff, rows, ok = stale_cutoff(cfg, today), [], 0
    for d in recent_sessions(cfg, today, int(conf.get("lookback_days", 7))):
        if str(d) in have:
            ok += 1
            continue
        url = CBOE_URL.format(day=d)
        try:
            payload = client.json(url)
        except FetchError as exc:
            if not_published(exc) and d >= cutoff:
                notes.append(f"cboe: no file for {d} yet (HTTP {exc.status}); published after the close")
                continue
            failed.append(exc.entry("cboe", date=str(d)))
            if exc.host or exc.status is None:   # host unreachable: the other days fail the same way
                break
            continue
        got, missing = parse_cboe(payload, d, wanted, now)
        if missing:
            failed.append({"source": "cboe", "date": str(d), "url": url,
                           "error": f"ratios missing from the file: {missing}"})
        ok += 1
        rows += got
    return rows, ok


# ---------- main ----------

def collect(cfg: dict, client, today: date, now: str) -> dict:
    market, conf = cfg["market"], cfg["macro"]
    lookback = int(conf.get("lookback_days", 30))
    new, failed, notes, warnings = {}, [], [], []
    rows: list[dict] = []
    ok_sources = 0

    if conf.get("treasury", True):
        try:
            got = treasury(client, today, lookback, now)
            if not got:
                failed.append({"source": "treasury", "error": f"no yield-curve rows in the last {lookback} days"})
            else:
                ok_sources += 1
                notes.append(f"treasury: {len(got)} values, latest {max(r['date'] for r in got)}")
            rows += got
        except FetchError as exc:
            failed.append(exc.entry("treasury"))

    fred_ok = 0
    for sid, meta in (conf.get("fred") or {}).items():
        meta = meta or {}
        url = FRED_URL.format(sid=sid, start=today - timedelta(days=lookback))
        try:
            text = client.get(url, headers={"Accept": "text/csv"}).decode("utf-8-sig")
        except FetchError as exc:
            failed.append(exc.entry(f"fred:{sid}"))
            continue
        got = parse_fred(text, sid, today - timedelta(days=lookback), meta.get("unit", "pct"), meta.get("name", sid), now)
        if not got:
            failed.append({"source": f"fred:{sid}", "url": url, "error": f"no values in the last {lookback} days"})
            continue
        fred_ok += 1
        rows += got
    ok_sources += fred_ok > 0

    if conf.get("cboe"):
        got, ok = cboe(client, cfg, today, conf["cboe"], market, now, failed, notes)
        rows += got
        ok_sources += ok > 0

    new["macro"] = store_changed(market, "macro", rows, today, VALUE_COLS)
    out = summary("macro", market, new, failed, notes, warnings, client)
    out["sources_ok"] = ok_sources
    return out


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    if not cfg.get("macro"):
        print(json.dumps({"collector": "macro", "market": cfg["market"],
                          "skipped": "no `macro:` section in this market's config"}))
        return 0
    client = Client(pause=float(cfg["macro"].get("pause_seconds", 1.0)))
    out = collect(cfg, client, utc_today(), utc_now())
    print(json.dumps(out, indent=2))
    return 1 if out["sources_ok"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
