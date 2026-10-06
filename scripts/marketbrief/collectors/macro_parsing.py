"""Parsers of the macro sources (US Treasury par yield curve CSV, FRED series CSV, Cboe daily options statistics):
each gives `macro` rows, one per series and observation date."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import NamedTuple

from marketbrief.constants.columns import COL_DATE, COL_ID
from marketbrief.constants.free_sources import (
    FRED_DATE_COLUMNS,
    HEADERS_CSV,
    MSG_NOT_YIELD_CSV,
    SOURCE_CBOE,
    SOURCE_FRED,
    SOURCE_TREASURY,
    TENOR_PATTERN,
    TREASURY_DATE_COLUMN,
    TREASURY_DATE_FORMAT,
    TREASURY_URL,
    UNIT_PERCENT,
    UNIT_RATIO,
    YIELD_CURVE_PREVIEW,
)
from marketbrief.sources.errors import FetchError
from marketbrief.utils.numbers import parse_accounting_amount


class SeriesInfo(NamedTuple):
    """What a series is: its unit, display name and source."""

    unit: str
    name: str
    source: str


def macro_row(series: str, day: date, value: float, info: SeriesInfo, now: str, complete: bool = True) -> dict:
    """One `macro` row (id <series>-<date>)."""
    return {
        COL_ID: f"{series}-{day}",
        COL_DATE: str(day),
        "series": series,
        "name": info.name,
        "value": value,
        "unit": info.unit,
        "source": info.source,
        "first_seen_at": now,
        "complete": complete,
    }


def tenor_series(column: str) -> str | None:
    """'3 Mo' -> UST_3M, '1.5 Month' -> UST_1.5M, '10 Yr' -> UST_10Y; other columns -> None."""
    match = re.fullmatch(TENOR_PATTERN, column)
    if not match:
        return None
    return f"UST_{match.group(1)}{'M' if match.group(2).startswith('Mo') else 'Y'}"


def parse_treasury(text: str, since: date, now: str) -> list[dict]:
    """The par yield rows of the Treasury CSV from `since` on, one per tenor and day, in percent."""
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        try:
            day = datetime.strptime((record.get(TREASURY_DATE_COLUMN) or "").strip(), TREASURY_DATE_FORMAT).date()
        except ValueError:
            continue
        if day < since:
            continue
        for column, raw in record.items():
            series, value = tenor_series(column or ""), parse_accounting_amount(raw)
            if series and value is not None:
                info = SeriesInfo(UNIT_PERCENT, f"Treasury par yield {column.strip()}", SOURCE_TREASURY)
                rows.append(macro_row(series, day, value, info, now))
    return rows


def treasury(client, today: date, lookback: int, now: str) -> list[dict]:
    """The Treasury yield rows of the lookback window (the CSV of each year it touches)."""
    since = today - timedelta(days=lookback)
    rows = []
    for year in sorted({since.year, today.year}):
        url = TREASURY_URL.format(year=year)
        text = client.get(url, headers=HEADERS_CSV).decode("utf-8-sig")
        if not text.lstrip().startswith(TREASURY_DATE_COLUMN):
            raise FetchError(url, MSG_NOT_YIELD_CSV.format(preview=text[:YIELD_CURVE_PREVIEW]))
        rows += parse_treasury(text, since, now)
    return rows


def parse_fred(text: str, series_id: str, since: date, unit: str, name: str, now: str) -> list[dict]:
    """fredgraph.csv: a date column (observation_date, formerly DATE) and one column per id;
    '.' marks a day without a value."""
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        raw_day = record.get(FRED_DATE_COLUMNS[0]) or record.get(FRED_DATE_COLUMNS[1])
        try:
            day = date.fromisoformat((raw_day or "").strip())
        except ValueError:
            continue
        value = parse_accounting_amount(record.get(series_id))
        if day >= since and value is not None:
            rows.append(macro_row(series_id, day, value, SeriesInfo(unit, name, SOURCE_FRED), now))
    return rows


def parse_cboe(payload: dict, day: date, wanted: dict[str, str], now: str) -> tuple[list[dict], list[str]]:
    """`ratios` list -> (rows for the configured ratio names ({name in Cboe's file: series}),
    configured names absent or without a number). Rows are `complete` only when none is missing."""
    by_name = {
        (ratio.get("name") or "").strip().upper(): parse_accounting_amount(ratio.get("value"))
        for ratio in payload.get("ratios") or []
    }
    found = {name: by_name.get(name.upper()) for name in wanted}
    missing = sorted(name for name, value in found.items() if value is None)
    rows = [
        macro_row(
            series, day, found[name], SeriesInfo(UNIT_RATIO, f"Cboe {name}", SOURCE_CBOE), now, complete=not missing
        )
        for name, series in wanted.items()
        if found[name] is not None
    ]
    return rows, missing
