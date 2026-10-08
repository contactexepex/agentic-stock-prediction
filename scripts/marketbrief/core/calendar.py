"""Trading calendar and scheduled events (library).

- Trading days come from exchange_calendars (config `calendar`, e.g. XNYS, XBOM). Outside the
  library's covered range we fall back to Monday-Friday and say so. Dates listed under the
  market config's `holidays` are always closed (exchange circulars the library lacks); dates under
  `special_sessions` always trade (NSE's Diwali Muhurat sessions on a holiday; their open and close are the
  `special_session_hours` of the config, else the regular hours). Without the exchange_calendars package
  nothing falls back silently: CalendarUnavailableError is raised.
- Market events come from config/events.yaml (rules + fixed dates) plus company earnings and
  ex-dividend dates collected into data/<market>/events/ by the events collector.
"""

from __future__ import annotations

import calendar as month_calendar
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import yaml

from marketbrief.constants.calendar import (
    BAR_SETTLE_MINUTES,
    CALENDAR_START,
    DEFAULT_CLOSE,
    DEFAULT_OPEN,
    EDGE_CLOSE,
    EDGE_OPEN,
    FILE_EVENTS_CONFIG,
    KEY_EVENTS_FIXED,
    KEY_EVENTS_RULES,
    KEY_PROVISIONAL,
    KEY_PROVISIONAL_DATES,
    KEY_PROVISIONAL_FROM,
    MAJOR_WINDOW_DAYS,
    MAX_SESSION_OFFSET,
    MIN_SESSION_OFFSET,
    MSG_BAD_SPECIAL_SESSION_HOURS,
    MSG_NO_EXCHANGE_CALENDARS,
    MSG_SESSION_OFFSET_RANGE,
    MSG_UNKNOWN_EVENT_RULE,
    PROVISIONAL_SUFFIX,
    RULE_FIRST_FRIDAY,
    RULE_LAST_WEEKDAY,
    RULE_MONTH_END,
    RULE_THIRD_FRIDAY,
    RULE_WEEKLY,
    WEEKDAY_FRIDAY,
    WEEKS_PADDING_DAYS,
    WORD_PROVISIONAL,
)
from marketbrief.constants.config_keys import (
    CFG_CALENDAR,
    CFG_HOLIDAYS,
    CFG_MARKET,
    CFG_SPECIAL_SESSION_HOURS,
    CFG_SPECIAL_SESSIONS,
    CFG_TIMEZONE,
)
from marketbrief.core import paths


class CalendarUnavailableError(RuntimeError):
    """The exchange_calendars package cannot be imported (never a silent Monday-Friday fallback, issue #43)."""


@lru_cache(maxsize=None)
def exchange_calendar(code: str):
    """The exchange_calendars calendar of an exchange code (XNYS, XBOM ...), loaded once."""
    try:
        import exchange_calendars
    except ImportError as exc:
        raise CalendarUnavailableError(MSG_NO_EXCHANGE_CALENDARS.format(error=exc)) from exc

    return exchange_calendars.get_calendar(code, start=CALENDAR_START)


def config_dates(cfg: dict, key: str) -> set[date]:
    """The dates listed under a market-config key (holidays, special_sessions)."""
    return {listed if isinstance(listed, date) else date.fromisoformat(str(listed)) for listed in cfg.get(key) or []}


def extra_holidays(cfg: dict) -> set[date]:
    """The market config's extra closed days."""
    return config_dates(cfg, CFG_HOLIDAYS)


def special_sessions(cfg: dict) -> set[date]:
    """The market config's extra trading days on exchange holidays (issue #41)."""
    return config_dates(cfg, CFG_SPECIAL_SESSIONS)


def special_session_hours(cfg: dict, day: date) -> tuple[time, time] | None:
    """(open, close) exchange-local times of a special session listed under `special_session_hours`
    ("HH:MM-HH:MM"; issue #45: NSE's one-hour Muhurat slot), or None."""
    for listed, hours in (cfg.get(CFG_SPECIAL_SESSION_HOURS) or {}).items():
        listed_day = listed if isinstance(listed, date) else date.fromisoformat(str(listed))
        if listed_day == day:
            try:
                open_text, close_text = str(hours).split("-")
                opens, closes = time.fromisoformat(open_text.strip()), time.fromisoformat(close_text.strip())
            except ValueError as error:
                raise ValueError(MSG_BAD_SPECIAL_SESSION_HOURS.format(day=listed_day, hours=hours)) from error
            if opens >= closes:
                raise ValueError(MSG_BAD_SPECIAL_SESSION_HOURS.format(day=listed_day, hours=hours))
            return opens, closes
    return None


