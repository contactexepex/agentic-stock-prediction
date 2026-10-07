"""NSE bhavcopy fallback of the prices collector (India): fill the watchlist bars Yahoo lacks for the last
sessions from NSE's security-wise bhavcopy, only when the file's price basis checks out against our stored bars.

Price basis: yfinance's `Close` (auto_adjust=False) is not dividend-adjusted but IS split/bonus-adjusted as
of the collection time, while the bhavcopy is as traded. A bar is therefore written only when NSE's PREV_CLOSE
is within PREV_CLOSE_TOLERANCE of our stored close of the previous session and the Yahoo frame shows no split
or bonus after that session; otherwise it is skipped with a note."""

from __future__ import annotations

import csv
import io
from datetime import date

from marketbrief.collectors import nse_session
from marketbrief.collectors.price_frames import prices_file, stored_bars, write_bar
from marketbrief.collectors.price_run import PriceRun
from marketbrief.constants.columns import COL_CLOSE, COL_DATE, COL_ID, COL_SOURCE, COL_TICKER, COL_URL
from marketbrief.constants.config_keys import CFG_FALLBACK_SESSIONS, CFG_PRICE_FALLBACK, CFG_TICKERS
from marketbrief.constants.kinds import KIND_PRICE_SOURCES
from marketbrief.constants.prices import (
    BHAVCOPY_COLUMNS,
    BHAVCOPY_PATH,
    BHAVCOPY_SERIES,
    DEFAULT_FALLBACK_SESSIONS,
    ENTRY_BEYOND_NSE_WINDOW,
    ENTRY_ERROR,
    ENTRY_FILLED_DATES,
    ERROR_TEXT_LIMIT,
    ENTRY_MISSING_AFTER_NSE,
    ENTRY_NEWEST_STORED_BAR,
    ENTRY_SESSIONS_BEHIND,
    ENTRY_YAHOO,
    MSG_BASIS_MISMATCH,
    MSG_BEYOND_WINDOW,
    MSG_BHAVCOPY_FETCH_FAILED,
    MSG_BHAVCOPY_NO_DATED_ROWS,
    MSG_BHAVCOPY_PROBLEM,
    MSG_BHAVCOPY_WRONG_DAY,
    MSG_FALLBACK_ERROR,
    MSG_HELD_BY_YAHOO_FRAME,
    MSG_MISSING_AFTER_FALLBACK,
    MSG_NO_EQ_ROW,
    MSG_NO_NEWEST_STORED,
    MSG_NO_PREV_CLOSE,
    MSG_NO_STORED_CLOSE,
    MSG_SPLIT_AFTER_PREVIOUS,
    NEWEST_LOOKBACK,
    NSE_ARCHIVES_FULL_URL,
    PREV_CLOSE_TOLERANCE,
    SOURCE_NSE_BHAVCOPY,
    SUMMARY_FILLED_FROM_NSE,
    SUMMARY_NSE_NOTES,
    SUMMARY_RESOLVED_BY_NSE,
)
from marketbrief.core.calendar import prev_session
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import nse_symbols, parse_day
from marketbrief.utils.numbers import parse_nse_number
from marketbrief.utils.sessions import last_completed_sessions


def newest_stored(cfg: dict, ticker: str, today: date) -> tuple[date | None, int]:
    """(date of the newest stored bar, sessions after it up to the previous session) for one stock,
    searching NEWEST_LOOKBACK sessions back; (None, NEWEST_LOOKBACK) when none is found."""
    day = today
    for behind in range(NEWEST_LOOKBACK):
        day = prev_session(cfg, day, include=False)
        if ticker in stored_bars(prices_file(cfg, day)):
            return day, behind
    return None, NEWEST_LOOKBACK


