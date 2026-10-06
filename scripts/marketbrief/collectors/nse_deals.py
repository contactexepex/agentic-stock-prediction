"""Bulk and block deals of the India relations collector: the large-deal snapshot (complete for the latest session),
falling back to the archive CSVs; `--deals-backfill N` also asks the historical API per ticker for the last N days
(market-wide calls are capped at 70 rows) -> data/india/deals/. Ids ignore the source, so a deal seen twice is
stored once."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from marketbrief.collectors.nse_runner import NseRun, coverage
from marketbrief.constants.columns import COL_DATE, COL_ID, COL_TICKER
from marketbrief.constants.nse_collection import (
    BACKFILL_CAP_ROWS,
    DEAL_TYPES,
    ENDPOINT_DEAL_HISTORY,
    ENDPOINT_DEAL_SNAPSHOT,
    MSG_DEALS_ARCHIVE_NOTE,
    MSG_DEALS_BACKFILL_NOTE,
    MSG_DEALS_CAP,
    MSG_DEALS_COVERAGE,
    NO_RECORDS,
    NSE_DATE_ARGUMENT,
    SOURCE_ARCHIVE,
    SOURCE_HISTORICAL,
    SOURCE_SNAPSHOT,
)
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import parse_day, pick, rows_of, short_hash
from marketbrief.utils.numbers import parse_nse_number

VALUE_DECIMALS = 2


def deal_record(row: dict, deal_type: str, source: str, symbols: dict[str, str], now: str) -> dict | None:
    """One bulk/block deal from any NSE shape: historical (BD_*), snapshot (camelCase), archive CSV."""
    ticker = symbols.get((pick(row, "BD_SYMBOL", "symbol", "Symbol") or "").upper())
    if not ticker:
        return None
    day = parse_day(pick(row, "BD_DT_DATE", "date", "Date"))
    client = pick(row, "BD_CLIENT_NAME", "clientName", "Client Name")
    side = (pick(row, "BD_BUY_SELL", "buySell", "Buy/Sell", "Buy / Sell") or "").lower() or None
    shares = parse_nse_number(pick(row, "BD_QTY_TRD", "qty", "Quantity Traded"))
    price = parse_nse_number(pick(row, "BD_TP_WATP", "watp", "Trade Price / Wght. Avg. Price"))
    if day is None or shares is None:
        return None
    return {
        COL_ID: f"nse-{deal_type}-{day}-{ticker}-" + short_hash(client, side, shares, price),
        COL_DATE: str(day),
        COL_TICKER: ticker,
        "deal_type": deal_type,
        "client": client,
        "side": side,
        "shares": shares,
        "price": price,
        "value": round(shares * price, VALUE_DECIMALS) if price else None,
        "remarks": pick(row, "BD_REMARKS", "remarks", "Remarks"),
        "source": source,
        "first_seen_at": now,
    }


def deal_records(rows: list[dict], deal_type: str, source: str, run: NseRun) -> list[dict]:
    """The watchlist deals among rows of one NSE shape."""
    return [d for r in rows if (d := deal_record(r, deal_type, source, run.symbols, run.now))]


def snapshot_deals(run: NseRun) -> list[dict]:
    """The latest session's bulk and block deals from the large-deal snapshot."""
    snapshot = run.nse.json(ENDPOINT_DEAL_SNAPSHOT)
    total, found = 0, []
    for deal_type in DEAL_TYPES:
        rows = rows_of(snapshot, f"{deal_type.upper()}_DEALS_DATA")
        total += len(rows)
        found += deal_records(rows, deal_type, SOURCE_SNAPSHOT, run)
    coverage(MSG_DEALS_COVERAGE.format(as_on=snapshot.get("as_on_date")), total, len(found), run.problems)
    return found


def archive_deals(run: NseRun) -> tuple[list[dict], int]:
    """(deals, sources read) from the bulk.csv and block.csv archive files, the fallback when the snapshot fails."""
    found, ok = [], 0
    for deal_type in DEAL_TYPES:
        try:
            rows = list(csv.DictReader(io.StringIO(run.nse.text(f"/content/equities/{deal_type}.csv"))))
        except FetchError as exc:
            run.problems.failed.append(exc.entry(f"deals:{deal_type}:archive"))
            continue
        rows = [{(k or "").strip(): v for k, v in row.items()} for row in rows]
        rows = [row for row in rows if (row.get("Date") or "").strip().upper() != NO_RECORDS]
        records = deal_records(rows, deal_type, SOURCE_ARCHIVE, run)
        run.problems.notes.append(
            MSG_DEALS_ARCHIVE_NOTE.format(deal_type=deal_type, rows=len(rows), watchlist=len(records))
        )
        found += records
        ok += 1
    return found, ok


def backfill_deals(run: NseRun, backfill_days: int) -> tuple[list[dict], int, bool]:
    """(deals, calls answered, aborted): the per-ticker historical API for the last `backfill_days` days; aborted
    when the egress proxy refuses the host (every other call fails the same way)."""
    start, calls, found_rows, found, ok = run.today - timedelta(days=backfill_days), 0, 0, [], 0
    for symbol in run.symbols:
        for deal_type in DEAL_TYPES:
            try:
                rows = rows_of(
                    run.nse.json(
                        ENDPOINT_DEAL_HISTORY,
                        {
                            "optionType": f"{deal_type}_deals",
                            "symbol": symbol,
                            "from": start.strftime(NSE_DATE_ARGUMENT),
                            "to": run.today.strftime(NSE_DATE_ARGUMENT),
                        },
                    )
                )
            except FetchError as exc:
                run.problems.failed.append(exc.entry(f"deals:{deal_type}:backfill:{symbol}"))
                if exc.host:
                    return found, ok, True
                continue
            ok += 1
            calls, found_rows = calls + 1, found_rows + len(rows)
            if len(rows) >= BACKFILL_CAP_ROWS:
                run.problems.notes.append(MSG_DEALS_CAP.format(deal_type=deal_type, symbol=symbol))
            found += deal_records(rows, deal_type, SOURCE_HISTORICAL, run)
    run.problems.notes.append(MSG_DEALS_BACKFILL_NOTE.format(calls=calls, since=start, found=found_rows))
    return found, ok, False


def deals(run: NseRun, lookback: int, backfill_days: int = 0) -> tuple[list[dict], int]:
    """Latest session from the snapshot (archive CSV if it fails), plus optional per-ticker
    backfill. Ids ignore the source, so a deal seen twice is stored once. Returns (rows, sources_ok)."""
    since: date = run.today - timedelta(days=lookback)
    found, ok = [], 0
    try:
        found += snapshot_deals(run)
        ok += 1
    except FetchError as exc:
        run.problems.failed.append(exc.entry("deals:snapshot"))
        archived, archive_ok = archive_deals(run)
        found += archived
        ok += archive_ok
    if backfill_days:
        backfilled, backfill_ok, aborted = backfill_deals(run, backfill_days)
        found += backfilled
        ok += backfill_ok
        if aborted:
            return found, ok
        since = run.today - timedelta(days=backfill_days)
    return [d for d in found if d[COL_DATE] >= str(since)], ok
