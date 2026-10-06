#!/usr/bin/env python3
"""Collect India market-wide flows and index data (the `india_flows:` section of the market
config; markets without one print `skipped`):
  fpi      NSDL "Daily Trends in FPI Investments" (fpi.nsdl.co.in, the latest report only): gross
           purchases, sales and net investment in INR crore (and USD million) by asset class
           (Equity, Debt-General Limit, Debt-VRR, Debt-FAR, Hybrid, Mutual Funds, AIFs, Total) and
           route (Stock Exchange, Primary market & others, Sub-total) -> data/india/fpi/.
           The reporting date is when custodians reported the trades: they are FPI trades of the
           previous trading day(s), depository-confirmed, unlike NSE's provisional FII/DII cash
           figures (collect_nse_india.py `flows`).
  indices  NSE's daily index close file (nsearchives.nseindia.com ind_close_all_DDMMYYYY.csv) for
           the configured indices: OHLC close, change %, P/E, P/B and dividend yield, one row per
           index and session in the lookback not yet stored -> data/india/indices/. The configured
           sector indices stand for the watchlist sectors that have no Yahoo index history.
Append-only; ids are nsdl-fpi-<reporting date>-<asset>-<route> and nse-idx-<date>-<index>; a
revised value is a new row; an index file missing a configured index (or holding another date)
is stored with `complete` false and fetched again on the next run. Prints a JSON summary with
`failed` (every page or file that could not be read or parsed, FPI table rows with unreadable
numbers, a session file missing before the latest completed session, a configured index absent
from a file). Exit code 1 only if both kinds failed. NSE throttles per
client: run it after collect_nse_india.py, never alongside the NSE collectors."""
from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
from datetime import date, datetime

from common import market_arg, require_market, utc_now, utc_today
from marketbrief.utils.text import slugify as slug
from sources import (Client, FetchError, complete_days, not_published, num, recent_sessions, stale_cutoff,
                     store_changed, summary)

FPI_URL = "https://fpi.nsdl.co.in/web/Reports/Latest.aspx"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{day:%d%m%Y}.csv"


# ---------- NSDL FPI ----------

def _cells(tr: str) -> list[str]:
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def parse_fpi(page: str, now: str) -> tuple[list[dict], str | None]:
    """Rows of the investment table, and a problem (layout changed) or None."""
    m = re.search(r"Daily Trends in FPI Investments on (\d{2}-[A-Za-z]{3}-\d{4})", page)
    if not m:
        return [], "report title 'Daily Trends in FPI Investments on <date>' not found (layout changed?)"
    reporting = datetime.strptime(m.group(1), "%d-%b-%Y").date()
    end = page.find("Daily Trends in FPI Derivative", m.end())
    body = page[m.end(): end if end > 0 else len(page)]
    rows, bad, asset, usd_inr = [], [], None, None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = _cells(tr)
        nums = [num(c) for c in cells]
        if len(cells) == 8:          # reporting date | asset | route | 4 numbers | USD/INR rate
            asset, route, values, usd_inr = cells[1], cells[2], nums[3:7], num(cells[7]) or usd_inr
        elif len(cells) == 6:        # asset | route | 4 numbers
            asset, route, values = cells[0], cells[1], nums[2:6]
        elif len(cells) == 5:        # route | 4 numbers (or Total | 4 numbers)
            route, values = cells[0], nums[1:5]
            if route.lower() == "total":
                asset = "Total"
        else:
            continue
        if asset is None or any(v is None for v in values):
            bad.append(" | ".join(cells)[:120])   # a data-shaped row we cannot read: reported, not skipped
            continue
        rows.append({"id": f"nsdl-fpi-{reporting}-{slug(asset)}-{slug(route)}", "reporting_date": str(reporting),
                     "asset_class": asset, "route": route, "gross_purchases_cr": values[0],
                     "gross_sales_cr": values[1], "net_cr": values[2], "net_usd_mn": values[3],
                     "usd_inr": usd_inr, "source": "nsdl_fpi_daily", "first_seen_at": now})
    problems = []
    if bad:
        problems.append(f"{len(bad)} table rows with unreadable numbers: {bad[:3]}")
    if not any(r["asset_class"] == "Equity" and r["route"].lower() == "sub-total" for r in rows) \
            or not any(r["asset_class"] == "Total" for r in rows):
        problems.append(f"parsed {len(rows)} rows without an Equity sub-total and a Total line (layout changed?)")
    return rows, "; ".join(problems) or None


