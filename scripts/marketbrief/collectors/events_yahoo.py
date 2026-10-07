"""Yahoo Finance part of the events collector: the earnings calendar, dividends and past earnings dates of one
ticker. yfinance hides most request errors behind empty answers, so each gap is reported with `what` it is.

The earnings-calendar page (finance.yahoo.com) is tried first for past earnings dates; if it fails (e.g. a network
that refuses the host) the screener fallback (query1) supplies the dates."""

from __future__ import annotations

from datetime import date

import pandas as pd

from marketbrief.collectors.event_timing import as_dates, timing
from marketbrief.constants.columns import COL_TICKER
from marketbrief.constants.events import (
    EARNINGS_DATES_LIMIT,
    EARNINGS_DATES_METHODS,
    ERROR_TEXT_LIMIT,
    FIELD_EX_DIVIDEND_DATE,
    METHOD_ERROR_LIMIT,
    MSG_CALENDAR_LISTS_EX_DIVIDEND,
    MSG_EMPTY_CALENDAR,
    MSG_METHOD_ERROR,
    MSG_NO_DIVIDENDS,
    MSG_STORED_DIVIDENDS,
    PRIORITY_CALL,
    PRIORITY_REPORT,
    TIMING_BEFORE_OPEN,
    WHAT_CALENDAR,
    WHAT_DIVIDENDS,
    YAHOO_CALL,
    YAHOO_EARNINGS,
    YAHOO_ESTIMATE_COLUMNS,
    YAHOO_EVENT_TYPE_COLUMN,
)

DIVIDEND_DECIMALS = 6


def estimate_rows(cfg: dict, frame: pd.DataFrame) -> list[dict]:
    """Yahoo's consensus EPS, reported EPS and surprise per earnings report of the frame (issue #17): report_at
    (UTC), report_date (exchange-local) and the values present; reports without any value are left out."""
    columns = {yahoo: ours for yahoo, ours in YAHOO_ESTIMATE_COLUMNS.items() if yahoo in frame.columns}
    if not columns:
        return []
    kinds = frame[YAHOO_EVENT_TYPE_COLUMN] if YAHOO_EVENT_TYPE_COLUMN in frame.columns else None
    rows = []
    for position, (stamp, values) in enumerate(frame[list(columns)].iterrows()):
        if (kinds is not None and kinds.iloc[position] != YAHOO_EARNINGS) or values.isna().all():
            continue
        stamp = pd.Timestamp(stamp)
        if stamp.tzinfo is None:
            continue  # no time zone: the report time is unknown
        found = {ours: (None if pd.isna(values[yahoo]) else round(float(values[yahoo]), 4)) for yahoo, ours in columns.items()}
        rows.append({"report_at": stamp.tz_convert("UTC").isoformat(), "report_date": timing(cfg, stamp)[0].isoformat(), **found})
    return rows


def yf_earnings(
    cfg: dict, ticker, limit: int = EARNINGS_DATES_LIMIT
) -> tuple[list[tuple[date, str | None, int]], str | None, list[str], list[dict]]:
    """Past earnings (date, timing, priority) from yfinance: the earnings-calendar page
    (finance.yahoo.com), else the screener endpoint (query1). Report rows beat earnings-call rows
    (a call only times the release if it is before the open). The third value lists each
    method's error ("<method>: <error>") when every method tried raised, so nothing was learnt;
    a method that answers with no rows is a real "no earnings dates", not an error. The fourth value holds
    the frame's consensus rows (estimate_rows)."""
    frame, used, errors, answered = None, None, [], False
    for method_name in EARNINGS_DATES_METHODS:
        method = getattr(ticker, method_name, None)
        if method is None:
            continue
        try:
            frame = method(limit=limit)
            answered = True
        except Exception as exc:
            frame = None
            errors.append(MSG_METHOD_ERROR.format(method=method_name.strip("_"), error=str(exc)[:METHOD_ERROR_LIMIT]))
        if frame is not None and not frame.empty:
            used = method_name.strip("_")
            break
    if frame is None or frame.empty:
        return [], None, ([] if answered else errors), []
    kinds = (
        frame[YAHOO_EVENT_TYPE_COLUMN]
        if YAHOO_EVENT_TYPE_COLUMN in frame.columns
        else pd.Series(YAHOO_EARNINGS, index=frame.index)
    )
    found = []
    for stamp, kind in zip(frame.index, kinds):
        if kind not in (YAHOO_EARNINGS, YAHOO_CALL):
            continue
        day, when = timing(cfg, stamp)
        if kind == YAHOO_CALL:
            found.append((day, when if when == TIMING_BEFORE_OPEN else None, PRIORITY_CALL))
        else:
            found.append((day, when, PRIORITY_REPORT))
    return found, used, [], estimate_rows(cfg, frame)


def dividends_expected(calendar: dict | None, stored_count: int, since: date) -> str | None:
    """Why this ticker should have dividends in the backfill window (some are stored for it, or
    Yahoo's calendar lists an ex-dividend date inside the window), or None."""
    if stored_count:
        return MSG_STORED_DIVIDENDS.format(count=stored_count)
    listed = [day for day in as_dates((calendar or {}).get(FIELD_EX_DIVIDEND_DATE)) if day >= since]
    return MSG_CALENDAR_LISTS_EX_DIVIDEND.format(day=max(listed)) if listed else None


def read_calendar(ticker, key: str, failed: list[dict]) -> dict | None:
    """Yahoo's calendar of a ticker ({} when empty; None when the request raised); gaps go to `failed`."""
    try:
        calendar = ticker.calendar or {}
        if not calendar:  # yfinance answers a failed request with {}; a listed stock has an earnings entry
            failed.append({COL_TICKER: key, "what": WHAT_CALENDAR, "error": MSG_EMPTY_CALENDAR})
        return calendar
    except Exception as exc:
        failed.append({COL_TICKER: key, "what": WHAT_CALENDAR, "error": str(exc)[:ERROR_TEXT_LIMIT]})
        return None


def read_dividends(
    ticker, key: str, calendar: dict | None, stored_count: int, since: date, failed: list[dict]
) -> dict[date, float]:
    """{ex-date: amount} of the dividends Yahoo lists; a missing answer where dividends are expected is a failure."""
    try:  # yfinance answers a failed price-history request with an empty series
        series = ticker.dividends
        dividends = (
            {stamp.date(): round(float(amount), DIVIDEND_DECIMALS) for stamp, amount in series.items()}
            if series is not None
            else {}
        )
        why = None if dividends else dividends_expected(calendar, stored_count, since)
        if why:
            failed.append({COL_TICKER: key, "what": WHAT_DIVIDENDS, "error": MSG_NO_DIVIDENDS.format(why=why)})
        return dividends
    except Exception as exc:
        failed.append({COL_TICKER: key, "what": WHAT_DIVIDENDS, "error": str(exc)[:ERROR_TEXT_LIMIT]})
        return {}
