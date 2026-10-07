"""What a check reads from data/ as of its time (check_at): the session's published ranges, the open calls and
model scores, the features (beta, volatility), the previous closes, and the news, announcements and events
behind the attribution. Every query keeps rows known by check_at only."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.analytics import call_basis
from marketbrief.constants.indicators import TRADING_DAYS
from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE
from marketbrief.core.calendar import next_session, sessions_ahead
from marketbrief.intraday.constants import CALL_MODEL, CALL_PREDICTION, EVENT_TYPES
from marketbrief.intraday.settings import configured_horizons

CALL_LOOKBACK_DAYS = 12   # the minimum: covers the as-of dates of WS5's stored calls, whatever the horizon list
CALENDAR_DAYS_PER_SESSION = 2   # B9: a generous calendar-day bound per session of the longest horizon


def call_lookback_days(horizons: tuple[int, ...]) -> int:
    """Calendar days back to the oldest as-of date whose call can still be open: enough for the longest configured
    horizon plus the entry session, weekends and holidays (never below CALL_LOOKBACK_DAYS); the exact window is
    checked per call."""
    longest = max(horizons, default=0)
    return max(CALL_LOOKBACK_DAYS, CALENDAR_DAYS_PER_SESSION * (longest + 1) + 7)


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


def call_window(cfg: dict, as_of: date, horizon: int, basis: str) -> tuple[date, date]:
    """(first session, last session) of a call's scored return (analytics/call_basis.py): open_to_close buys at the
    open of D (the session after as-of) and sells at the close of D+1 (1d) or D+4 (5d); close_to_close runs from the
    as-of close to the close of the h-th session after it."""
    sessions = sessions_ahead(cfg, next_session(cfg, as_of, include=False), call_basis.target_offset(basis, horizon))
    return sessions[0], sessions[-1]


def open_calls(con, cfg: dict, session_date: date, check_at: datetime) -> dict[str, list[dict]]:
    """{ticker: calls}: predictions made and model scores computed by check_at whose scored window contains this
    session. Each model score id: its newest row by check_at (basis = its label_convention); a prediction's basis is
    call_basis.basis_for(made_at). entry_kind: open (open_to_close: the open of entry_date) or close (close_to_close:
    the as-of close)."""
    since = session_date - timedelta(days=call_lookback_days(configured_horizons()))
    predictions = con.execute(
        "SELECT id, ticker, horizon_days, as_of_date, made_at, direction, NULL AS prob_up, "
        "NULL AS label_convention FROM predictions WHERE made_at <= ? AND as_of_date >= ? AND as_of_date < ? "
        "ORDER BY id",
        [check_at, since, session_date],
    ).df()
    scores = con.execute(
        "SELECT DISTINCT ON (id) id, ticker, horizon_days, as_of_date, NULL AS made_at, NULL AS direction, prob_up, "
        "label_convention FROM model_scores WHERE computed_at <= ? AND as_of_date >= ? AND as_of_date < ? "
        "ORDER BY id, computed_at DESC",
        [check_at, since, session_date],
    ).df()
    rule = call_basis.switch()
    out: dict[str, list[dict]] = {}
    for source, frame in ((CALL_PREDICTION, predictions), (CALL_MODEL, scores)):
        for row in records(frame):
            as_of = pd.Timestamp(row["as_of_date"]).date()
            if source == CALL_PREDICTION:
                basis = call_basis.basis_for(row["made_at"], rule)
            else:
                basis = row["label_convention"] or LABEL_OPEN_TO_CLOSE
            first, last = call_window(cfg, as_of, int(row["horizon_days"]), basis)
            if first <= session_date <= last:
                by_open = basis == LABEL_OPEN_TO_CLOSE
                out.setdefault(row["ticker"], []).append({
                    "source": source, "id": row["id"], "horizon_days": int(row["horizon_days"]),
                    "direction": row["direction"], "prob_up": row["prob_up"], "basis": basis,
                    "entry_kind": "open" if by_open else "close",
                    "entry_date": (first if by_open else as_of).isoformat(), "last_session": last.isoformat(),
                    "sessions_held": len(sessions_between(cfg, first, session_date)),
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


# The split/bonus records known at a time (bind check_at twice): each id's first row detected by then, minus the ones
# a correction detected by then names in `supersedes` (the price_adjustments view, as of the time; issue #71).
ADJUSTMENTS_ASOF = (
    "adj AS (SELECT * FROM (SELECT DISTINCT ON (id) * FROM adjustments WHERE detected_at <= ? "
    "ORDER BY id, detected_at) x WHERE id NOT IN (SELECT supersedes FROM adjustments WHERE detected_at <= ? "
    "AND supersedes IS NOT NULL))"
)


def stored_bars(con, session_date: date, check_at: datetime) -> pd.DataFrame:
    """Daily bars before the session as known at check_at: per (ticker, date) the newest stored row collected by
    check_at, minus the exchange's closed days (as the ohlc_raw view), times the split/bonus factors detected by
    check_at with an ex-date after the bar and up to the session (as the ohlc view, on today's basis; corrections
    count only once detected by check_at)."""
    return con.execute(
        f"WITH {ADJUSTMENTS_ASOF}, p AS (SELECT DISTINCT ON (ticker, date) ticker, date, open, close FROM prices "
        "WHERE collected_at <= ? AND date < ? ORDER BY ticker, date, collected_at DESC), "
        "q AS (SELECT * FROM p WHERE NOT EXISTS (SELECT 1 FROM own_closed_days c WHERE c.ticker = p.ticker "
        "AND c.date = p.date)), "
        "f AS (SELECT q.ticker, q.date, coalesce(list_product(list_sort(list(a.factor))), 1.0) AS factor FROM q "
        "LEFT JOIN adj a ON a.ticker = q.ticker AND a.ex_date > q.date AND a.ex_date <= ? "
        "GROUP BY q.ticker, q.date) "
        "SELECT q.ticker, q.date, q.open * f.factor AS open, q.close * f.factor AS close FROM q JOIN f "
        "USING (ticker, date) ORDER BY q.ticker, q.date",
        [check_at, check_at, check_at, session_date, session_date],
    ).df()


def entry_prices(bars: pd.DataFrame, keys: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], float]:
    """{(ticker, date, open|close): price} of the stored bars (stored_bars) for the calls' entries before today."""
    out = {}
    for ticker, day, kind in keys:
        match = bars[(bars["ticker"] == ticker) & (bars["date"].astype(str).str[:10] == day)]
        if not match.empty and pd.notna(match.iloc[-1][kind]):
            out[(ticker, day, kind)] = float(match.iloc[-1][kind])
    return out