def calendar_covers(cfg: dict, day: date) -> bool:
    """True when the exchange calendar library covers `day`."""
    try:
        calendar = exchange_calendar(cfg[CFG_CALENDAR])
        return calendar.first_session.date() <= day <= calendar.last_session.date()
    except CalendarUnavailableError:
        raise
    except Exception:
        return False


def is_session(cfg: dict, day: date) -> bool:
    """True when the market trades on `day` (Monday-Friday outside the library's range)."""
    if day in special_sessions(cfg):
        return True
    if day in extra_holidays(cfg):
        return False
    if calendar_covers(cfg, day):
        return bool(exchange_calendar(cfg[CFG_CALENDAR]).is_session(day.isoformat()))
    return day.weekday() < 5


def next_session(cfg: dict, day: date, include: bool = True) -> date:
    """The first session on or after `day` (after it when include is False)."""
    day = day if include else day + timedelta(days=1)
    while not is_session(cfg, day):
        day += timedelta(days=1)
    return day


def prev_session(cfg: dict, day: date, include: bool = True) -> date:
    """The last session on or before `day` (before it when include is False)."""
    day = day if include else day - timedelta(days=1)
    while not is_session(cfg, day):
        day -= timedelta(days=1)
    return day


def _session_edge_utc(cfg: dict, day: date, edge: str) -> datetime:
    """Open or close of session `day` as an aware UTC datetime."""
    special = special_session_hours(cfg, day) if day in special_sessions(cfg) else None
    if special is not None:
        local_time = special[0] if edge == EDGE_OPEN else special[1]
        return datetime.combine(day, local_time, ZoneInfo(cfg[CFG_TIMEZONE])).astimezone(timezone.utc)
    try:
        calendar = exchange_calendar(cfg[CFG_CALENDAR])
        if calendar_covers(cfg, day) and calendar.is_session(day.isoformat()):
            session = day.isoformat()
            edge_time = calendar.session_open(session) if edge == EDGE_OPEN else calendar.session_close(session)
            return edge_time.to_pydatetime().astimezone(timezone.utc)
        zone = ZoneInfo(str(calendar.tz))
        local_time = (calendar.open_times if edge == EDGE_OPEN else calendar.close_times)[-1][1]
    except CalendarUnavailableError:
        raise
    except Exception:
        zone, local_time = ZoneInfo(cfg[CFG_TIMEZONE]), DEFAULT_OPEN if edge == EDGE_OPEN else DEFAULT_CLOSE
    return datetime.combine(day, local_time, zone).astimezone(timezone.utc)


def session_open_utc(cfg: dict, day: date) -> datetime:
    """Regular open of session `day` as an aware UTC datetime (exchange calendar, late opens
    included). Outside the calendar's range, its regular local open time is applied to `day`."""
    return _session_edge_utc(cfg, day, EDGE_OPEN)


def session_close_utc(cfg: dict, day: date) -> datetime:
    """Regular close of session `day` as an aware UTC datetime (exchange calendar, early closes
    included). Outside the calendar's range, its regular local close time is applied to `day`."""
    return _session_edge_utc(cfg, day, EDGE_CLOSE)


def last_complete_session(cfg: dict, now: datetime) -> date:
    """The newest session whose bar is final at `now` (aware): its close plus BAR_SETTLE_MINUTES has passed
    (issue #20: the bar cut-off and market_status use the exchange's own session, not the UTC date)."""
    day = prev_session(cfg, now.astimezone(ZoneInfo(cfg[CFG_TIMEZONE])).date())
    while session_close_utc(cfg, day) + timedelta(minutes=BAR_SETTLE_MINUTES) > now:
        day = prev_session(cfg, day, include=False)
    return day


def sessions_ahead(cfg: dict, start: date, count: int) -> list[date]:
    """The next `count` trading days from start (inclusive)."""
    found, day = [], start
    while len(found) < count:
        if is_session(cfg, day):
            found.append(day)
        day += timedelta(days=1)
    return found


