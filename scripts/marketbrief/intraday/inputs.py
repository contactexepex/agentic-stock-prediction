"""What a check reads from data/ as of its time (check_at): the session's published ranges, the open calls and
model scores, the features (beta, volatility), the previous closes, and the news, announcements and events
behind the attribution. Every query keeps rows known by check_at only."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.constants.indicators import TRADING_DAYS
from marketbrief.core.calendar import next_session, sessions_ahead
from marketbrief.intraday.constants import CALL_MODEL, CALL_PREDICTION, EVENT_TYPES

CALL_LOOKBACK_DAYS = 12   # calendar days back that cover the as-of dates of open 5-day calls


def records(frame: pd.DataFrame) -> list[dict]:
    """DataFrame rows as dicts with None for missing values."""
    rows = frame.to_dict("records")
    return [{key: (None if _missing(value) else value) for key, value in row.items()} for row in rows]


def _missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def published_ranges(con, session_date: date, check_at: datetime) -> dict[str, dict[int, dict]]:
    """{ticker: {horizon: range}}: the first published range per id for this session, made by check_at."""
    frame = con.execute(
        "SELECT DISTINCT ON (id) id, ticker, horizon_days, lo50, hi50, lo80, hi80, sigma_h, notes, made_at "
        "FROM ranges WHERE session_date = ? AND made_at <= ? ORDER BY id, made_at",
        [session_date, check_at],
    ).df()
    out: dict[str, dict[int, dict]] = {}
    for row in records(frame):
        out.setdefault(row["ticker"], {})[int(row["horizon_days"])] = row
    return out


def call_window(cfg: dict, as_of: date, horizon: int) -> tuple[date, date]:
    """(entry date, last session) of a call: entry at the open of the session after as-of."""
    entry = next_session(cfg, as_of, include=False)
    return entry, sessions_ahead(cfg, entry, horizon)[-1]


def open_calls(con, cfg: dict, session_date: date, check_at: datetime) -> dict[str, list[dict]]:
    """{ticker: calls}: predictions made and model scores computed by check_at whose holding window (entry open
    to the close of the last session) contains this session. Each model score id: its newest row by check_at."""
    since = session_date - timedelta(days=CALL_LOOKBACK_DAYS)
    predictions = con.execute(
        "SELECT id, ticker, horizon_days, as_of_date, direction, confidence, NULL AS prob_up FROM predictions "
        "WHERE made_at <= ? AND as_of_date >= ? AND as_of_date < ? ORDER BY id",
        [check_at, since, session_date],
    ).df()
    scores = con.execute(
        "SELECT DISTINCT ON (id) id, ticker, horizon_days, as_of_date, NULL AS direction, NULL AS confidence, "
        "prob_up FROM model_scores WHERE computed_at <= ? AND as_of_date >= ? AND as_of_date < ? "
        "ORDER BY id, computed_at DESC",
        [check_at, since, session_date],
    ).df()
    out: dict[str, list[dict]] = {}
    for source, frame in ((CALL_PREDICTION, predictions), (CALL_MODEL, scores)):
        for row in records(frame):
            as_of = pd.Timestamp(row["as_of_date"]).date()
            entry, last = call_window(cfg, as_of, int(row["horizon_days"]))
            if entry <= session_date <= last:
                out.setdefault(row["ticker"], []).append({
                    "source": source, "id": row["id"], "horizon_days": int(row["horizon_days"]),
                    "direction": row["direction"], "prob_up": row["prob_up"], "entry_date": entry.isoformat(),
                    "sessions_held": len(sessions_between(cfg, entry, session_date)),
                })
    return out


def sessions_between(cfg: dict, start: date, end: date) -> list[date]:
    """Sessions from start to end inclusive."""
    found, day = [], start
    while day <= end:
        day = next_session(cfg, day)
        if day <= end:
            found.append(day)
        day += timedelta(days=1)
    return found


def entry_opens(con, keys: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """{(ticker, entry date): open} from the stored bars (adjusted basis)."""
    if not keys:
        return {}
    frame = con.execute(
        "SELECT ticker, CAST(date AS VARCHAR) AS day, open FROM ohlc WHERE list_contains(?, ticker || '|' || "
        "CAST(date AS VARCHAR))",
        [[f"{ticker}|{day}" for ticker, day in keys]],
    ).df()
    return {(row["ticker"], row["day"]): float(row["open"]) for row in records(frame) if row["open"] is not None}


def latest_features(con, session_date: date, check_at: datetime) -> dict[str, dict]:
    """{ticker: {beta_1y, ewma_vol}} of the newest features before this session, computed by check_at."""
    frame = con.execute(
        "SELECT DISTINCT ON (ticker) ticker, beta_1y, ewma_vol FROM features WHERE as_of_date < ? "
        "AND computed_at <= ? ORDER BY ticker, as_of_date DESC, computed_at DESC",
        [session_date, check_at],
    ).df()
    return {row["ticker"]: row for row in records(frame)}


def daily_sigma(bands: dict[int, dict], features: dict | None) -> tuple[float | None, str | None]:
    """The 1-day sigma: the published 1-day range's sigma_h, else the 5-day range's sigma_h / sqrt(5), else the
    features' EWMA vol / sqrt(252) (the fallback used is returned as a note)."""
    range_1d, range_5d = bands.get(1), bands.get(5)
    if range_1d and range_1d.get("sigma_h"):
        return float(range_1d["sigma_h"]), None
    if range_5d and range_5d.get("sigma_h"):
        return float(range_5d["sigma_h"]) / math.sqrt(5), "sigma_from_5d_range"
    if features and features.get("ewma_vol"):
        return float(features["ewma_vol"]) / math.sqrt(TRADING_DAYS), "sigma_from_ewma_vol"
    return None, "no_sigma"


