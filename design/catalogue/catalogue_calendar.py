"""Calendar events and the market-status benchmark and vol-index blocks (EXAMPLES only), built with the engine's code:
core/calendar.market_events (config/events.yaml), the warehouse's as-of read of the stored `events` kind
(warehouse/read_models.upcoming_events), analytics/earnings_reaction.affected_sessions and indicators.period_return."""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd

from marketbrief.analytics.earnings_reaction import affected_sessions
from marketbrief.analytics.indicators import period_return
from marketbrief.core import calendar
from marketbrief.core.market_config import load_market
from marketbrief.warehouse.read_models import upcoming_events

CUTOFF = "2026-10-07T12:00:00Z"   # the examples' cut-off (the files' as_of)
AS_OF = "2026-10-06"              # the newest stored close
WINDOW = (date(2026, 10, 7), date(2026, 12, 2))   # session date 7 Oct and the 8 weeks after it
INACTIVE_IN_EXAMPLES = {"INDIGO", "DAL"}          # company.json shows these as inactive, so their dates are left out
# Stored `events` rows (data/<market>/events/) of the window, as the warehouse's as-of read returns them at the cut-off,
# plus AAPL's later row (first seen 12:27Z on 7 Oct, after the cut-off, so the read still gives 29 Oct):
# (id, first_seen_at); every row has source yfinance and no timing.
STORED_EVENTS = {
    "india": [(f"{t}-earnings-{d}", "2026-10-05T14:27:50Z") for t, d in (
        ("TCS", "2026-10-08"), ("HDFCLIFE", "2026-10-15"), ("RELIANCE", "2026-10-16"), ("HDFCBANK", "2026-10-17"),
        ("ICICIBANK", "2026-10-17"), ("ULTRACEMCO", "2026-10-19"), ("DRREDDY", "2026-10-23"), ("INFY", "2026-10-23"),
        ("SBILIFE", "2026-10-23"), ("ADANIPORTS", "2026-10-28"), ("LT", "2026-10-28"), ("HINDUNILVR", "2026-10-29"),
        ("ITC", "2026-10-29"), ("MARUTI", "2026-10-29"), ("INDIGO", "2026-11-03"), ("M&M", "2026-11-04"),
        ("SUNPHARMA", "2026-11-05"), ("HINDALCO", "2026-11-06"), ("ONGC", "2026-11-06"), ("TATASTEEL", "2026-11-11"))],
    "us": [(f"{t}-{kind}-{d}", "2026-10-05T14:28:27Z") for t, kind, d in (
        ("DAL", "earnings", "2026-10-09"), ("JPM", "earnings", "2026-10-13"), ("BAC", "earnings", "2026-10-14"),
        ("PGR", "earnings", "2026-10-14"), ("DAL", "ex_dividend", "2026-10-15"), ("GM", "earnings", "2026-10-20"),
        ("UAL", "earnings", "2026-10-20"), ("TSLA", "earnings", "2026-10-21"), ("GOOGL", "earnings", "2026-10-28"),
        ("META", "earnings", "2026-10-28"), ("AAPL", "earnings", "2026-10-29"), ("CAT", "earnings", "2026-10-29"),
        ("LLY", "earnings", "2026-10-29"), ("MRK", "earnings", "2026-10-29"), ("CVX", "earnings", "2026-10-30"),
        ("XOM", "earnings", "2026-10-30"), ("ALL", "earnings", "2026-11-04"), ("NVDA", "earnings", "2026-11-17"),
        ("WMT", "earnings", "2026-11-19"), ("DE", "earnings", "2026-11-25"))]
    + [("AAPL-earnings-2026-11-02", "2026-10-07T12:27:19Z")],
}
# Stored closes (ohlc) of the market-level symbols, the 6 sessions to 6 Oct.
LEVEL_BARS = {
    "india": {"benchmark": ("NIFTY50", {"2026-09-28": 22780.25, "2026-09-29": 22716.1992, "2026-09-30": 22620.4492,
                                        "2026-10-01": 22421.9492, "2026-10-05": 22555.75, "2026-10-06": 22776.0996}),
              "vol_index": ("INDIAVIX", {"2026-09-28": 13.64, "2026-09-29": 13.41, "2026-09-30": 13.49,
                                         "2026-10-01": 14.46, "2026-10-05": 14.78, "2026-10-06": 13.61})},
    "us": {"benchmark": ("SPY", {"2026-09-29": 764.20, "2026-09-30": 762.63, "2026-10-01": 763.99,
                                 "2026-10-02": 769.64, "2026-10-05": 774.83, "2026-10-06": 779.09}),
           "vol_index": ("VIX", {"2026-09-29": 16.04, "2026-09-30": 16.34, "2026-10-01": 16.39,
                                 "2026-10-02": 15.31, "2026-10-05": 15.52, "2026-10-06": 15.01})},
}