# ---------- rule dates ----------


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """The nth given weekday (Monday = 0) of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (nth - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    """The last given weekday (Monday = 0) of a month."""
    last = date(year, month, month_calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _weekly_dates(rule: dict, start: date, end: date) -> list[date]:
    """Every date of a weekly rule between start and end."""
    found, day = [], start + timedelta(days=(rule["weekday"] - start.weekday()) % 7)
    while day <= end:
        found.append(day)
        day += timedelta(days=7)
    return found


def _monthly_date(rule: dict, year: int, month: int) -> date:
    """The date a monthly rule gives in one month."""
    kind = rule["rule"]
    if kind == RULE_THIRD_FRIDAY:
        return nth_weekday(year, month, WEEKDAY_FRIDAY, 3)
    if kind == RULE_FIRST_FRIDAY:
        return nth_weekday(year, month, WEEKDAY_FRIDAY, 1)
    if kind == RULE_LAST_WEEKDAY:
        return last_weekday(year, month, rule["weekday"])
    if kind == RULE_MONTH_END:
        return date(year, month, month_calendar.monthrange(year, month)[1])
    raise ValueError(MSG_UNKNOWN_EVENT_RULE.format(kind=kind))


def rule_dates(rule: dict, start: date, end: date) -> list[date]:
    """The dates a weekly or monthly rule gives between start and end."""
    if rule["rule"] == RULE_WEEKLY:
        return _weekly_dates(rule, start, end)
    months, found = rule.get("months"), []
    year, month = start.year, start.month
    while date(year, month, 1) <= end:
        if not months or month in months:
            found.append(_monthly_date(rule, year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return [rule_day for rule_day in found if start <= rule_day <= end]


def session_offset(rule: dict) -> int:
    """Trading sessions to step back after the holiday shift (`session_offset: -1` = the session
    before). Only 0 or a small negative offset is allowed."""
    offset = int(rule.get("session_offset") or 0)
    if not MIN_SESSION_OFFSET <= offset <= MAX_SESSION_OFFSET:
        raise ValueError(
            MSG_SESSION_OFFSET_RANGE.format(low=MIN_SESSION_OFFSET, high=MAX_SESSION_OFFSET, offset=offset)
        )
    return offset


def is_provisional(spec: dict, day: date) -> bool:
    """True when an event's date is not confirmed (issue #15): `provisional: true`, the emitted date listed under
    the rule's `provisional_dates`, on or after its `provisional_from`, or "provisional" in its name."""
    listed = config_dates(spec, KEY_PROVISIONAL_DATES)
    start = spec.get(KEY_PROVISIONAL_FROM)
    start = start if start is None or isinstance(start, date) else date.fromisoformat(str(start))
    return (
        bool(spec.get(KEY_PROVISIONAL))
        or day in listed
        or (start is not None and day >= start)
        or WORD_PROVISIONAL in spec["name"].lower()
    )


def _market_event(day: date, spec: dict) -> dict:
    """One market-level event row; a provisional date gets `provisional: True` and the word in its name."""
    provisional = is_provisional(spec, day)
    name = spec["name"]
    if provisional and WORD_PROVISIONAL not in name.lower():
        name += PROVISIONAL_SUFFIX
    return {
        "date": day,
        "type": spec["type"],
        "name": name,
        "major": bool(spec.get("major")),
        "ticker": None,
        "release": spec.get("release"),
        "provisional": provisional,
    }


def _rule_events(cfg: dict, spec: dict, start: date, end: date) -> list[dict]:
    """The events of the config's rules between start and end."""
    found = []
    padding = timedelta(days=WEEKS_PADDING_DAYS)
    for rule in spec.get(KEY_EVENTS_RULES, []):
        if cfg[CFG_MARKET] not in rule["markets"]:
            continue
        skip = {
            skipped_day if isinstance(skipped_day, date) else date.fromisoformat(str(skipped_day))
            for skipped_day in rule.get("skip") or []
        }
        steps_back = -session_offset(rule)
        for day in rule_dates(rule, start - padding, end + padding):
            if day in skip:  # known not to happen on (or before) this date
                continue
            day = prev_session(cfg, day)  # holiday -> previous trading day
            for _ in range(steps_back):  # e.g. the session before the last session of the month
                day = prev_session(cfg, day, include=False)
            if start <= day <= end:
                found.append(_market_event(day, rule))
    return found


def market_events(cfg: dict, start: date, end: date, path=None) -> list[dict]:
    """Rule-based and fixed market-level events between start and end (inclusive)."""
    spec = yaml.safe_load((path or paths.CONFIG / FILE_EVENTS_CONFIG).read_text()) or {}
    found = _rule_events(cfg, spec, start, end)
    for fixed in spec.get(KEY_EVENTS_FIXED, []):
        day = fixed["date"] if isinstance(fixed["date"], date) else date.fromisoformat(str(fixed["date"]))
        if cfg[CFG_MARKET] in fixed["markets"] and start <= day <= end:
            found.append(_market_event(day, fixed))
    return sorted(found, key=lambda event: (event["date"], event["type"]))


def major_events_near(events: list[dict], day: date, window: int = MAJOR_WINDOW_DAYS) -> list[dict]:
    """Company-independent major events from `day` to `window` days after it."""
    return [
        event
        for event in events
        if event["major"] and event["ticker"] is None and day <= event["date"] <= day + timedelta(days=window)
    ]