def previous_closes(con, session_date: date) -> dict[str, float]:
    """{symbol: close} of each symbol's newest stored bar before this session."""
    frame = con.execute(
        "SELECT DISTINCT ON (ticker) ticker, close FROM ohlc WHERE date < ? ORDER BY ticker, date DESC",
        [session_date],
    ).df()
    return {row["ticker"]: float(row["close"]) for row in records(frame) if row["close"] is not None}


def news_since(con, ticker: str, since: datetime, check_at: datetime, limit: int) -> list[dict]:
    """News tagged with the ticker first seen in [since, check_at] and published by check_at, with each id's
    verification status as of check_at (unverified when no status row lists it) and its enrichment by then."""
    frame = con.execute(
        "WITH s AS (SELECT news_id, status FROM news_status_ids_asof(?) WHERE ticker = ?), "
        "e AS (SELECT DISTINCT ON (id) id, materiality, sentiment FROM news_enriched WHERE analyzed_at <= ? "
        "ORDER BY id, analyzed_at DESC) "
        "SELECT n.id, n.title, n.source, n.published_at, n.first_seen_at, coalesce(s.status, 'unverified') AS status, "
        "e.materiality, e.sentiment FROM news n LEFT JOIN s ON s.news_id = n.id LEFT JOIN e ON e.id = n.id "
        "WHERE list_contains(n.tickers, ?) AND n.first_seen_at >= ? AND n.first_seen_at <= ? "
        "AND coalesce(n.published_at, n.first_seen_at) <= ? ORDER BY n.first_seen_at, n.id LIMIT ?",
        [check_at, ticker, check_at, ticker, since, check_at, check_at, limit],
    ).df()
    return records(frame)


def announcements_since(con, ticker: str, since: datetime, check_at: datetime, limit: int) -> list[dict]:
    """Exchange announcements (India, NSE) of the ticker first seen in [since, check_at], public by check_at."""
    frame = con.execute(
        "SELECT DISTINCT ON (id) id, subject, category, published_at, first_seen_at FROM announcements "
        "WHERE ticker = ? AND first_seen_at >= ? AND first_seen_at <= ? AND coalesce(published_at, first_seen_at) "
        "<= ? ORDER BY id, first_seen_at",
        [ticker, since, check_at, check_at],
    ).df()
    rows = sorted(records(frame), key=lambda row: (row["first_seen_at"], row["id"]))
    return rows[:limit]


def events_today(con, ticker: str, session_date: date, check_at: datetime) -> list[dict]:
    """The ticker's earnings and ex-dividend events dated this session, known by check_at."""
    frame = con.execute(
        "SELECT DISTINCT ON (id) id, type, name, timing, amount FROM events WHERE ticker = ? AND date = ? "
        "AND list_contains(?, type) AND first_seen_at <= ? ORDER BY id, first_seen_at",
        [ticker, session_date, list(EVENT_TYPES), check_at],
    ).df()
    return records(frame)