def stored_rows(market: str, cfg: dict) -> pd.DataFrame:
    rows = []
    for event_id, first_seen in STORED_EVENTS[market]:
        ticker, kind, day = event_id.split("-", 1)[0], event_id.split("-")[-4], event_id[-10:]
        label = "earnings" if kind == "earnings" else "ex-dividend"
        rows.append({"id": event_id, "date": pd.Timestamp(day).date(), "type": kind, "ticker": ticker,
                     "name": f"{cfg['tickers'][ticker]['name']} {label}", "source": "yfinance",
                     "first_seen_at": pd.Timestamp(first_seen), "amount": None, "timing": None})
    return pd.DataFrame(rows)


def company_events(market: str, cfg: dict) -> list[dict]:
    """The active companies' events in the window, as the warehouse reads them at the cut-off."""
    con = duckdb.connect()
    con.register("stored", stored_rows(market, cfg))
    con.execute("CREATE TABLE events AS SELECT * FROM stored")
    out = []
    for ticker, events in upcoming_events(con, AS_OF, CUTOFF).items():
        if ticker not in cfg["active_tickers"] or ticker in INACTIVE_IN_EXAMPLES:
            continue
        for event in events:
            day = date.fromisoformat(event["date"])
            if not WINDOW[0] <= day <= WINDOW[1]:
                continue
            earnings = event["type"] == "earnings"
            out.append({"market": market, "date": event["date"], "type": event["type"],
                        "name": f"{cfg['tickers'][ticker]['name']} {'results' if earnings else 'ex-dividend'}",
                        "ticker": ticker, "timing": event["timing"],
                        "reaction_sessions": [str(s) for s in affected_sessions(cfg, day, event["timing"])]
                        if earnings else None,
                        "major": False, "widens": "company" if earnings else None, "provisional": False,
                        "release": None, "source": f"events ({event['source']})", "event_id": event["id"]})
    return out


def market_rows(market: str, cfg: dict) -> list[dict]:
    rows = [{"market": market, "date": str(event["date"]), "type": event["type"], "name": event["name"], "ticker": None,
             "timing": None, "reaction_sessions": None, "major": event["major"],
             "widens": "market" if event["major"] else None, "provisional": event["provisional"],
             "release": event["release"], "source": "config/events.yaml", "event_id": None}
            for event in calendar.market_events(cfg, *WINDOW)]
    names = {}
    regular = calendar.exchange_calendar(cfg["calendar"]).regular_holidays
    if regular is not None:
        names = {ts.date(): name for ts, name in regular.holidays(*WINDOW, return_name=True).items()}
    exchange = "NSE" if market == "india" else "US exchanges"
    day = WINDOW[0]
    while day <= WINDOW[1]:
        if day.weekday() < 5 and not calendar.is_session(cfg, day):
            label = f": {names[day]}" if day in names else ""
            rows.append({"market": market, "date": str(day), "type": "holiday", "name": f"{exchange} closed{label}",
                         "ticker": None, "timing": None, "reaction_sessions": None, "major": False, "widens": None,
                         "provisional": False, "release": None, "source": "market calendar", "event_id": None})
        day += timedelta(days=1)
    return rows


def calendar_events() -> list[dict]:
    rows = []
    for market in ("india", "us"):
        cfg = load_market(market)
        rows += market_rows(market, cfg) + company_events(market, cfg)
    return sorted(rows, key=lambda r: (r["market"], r["date"], r["ticker"] is not None, r["type"], r["name"]))


def level_block(market: str, role: str) -> dict:
    """A market-level symbol's last stored close with its 1- and 5-session changes (indicators.period_return)."""
    symbol, closes = LEVEL_BARS[market][role]
    series = pd.Series(closes)
    cfg = load_market(market)
    one, five = period_return(series, 1), period_return(series, 5)
    return {"symbol": symbol, "name": cfg["symbols"][symbol]["name"], "close": series.iloc[-1],
            "close_date": series.index[-1], "change_pct": round(one * 100, 2), "change_5d_pct": round(five * 100, 2)}
