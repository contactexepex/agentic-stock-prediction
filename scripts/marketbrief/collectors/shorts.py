"""Collect FINRA short-selling data for the watchlist (the `shorts:` section of the market
config; markets without one print `skipped`):
  shorts          daily short-sale volume from FINRA's Reg SHO consolidated file
                  (cdn.finra.org CNMSshvol<YYYYMMDD>.txt), for sessions in the lookback not yet
                  stored -> data/<market>/shorts/. It covers trades reported to FINRA's
                  facilities (off-exchange and ATS volume), not exchange volume, so short_pct is
                  the short share of that volume (around 40-50% is ordinary); compare a ticker with
                  its own history, never with short interest.
  short_interest  FINRA consolidated short interest (api.finra.org, twice a month, published about
                  a week after the settlement date) -> data/<market>/short_interest/
Append-only; ids are finra-shvol-<date>-<ticker> and finra-si-<settlement date>-<ticker>; a
revised value is a new row; a day file that is truncated or misses a watchlist ticker is
stored with `complete` false and fetched again on the next run. Prints a JSON summary: `failed`
lists every file or call that could not be read, a session file missing before the latest completed session,
a truncated file (row count differs from FINRA's trailer) and a watchlist ticker missing from a file. Exit
code 1 only if both kinds failed."""

from __future__ import annotations

import json
from datetime import date, timedelta

from marketbrief.collectors.collector_store import (
    Problems,
    complete_days,
    refetch_since,
    not_published,
    stale_cutoff,
    store_changed,
    summary,
)
from marketbrief.collectors.shorts_parsing import finra_symbols, parse_short_interest, parse_volume
from marketbrief.constants.columns import COL_TICKER
from marketbrief.constants.config_keys import CFG_MARKET, CFG_SHORTS
from marketbrief.constants.free_sources import (
    COLLECTOR_SHORTS,
    DEFAULT_INTEREST_LOOKBACK_DAYS,
    DEFAULT_SHORTS_PAUSE_SECONDS,
    DEFAULT_VOLUME_LOOKBACK_DAYS,
    HEADERS_JSON_POST,
    MSG_FINRA_NOT_YET,
    MSG_INTEREST_NOTE,
    MSG_INTEREST_SETTLEMENT_MISSING,
    MSG_NO_INTEREST_ROWS,
    MSG_NO_TICKER_ROWS,
    MSG_SKIPPED_NO_SHORTS,
    SHORT_INTEREST_FIELDS,
    SHORT_INTEREST_LIMIT,
    SHORT_INTEREST_URL,
    SHORT_INTEREST_VALUE_COLUMNS,
    SHORTS_VALUE_COLUMNS,
    SOURCE_FINRA_INTEREST,
    SOURCE_FINRA_VOLUME,
    VOLUME_URL,
)
from marketbrief.constants.kinds import KIND_SHORT_INTEREST, KIND_SHORTS
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_MARKET, SUMMARY_SKIPPED
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.sources.errors import FetchError
from marketbrief.sources.free_source_client import FreeSourceClient
from marketbrief.utils.sessions import sessions_in_window


def daily_volume(client, cfg: dict, today: date, settings: dict, now: str, problems: Problems) -> tuple[list, int]:
    """(rows, sessions available) of the FINRA short-sale volume for the sessions in the lookback that are not
    stored complete; an incomplete day is stored but fetched again next run (complete_days)."""
    symbols = finra_symbols(cfg)
    have = complete_days(cfg[CFG_MARKET], KIND_SHORTS, COL_TICKER, set(symbols.values()), refetch_since(cfg, today))
    cutoff, rows, available = stale_cutoff(cfg, today), [], 0
    for day in sessions_in_window(cfg, today, int(settings.get("lookback_days", DEFAULT_VOLUME_LOOKBACK_DAYS))):
        if str(day) in have:
            available += 1
            continue
        url = VOLUME_URL.format(day=day)
        try:
            text = client.get(url).decode("utf-8", "replace")
        except FetchError as exc:
            if not_published(exc) and day >= cutoff:
                problems.notes.append(MSG_FINRA_NOT_YET.format(day=day, status=exc.status))
                continue
            problems.failed.append(exc.entry(SOURCE_FINRA_VOLUME, date=str(day)))
            if exc.host or exc.status is None:
                break
            continue
        found, problem = parse_volume(text, day, symbols, now)
        if problem:
            problems.failed.append({"source": SOURCE_FINRA_VOLUME, "date": str(day), "url": url, "error": problem})
        missing = sorted(set(symbols.values()) - {found_row[COL_TICKER] for found_row in found})
        if missing:
            problems.failed.append(
                {
                    "source": SOURCE_FINRA_VOLUME,
                    "date": str(day),
                    "url": url,
                    "error": MSG_NO_TICKER_ROWS.format(missing=missing),
                }
            )
        for row in found:
            row["complete"] = not problem and not missing
        available += 1
        rows += found
    return rows, available


