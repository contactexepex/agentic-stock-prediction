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

import json
from datetime import date, timedelta

from marketbrief.collectors.collector_store import (
    Problems,
    complete_days,
    not_published,
    stale_cutoff,
    store_changed,
    summary,
)
from marketbrief.collectors.macro_parsing import parse_cboe, parse_fred, treasury
from marketbrief.constants.config_keys import CFG_MACRO, CFG_MARKET
from marketbrief.constants.free_sources import (
    CBOE_URL,
    COLLECTOR_MACRO,
    DEFAULT_CBOE_LOOKBACK_DAYS,
    DEFAULT_MACRO_LOOKBACK_DAYS,
    DEFAULT_MACRO_PAUSE_SECONDS,
    FRED_URL,
    HEADERS_CSV,
    MACRO_VALUE_COLUMNS,
    MSG_CBOE_NOT_YET,
    MSG_CBOE_RATIOS_MISSING,
    MSG_NO_FRED_VALUES,
    MSG_NO_YIELD_ROWS,
    MSG_SKIPPED_NO_MACRO,
    MSG_TREASURY_NOTE,
    SOURCE_CBOE,
    SOURCE_TREASURY,
    UNIT_PERCENT,
)
from marketbrief.constants.kinds import KIND_MACRO
from marketbrief.constants.statuses import (
    SUMMARY_COLLECTOR,
    SUMMARY_MARKET,
    SUMMARY_SKIPPED,
)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.sources.errors import FetchError
from marketbrief.sources.free_source_client import FreeSourceClient
from marketbrief.utils.sessions import sessions_in_window


def collect_cboe(client, cfg: dict, today: date, settings: dict, now: str, problems: Problems) -> tuple[list, int]:
    """(rows, sessions available) of the Cboe put/call ratios for the sessions in the lookback that are not stored
    complete; a missing file is a failure, except the latest session's (publishing lag, a note)."""
    market = cfg[CFG_MARKET]
    wanted = settings.get("ratios") or {}
    have = complete_days(market, KIND_MACRO, "series", set(wanted.values()))
    cutoff, rows, available = stale_cutoff(cfg, today), [], 0
    for day in sessions_in_window(cfg, today, int(settings.get("lookback_days", DEFAULT_CBOE_LOOKBACK_DAYS))):
        if str(day) in have:
            available += 1
            continue
        url = CBOE_URL.format(day=day)
        try:
            payload = client.json(url)
        except FetchError as exc:
            if not_published(exc) and day >= cutoff:
                problems.notes.append(MSG_CBOE_NOT_YET.format(day=day, status=exc.status))
                continue
            problems.failed.append(exc.entry(SOURCE_CBOE, date=str(day)))
            if exc.host or exc.status is None:  # host unreachable: the other days fail the same way
                break
            continue
        found, missing = parse_cboe(payload, day, wanted, now)
        if missing:
            problems.failed.append(
                {
                    "source": SOURCE_CBOE,
                    "date": str(day),
                    "url": url,
                    "error": MSG_CBOE_RATIOS_MISSING.format(missing=missing),
                }
            )
        available += 1
        rows += found
    return rows, available


def collect_treasury(client, today: date, lookback: int, now: str, problems: Problems) -> tuple[list, bool]:
    """(rows, whether the source answered with rows) of the Treasury yield curve."""
    try:
        rows = treasury(client, today, lookback, now)
    except FetchError as exc:
        problems.failed.append(exc.entry(SOURCE_TREASURY))
        return [], False
    if not rows:
        problems.failed.append({"source": SOURCE_TREASURY, "error": MSG_NO_YIELD_ROWS.format(days=lookback)})
        return rows, False
    problems.notes.append(MSG_TREASURY_NOTE.format(count=len(rows), latest=max(row["date"] for row in rows)))
    return rows, True


def collect_fred(client, series: dict, today: date, lookback: int, now: str, problems: Problems) -> tuple[list, bool]:
    """(rows, whether any series answered with values) of the configured FRED series."""
    rows, answered = [], 0
    since = today - timedelta(days=lookback)
    for series_id, meta in (series or {}).items():
        meta = meta or {}
        url = FRED_URL.format(series_id=series_id, start=since)
        try:
            text = client.get(url, headers=HEADERS_CSV).decode("utf-8-sig")
        except FetchError as exc:
            problems.failed.append(exc.entry(f"fred:{series_id}"))
            continue
        found = parse_fred(text, series_id, since, meta.get("unit", UNIT_PERCENT), meta.get("name", series_id), now)
        if not found:
            problems.failed.append(
                {"source": f"fred:{series_id}", "url": url, "error": MSG_NO_FRED_VALUES.format(days=lookback)}
            )
            continue
        answered += 1
        rows += found
    return rows, answered > 0


def collect(cfg: dict, client, today: date, now: str) -> dict:
    """One macro run: Treasury, FRED and Cboe, stored when new or revised; returns the JSON summary."""
    market, settings = cfg[CFG_MARKET], cfg[CFG_MACRO]
    lookback = int(settings.get("lookback_days", DEFAULT_MACRO_LOOKBACK_DAYS))
    problems = Problems()
    rows: list[dict] = []
    sources_ok = 0
    if settings.get("treasury", True):
        found, source_ok = collect_treasury(client, today, lookback, now, problems)
        rows += found
        sources_ok += source_ok
    found, source_ok = collect_fred(client, settings.get("fred"), today, lookback, now, problems)
    rows += found
    sources_ok += source_ok
    if settings.get("cboe"):
        found, available = collect_cboe(client, cfg, today, settings["cboe"], now, problems)
        rows += found
        sources_ok += available > 0
    new = {KIND_MACRO: store_changed(market, KIND_MACRO, rows, today, MACRO_VALUE_COLUMNS)}
    out = summary(COLLECTOR_MACRO, market, new, problems, client)
    out["sources_ok"] = sources_ok
    return out


def main() -> int:
    """Entry point of scripts/collect_macro.py."""
    cfg = require_market(market_arg(__doc__).parse_args())
    if not cfg.get(CFG_MACRO):
        print(
            json.dumps(
                {
                    SUMMARY_COLLECTOR: COLLECTOR_MACRO,
                    SUMMARY_MARKET: cfg[CFG_MARKET],
                    SUMMARY_SKIPPED: MSG_SKIPPED_NO_MACRO,
                }
            )
        )
        return 0
    client = FreeSourceClient(pause=float(cfg[CFG_MACRO].get("pause_seconds", DEFAULT_MACRO_PAUSE_SECONDS)))
    out = collect(cfg, client, utc_today(), utc_now())
    print(json.dumps(out, indent=2))
    return 1 if out["sources_ok"] == 0 else 0