def previous_closes(bars: pd.DataFrame) -> dict[str, tuple[float, str]]:
    """{symbol: (close, date)} of each symbol's newest stored bar before the session (stored_bars)."""
    out = {}
    for row in records(bars):
        if row["close"] is not None:
            out[row["ticker"]] = (float(row["close"]), str(row["date"])[:10])
    return out


def latest_features(con, session_date: date, check_at: datetime) -> dict[str, dict]:
    """{ticker: {beta_1y, ewma_vol}} of the newest features before this session, computed by check_at."""
    frame = con.execute(
        "SELECT DISTINCT ON (ticker) ticker, beta_1y, ewma_vol FROM features WHERE as_of_date < ? "
        "AND computed_at <= ? ORDER BY ticker, as_of_date DESC, computed_at DESC",
        [session_date, check_at],
    ).df()
    return {row["ticker"]: row for row in records(frame)}


def daily_sigma(bands: dict[int, dict], features: dict | None) -> tuple[float | None, str | None]:
    """The 1-day sigma: the shortest published horizon k with a sigma_h, as sigma_h / sqrt(k) (k = 1: as is; any
    other k is noted sigma_from_<k>d_range), else the features' EWMA vol / sqrt(252) (noted)."""
    for horizon in sorted(bands):
        band = bands[horizon]
        if band and band.get("sigma_h"):
            note = None if horizon == 1 else f"sigma_from_{horizon}d_range"
            return float(band["sigma_h"]) / math.sqrt(horizon), note
    if features and features.get("ewma_vol"):
        return float(features["ewma_vol"]) / math.sqrt(TRADING_DAYS), "sigma_from_ewma_vol"
    return None, "no_sigma"


def news_since(con, ticker: str, since: datetime, check_at: datetime, limit: int | None) -> list[dict]:
    """News tagged with the ticker first seen in [since, check_at] and published by check_at, with each id's
    verification status as of check_at (unverified when no status row lists it) and its enrichment by then. limit
    None: every item."""
    frame = con.execute(
        "WITH s AS (SELECT news_id, status FROM news_status_ids_asof(?) WHERE ticker = ?), "
        "e AS (SELECT id, materiality, sentiment FROM news_enriched_asof(?::TIMESTAMPTZ)) "
        "SELECT n.id, n.title, n.source, n.published_at, n.first_seen_at, coalesce(s.status, 'unverified') AS status, "
        "e.materiality, e.sentiment FROM news_asof(?::TIMESTAMPTZ) n "
        "LEFT JOIN s ON s.news_id = n.id LEFT JOIN e ON e.id = n.id "
        "WHERE list_contains(n.tickers, ?) AND n.first_seen_at >= ? AND n.first_seen_at <= ? "
        "AND coalesce(n.published_at, n.first_seen_at) <= ? ORDER BY n.first_seen_at, n.id LIMIT ?",
        [check_at, ticker, check_at, check_at, ticker, since, check_at, check_at, limit],
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