def short_interest(client, cfg: dict, today: date, settings: dict, now: str, problems: Problems) -> list[dict]:
    """The rows of FINRA's consolidated short interest for the watchlist, from the lookback window."""
    symbols = finra_symbols(cfg)
    lookback = int(settings.get("lookback_days", DEFAULT_INTEREST_LOOKBACK_DAYS))
    body = {
        "limit": SHORT_INTEREST_LIMIT,
        "fields": SHORT_INTEREST_FIELDS,
        "domainFilters": [{"fieldName": "symbolCode", "values": sorted(symbols)}],
        "dateRangeFilters": [
            {"fieldName": "settlementDate", "startDate": str(today - timedelta(days=lookback)), "endDate": str(today)}
        ],
    }
    payload = client.json(SHORT_INTEREST_URL, data=json.dumps(body).encode(), headers=HEADERS_JSON_POST)
    rows = parse_short_interest(payload, symbols, now)
    if not rows:
        problems.failed.append(
            {
                "source": SOURCE_FINRA_INTEREST,
                "url": SHORT_INTEREST_URL,
                "error": MSG_NO_INTEREST_ROWS.format(days=lookback),
            }
        )
        return rows
    latest = max(row["settlement_date"] for row in rows)
    missing = sorted(set(symbols.values()) - {row[COL_TICKER] for row in rows if row["settlement_date"] == latest})
    if missing:
        problems.failed.append(
            {
                "source": SOURCE_FINRA_INTEREST,
                "url": SHORT_INTEREST_URL,
                "error": MSG_INTEREST_SETTLEMENT_MISSING.format(latest=latest, missing=missing),
            }
        )
    settlements = ", ".join(sorted({row["settlement_date"] for row in rows}))
    problems.notes.append(MSG_INTEREST_NOTE.format(count=len(rows), settlements=settlements))
    return rows


def collect(cfg: dict, client, today: date, now: str) -> dict:
    """One shorts run: daily volume and short interest, stored when new or revised; returns the JSON summary."""
    market, settings = cfg[CFG_MARKET], cfg[CFG_SHORTS]
    new, problems = {}, Problems()
    if (settings.get("daily_volume") or {}).get("enabled", True):
        rows, available = daily_volume(client, cfg, today, settings.get("daily_volume") or {}, now, problems)
        new[KIND_SHORTS] = store_changed(market, KIND_SHORTS, rows, today, SHORTS_VALUE_COLUMNS) if available else None
    if (settings.get("short_interest") or {}).get("enabled", True):
        try:
            rows = short_interest(client, cfg, today, settings.get("short_interest") or {}, now, problems)
            new[KIND_SHORT_INTEREST] = (
                store_changed(market, KIND_SHORT_INTEREST, rows, today, SHORT_INTEREST_VALUE_COLUMNS) if rows else None
            )
        except FetchError as exc:
            problems.failed.append(exc.entry(SOURCE_FINRA_INTEREST))
            new[KIND_SHORT_INTEREST] = None
    return summary(COLLECTOR_SHORTS, market, new, problems, client)


def main() -> int:
    """Entry point of scripts/collect_shorts.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    if not cfg.get(CFG_SHORTS):
        print(
            json.dumps(
                {
                    SUMMARY_COLLECTOR: COLLECTOR_SHORTS,
                    SUMMARY_MARKET: cfg[CFG_MARKET],
                    SUMMARY_SKIPPED: MSG_SKIPPED_NO_SHORTS,
                }
            )
        )
        return 0
    client = FreeSourceClient(pause=float(cfg[CFG_SHORTS].get("pause_seconds", DEFAULT_SHORTS_PAUSE_SECONDS)))
    out = collect(cfg, client, utc_today(), utc_now())
    print(json.dumps(out, indent=2))
    return 1 if out["new"] and all(new_value is None for new_value in out["new"].values()) else 0
