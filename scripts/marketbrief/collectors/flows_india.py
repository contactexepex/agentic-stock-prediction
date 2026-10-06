"""Collect India market-wide flows and index data (the `india_flows:` section of the market
config; markets without one print `skipped`):
  fpi      NSDL "Daily Trends in FPI Investments" (fpi.nsdl.co.in, the latest report only): gross
           purchases, sales and net investment in INR crore (and USD million) by asset class
           (Equity, Debt-General Limit, Debt-VRR, Debt-FAR, Hybrid, Mutual Funds, AIFs, Total) and
           route (Stock Exchange, Primary market & others, Sub-total) -> data/india/fpi/.
           The reporting date is when custodians reported the trades: they are FPI trades of the
           previous trading day(s), depository-confirmed, unlike NSE's provisional FII/DII cash
           figures (the nse_india collector's `flows`).
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

import json
from datetime import date

from marketbrief.collectors.flows_parsing import parse_fpi, parse_indices
from marketbrief.collectors.collector_store import (
    Problems,
    complete_days,
    not_published,
    stale_cutoff,
    store_changed,
    summary,
)
from marketbrief.constants.config_keys import CFG_INDIA_FLOWS, CFG_MARKET
from marketbrief.constants.free_sources import (
    COLLECTOR_FLOWS_INDIA,
    DEFAULT_FLOWS_PAUSE_SECONDS,
    DEFAULT_INDEX_LOOKBACK_DAYS,
    FPI_ASSET_EQUITY,
    FPI_ROUTE_SUBTOTAL,
    FPI_URL,
    FPI_VALUE_COLUMNS,
    HEADERS_CSV,
    HEADERS_HTML,
    INDEX_URL,
    INDEX_VALUE_COLUMNS,
    MSG_FPI_EQUITY_NET,
    MSG_FPI_NOTE,
    MSG_FPI_NO_EQUITY,
    MSG_INDEX_MISSING,
    MSG_INDEX_NOT_YET,
    MSG_SKIPPED_NO_FLOWS,
    SOURCE_NSDL_FPI,
    SOURCE_NSE_INDICES,
)
from marketbrief.constants.kinds import KIND_FPI, KIND_INDICES
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_MARKET, SUMMARY_SKIPPED
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.sources.errors import FetchError
from marketbrief.sources.free_source_client import FreeSourceClient
from marketbrief.utils.sessions import sessions_in_window


def collect_fpi(client, now: str, problems: Problems) -> list[dict] | None:
    """The latest NSDL FPI report's rows (None when the page could not be read or held no rows)."""
    try:
        page = client.get(FPI_URL, headers=HEADERS_HTML).decode("utf-8", "replace")
    except FetchError as exc:
        problems.failed.append(exc.entry(SOURCE_NSDL_FPI))
        return None
    rows, problem = parse_fpi(page, now)
    if problem:
        problems.failed.append({"source": SOURCE_NSDL_FPI, "url": FPI_URL, "error": problem})
    equity = next(
        (r for r in rows if r["asset_class"] == FPI_ASSET_EQUITY and r["route"].lower() == FPI_ROUTE_SUBTOTAL), None
    )
    if rows:
        tail = MSG_FPI_EQUITY_NET.format(net=equity["net_cr"]) if equity else MSG_FPI_NO_EQUITY
        problems.notes.append(MSG_FPI_NOTE.format(reporting=rows[0]["reporting_date"], count=len(rows)) + tail)
    return rows or None


def collect_indices(client, cfg: dict, today: date, settings: dict, now: str, problems: Problems) -> tuple[list, int]:
    """(rows, sessions available) of NSE's index close files for the sessions in the lookback that are not stored
    complete; an incomplete day is stored but fetched again next run (complete_days)."""
    names = settings.get("names") or {}
    have = complete_days(cfg[CFG_MARKET], KIND_INDICES, "index_name", set(names))
    cutoff, rows, available = stale_cutoff(cfg, today), [], 0
    for day in sessions_in_window(cfg, today, int(settings.get("lookback_days", DEFAULT_INDEX_LOOKBACK_DAYS))):
        if str(day) in have:
            available += 1
            continue
        url = INDEX_URL.format(day=day)
        try:
            text = client.get(url, headers=HEADERS_CSV).decode("utf-8", "replace")
        except FetchError as exc:
            if not_published(exc) and day >= cutoff:
                problems.notes.append(MSG_INDEX_NOT_YET.format(day=day, status=exc.status))
                continue
            problems.failed.append(exc.entry(SOURCE_NSE_INDICES, date=str(day)))
            if exc.host or exc.status is None:
                break
            continue
        found, missing, problem = parse_indices(text, day, names, now)
        if problem:
            problems.failed.append({"source": SOURCE_NSE_INDICES, "date": str(day), "url": url, "error": problem})
        if missing:
            problems.failed.append(
                {
                    "source": SOURCE_NSE_INDICES,
                    "date": str(day),
                    "url": url,
                    "error": MSG_INDEX_MISSING.format(missing=missing),
                }
            )
        for row in found:
            row["complete"] = not problem and not missing
        available += 1
        rows += found
    return rows, available


def collect(cfg: dict, client, today: date, now: str) -> dict:
    """One flows run: the FPI report and the index closes, stored when new or revised; returns the JSON summary."""
    market, settings = cfg[CFG_MARKET], cfg[CFG_INDIA_FLOWS]
    new, problems = {}, Problems()
    if settings.get("fpi", True):
        rows = collect_fpi(client, now, problems)
        new[KIND_FPI] = None if rows is None else store_changed(market, KIND_FPI, rows, today, FPI_VALUE_COLUMNS)
    if settings.get("indices"):
        rows, available = collect_indices(client, cfg, today, settings["indices"], now, problems)
        new[KIND_INDICES] = store_changed(market, KIND_INDICES, rows, today, INDEX_VALUE_COLUMNS) if available else None
    return summary(COLLECTOR_FLOWS_INDIA, market, new, problems, client)


def main() -> int:
    """Entry point of scripts/collect_flows_india.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    if not cfg.get(CFG_INDIA_FLOWS):
        print(
            json.dumps(
                {
                    SUMMARY_COLLECTOR: COLLECTOR_FLOWS_INDIA,
                    SUMMARY_MARKET: cfg[CFG_MARKET],
                    SUMMARY_SKIPPED: MSG_SKIPPED_NO_FLOWS,
                }
            )
        )
        return 0
    client = FreeSourceClient(pause=float(cfg[CFG_INDIA_FLOWS].get("pause_seconds", DEFAULT_FLOWS_PAUSE_SECONDS)))
    out = collect(cfg, client, utc_today(), utc_now())
    print(json.dumps(out, indent=2))
    return 1 if out["new"] and all(v is None for v in out["new"].values()) else 0
