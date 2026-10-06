"""Delivery percentages of the NSE primary-source collector: the security-wise bhavcopy (sec_bhavdata_full) of each
session in the lookback not yet stored -> data/india/delivery/. On a holiday NSE serves the previous session's
file, so ids use the file's date."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from marketbrief.collectors.nse_runner import NseRun, coverage
from marketbrief.constants.columns import COL_CLOSE, COL_DATE, COL_ID, COL_TICKER
from marketbrief.constants.kinds import KIND_DELIVERY
from marketbrief.constants.nse_collection import (
    BHAVCOPY_PATH,
    DELIVERY_ERROR_LIMIT,
    DELIVERY_ID_PREFIX,
    DELIVERY_SEEN_DAYS,
    MSG_DELIVERY_COVERAGE,
    MSG_DELIVERY_HOLIDAY,
    MSG_DELIVERY_MISSING,
    PUBLISHED_HOUR_IST,
    SOURCE_BHAVCOPY,
    WEEKEND_FIRST_DAY,
)
from marketbrief.core.storage import recent_ids
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import IST, parse_day
from marketbrief.utils.numbers import parse_nse_number

STORED_DATE_PART = 2  # ids are nse-dlv-<YYYY-MM-DD>-<ticker>
BHAVCOPY_SERIES = "EQ"


def delivery_row(record: dict, day: date, ticker: str, now: str) -> dict:
    """One `delivery` row of a bhavcopy record."""
    return {
        COL_ID: f"{DELIVERY_ID_PREFIX}{day}-{ticker}",
        COL_DATE: str(day),
        COL_TICKER: ticker,
        "series": BHAVCOPY_SERIES,
        COL_CLOSE: parse_nse_number(record.get("CLOSE_PRICE")),
        "volume": parse_nse_number(record.get("TTL_TRD_QNTY")),
        "delivery_qty": parse_nse_number(record.get("DELIV_QTY")),
        "delivery_pct": parse_nse_number(record.get("DELIV_PER")),
        "trades": parse_nse_number(record.get("NO_OF_TRADES")),
        "turnover_lacs": parse_nse_number(record.get("TURNOVER_LACS")),
        "source": SOURCE_BHAVCOPY,
        "first_seen_at": now,
    }


def delivery(run: NseRun, lookback: int) -> tuple[list[dict], int]:
    """(rows, bhavcopies read) of the sessions in the lookback that are not stored yet."""
    stored = {
        i.split("-", STORED_DATE_PART)[STORED_DATE_PART][:10]
        for i in recent_ids(run.market, KIND_DELIVERY, days=DELIVERY_SEEN_DAYS)
        if i.startswith(DELIVERY_ID_PREFIX)
    }
    ist_now = datetime.now(IST)
    found, ok = [], 0
    for back in range(lookback, -1, -1):
        day = run.today - timedelta(days=back)
        if (
            day.weekday() >= WEEKEND_FIRST_DAY
            or str(day) in stored
            or (day == ist_now.date() and ist_now.hour < PUBLISHED_HOUR_IST)
        ):
            continue  # weekend, already stored, or today's file not published yet
        try:
            text = run.nse.text(BHAVCOPY_PATH.format(day=day))
        except FetchError as exc:
            if exc.host:
                run.problems.failed.append(exc.entry(KIND_DELIVERY))
                return found, ok
            run.problems.notes.append(MSG_DELIVERY_MISSING.format(day=day, error=exc.error[:DELIVERY_ERROR_LIMIT]))
            continue
        ok += 1
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]
        served = {str(parse_day(r.get("DATE1"))) for r in rows if parse_day(r.get("DATE1"))}
        if served and str(day) not in served:  # on a holiday NSE serves the previous session's file
            run.problems.notes.append(MSG_DELIVERY_HOLIDAY.format(day=day, served=", ".join(sorted(served))))
        matched = 0
        for record in rows:
            ticker = run.symbols.get(record.get("SYMBOL", "").upper())
            if not ticker or record.get("SERIES") != BHAVCOPY_SERIES:
                continue
            matched += 1
            found.append(delivery_row(record, parse_day(record.get("DATE1")) or day, ticker, run.now))
        coverage(MSG_DELIVERY_COVERAGE.format(day=day), len(rows), matched, run.problems)
    return found, ok