def bhavcopy_rows(text: str) -> list[dict]:
    """The rows of a sec_bhavdata_full file with trimmed keys and values."""
    return [
        {(key or "").strip(): (value or "").strip() for key, value in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]


def bhavcopy_bar(row: dict) -> dict | None:
    """One watchlist bar of a bhavcopy row (open, high, low, close, volume, NSE's PREV_CLOSE), or None when
    a value is missing or the prices are inconsistent."""
    open_, high, low, close = (
        parse_nse_number(row.get(BHAVCOPY_COLUMNS[name])) for name in ("open", "high", "low", "close")
    )
    volume = parse_nse_number(row.get(BHAVCOPY_COLUMNS["volume"]))
    if None in (open_, high, low, close, volume) or min(open_, high, low, close) <= 0:
        return None
    if not low <= min(open_, close) <= max(open_, close) <= high:
        return None
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": int(volume),
        "prev_close": parse_nse_number(row.get(BHAVCOPY_COLUMNS["prev_close"])),
    }


def bhavcopy_bars(text: str, day: date, symbols: dict[str, str]) -> tuple[dict[str, dict], str | None]:
    """Watchlist bars (series EQ) of one sec_bhavdata_full file -> ({ticker: bar}, problem).
    A file whose DATE1 is not `day` (NSE serves the previous session's file on a holiday) gives
    no bars and a problem. Each bar carries NSE's PREV_CLOSE for the corporate-action guard."""
    rows = bhavcopy_rows(text)
    served = {parse_day(row.get(BHAVCOPY_COLUMNS["day"])) for row in rows} - {None}
    if served != {day}:
        held = ", ".join(sorted(map(str, served))) or MSG_BHAVCOPY_NO_DATED_ROWS
        return {}, MSG_BHAVCOPY_WRONG_DAY.format(day=day, held=held)
    bars = {}
    for row in rows:
        ticker = symbols.get(row.get(BHAVCOPY_COLUMNS["symbol"], "").upper())
        if not ticker or row.get(BHAVCOPY_COLUMNS["series"]) != BHAVCOPY_SERIES:
            continue
        bar = bhavcopy_bar(row)
        if bar:
            bars[ticker] = bar
    return bars, None


def basis_problem(
    cfg: dict, ticker: str, day: date, bar: dict, splits: list[date], recorded: set[str] | frozenset = frozenset()
) -> str | None:
    """Why a bhavcopy bar may be on another price basis than our stored bars, or None.
    Stored Yahoo bars are split/bonus-adjusted as of their collection time; the bhavcopy is as
    traded. So the bar is used only when NSE's PREV_CLOSE matches our stored close of the
    previous session (within PREV_CLOSE_TOLERANCE) and Yahoo reports no split or bonus after it
    that is not already recorded in data/<market>/adjustments/ (ids in `recorded`): a recorded
    one is applied on read, and the as-traded bar then sits on the basis the views expect."""
    previous = prev_session(cfg, day, include=False)
    after = sorted(
        split_day for split_day in splits if split_day > previous and f"{ticker}-{split_day}" not in recorded
    )
    if after:
        return MSG_SPLIT_AFTER_PREVIOUS.format(day=after[0])
    row = stored_bars(prices_file(cfg, previous)).get(ticker)
    if row is None:
        return MSG_NO_STORED_CLOSE.format(previous=previous)
    stored, nse_previous = float(row[COL_CLOSE]), bar.get("prev_close")
    if not nse_previous or stored <= 0:
        return MSG_NO_PREV_CLOSE.format(previous=previous)
    gap = nse_previous / stored - 1
    if abs(gap) > PREV_CLOSE_TOLERANCE:
        return MSG_BASIS_MISMATCH.format(nse_previous=nse_previous, stored=stored, previous=previous, gap=gap)
    return None


