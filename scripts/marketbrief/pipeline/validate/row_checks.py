"""Day files and rows: reading, type and schema problems, tickers of rows."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
from marketbrief.utils.timefmt import ISO_UTC, as_utc_timestamp
from marketbrief.core import paths, schemas
from marketbrief.constants.validation import TRADING_DATE_KINDS
from marketbrief.constants.validation import (
    MSG_LAST_LINE_HAS_NO_NEWLINE_TRUNCATED,
    MSG_LINE_IS_NOT_A_JSON_OBJECT,
    MSG_LINE_IS_NOT_JSON,
    MSG_MORE_PROBLEMS_OMITTED,
    MSG_ROW_TYPE_PROBLEM,
    MSG_ROW_FIELDS_NOT_IN_THE_SCHEMA,
    MSG_ROW_IS_IN_THE_FUTURE_NOW,
    MSG_ROW_MISSING_ID,
)


def kind_files(market: str, kind: str) -> list[Path]:
    ext = schemas.SCHEMAS[kind][0]
    return sorted((paths.data_dir(market) / kind).glob(f"**/*.{ext}"))


def file_day(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem[:10])
    except ValueError:
        return None


def todays_files(market: str, kind: str, today: date) -> list[Path]:
    """Files this run wrote: named today (UTC), or, for kinds named by the trading date, any file of
    the last 10 days holding a row written today."""
    files = kind_files(market, kind)
    if kind not in TRADING_DATE_KINDS:
        return [path for path in files if file_day(path) == today]
    col, out = TRADING_DATE_KINDS[kind], []
    for path in files:
        file_date = file_day(path)
        # adjustments are filed by ex-date, which can lie further back than 10 days: all files are read
        if file_date is None or (kind != "adjustments" and file_date < today - timedelta(days=10)):
            continue
        if path.stat().st_size == 0 or any(
            row.get(col) and str(row[col])[:10] == str(today) for row in read_rows(path)[0]
        ):
            out.append(path)
    return out


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
    """(rows, problems) of one data file: truncation, bad JSON, empty file."""
    problems, rows = [], []
    raw = path.read_bytes()
    if not raw:
        return [], ["empty file"]
    if not raw.endswith(b"\n"):
        problems.append(MSG_LAST_LINE_HAS_NO_NEWLINE_TRUNCATED)
    text = raw.decode("utf-8", errors="replace")
    if path.suffix == ".csv":
        reader = csv.DictReader(text.splitlines())
        return list(reader), problems
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(MSG_LINE_IS_NOT_JSON.format(index=index, msg=e.msg))
            continue
        if not isinstance(row, dict):
            problems.append(MSG_LINE_IS_NOT_A_JSON_OBJECT.format(index=index))
            continue
        rows.append(row)
    return rows, problems


def number_problem(value, typ: str, csv_row: bool) -> str | None:
    """Why a value is not a DOUBLE, INTEGER or BIGINT (None = fits)."""
    if csv_row:
        try:
            number = float(value)
        except ValueError:
            return "not a number"
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        return "not a number"
    else:
        number = float(value)
    return "not an integer" if typ != "DOUBLE" and number != int(number) else None


def date_problem(value) -> str | None:
    """Why a value is not a YYYY-MM-DD date (None = fits)."""
    try:
        date.fromisoformat(str(value)[:10])
    except ValueError:
        return "not YYYY-MM-DD"
    return None if len(str(value)) == 10 else "not YYYY-MM-DD"


def text_boolean_or_list_problem(value, typ: str, csv_row: bool) -> str | None:
    """Why a value is not text, true/false, an ISO UTC timestamp or a list of text (None = fits or JSON)."""
    if typ == "VARCHAR":
        return None if isinstance(value, str) else "not text"
    if typ == "BOOLEAN":
        return None if isinstance(value, bool) or (csv_row and value in ("true", "false")) else "not true/false"
    if typ == "TIMESTAMPTZ":
        return None if isinstance(value, str) and ISO_UTC.match(value) else "not an ISO 8601 UTC timestamp"
    if typ.endswith("[]"):
        is_text_list = isinstance(value, list) and all(item is None or isinstance(item, str) for item in value)
        return None if is_text_list else "not a list of text"
    return None  # JSON


def type_problem(value, typ: str, csv_row: bool) -> str | None:
    """Why a value does not fit a DuckDB column type (None = fits; null always fits)."""
    if value is None or (csv_row and value == ""):
        return None
    if typ in ("DOUBLE", "INTEGER", "BIGINT"):
        return number_problem(value, typ, csv_row)
    if typ == "DATE":
        return date_problem(value)
    return text_boolean_or_list_problem(value, typ, csv_row)


def check_rows(kind: str, rows: list[dict], csv_row: bool, now: pd.Timestamp, tol: timedelta) -> list[str]:
    """Schema and timestamp problems of one kind's rows (at most a few per kind)."""
    cols = schemas.SCHEMAS[kind][1]
    out = []
    for index, row in enumerate(rows, 1):
        unknown = [key for key in row if key not in cols]
        if unknown:
            out.append(MSG_ROW_FIELDS_NOT_IN_THE_SCHEMA.format(index=index, kind=kind, unknown=unknown))
        if "id" in cols and not row.get("id"):
            out.append(MSG_ROW_MISSING_ID.format(index=index))
        for key, typ in cols.items():
            if key not in row:
                continue
            why = type_problem(row[key], typ, csv_row)
            if why:
                out.append(MSG_ROW_TYPE_PROBLEM.format(index=index, key=key, value=str(row[key])[:40], why=why))
            elif typ == "TIMESTAMPTZ" and row[key]:
                timestamp = as_utc_timestamp(row[key])
                if timestamp is not None and timestamp > now + tol:
                    out.append(
                        MSG_ROW_IS_IN_THE_FUTURE_NOW.format(
                            index=index, key=key, value=row[key], isoformat=now.isoformat()
                        )
                    )
        if len(out) >= 5:
            out.append(MSG_MORE_PROBLEMS_OMITTED)
            break
    return out


def tickers_in(rows: list[dict]) -> list[str]:
    return [str(row.get("ticker")) for row in rows if row.get("ticker")]
