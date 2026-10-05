"""Trading calendar and scheduled events (library).

- Trading days come from exchange_calendars (config `calendar`, e.g. XNYS, XBOM). Outside the
  library's covered range we fall back to Monday-Friday and say so. Dates listed under the
  market config's `holidays` are always closed (exchange circulars the library lacks).
- Market events come from config/events.yaml (rules + fixed dates) plus company earnings and
  ex-dividend dates collected into data/<market>/events/ by collect_events.py.
"""
from __future__ import annotations

import calendar as pycal
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import yaml

from common import CONFIG

MAJOR_WINDOW_DAYS = 2  # PASDS: a major event within 2 calendar days -> EVENT_HEAVY
DEFAULT_CLOSE = time(16, 0)  # local close assumed only when the exchange calendar is unavailable


@lru_cache(maxsize=None)
def _xcal(code: str):
    import exchange_calendars as xc
    return xc.get_calendar(code, start="2020-01-01")


def extra_holidays(cfg: dict) -> set[date]:
    return {h if isinstance(h, date) else date.fromisoformat(str(h)) for h in cfg.get("holidays") or []}


def is_session(cfg: dict, d: date) -> bool:
    if d in extra_holidays(cfg):
        return False
    try:
        cal = _xcal(cfg["calendar"])
        if cal.first_session.date() <= d <= cal.last_session.date():
            return bool(cal.is_session(d.isoformat()))
    except Exception:
        pass
    return d.weekday() < 5


def calendar_covers(cfg: dict, d: date) -> bool:
    try:
        cal = _xcal(cfg["calendar"])
        return cal.first_session.date() <= d <= cal.last_session.date()
    except Exception:
        return False


def next_session(cfg: dict, d: date, include: bool = True) -> date:
    d = d if include else d + timedelta(days=1)
    while not is_session(cfg, d):
        d += timedelta(days=1)
    return d


def prev_session(cfg: dict, d: date, include: bool = True) -> date:
    d = d if include else d - timedelta(days=1)
    while not is_session(cfg, d):
        d -= timedelta(days=1)
    return d


def session_close_utc(cfg: dict, d: date) -> datetime:
    """Regular close of session d as an aware UTC datetime (exchange calendar, early closes
    included). Outside the calendar's range, its regular local close time is applied to d."""
    try:
        cal = _xcal(cfg["calendar"])
        if calendar_covers(cfg, d) and cal.is_session(d.isoformat()):
            return cal.session_close(d.isoformat()).to_pydatetime().astimezone(timezone.utc)
        tz, close = ZoneInfo(str(cal.tz)), cal.close_times[-1][1]
    except Exception:
        tz, close = ZoneInfo(cfg["timezone"]), DEFAULT_CLOSE
    return datetime.combine(d, close, tz).astimezone(timezone.utc)


def sessions_ahead(cfg: dict, start: date, n: int) -> list[date]:
    """The next n trading days from start (inclusive)."""
    out, d = [], start
    while len(out) < n:
        if is_session(cfg, d):
            out.append(d)
        d += timedelta(days=1)
    return out


# ---------- rule dates ----------

def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, pycal.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def rule_dates(rule: dict, start: date, end: date) -> list[date]:
    kind, months = rule["rule"], rule.get("months")
    out: list[date] = []
    if kind == "weekly":
        d = start + timedelta(days=(rule["weekday"] - start.weekday()) % 7)
        while d <= end:
            out.append(d)
            d += timedelta(days=7)
        return out
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        if not months or m in months:
            if kind == "third_friday":
                out.append(nth_weekday(y, m, 4, 3))
            elif kind == "first_friday":
                out.append(nth_weekday(y, m, 4, 1))
            elif kind == "last_weekday":
                out.append(last_weekday(y, m, rule["weekday"]))
            elif kind == "month_end":  # last calendar day; market_events moves it to the last session
                out.append(date(y, m, pycal.monthrange(y, m)[1]))
            else:
                raise ValueError(f"unknown event rule {kind!r}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return [d for d in out if start <= d <= end]


def session_offset(rule: dict) -> int:
    """Trading sessions to step back after the holiday shift (`session_offset: -1` = the session
    before). Only 0 or a small negative offset is allowed."""
    off = int(rule.get("session_offset") or 0)
    if not -5 <= off <= 0:
        raise ValueError(f"session_offset must be between -5 and 0, got {off}")
    return off


def market_events(cfg: dict, start: date, end: date, path=None) -> list[dict]:
    """Rule-based and fixed market-level events between start and end (inclusive)."""
    spec = yaml.safe_load((path or CONFIG / "events.yaml").read_text()) or {}
    market, out = cfg["market"], []
    for rule in spec.get("rules", []):
        if market not in rule["markets"]:
            continue
        skip = {s if isinstance(s, date) else date.fromisoformat(str(s)) for s in rule.get("skip") or []}
        off = session_offset(rule)
        for d in rule_dates(rule, start - timedelta(days=7), end + timedelta(days=7)):
            if d in skip:  # known not to happen on (or before) this date
                continue
            d = prev_session(cfg, d)  # holiday -> previous trading day
            for _ in range(-off):     # e.g. the session before the last session of the month
                d = prev_session(cfg, d, include=False)
            if start <= d <= end:
                out.append({"date": d, "type": rule["type"], "name": rule["name"],
                            "major": bool(rule.get("major")), "ticker": None, "release": rule.get("release")})
    for ev in spec.get("fixed", []):
        d = ev["date"] if isinstance(ev["date"], date) else date.fromisoformat(str(ev["date"]))
        if market in ev["markets"] and start <= d <= end:
            out.append({"date": d, "type": ev["type"], "name": ev["name"],
                        "major": bool(ev.get("major")), "ticker": None, "release": ev.get("release")})
    return sorted(out, key=lambda e: (e["date"], e["type"]))


def major_events_near(events: list[dict], day: date, window: int = MAJOR_WINDOW_DAYS) -> list[dict]:
    return [e for e in events if e["major"] and e["ticker"] is None
            and day <= e["date"] <= day + timedelta(days=window)]