class NseBarFiller:
    """Fills missing watchlist bars of the last sessions from the NSE bhavcopy, oldest session first (a filled
    bar can then anchor the next session's basis check)."""

    def __init__(
        self,
        run: PriceRun,
        splits: dict[str, list[date]] | None = None,
        recorded: set[str] | frozenset = frozenset(),
        held: set[str] | frozenset = frozenset(),
    ):
        """The NSE fallback's run, known splits and recorded and held bars."""
        self.run, self.splits, self.recorded, self.held = run, splits or {}, recorded, held
        self.symbols = nse_symbols(run.cfg)
        self.filled: list[dict] = []
        self.still_missing: dict[str, list[dict]] = {}
        self.notes: list[str] = []
        self.denied: str | None = None

    def missing_by_session(self, sessions: int) -> dict[date, list[str]]:
        """{session: watchlist tickers with no stored bar}, for the sessions that lack any."""
        missing = {}
        for day in last_completed_sessions(self.run.cfg, self.run.today, sessions):
            have = stored_bars(prices_file(self.run.cfg, day))
            lacking = [ticker for ticker in self.run.cfg[CFG_TICKERS] if ticker not in have]
            if lacking:
                missing[day] = lacking
        return missing

    def fill(self, sessions: int, nse=None) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
        """Returns (filled bars, {ticker: [{date, reason}] still missing}, notes)."""
        missing = self.missing_by_session(sessions)
        if not missing:
            return self.filled, self.still_missing, self.notes
        nse = nse or nse_session.nse_client(self.run.cfg)
        for day, lacking in missing.items():
            bars, problem = self.day_bars(nse, day)
            for ticker in lacking:
                self.fill_ticker(ticker, day, bars.get(ticker), problem)
        return self.filled, self.still_missing, self.notes

    def day_bars(self, nse, day: date) -> tuple[dict[str, dict], str | None]:
        """The bars of one session's bhavcopy and the problem that stops them from being used, if any. A host the
        proxy refuses fails every other file the same way, so its problem is reused without a request."""
        if self.denied is not None:
            return {}, self.denied
        bars, problem = {}, None
        try:
            bars, problem = bhavcopy_bars(nse.text(BHAVCOPY_PATH.format(day=day)), day, self.symbols)
            problem = MSG_BHAVCOPY_PROBLEM.format(problem=problem) if problem else None
        except FetchError as exc:
            problem = MSG_BHAVCOPY_FETCH_FAILED.format(day=day, error=exc.error[:120])
            if exc.host:
                self.denied = problem
        if problem:
            self.notes.append(problem)
        return bars, problem

    def reason_not_filled(self, ticker: str, day: date, bar: dict | None, problem: str | None) -> str | None:
        """Why a lacking bar is not written, or None."""
        reason = problem or (None if bar else MSG_NO_EQ_ROW.format(ticker=ticker))
        if not reason and ticker in self.held:  # its Yahoo frame failed the split/bonus check this run
            reason = MSG_HELD_BY_YAHOO_FRAME
        return reason or basis_problem(self.run.cfg, ticker, day, bar, self.splits.get(ticker, []), self.recorded)

    def fill_ticker(self, ticker: str, day: date, bar: dict | None, problem: str | None) -> None:
        """Write one missing bar, or record why it stays missing."""
        reason = self.reason_not_filled(ticker, day, bar, problem)
        if reason:  # listed once, in failed[].missing_after_nse (issue #35: no second copy in nse_notes)
            self.still_missing.setdefault(ticker, []).append({COL_DATE: day.isoformat(), "reason": reason})
            return
        path = prices_file(self.run.cfg, day)
        if ticker in stored_bars(path):  # never a second bar for a (date, ticker)
            return
        write_bar(
            path,
            [
                day.isoformat(),
                ticker,
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"],
                bar["close"],
                bar["volume"],
                self.run.now,
            ],
        )
        url = NSE_ARCHIVES_FULL_URL.format(path=BHAVCOPY_PATH.format(day=day))
        append_jsonl(
            day_file(self.run.cfg["market"], KIND_PRICE_SOURCES, day),
            [
                {
                    COL_ID: f"{day}-{ticker}",
                    COL_DATE: day.isoformat(),
                    COL_TICKER: ticker,
                    COL_SOURCE: SOURCE_NSE_BHAVCOPY,
                    COL_URL: url,
                    "filled_at": self.run.now,
                }
            ],
        )
        self.filled.append(
            {
                COL_TICKER: ticker,
                COL_DATE: day.isoformat(),
                **{field: value for field, value in bar.items() if field != "prev_close"},
                COL_SOURCE: SOURCE_NSE_BHAVCOPY,
                COL_URL: url,
            }
        )


