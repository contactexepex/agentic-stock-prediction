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


def kind_files(market: str, kind: str) -> list[Path]:
    ext = schemas.SCHEMAS[kind][0]
    return sorted((paths.data_dir(market) / kind).glob(f"**/*.{ext}"))


def file_day(p: Path) -> date | None:
    try:
        return date.fromisoformat(p.stem[:10])
    except ValueError:
        return None


def todays_files(market: str, kind: str, today: date) -> list[Path]:
    """Files this run wrote: named today (UTC), or, for kinds named by the trading date, any file of
    the last 10 days holding a row written today."""
    files = kind_files(market, kind)
    if kind not in TRADING_DATE_KINDS:
        return [p for p in files if file_day(p) == today]
    col, out = TRADING_DATE_KINDS[kind], []
    for p in files:
        d = file_day(p)
        # adjustments are filed by ex-date, which can lie further back than 10 days: all files are read
        if d is None or (kind != "adjustments" and d < today - timedelta(days=10)):
            continue
        if p.stat().st_size == 0 or any(r.get(col) and str(r[col])[:10] == str(today) for r in read_rows(p)[0]):
            out.append(p)
    return out


def read_rows(p: Path) -> tuple[list[dict], list[str]]:
    """(rows, problems) of one data file: truncation, bad JSON, empty file."""
    problems, rows = [], []
    raw = p.read_bytes()
    if not raw:
        return [], ["empty file"]
    if not raw.endswith(b"\n"):
        problems.append("last line has no newline (truncated write?)")
    text = raw.decode("utf-8", errors="replace")
    if p.suffix == ".csv":
        reader = csv.DictReader(text.splitlines())
        return list(reader), problems
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"line {i} is not JSON ({e.msg})")
            continue
        if not isinstance(r, dict):
            problems.append(f"line {i} is not a JSON object")
            continue
        rows.append(r)
    return rows, problems


def type_problem(v, typ: str, csv_row: bool) -> str | None:
    """Why a value does not fit a DuckDB column type (None = fits; null always fits)."""
    if v is None or (csv_row and v == ""):
        return None
    if typ == "VARCHAR":
        return None if isinstance(v, str) else "not text"
    if typ in ("DOUBLE", "INTEGER", "BIGINT"):
        if csv_row:
            try:
                x = float(v)
            except ValueError:
                return "not a number"
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return "not a number"
            x = float(v)
        if typ != "DOUBLE" and x != int(x):
            return "not an integer"
        return None
    if typ == "BOOLEAN":
        return None if isinstance(v, bool) or (csv_row and v in ("true", "false")) else "not true/false"
    if typ == "DATE":
        try:
            date.fromisoformat(str(v)[:10])
            return None if len(str(v)) == 10 else "not YYYY-MM-DD"
        except ValueError:
            return "not YYYY-MM-DD"
    if typ == "TIMESTAMPTZ":
        return None if isinstance(v, str) and ISO_UTC.match(v) else "not an ISO 8601 UTC timestamp"
    if typ.endswith("[]"):
        return None if isinstance(v, list) and all(x is None or isinstance(x, str) for x in v) else "not a list of text"
    return None  # JSON


def check_rows(kind: str, rows: list[dict], csv_row: bool, now: pd.Timestamp, tol: timedelta) -> list[str]:
    """Schema and timestamp problems of one kind's rows (at most a few per kind)."""
    cols = schemas.SCHEMAS[kind][1]
    out = []
    for i, r in enumerate(rows, 1):
        unknown = [k for k in r if k not in cols]
        if unknown:
            out.append(f"row {i}: fields not in the {kind} schema: {unknown}")
        if "id" in cols and not r.get("id"):
            out.append(f"row {i}: missing id")
        for k, typ in cols.items():
            if k not in r:
                continue
            why = type_problem(r[k], typ, csv_row)
            if why:
                out.append(f"row {i}: {k}={str(r[k])[:40]!r} {why}")
            elif typ == "TIMESTAMPTZ" and r[k]:
                t = as_utc_timestamp(r[k])
                if t is not None and t > now + tol:
                    out.append(f"row {i}: {k} {r[k]} is in the future (now {now.isoformat()})")
        if len(out) >= 5:
            out.append("...")
            break
    return out


def tickers_in(rows: list[dict]) -> list[str]:
    return [str(r.get("ticker")) for r in rows if r.get("ticker")]
