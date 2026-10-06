"""Collect company events (earnings, ex-dividend) for watchlist tickers via yfinance into
data/<market>/events/YYYY/MM/<today>.jsonl. Append-only: an event id (<ticker>-<type>-<date>) is written once; a moved
date is a new event id, and the newest first_seen_at wins when reading (see the `company_events` view).

Upcoming events come from the yfinance calendar; an ex-dividend row carries the dividend `amount` (the announced one
if Yahoo lists it, else the last dividend paid, marked "est."). Unless --no-history, past events are backfilled for
the range engine (source ending in "_history", read through the `event_history` view): dividends with amounts, and
earnings dates with `timing` (before_open / during / after_close) from yfinance's earnings dates and, for SEC markets
with SEC_USER_AGENT set, 8-K item 2.02 (results of operations) acceptance times; for SEC markets each 10-Q/10-K
acceptance is also stored, as a `periodic_report` row with its `period_end`. Not every 2.02 is a quarter's results
release (Tesla's quarterly delivery reports, pre-announcements, guidance updates): every 2.02 is stored as it was
filed, and the range inputs' results_filter keeps one release per quarter when the dates are read, using only the
reports accepted by the as-of date (so the walk-forward backtest never looks ahead); a past yfinance date within 45
days of a release that a 10-Q/10-K confirms loses to it (new report rows are counted as `sec_reports` in the
summary). NSE markets (`relations.source: nse`) take earnings dates from NSE results filings (see events_nse.py),
polled only for tickers that are due (see nse_due). Tickers whose SEC submissions or NSE requests fail are listed in
the summary (`sec_failed`, `nse_failed`; a failed SEC step as a whole in `sec_error`).

yfinance hides most request errors behind empty answers, so `failed` lists the Yahoo gaps (with `what`): `calendar`
(an error or an empty calendar), `dividends` (an error, or no dividends although some are stored for the ticker or its
calendar lists an ex-dividend date in the backfill window) and `earnings_history` (both yfinance methods raised). The
earnings-calendar page (finance.yahoo.com) is tried first; if it fails (e.g. a network that refuses the host) the
screener fallback (query1) supplies the dates. `earnings_history_sources` counts which method was used."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta

from marketbrief.collectors import nse_session
from marketbrief.collectors.event_timing import as_dates, between_quarters, merge_near
from marketbrief.collectors.events_nse import nse_due, nse_earnings
from marketbrief.collectors.events_sec import sec_earnings
from marketbrief.collectors.events_yahoo import read_calendar, read_dividends, yf_earnings
from marketbrief.constants.columns import (
    COL_DATE,
    COL_FIRST_SEEN_AT,
    COL_ID,
    COL_NAME,
    COL_SOURCE,
    COL_TICKER,
    COL_TYPE,
)
from marketbrief.constants.config_keys import (
    CFG_FILINGS,
    CFG_MARKET,
    CFG_RELATIONS,
    CFG_TICKERS,
    FILINGS_SOURCE_SEC,
    META_YAHOO,
    REL_SOURCE,
    REL_SOURCE_NSE,
)
from marketbrief.constants.environment import ENV_SEC_USER_AGENT
from marketbrief.constants.events import (
    CALENDAR_FIELDS,
    COLLECTOR_EVENTS,
    DEFAULT_HISTORY_DAYS,
    ERROR_TEXT_LIMIT,
    EVENT_EARNINGS,
    EVENT_EX_DIVIDEND,
    EVENT_LABELS,
    EVENT_PERIODIC_REPORT,
    HISTORY_SUFFIX,
    MSG_ESTIMATED_DIVIDEND,
    MSG_PERIODIC_REPORT,
    NEAR_DAYS,
    PRIORITY_FILING,
    SOURCE_NSE_HISTORY,
    SOURCE_SEC_HISTORY,
    SOURCE_YFINANCE,
    SOURCE_YFINANCE_HISTORY,
    WHAT_CALENDAR,
    WHAT_EARNINGS_HISTORY,
)
from marketbrief.constants.files import ENCODING_UTF8, JSONL_GLOB
from marketbrief.constants.kinds import KIND_EVENTS
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.paths import data_dir
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.sec_acceptance import time_warnings

ISO_DATE_LENGTH = 10


def stored_events(market: str) -> list[dict]:
    """Rows of every stored event file (for de-duplication). All files, not a recent window:
    the backfill reaches years back, so a window would let old history ids be written again."""
    rows = []
    for file in sorted((data_dir(market) / KIND_EVENTS).glob(JSONL_GLOB)):
        rows += [json.loads(line) for line in file.read_text(encoding=ENCODING_UTF8).splitlines() if line.strip()]
    return rows


@dataclass(frozen=True)
class EventDetails:
    """What an event row carries besides its id, type, date and source."""

    amount: float | None = None
    when: str | None = None
    note: str = ""
    extra: dict | None = None


NO_DETAILS = EventDetails()


def stored_day(row: dict) -> date:
    """The date of a stored event row."""
    return date.fromisoformat(str(row[COL_DATE])[:ISO_DATE_LENGTH])


class StoredHistory:
    """What the stored events say: ids seen, past earnings dates per ticker (all sources, NSE's), dividend counts."""

    def __init__(self, stored: list[dict]):
        """The stored events (to skip ids already seen) or the Yahoo collector's config."""
        self.seen = {row[COL_ID] for row in stored}
        self.earnings: dict[str, list[date]] = {}
        self.nse_dates: dict[str, list[date]] = {}
        self.dividend_counts: dict[str, int] = {}
        for row in stored:
            if row.get(COL_TYPE) == EVENT_EARNINGS and str(row.get(COL_SOURCE, "")).endswith(HISTORY_SUFFIX):
                self.earnings.setdefault(row[COL_TICKER], []).append(stored_day(row))
                if row.get(COL_SOURCE) == SOURCE_NSE_HISTORY:
                    self.nse_dates.setdefault(row[COL_TICKER], []).append(stored_day(row))
            if row.get(COL_TYPE) == EVENT_EX_DIVIDEND:
                self.dividend_counts[row[COL_TICKER]] = self.dividend_counts.get(row[COL_TICKER], 0) + 1


class EventsCollector:
    """One events run: stored history, SEC and NSE earnings, then each ticker's Yahoo calendar, dividends and
    past earnings dates, merged into new event rows."""

    def __init__(self, cfg: dict, yfinance, no_history: bool, history_days: int):
        """The stored events (to skip ids already seen) or the Yahoo collector's config."""
        self.cfg, self.yfinance, self.no_history = cfg, yfinance, no_history
        self.market, self.now, self.today = cfg[CFG_MARKET], utc_now(), utc_today()
        self.since = self.today - timedelta(days=history_days)
        self.stored = stored_events(self.market)
        self.history = StoredHistory(self.stored)
        self.seen = self.history.seen
        self.sec: dict[str, list] = {}
        self.sec_reports: dict[str, list] = {}
        self.sec_error, self.sec_failed, self.sec_times = None, [], {}
        self.nse: dict[str, list] = {}
        self.nse_info: dict = {}
        self.rows: list[dict] = []
        self.failed: list[dict] = []
        self.new_history = {EVENT_EARNINGS: 0, EVENT_EX_DIVIDEND: 0}
        self.earnings_sources: dict[str, int] = {}
        self.report_count = 0

    def add(self, key: str, event_type: str, day: date, source: str, details: EventDetails = NO_DETAILS) -> bool:
        """Add an event row unless its id (<ticker>-<type>-<date>) is stored; True when added."""
        event_id = f"{key}-{event_type}-{day}"
        if event_id in self.seen:
            return False
        label = EVENT_LABELS.get(event_type, event_type.replace("_", " "))
        name = self.cfg[CFG_TICKERS][key][COL_NAME]
        self.rows.append(
            {
                COL_ID: event_id,
                COL_DATE: day.isoformat(),
                COL_TYPE: event_type,
                COL_TICKER: key,
                COL_NAME: f"{name} {label}{details.note}",
                COL_SOURCE: source,
                COL_FIRST_SEEN_AT: self.now,
                "amount": details.amount,
                "timing": details.when,
                **(details.extra or {}),
            }
        )
        self.seen.add(event_id)
        return True

    def collect_sec(self) -> None:
        """SEC markets with a user agent: results filings (item 2.02) and 10-Q/10-K acceptances."""
        user_agent = os.environ.get(ENV_SEC_USER_AGENT)
        if self.no_history or self.cfg.get(CFG_FILINGS) != FILINGS_SOURCE_SEC or not user_agent:
            return
        try:
            self.sec, self.sec_failed = sec_earnings(
                self.cfg, self.cfg[CFG_TICKERS], user_agent, self.sec_reports, self.sec_times
            )
        except Exception as exc:
            self.sec_error = str(exc)[:ERROR_TEXT_LIMIT]

    def collect_nse(self) -> None:
        """NSE markets: results releases of the tickers that are due."""
        if self.no_history or (self.cfg.get(CFG_RELATIONS) or {}).get(REL_SOURCE) != REL_SOURCE_NSE:
            return
        due = nse_due(self.stored, list(self.cfg[CFG_TICKERS]), self.today)
        self.nse_info = {
            "nse_polled": len(due),
            "nse_backfill": sum(last_date is None for last_date in due.values()),
            "nse_failed": [],
            "nse_notes": [],
        }
        if due:
            client = nse_session.nse_client(self.cfg)
            self.nse, self.nse_info["nse_failed"], self.nse_info["nse_notes"] = nse_earnings(
                self.cfg, client, due, self.since, self.today
            )
            self.nse_info["nse_requests"] = client.requests
        self.nse_info["nse_tickers"] = len(self.nse)

    def add_periodic_reports(self) -> None:
        """SEC 10-Q/10-K acceptances with their period end: the range inputs' results_filter picks each
        quarter's results release among the 2.02 rows by them. Same window as the 2.02 rows."""
        for key, reports in self.sec_reports.items():
            for day, when, form, period_end in sorted(reports, key=lambda report: report[0]):
                details = EventDetails(
                    when=when,
                    note=MSG_PERIODIC_REPORT.format(form=form, period=period_end),
                    extra={"period_end": period_end.isoformat() if period_end else None},
                )
                if self.since <= day < self.today and self.add(
                    key, EVENT_PERIODIC_REPORT, day, SOURCE_SEC_HISTORY, details
                ):
                    self.report_count += 1

    def add_upcoming(self, key: str, calendar: dict | None, dividends: dict[date, float]) -> None:
        """The upcoming earnings and ex-dividend dates of Yahoo's calendar, with the dividend amount."""
        last_dividend = dividends[max(dividends)] if dividends else None
        for field, event_type in CALENDAR_FIELDS.items():
            for day in as_dates((calendar or {}).get(field)):
                if day < self.today:
                    continue
                if event_type == EVENT_EX_DIVIDEND:
                    amount = dividends.get(day, last_dividend)
                    note = "" if day in dividends or amount is None else MSG_ESTIMATED_DIVIDEND.format(amount=amount)
                    self.add(key, event_type, day, SOURCE_YFINANCE, EventDetails(amount=amount, note=note))
                else:
                    self.add(key, event_type, day, SOURCE_YFINANCE)

    def add_dividend_history(self, key: str, dividends: dict[date, float]) -> None:
        """Announced dividends are upcoming events, past ones are history."""
        for day, amount in sorted(dividends.items()):
            if day >= self.today:
                self.add(key, EVENT_EX_DIVIDEND, day, SOURCE_YFINANCE, EventDetails(amount=amount))
            elif day >= self.since and self.add(
                key, EVENT_EX_DIVIDEND, day, SOURCE_YFINANCE_HISTORY, EventDetails(amount=amount)
            ):
                self.new_history[EVENT_EX_DIVIDEND] += 1

    def add_earnings_history(self, key: str, ticker) -> None:
        """Past earnings days, timed where the source has a time: SEC or NSE filings first, then Yahoo."""
        yahoo_dates, used, yahoo_errors = yf_earnings(self.cfg, ticker)
        if used:
            self.earnings_sources[used] = self.earnings_sources.get(used, 0) + 1
        if yahoo_errors:
            self.failed.append({COL_TICKER: key, "what": WHAT_EARNINGS_HISTORY, "error": "; ".join(yahoo_errors)})
        # a yfinance date between two NSE results dates a quarter apart is either the same report
        # or not a results release (no quarter is missing there)
        known_nse = self.history.nse_dates.get(key, []) + [known_day for known_day, _, _ in self.nse.get(key, [])]
        yahoo_dates = [candidate for candidate in yahoo_dates if not between_quarters(candidate[0], known_nse)]
        primary = SOURCE_NSE_HISTORY if self.nse_info else SOURCE_SEC_HISTORY  # the filings source of this market
        for day, when, priority in merge_near(self.sec.get(key, []) + self.nse.get(key, []) + yahoo_dates):
            if not (self.since <= day < self.today):
                continue
            if any(abs((day - known).days) <= NEAR_DAYS for known in self.history.earnings.get(key, [])):
                continue
            source = primary if priority == PRIORITY_FILING else SOURCE_YFINANCE_HISTORY
            if self.add(key, EVENT_EARNINGS, day, source, EventDetails(when=when)):
                self.new_history[EVENT_EARNINGS] += 1
                self.history.earnings.setdefault(key, []).append(day)

    def collect_ticker(self, key: str, meta: dict) -> None:
        """Calendar, dividends and (unless --no-history) earnings history of one ticker."""
        ticker = self.yfinance.Ticker(meta[META_YAHOO])
        calendar = read_calendar(ticker, key, self.failed)
        dividends = read_dividends(
            ticker, key, calendar, self.history.dividend_counts.get(key, 0), self.since, self.failed
        )
        self.add_upcoming(key, calendar, dividends)
        if self.no_history:
            return
        self.add_dividend_history(key, dividends)
        self.add_earnings_history(key, ticker)

    def summary(self, written: int) -> dict:
        """The run's JSON summary."""
        sec_times = {"sec_times": self.sec_times, "warnings": time_warnings(self.sec_times)} if self.sec_times else {}
        return {
            SUMMARY_COLLECTOR: COLLECTOR_EVENTS,
            SUMMARY_MARKET: self.market,
            "new_events": written - sum(self.new_history.values()) - self.report_count,
            "new_history": self.new_history,
            "earnings_history_sources": self.earnings_sources,
            "sec_tickers": len(self.sec),
            "sec_reports": self.report_count,
            "sec_error": self.sec_error,
            "sec_failed": self.sec_failed,
            **sec_times,
            **self.nse_info,
            SUMMARY_FAILED: self.failed,
        }

    def collect(self) -> int:
        """Run everything, store the rows, print the summary; returns the exit code."""
        self.collect_sec()
        self.collect_nse()
        self.add_periodic_reports()
        for key, meta in self.cfg[CFG_TICKERS].items():
            self.collect_ticker(key, meta)
        written = append_jsonl(day_file(self.market, KIND_EVENTS, self.today), self.rows)
        print(json.dumps(self.summary(written), indent=2))
        # exit 1 only when Yahoo's calendar failed for every ticker (several `failed` entries per ticker)
        no_calendar = {failure[COL_TICKER] for failure in self.failed if failure["what"] == WHAT_CALENDAR}
        return 1 if no_calendar and len(no_calendar) == len(self.cfg[CFG_TICKERS]) else 0


def main() -> int:
    """Entry point of scripts/collect_events.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--no-history", action="store_true", help="skip the past earnings/dividend backfill")
    parser.add_argument(
        "--history-days",
        type=int,
        default=DEFAULT_HISTORY_DAYS,
        help=f"how far back to backfill (default {DEFAULT_HISTORY_DAYS})",
    )
    args = parser.parse_args()
    cfg = require_market(args)
    import yfinance

    return EventsCollector(cfg, yfinance, args.no_history, args.history_days).collect()
