"""Issue #40: Yahoo's flat zero-volume bar on an exchange holiday (2026-10-02, NSE closed) is not stored by
collect_prices.py (listed in `dropped_non_session`), and a holiday row already stored is left out on read by
the ohlc_raw / ohlc / bars / returns views. Cues and factors keep their own calendars; indices with volume 0
on real sessions are kept."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.storage import day_file  # noqa: E402
from test_price_fallback import FakeTicker, bars, daily, make_env, run  # noqa: E402

TODAY = date(2026, 10, 6)
HOLIDAY = date(2026, 10, 2)  # Gandhi Jayanti, Friday
DAYS = [date(2026, 9, 30), date(2026, 10, 1), HOLIDAY, date(2026, 10, 5)]


def flat_on(frame: pd.DataFrame, day: date, volume: int = 0) -> pd.DataFrame:
    """Yahoo's holiday bar: open = high = low = close = the previous close, the given volume."""
    stamp = pd.Timestamp(day).tz_localize("Asia/Kolkata")
    previous = frame["Close"].shift(1)[stamp]
    frame.loc[stamp, ["Open", "High", "Low", "Close", "Adj Close", "Volume"]] = [previous] * 5 + [volume]
    return frame


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, ["INFY", "TCS"], TODAY)
    path = tmp_path / "config" / "markets" / "india.yaml"
    doc = yaml.safe_load(path.read_text())
    real = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "markets" / "india.yaml").read_text())
    doc["symbols"] = {key: real["symbols"][key] for key in ("NIFTY50", "INDIAVIX", "SPX")}
    path.write_text(yaml.safe_dump(doc))
    days = [*DAYS, TODAY]
    FakeTicker.frames = {
        "^NSEI": flat_on(daily(days, 22000), HOLIDAY),
        "^INDIAVIX": flat_on(daily(days, 12), HOLIDAY),
        "^GSPC": daily(days, 6000),  # the S&P 500 trades on 2026-10-02
        "INFY.NS": flat_on(daily(days, 1000), HOLIDAY),
        "TCS.NS": flat_on(daily(days, 3000), HOLIDAY),
    }
    return e


def test_holiday_bar_is_dropped_at_collection(env, monkeypatch, capsys):
    _, out = run(monkeypatch, capsys)
    assert set(bars(env.root, HOLIDAY)) == {"SPX"}  # the US cue trades that day; no own-exchange bar is stored
    dropped = {(d["ticker"], d["date"], d["reason"]) for d in out["dropped_non_session"]}
    assert dropped == {
        (key, "2026-10-02", "not a session of the market calendar") for key in ("NIFTY50", "INDIAVIX", "INFY", "TCS")
    }
    for day in (DAYS[1], DAYS[3]):
        assert set(bars(env.root, day)) == {"NIFTY50", "INDIAVIX", "SPX", "INFY", "TCS"}


def test_flat_zero_volume_stock_bar_on_a_session_is_dropped_but_an_index_is_kept(env, monkeypatch, capsys):
    session = date(2026, 10, 1)
    days = [*DAYS, TODAY]
    FakeTicker.frames["INFY.NS"] = flat_on(daily(days, 1000), session)
    FakeTicker.frames["^NSEI"] = flat_on(daily(days, 22000), session)  # volume 0 is normal for an index
    FakeTicker.frames["^INDIAVIX"] = flat_on(daily(days, 12), session)
    _, out = run(monkeypatch, capsys)
    stored = bars(env.root, session)
    assert "INFY" not in stored
    assert {"NIFTY50", "INDIAVIX", "TCS"} <= set(stored)
    reasons = {(d["ticker"], d["date"]): d["reason"] for d in out["dropped_non_session"]}
    assert reasons[("INFY", "2026-10-01")] == "flat bar with zero volume"
    assert ("NIFTY50", "2026-10-01") not in reasons
    assert ("INDIAVIX", "2026-10-01") not in reasons