def fpi(client, now: str, failed: list, notes: list) -> list[dict] | None:
    try:
        page = client.get(FPI_URL, headers={"Accept": "text/html"}).decode("utf-8", "replace")
    except FetchError as exc:
        failed.append(exc.entry("nsdl_fpi"))
        return None
    rows, problem = parse_fpi(page, now)
    if problem:
        failed.append({"source": "nsdl_fpi", "url": FPI_URL, "error": problem})
    eq = next((r for r in rows if r["asset_class"] == "Equity" and r["route"].lower() == "sub-total"), None)
    if rows:
        notes.append(f"fpi: report {rows[0]['reporting_date']}, {len(rows)} rows"
                     + (f", equity net {eq['net_cr']:+,.2f} cr" if eq else ", no equity sub-total"))
    return rows or None


# ---------- NSE index closes ----------

def parse_indices(text: str, day: date, names: dict, now: str) -> tuple[list[dict], list[str], str | None]:
    """(rows for the configured indices, configured names absent from the file, problem or None)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or "Index Name" not in reader.fieldnames:
        return [], [], f"unexpected header: {text[:80]!r}"
    want = {n.lower(): (n, sector) for n, sector in names.items()}
    rows, served = [], set()
    for r in reader:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        hit = want.get(r.get("Index Name", "").lower())
        if not hit:
            continue
        try:
            d = datetime.strptime(r.get("Index Date", ""), "%d-%m-%Y").date()
        except ValueError:
            continue
        served.add(d)
        name, sector = hit
        rows.append({"id": f"nse-idx-{d}-{slug(name)}", "date": str(d), "index_name": name, "sector": sector,
                     "open": num(r.get("Open Index Value")), "high": num(r.get("High Index Value")),
                     "low": num(r.get("Low Index Value")), "close": num(r.get("Closing Index Value")),
                     "change_pct": num(r.get("Change(%)")), "volume": num(r.get("Volume")),
                     "turnover_cr": num(r.get("Turnover (Rs. Cr.)")), "pe": num(r.get("P/E")),
                     "pb": num(r.get("P/B")), "div_yield": num(r.get("Div Yield")),
                     "source": "nse_ind_close_all", "first_seen_at": now})
    missing = sorted(n for n, _ in want.values() if n not in {r["index_name"] for r in rows})
    problem = f"file for {day} holds {sorted(map(str, served))}" if served and day not in served else None
    return rows, missing, problem


def indices(client, cfg: dict, today: date, conf: dict, now: str, failed: list, notes: list) -> tuple[list, int]:
    names = conf.get("names") or {}
    have = complete_days(cfg["market"], "indices", "index_name", set(names))
    cutoff, rows, ok = stale_cutoff(cfg, today), [], 0
    for d in recent_sessions(cfg, today, int(conf.get("lookback_days", 7))):
        if str(d) in have:
            ok += 1
            continue
        url = INDEX_URL.format(day=d)
        try:
            text = client.get(url, headers={"Accept": "text/csv"}).decode("utf-8", "replace")
        except FetchError as exc:
            if not_published(exc) and d >= cutoff:
                notes.append(f"indices: no NSE index file for {d} yet (HTTP {exc.status}); published after the close")
                continue
            failed.append(exc.entry("nse_indices", date=str(d)))
            if exc.host or exc.status is None:
                break
            continue
        got, missing, problem = parse_indices(text, d, names, now)
        if problem:
            failed.append({"source": "nse_indices", "date": str(d), "url": url, "error": problem})
        if missing:
            failed.append({"source": "nse_indices", "date": str(d), "url": url,
                           "error": f"configured indices not in the file: {missing}"})
        for r in got:   # an incomplete day is stored but fetched again next run (complete_days)
            r["complete"] = not problem and not missing
        ok += 1
        rows += got
    return rows, ok


def collect(cfg: dict, client, today: date, now: str) -> dict:
    market, conf = cfg["market"], cfg["india_flows"]
    new, failed, notes, warnings = {}, [], [], []
    if conf.get("fpi", True):
        rows = fpi(client, now, failed, notes)
        new["fpi"] = None if rows is None else store_changed(
            market, "fpi", rows, today, ["gross_purchases_cr", "gross_sales_cr", "net_cr"])
    if conf.get("indices"):
        rows, ok = indices(client, cfg, today, conf["indices"], now, failed, notes)
        new["indices"] = store_changed(market, "indices", rows, today,
                                       ["close", "pe", "pb", "div_yield", "complete"]) if ok else None
    return summary("flows_india", market, new, failed, notes, warnings, client)


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    if not cfg.get("india_flows"):
        print(json.dumps({"collector": "flows_india", "market": cfg["market"],
                          "skipped": "no `india_flows:` section in this market's config"}))
        return 0
    client = Client(pause=float(cfg["india_flows"].get("pause_seconds", 1.0)))
    out = collect(cfg, client, utc_today(), utc_now())
    print(json.dumps(out, indent=2))
    return 1 if out["new"] and all(v is None for v in out["new"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
