"""Calendar events as the market pages show them (catalogue entity "Calendar event", docs/DATA_CATALOGUE.md): the
market's scheduled events (`core/calendar.market_events`, config/events.yaml), the weekday holidays of the exchange
calendar and the companies' results and ex-dividend dates (the stored `events` kind read as of the cut-off:
per company and type, the newest date first seen by then, warehouse/read_models.upcoming_events' rule), from a first
date to a last date. Rules as in W1's catalogue build (design/catalogue/catalogue_calendar.py)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from marketbrief.analytics.earnings_reaction import affected_sessions
from marketbrief.constants.market_pages import (
    CALENDAR_SOURCE_CONFIG,
    CALENDAR_SOURCE_MARKET,
    CALENDAR_TYPE_HOLIDAY,
    COMPANY_EVENT_LABEL,
    EVENT_EARNINGS,
    EXCHANGE_CLOSED_NAME,
    WIDENS_COMPANY,
    WIDENS_MARKET,
)
from marketbrief.core import calendar
from marketbrief.lifecycle import accessor
from marketbrief.lifecycle.constants import STATE_COLLECTED
from marketbrief.presentation.dashboard import reads

COMPANY_EVENTS_SQL = f"""SELECT ticker, id, date, type, source, timing FROM ({reads.COMPANY_EVENTS_ASOF_SQL})
WHERE date >= $first AND date <= $last ORDER BY date, ticker, type, id"""


def row(market: str, day: str, kind: str, name: str, **fields) -> dict:
    """One calendar row with every catalogue field (the ones not given are empty)."""
    return {
        "market": market,
        "date": day,
        "type": kind,
        "name": name,
        "ticker": fields.get("ticker"),
        "timing": fields.get("timing"),
        "reaction_sessions": fields.get("reaction_sessions"),
        "major": fields.get("major", False),
        "widens": fields.get("widens"),
        "provisional": fields.get("provisional", False),
        "release": fields.get("release"),
        "source": fields.get("source"),
        "event_id": fields.get("event_id"),
    }


def market_rows(cfg: dict, first: date, last: date) -> list[dict]:
    """The market's scheduled events and the weekdays its exchange is closed."""
    market = cfg["market"]
    rows = [
        row(market, str(event["date"]), event["type"], event["name"], major=event["major"],
            widens=WIDENS_MARKET if event["major"] else None, provisional=event["provisional"],
            release=event["release"], source=CALENDAR_SOURCE_CONFIG)
        for event in calendar.market_events(cfg, first, last)
    ]
    names = {}
    regular = calendar.exchange_calendar(cfg["calendar"]).regular_holidays
    if regular is not None:
        names = {stamp.date(): name for stamp, name in regular.holidays(first, last, return_name=True).items()}
    day = first
    while day <= last:
        if day.weekday() < 5 and not calendar.is_session(cfg, day):
            label = f": {names[day]}" if day in names else ""
            rows.append(row(market, str(day), CALENDAR_TYPE_HOLIDAY, f"{EXCHANGE_CLOSED_NAME[market]} closed{label}",
                            source=CALENDAR_SOURCE_MARKET))
        day += timedelta(days=1)
    return rows


def company_rows(con, cfg: dict, tickers: set[str], first: date, last: date, cutoff: str) -> list[dict]:
    """The results and ex-dividend dates of `tickers` known by the cut-off."""
    rows = []
    frame = reads.frame(con, COMPANY_EVENTS_SQL, {"first": first, "last": last, "cutoff": cutoff})
    for event in frame.to_dict("records"):
        if event["ticker"] not in tickers or event["type"] not in COMPANY_EVENT_LABEL:
            continue
        day = pd.Timestamp(event["date"]).date()
        timing = event["timing"] if isinstance(event["timing"], str) else None
        earnings = event["type"] == EVENT_EARNINGS
        name = f"{cfg['tickers'][event['ticker']]['name']} {COMPANY_EVENT_LABEL[event['type']]}"
        reaction = [str(session) for session in affected_sessions(cfg, day, timing)] if earnings else None
        rows.append(row(cfg["market"], str(day), event["type"], name, ticker=event["ticker"], timing=timing,
                        reaction_sessions=reaction, widens=WIDENS_COMPANY if earnings else None,
                        source=f"events ({event['source']})", event_id=event["id"]))
    return rows


def calendar_events(cfg: dict, con, cutoff: datetime, from_date: date, to_date: date,
                    tickers: list[str] | None = None) -> list[dict]:
    """Every calendar row from `from_date` to `to_date` as known by the cut-off: the market's rows and the company
    rows of `tickers` (None: every collected company, i.e. active and inactive at the cut-off; the market pages pass
    the active ones). Order: date, major first, market rows before company rows, type, name. Shared with the company
    page (B12), which filters it per ticker."""
    if tickers is None:
        tickers = [record["ticker"] for record in accessor.watchlist(cfg["market"], cutoff, STATE_COLLECTED)]
    rows = market_rows(cfg, from_date, to_date) + company_rows(con, cfg, set(tickers), from_date, to_date,
                                                               cutoff.isoformat())
    return sorted(rows, key=lambda r: (r["date"], not r["major"], r["ticker"] is not None, r["type"], r["name"]))