@pytest.mark.usefixtures("env")
def test_stored_holiday_rows_are_excluded_on_read():
    header = "date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
    rows = {  # (ticker, close, volume); the holiday rows repeat the 10-01 close with volume 0
        date(2026, 10, 1): [("INFY", 1000.0, 1000), ("NIFTY50", 25000.0, 0), ("SPX", 6000.0, 0)],
        HOLIDAY: [("INFY", 1000.0, 0), ("NIFTY50", 25000.0, 0), ("SPX", 6010.0, 0)],
        date(2026, 10, 5): [("INFY", 1020.0, 900), ("NIFTY50", 25250.0, 0), ("SPX", 6020.0, 0)],
    }
    for day, items in rows.items():
        path = day_file("india", "prices", day, "csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{day},{key},{c},{c},{c},{c},{c},{volume},{day}T10:00:00+00:00\n" for key, c, volume in items]
        path.write_text(header + "".join(lines))
    con = connect("india")
    assert con.execute("SELECT count(*) FROM prices").fetchone()[0] == 9  # the holiday rows are still stored
    kept = con.execute("SELECT ticker, date FROM ohlc_raw WHERE date = ? ORDER BY ticker", [HOLIDAY]).fetchall()
    assert kept == [("SPX", HOLIDAY)]  # only the cue, which trades on its own calendar
    for view in ("ohlc", "bars", "bars_raw", "returns"):
        found = con.execute(f"SELECT date FROM {view} WHERE ticker IN ('INFY', 'NIFTY50')").fetchall()
        assert {row[0] for row in found} == {date(2026, 10, 1), date(2026, 10, 5)}, view
    # the index (volume 0 on every real session) keeps its real bars
    assert con.execute("SELECT count(*) FROM ohlc WHERE ticker = 'NIFTY50'").fetchone()[0] == 2
    # a return across the holiday uses the real previous session, and sessions are numbered without a gap
    ret = con.execute("SELECT ret_1d FROM returns WHERE ticker = 'INFY' AND date = '2026-10-05'").fetchone()[0]
    assert ret == pytest.approx(1020.0 / 1000.0 - 1)
    numbers = con.execute("SELECT rn FROM bars WHERE ticker = 'INFY' ORDER BY date").fetchall()
    assert [row[0] for row in numbers] == [1, 2]


def bar_row(close: float, flat: bool = True, volume: int = 0) -> pd.Series:
    """A yfinance row; flat = open = high = low = close."""
    spread = 0.0 if flat else 1.0
    values = {"Open": close, "High": close + spread, "Low": close - spread, "Close": close, "Adj Close": close}
    return pd.Series({**values, "Volume": volume})


def collector_for(market: str):
    """A PriceCollector shell with the real config of `market` (drop_reason reads only the config)."""
    from marketbrief.collectors.prices import PriceCollector
    from marketbrief.core.market_config import load_market

    shell = object.__new__(PriceCollector)
    shell.cfg = load_market(market)
    return shell


def test_drop_reason_rules_for_the_us_and_for_sector_indices():
    us, india = collector_for("us"), collector_for("india")
    labor_day, memorial_day, session = date(2026, 9, 7), date(2026, 5, 25), date(2026, 9, 8)
    not_a_session = "not a session of the market calendar"
    assert us.drop_reason("SPY", labor_day, bar_row(500)) == not_a_session  # benchmark
    assert us.drop_reason("AAPL", labor_day, bar_row(200)) == not_a_session  # stock
    assert us.drop_reason("VIX", memorial_day, bar_row(15, flat=False)) == not_a_session  # vol index, not flat
    assert us.drop_reason("ES", labor_day, bar_row(5000, flat=False, volume=10)) is None  # cue: futures trade
    assert us.drop_reason("US10Y", labor_day, bar_row(4.1)) is None  # factor keeps its own calendar
    assert us.drop_reason("AAPL", session, bar_row(200)) == "flat bar with zero volume"
    assert us.drop_reason("AAPL", session, bar_row(200, flat=False, volume=5)) is None
    assert us.drop_reason("SPY", session, bar_row(500)) is None  # an index with volume 0 on a session
    assert india.drop_reason("NIFTYBANK", date(2026, 10, 2), bar_row(55000)) == not_a_session  # sector_etf
    assert india.drop_reason("NIFTYBANK", date(2026, 10, 1), bar_row(55000)) is None
    assert india.drop_reason("SPX", date(2026, 10, 2), bar_row(6000)) is None


@pytest.mark.parametrize("now, stored", [
    ("2026-10-05T11:00:00+00:00", set()),                   # 16:30 IST: the close (10:00 UTC) is still settling
    ("2026-10-05T14:40:00+00:00", {"NIFTY50", "INFY"}),     # 20:10 IST, before UTC midnight (issue #20)
])
def test_own_session_bar_is_stored_once_final_before_utc_midnight(tmp_path, monkeypatch, capsys, now, stored):
    from marketbrief.collectors import prices as collect_prices

    root = make_env(tmp_path, monkeypatch, ["INFY"], date(2026, 10, 5)).root
    path = tmp_path / "config" / "markets" / "india.yaml"
    doc = yaml.safe_load(path.read_text())
    real = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "markets" / "india.yaml").read_text())
    doc["symbols"] = {key: real["symbols"][key] for key in ("NIFTY50", "SPX")}
    path.write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(collect_prices, "utc_now", lambda: now)
    days = [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 5)]
    FakeTicker.frames = {"^NSEI": daily(days, 22000), "INFY.NS": daily(days, 1000), "^GSPC": daily(days, 6000)}
    run(monkeypatch, capsys)
    assert set(bars(root, date(2026, 10, 5))) == stored   # the S&P 500 cue (another calendar) waits for UTC 10-06
    assert set(bars(root, date(2026, 10, 1))) == {"NIFTY50", "INFY", "SPX"}


