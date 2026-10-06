"""Parsers of the India flow sources: NSDL's "Daily Trends in FPI Investments" page and NSE's daily index close
file (ind_close_all_DDMMYYYY.csv)."""
from __future__ import annotations

import csv
import html
import io
import re
from datetime import date, datetime

from marketbrief.constants.columns import COL_DATE, COL_ID
from marketbrief.constants.free_sources import (BAD_ROW_PREVIEW, FPI_ASSET_EQUITY, FPI_ASSET_ROW_CELLS,
                                                FPI_ASSET_TOTAL, FPI_DATE_FORMAT, FPI_DERIVATIVE_TITLE,
                                                FPI_FULL_ROW_CELLS, FPI_ROUTE_ROW_CELLS, FPI_ROUTE_SUBTOTAL,
                                                FPI_ROUTE_TOTAL, FPI_TITLE_PATTERN, INDEX_DATE_FORMAT,
                                                MSG_FPI_BAD_ROWS, MSG_FPI_NO_TOTALS, MSG_FPI_TITLE_MISSING,
                                                MSG_INDEX_FILE_DATES, MSG_UNEXPECTED_HEADER, SOURCE_NSDL_FPI_DAILY,
                                                SOURCE_NSE_IND_CLOSE)
from marketbrief.utils.numbers import parse_accounting_amount
from marketbrief.utils.text import slugify

BYTE_ORDER_MARK = "﻿"
UNEXPECTED_HEADER_PREVIEW = 80
BAD_ROWS_SHOWN = 3
INDEX_COLUMNS = {"open": "Open Index Value", "high": "High Index Value", "low": "Low Index Value",
                 "close": "Closing Index Value", "change_pct": "Change(%)", "volume": "Volume",
                 "turnover_cr": "Turnover (Rs. Cr.)", "pe": "P/E", "pb": "P/B", "div_yield": "Div Yield"}


def table_cells(table_row: str) -> list[str]:
    """The text of each <td> of a table row, tags and entities removed, spaces collapsed."""
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", table_row, re.S)]


def fpi_row(reporting: date, asset: str, route: str, values: list, usd_inr, now: str) -> dict:
    """One `fpi` row: gross purchases, gross sales, net (INR crore) and net (USD million)."""
    return {COL_ID: f"nsdl-fpi-{reporting}-{slugify(asset)}-{slugify(route)}", "reporting_date": str(reporting),
            "asset_class": asset, "route": route, "gross_purchases_cr": values[0], "gross_sales_cr": values[1],
            "net_cr": values[2], "net_usd_mn": values[3], "usd_inr": usd_inr, "source": SOURCE_NSDL_FPI_DAILY,
            "first_seen_at": now}


def fpi_layout_problems(rows: list[dict], bad: list[str]) -> str | None:
    """The problems of a parse (rows with unreadable numbers, no Equity sub-total or Total line), joined, or None."""
    problems = []
    if bad:
        problems.append(MSG_FPI_BAD_ROWS.format(count=len(bad), rows=bad[:BAD_ROWS_SHOWN]))
    has_equity = any(r["asset_class"] == FPI_ASSET_EQUITY and r["route"].lower() == FPI_ROUTE_SUBTOTAL for r in rows)
    if not has_equity or not any(r["asset_class"] == FPI_ASSET_TOTAL for r in rows):
        problems.append(MSG_FPI_NO_TOTALS.format(count=len(rows)))
    return "; ".join(problems) or None


def parse_fpi(page: str, now: str) -> tuple[list[dict], str | None]:
    """Rows of the investment table, and a problem (layout changed) or None."""
    title = re.search(FPI_TITLE_PATTERN, page)
    if not title:
        return [], MSG_FPI_TITLE_MISSING
    reporting = datetime.strptime(title.group(1), FPI_DATE_FORMAT).date()
    end = page.find(FPI_DERIVATIVE_TITLE, title.end())
    body = page[title.end(): end if end > 0 else len(page)]
    rows, bad, asset, usd_inr = [], [], None, None
    for table_row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = table_cells(table_row)
        numbers = [parse_accounting_amount(cell) for cell in cells]
        if len(cells) == FPI_FULL_ROW_CELLS:     # reporting date | asset | route | 4 numbers | USD/INR rate
            asset, route, values = cells[1], cells[2], numbers[3:7]
            usd_inr = parse_accounting_amount(cells[7]) or usd_inr
        elif len(cells) == FPI_ASSET_ROW_CELLS:  # asset | route | 4 numbers
            asset, route, values = cells[0], cells[1], numbers[2:6]
        elif len(cells) == FPI_ROUTE_ROW_CELLS:  # route | 4 numbers (or Total | 4 numbers)
            route, values = cells[0], numbers[1:5]
            if route.lower() == FPI_ROUTE_TOTAL:
                asset = FPI_ASSET_TOTAL
        else:
            continue
        if asset is None or any(v is None for v in values):
            bad.append(" | ".join(cells)[:BAD_ROW_PREVIEW])   # a data-shaped row we cannot read: reported, not skipped
            continue
        rows.append(fpi_row(reporting, asset, route, values, usd_inr, now))
    return rows, fpi_layout_problems(rows, bad)


def index_row(record: dict, day: date, name: str, sector, now: str) -> dict:
    """One `indices` row of an index close file record."""
    return {COL_ID: f"nse-idx-{day}-{slugify(name)}", COL_DATE: str(day), "index_name": name, "sector": sector,
            **{column: parse_accounting_amount(record.get(header)) for column, header in INDEX_COLUMNS.items()},
            "source": SOURCE_NSE_IND_CLOSE, "first_seen_at": now}


def parse_indices(text: str, day: date, names: dict, now: str) -> tuple[list[dict], list[str], str | None]:
    """(rows for the configured indices, configured names absent from the file, problem or None)."""
    reader = csv.DictReader(io.StringIO(text.lstrip(BYTE_ORDER_MARK)))
    if not reader.fieldnames or "Index Name" not in reader.fieldnames:
        return [], [], MSG_UNEXPECTED_HEADER.format(preview=repr(text[:UNEXPECTED_HEADER_PREVIEW]))
    wanted = {name.lower(): (name, sector) for name, sector in names.items()}
    rows, served = [], set()
    for record in reader:
        record = {(k or "").strip(): (v or "").strip() for k, v in record.items()}
        hit = wanted.get(record.get("Index Name", "").lower())
        if not hit:
            continue
        try:
            file_day = datetime.strptime(record.get("Index Date", ""), INDEX_DATE_FORMAT).date()
        except ValueError:
            continue
        served.add(file_day)
        rows.append(index_row(record, file_day, hit[0], hit[1], now))
    missing = sorted(name for name, _ in wanted.values() if name not in {r["index_name"] for r in rows})
    problem = (MSG_INDEX_FILE_DATES.format(day=day, served=sorted(map(str, served)))
               if served and day not in served else None)
    return rows, missing, problem