def nse_fallback(
    run: PriceRun,
    sessions: int,
    splits: dict[str, list[date]] | None = None,
    nse=None,
    recorded: set[str] | frozenset = frozenset(),
    held: set[str] | frozenset = frozenset(),
) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    """Fill missing watchlist bars of the last `sessions` sessions from the NSE bhavcopy.
    Returns (filled bars, {ticker: [{date, reason}] still missing}, notes)."""
    return NseBarFiller(run, splits, recorded, held).fill(sessions, nse)


def annotate_failure(
    failure: dict, still_missing: list[dict] | None, newest: tuple[date | None, int], sessions: int, window_start: date
) -> None:
    """Add what the fallback found to a Yahoo failure: the sessions still missing, and the newest stored bar
    when the gap reaches further back than the sessions the fallback checks."""
    if still_missing:
        failure[ENTRY_MISSING_AFTER_NSE] = still_missing
    last, behind = newest
    if last is None or behind > sessions:  # a gap older than the checked sessions: not closed
        failure[ENTRY_NEWEST_STORED_BAR] = str(last) if last else MSG_NO_NEWEST_STORED.format(sessions=NEWEST_LOOKBACK)
        failure[ENTRY_SESSIONS_BEHIND] = behind
        failure[ENTRY_BEYOND_NSE_WINDOW] = MSG_BEYOND_WINDOW.format(start=window_start)


def apply_fallback(
    run: PriceRun,
    targets: dict,
    failed: list[dict],
    splits: dict[str, list[date]],
    recorded: set[str] | frozenset = frozenset(),
    held: set[str] | frozenset = frozenset(),
) -> dict:
    """Run the NSE fallback and sort the Yahoo failures: a stock whose recent sessions are all
    stored afterwards moves to `resolved_by_nse`; one still missing a session, or whose newest
    stored bar (before the fallback) lies further back than the checked sessions, stays in `failed`."""
    cfg = run.cfg
    sessions = int((cfg.get(CFG_PRICE_FALLBACK) or {}).get(CFG_FALLBACK_SESSIONS, DEFAULT_FALLBACK_SESSIONS))
    window_start = last_completed_sessions(cfg, run.today, sessions)[0]
    newest = {
        configured_ticker: newest_stored(cfg, configured_ticker, run.today)
        for configured_ticker in cfg[CFG_TICKERS]
        if any(failed_entry[COL_TICKER] == configured_ticker for failed_entry in failed)
    }
    try:
        filled, still, notes = nse_fallback(run, sessions, splits, recorded=recorded, held=held)
    except Exception as exc:  # the fallback must never cost the Yahoo bars already written
        filled, still, notes = [], {}, [MSG_FALLBACK_ERROR.format(error=str(exc)[:ERROR_TEXT_LIMIT])]
    resolved, keep = [], []
    for failure in failed:
        ticker = failure[COL_TICKER]
        if ticker not in cfg[CFG_TICKERS]:
            keep.append(failure)
            continue
        annotate_failure(failure, still.get(ticker), newest.get(ticker, (None, 0)), sessions, window_start)
        if ticker in still or ENTRY_BEYOND_NSE_WINDOW in failure or ticker in held:  # a held stock stays failed
            keep.append(failure)
        else:
            dates = [bar[COL_DATE] for bar in filled if bar[COL_TICKER] == ticker]
            resolved.append({**failure, ENTRY_FILLED_DATES: dates})
    for ticker, days in still.items():  # a gap Yahoo did not flag is listed too
        if not any(failed_entry[COL_TICKER] == ticker for failed_entry in keep):
            keep.append(
                {
                    COL_TICKER: ticker,
                    ENTRY_YAHOO: targets[ticker],
                    ENTRY_ERROR: MSG_MISSING_AFTER_FALLBACK,
                    ENTRY_MISSING_AFTER_NSE: days,
                }
            )
    failed[:] = keep
    return {SUMMARY_FILLED_FROM_NSE: filled, SUMMARY_RESOLVED_BY_NSE: resolved, SUMMARY_NSE_NOTES: notes}