MUHURAT = (date(2024, 11, 1), date(2025, 10, 21))  # NSE Diwali Muhurat sessions on exchange holidays


def test_special_sessions_count_as_sessions():
    """Issue #41: `special_sessions` in the market config are sessions although the exchange calendar is closed."""
    from marketbrief.core.calendar import exchange_calendar, is_session, next_session, prev_session
    from marketbrief.core.market_config import load_market

    cfg = load_market("india")
    assert set(cfg["special_sessions"]) == set(MUHURAT)
    for day in MUHURAT:
        assert not exchange_calendar("XBOM").is_session(day.isoformat())  # a holiday for the library
        assert is_session(cfg, day)
        assert not is_session({**cfg, "special_sessions": []}, day)
        assert collector_for("india").drop_reason("INFY", day, bar_row(1500, flat=False, volume=10)) is None
    assert not is_session(cfg, date(2025, 10, 22))  # the next day stays closed
    assert next_session(cfg, date(2025, 10, 21)) == date(2025, 10, 21)
    assert prev_session(cfg, date(2025, 10, 22)) == date(2025, 10, 21)


def test_special_sessions_use_their_own_hours():
    """Issue #45: a Muhurat session opens and closes at its `special_session_hours` (NSE circulars), not at the
    regular 09:15-15:30 IST; a special session without hours keeps the regular hours."""
    from datetime import datetime, timezone

    from marketbrief.core.calendar import last_complete_session, session_close_utc, session_open_utc
    from marketbrief.core.market_config import load_market

    cfg = load_market("india")
    utc = timezone.utc
    assert session_open_utc(cfg, date(2024, 11, 1)) == datetime(2024, 11, 1, 12, 30, tzinfo=utc)   # 18:00 IST
    assert session_close_utc(cfg, date(2024, 11, 1)) == datetime(2024, 11, 1, 13, 30, tzinfo=utc)  # 19:00 IST
    assert session_open_utc(cfg, date(2025, 10, 21)) == datetime(2025, 10, 21, 8, 15, tzinfo=utc)  # 13:45 IST
    assert session_close_utc(cfg, date(2025, 10, 21)) == datetime(2025, 10, 21, 9, 15, tzinfo=utc) # 14:45 IST
    assert session_close_utc(cfg, date(2025, 10, 20)) == datetime(2025, 10, 20, 10, 0, tzinfo=utc)  # regular 15:30
    regular = {**cfg, "special_session_hours": {}}
    assert session_close_utc(regular, date(2025, 10, 21)) == datetime(2025, 10, 21, 10, 0, tzinfo=utc)
    # the Muhurat bar is final 120 min (BAR_SETTLE_MINUTES) after its own 14:45 close, before the regular one
    assert last_complete_session(cfg, datetime(2025, 10, 21, 11, 30, tzinfo=utc)) == date(2025, 10, 21)
    assert last_complete_session(regular, datetime(2025, 10, 21, 11, 30, tzinfo=utc)) == date(2025, 10, 20)


@pytest.mark.usefixtures("env")
def test_special_session_bars_are_kept_on_read():
    header = "date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
    for day, close in ((date(2024, 10, 31), 1000.0), (MUHURAT[0], 1010.0), (date(2024, 11, 4), 1020.0)):
        path = day_file("india", "prices", day, "csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        bar = f"{day},INFY,{close},{close + 5},{close - 5},{close},{close},500,{day}T13:00:00+00:00\n"
        path.write_text(header + bar)
    con = connect("india")
    days = [row[0] for row in con.execute("SELECT date FROM bars WHERE ticker = 'INFY' ORDER BY date").fetchall()]
    assert days == [date(2024, 10, 31), MUHURAT[0], date(2024, 11, 4)]


def test_missing_exchange_calendars_fails_loudly(monkeypatch):
    """Issue #43: without the exchange_calendars package, is_session raises instead of a silent Monday-Friday rule."""
    from marketbrief.core import calendar

    calendar.exchange_calendar.cache_clear()
    monkeypatch.setitem(sys.modules, "exchange_calendars", None)  # import now raises ImportError
    try:
        with pytest.raises(calendar.CalendarUnavailableError, match="exchange_calendars cannot be imported"):
            calendar.is_session({"calendar": "XNYS"}, date(2026, 10, 5))
        with pytest.raises(calendar.CalendarUnavailableError):
            calendar.session_open_utc({"calendar": "XNYS", "timezone": "America/New_York"}, date(2026, 10, 5))
    finally:
        calendar.exchange_calendar.cache_clear()


def test_connect_warns_without_a_market_config(capsys):
    """Issue #41: a market without a config file gets an empty own_closed_days table and a warning, not silence."""
    con = connect("nosuchmarket")
    assert con.execute("SELECT count(*) FROM own_closed_days").fetchone()[0] == 0
    assert "no config/markets/nosuchmarket.yaml" in capsys.readouterr().err
