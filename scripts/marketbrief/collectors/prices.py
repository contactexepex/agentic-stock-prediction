"""Collect daily OHLCV bars via yfinance (free, unofficial Yahoo Finance access; personal use)
for a market's tickers and market-level symbols (benchmark, vol index, cues, factors) into
data/<market>/prices/YYYY/MM/<trading-date>.csv. One file per trading date; a bar is written
once. Today's bar (UTC) is skipped because it may be incomplete.
First run: --period 2y (needed for 1-year beta and the range backtest).
A symbol is listed in `failed` when Yahoo returns nothing, no completed bar, or only stale bars:
the newest completed bar is older than the market's previous session (its stocks, benchmark, vol
index and sector indices) or than STALE_DAYS calendar days (cues and factors on other exchanges).
Stale bars are still stored; the entry says how old the newest one is.

Official fallback (markets with `price_fallback: {source: nse_bhavcopy}`, i.e. India): after the
Yahoo pass, every watchlist stock (`tickers`, not indices, cues or factors) that has no stored bar
for one of the last `price_fallback.sessions` completed sessions of the exchange calendar gets
that day's open, high, low, close and volume from NSE's security-wise bhavcopy
(nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv, series EQ; the file
is used only when its DATE1 is that session), oldest session first. `adj_close` is set to the close.
Price basis: yfinance's `Close` (auto_adjust=False) is not dividend-adjusted but IS split/bonus-
adjusted as of the collection time, so a stored bar collected after a split or bonus is on the
post-event basis (HDFCBANK 2025-08-22, stored after its 1:1 bonus: close 982.3, volume 19,833,502;
NSE's bhavcopy: 1964.60 and 9,916,751). The bhavcopy is as traded. A bhavcopy bar is therefore
written only when NSE's PREV_CLOSE is within 0.5% of our stored close of the previous session and
the Yahoo frame shows no split or bonus after that session; otherwise it is skipped with a note.
A bar is never overwritten: Yahoo is asked first, and the fallback only writes a (date, ticker)
no file holds yet. The prices CSV keeps its columns (a source column would break the
fixed-column reader); each filled bar gets a row in data/<market>/price_sources/ (view
`bar_sources`) and is listed in the summary's `filled_from_nse`. A watchlist stock that Yahoo
failed (stale, empty, error) moves from `failed` to `resolved_by_nse` (Yahoo's error plus
`filled_dates`, this run's fills, empty when an earlier run stored them) only when every checked
session is stored afterwards and its newest bar before the fallback was no more than `sessions`
sessions behind. Otherwise it stays in `failed` with `missing_after_nse` (date and reason) and/or
`newest_stored_bar` and `sessions_behind`; a gap Yahoo did not flag is added there too.

Holiday bars (issue #40): Yahoo serves a flat zero-volume bar (open = high = low = close = the previous close) on
exchange holidays. A stock or own-exchange index (benchmark, vol index, sector index) bar on a day that is not a session
of the market calendar, and a flat zero-volume stock bar on any day, is not stored; it is listed in the summary's
`dropped_non_session` (ticker, date, reason). Cues and factors follow other calendars and are kept. Bars already stored
stay; the `ohlc_raw` view leaves them out on read (`own_closed_days`, built by `connect`).

Splits and bonus issues (issue #31, both markets; price_split_detection.py, analytics/price_adjustments.py):
before a symbol's new bars are written, Yahoo's frame (today's basis) is compared with our stored bars of
the same dates. A `Stock Splits` row whose stored bars before it sit on the old basis is recorded
once in data/<market>/adjustments/ (summary `adjustments`) and applied on read by the ohlc and bars
views; for India a re-base with no split row can be confirmed from NSE's bhavcopies instead (which
also finds the ex-date after a missed run). Any other mismatch above 2% goes to `warnings` and is
never recorded; when it is a re-base or a split row no source confirms, the symbol's new bars are
held (`held`, `failed`) on every run until a later run can record it (a frame that no longer
covers our stored bars is refetched from before the newest one, so the check keeps its overlap). An
older bar Yahoo serves after a recorded split is written on its date's stored basis (`rebased_bars`), and a
recorded split no longer blocks the bhavcopy fallback."""

from __future__ import annotations

import json
from datetime import date, timedelta

from marketbrief.analytics.price_adjustments import factor_after, load_adjustments
from marketbrief.collectors import nse_session
from marketbrief.collectors.price_frames import (
    frame_error,
    newest_stored_before,
    prices_file,
    stored_bars,
    stored_overlap,
    to_stored_basis,
    write_bar,
    yahoo_splits,
)
from marketbrief.collectors.price_nse_basis_check import NseBasisCheck
from marketbrief.collectors.price_nse_fallback import apply_fallback
from marketbrief.collectors.price_run import PriceRun
from marketbrief.collectors.price_split_detection import AdjustmentDetector
from marketbrief.constants.columns import COL_DATE, COL_ID, COL_TICKER
from marketbrief.constants.config_keys import (
    CFG_FALLBACK_SOURCE,
    CFG_MARKET,
    CFG_PRICE_FALLBACK,
    CFG_SYMBOLS,
    CFG_TICKERS,
    META_ROLE,
    META_YAHOO,
)
from marketbrief.constants.kinds import KIND_ADJUSTMENTS
from marketbrief.constants.price_adjustments import KEY_EX_DATE
from marketbrief.constants.prices import (
    COLLECTOR_PRICES,
    DEFAULT_PERIOD,
    DROP_REASON_FLAT_ZERO_VOLUME,
    DROP_REASON_NOT_A_SESSION,
    ENTRY_ERROR,
    ENTRY_REASON,
    ENTRY_YAHOO,
    ERROR_STALE_PREFIX,
    ERROR_TEXT_LIMIT,
    GAP_REFETCH_DAYS,
    MIN_OVERLAP,
    MSG_HELD_NOTE,
    MSG_LONGER_HISTORY_FAILED,
    MSG_SPLIT_CHECK_FAILED,
    OWN_EXCHANGE_ROLES,
    PRICE_DECIMALS,
    SOURCE_NSE_BHAVCOPY,
    SUMMARY_ADJUSTMENTS,
    SUMMARY_DROPPED_NON_SESSION,
    SUMMARY_HELD,
    SUMMARY_NEW_BARS,
    SUMMARY_REBASED,
    SUMMARY_SYMBOLS,
    WARNING_TEXT_LIMIT,
    YAHOO_ADJ_CLOSE,
    YAHOO_CLOSE,
    YAHOO_HIGH,
    YAHOO_INTERVAL_DAILY,
    YAHOO_LOW,
    YAHOO_OHLC,
    YAHOO_OPEN,
    YAHOO_VOLUME,
)
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET, SUMMARY_WARNINGS
from marketbrief.core.calendar import is_session
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file


def uses_nse_fallback(cfg: dict) -> bool:
    """True for markets whose config names the NSE bhavcopy as the official fallback (India)."""
    return (cfg.get(CFG_PRICE_FALLBACK) or {}).get(CFG_FALLBACK_SOURCE) == SOURCE_NSE_BHAVCOPY


class PriceCollector:
    """One prices run: fetch each symbol's Yahoo frame, check splits, write the new bars, run the NSE fallback."""

    def __init__(self, cfg: dict, period: str):
        """The price collector's config and download period."""
        self.cfg, self.period = cfg, period
        self.run = PriceRun(cfg, utc_today(), utc_now())
        self.targets = {
            **{key: meta[META_YAHOO] for key, meta in cfg[CFG_SYMBOLS].items()},
            **{key: meta[META_YAHOO] for key, meta in cfg[CFG_TICKERS].items()},
        }
        market = cfg[CFG_MARKET]
        self.adjustments = load_adjustments(market)
        self.seen = {
            (adjustment[COL_TICKER], adjustment[KEY_EX_DATE])
            for adjustment in load_adjustments(market, include_superseded=True)
        }
        self.written = 0
        self.failed: list[dict] = []
        self.splits: dict[str, list[date]] = {}
        self.new_adjustments: list[dict] = []
        self.warnings: list[str] = []
        self.rebased: list[dict] = []
        self.held: list[str] = []
        self.dropped: list[dict] = []
        nse_box: dict = {}
        nse_check = None
        if uses_nse_fallback(cfg):
            nse_check = NseBasisCheck(self.run, lambda: nse_box.setdefault("client", nse_session.nse_client(cfg)))
        self.detector = AdjustmentDetector(self.run, self.adjustments, nse_check)

    def history(self, yfinance, symbol: str, **window):
        """One yfinance daily history request (unadjusted closes)."""
        return yfinance.Ticker(symbol).history(**window, interval=YAHOO_INTERVAL_DAILY, auto_adjust=False)

    def with_overlap(self, yfinance, key: str, symbol: str, frame):
        """The frame, or a longer one fetched from before our newest stored bar when the frame covers too few
        stored bars for the basis check."""
        if frame is None or frame.empty or stored_overlap(self.cfg, key, frame, self.run.today) >= MIN_OVERLAP:
            return frame
        first = min(stamp.date() for stamp in frame.index)
        newest = newest_stored_before(self.cfg, key, first)
        if not newest:
            return frame
        try:  # a gap: fetch from before our newest stored bar so the basis check has an overlap
            longer = self.history(yfinance, symbol, start=(newest[0] - timedelta(days=GAP_REFETCH_DAYS)).isoformat())
            if longer is not None and not longer.empty and min(stamp.date() for stamp in longer.index) < first:
                return longer
        except Exception as exc:  # the check below then compares across the gap
            self.warnings.append(MSG_LONGER_HISTORY_FAILED.format(key=key, error=str(exc)[:120]))
        return frame

    def detect_adjustments(self, key: str, frame) -> tuple[list[dict], list[str], bool]:
        """The splits and bonus issues of one symbol (before its bars are written); a failed check costs no bars."""
        try:
            return self.detector.detect(key, frame, self.seen)
        except Exception as exc:
            return [], [MSG_SPLIT_CHECK_FAILED.format(key=key, error=str(exc)[:WARNING_TEXT_LIMIT])], False

    def record_adjustments(self, key: str, records: list[dict]) -> None:
        """Append new adjustment records to data/<market>/adjustments/ and remember them."""
        for record in records:
            ex_date = date.fromisoformat(record[KEY_EX_DATE])
            append_jsonl(day_file(self.cfg[CFG_MARKET], KIND_ADJUSTMENTS, ex_date), [record])
            self.adjustments.append({**record, KEY_EX_DATE: ex_date})
            self.seen.add((key, ex_date))
        self.new_adjustments += records

    def hold_symbol(self, key: str, symbol: str) -> None:
        """Yahoo's frame is on a basis no source confirms: no new bar is written this run."""
        self.held.append(key)
        entry = next((failure for failure in self.failed if failure[COL_TICKER] == key), None)
        if entry:
            entry[ENTRY_ERROR] += f"; {MSG_HELD_NOTE}"
        else:
            self.failed.append({COL_TICKER: key, ENTRY_YAHOO: symbol, ENTRY_ERROR: MSG_HELD_NOTE})

    def drop_reason(self, key: str, day: date, row) -> str | None:
        """Why Yahoo's bar is no real session bar, or None. Yahoo serves a flat zero-volume bar (open = high = low =
        close = the previous close) for an exchange holiday. A stock or an index of the market's own exchange
        (benchmark, vol index, sector index) is dropped on a day that is not a session of the market calendar; a
        stock is also dropped for a flat bar with zero volume (indices report volume 0 legitimately; cues and
        factors trade on other exchanges' calendars)."""
        is_stock = key in self.cfg[CFG_TICKERS]
        own_exchange = is_stock or self.cfg[CFG_SYMBOLS].get(key, {}).get(META_ROLE) in OWN_EXCHANGE_ROLES
        if own_exchange and not is_session(self.cfg, day):
            return DROP_REASON_NOT_A_SESSION
        flat = len({float(row[column]) for column in YAHOO_OHLC}) == 1
        volume = row[YAHOO_VOLUME]
        if is_stock and flat and (volume != volume or int(volume) == 0):
            return DROP_REASON_FLAT_ZERO_VOLUME
        return None

    def write_new_bars(self, key: str, frame) -> None:
        """Write each completed bar of the frame that no prices file holds yet (bars of days without a session
        and flat zero-volume stock bars are listed in `dropped_non_session`, not stored)."""
        today = self.run.today
        for stamp, row in frame.iterrows():
            day = stamp.date()
            if day >= today or row.isna()[YAHOO_OHLC].any():
                continue
            path = prices_file(self.cfg, day)
            if key in stored_bars(path):
                continue
            reason = self.drop_reason(key, day, row)
            if reason:
                self.dropped.append({COL_TICKER: key, COL_DATE: day.isoformat(), ENTRY_REASON: reason})
                continue
            close = float(row[YAHOO_CLOSE])
            adj_close = float(row[YAHOO_ADJ_CLOSE]) if YAHOO_ADJ_CLOSE in row else close
            volume = int(row[YAHOO_VOLUME]) if row[YAHOO_VOLUME] == row[YAHOO_VOLUME] else 0
            bar = [
                day.isoformat(),
                key,
                *(round(float(row[column]), PRICE_DECIMALS) for column in (YAHOO_OPEN, YAHOO_HIGH, YAHOO_LOW)),
                round(close, PRICE_DECIMALS),
                round(adj_close, PRICE_DECIMALS),
                volume,
                self.run.now,
            ]
            factor = factor_after(self.adjustments, key, day)
            if factor != 1:  # an older bar Yahoo serves on today's basis, written on its stored basis
                bar = to_stored_basis(bar, factor)
                self.rebased.append({COL_TICKER: key, COL_DATE: day.isoformat(), "factor": factor})
            write_bar(path, bar)
            self.written += 1

    def process_symbol(self, yfinance, key: str, symbol: str) -> None:
        """Fetch, check and store one symbol."""
        try:
            frame = self.history(yfinance, symbol, period=self.period)
        except Exception as exc:  # network or symbol errors must not stop other symbols
            self.failed.append({COL_TICKER: key, ENTRY_YAHOO: symbol, ENTRY_ERROR: str(exc)[:ERROR_TEXT_LIMIT]})
            return
        frame = self.with_overlap(yfinance, key, symbol, frame)
        self.splits[key] = yahoo_splits(frame)
        error = frame_error(self.cfg, key, frame, self.run.today)
        if error:
            self.failed.append({COL_TICKER: key, ENTRY_YAHOO: symbol, ENTRY_ERROR: error})
            if not error.startswith(ERROR_STALE_PREFIX):
                return
        records, warnings, hold = self.detect_adjustments(key, frame)
        self.record_adjustments(key, records)
        self.warnings += warnings
        if hold:
            self.hold_symbol(key, symbol)
            return
        self.write_new_bars(key, frame)

    def summary(self) -> dict:
        """The run's JSON summary (the NSE fallback runs here, after the Yahoo pass)."""
        summary = {
            SUMMARY_COLLECTOR: COLLECTOR_PRICES,
            SUMMARY_MARKET: self.cfg[CFG_MARKET],
            SUMMARY_SYMBOLS: len(self.targets),
            SUMMARY_NEW_BARS: self.written,
            SUMMARY_ADJUSTMENTS: self.new_adjustments,
        }
        if self.rebased:
            summary[SUMMARY_REBASED] = self.rebased
        if self.held:
            summary[SUMMARY_HELD] = self.held
        if self.dropped:
            summary[SUMMARY_DROPPED_NON_SESSION] = self.dropped
        if uses_nse_fallback(self.cfg):
            recorded = {adjustment[COL_ID] for adjustment in self.adjustments}
            summary.update(apply_fallback(self.run, self.targets, self.failed, self.splits, recorded, set(self.held)))
        summary[SUMMARY_WARNINGS] = self.warnings
        summary[SUMMARY_FAILED] = self.failed
        return summary

    def collect(self, yfinance) -> dict:
        """Process every symbol and return the summary."""
        for key, symbol in self.targets.items():
            self.process_symbol(yfinance, key, symbol)
        return self.summary()


def main() -> int:
    """Entry point of scripts/collect_prices.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--period", default=DEFAULT_PERIOD, help="yfinance period, e.g. 1mo, 3mo, 1y, 2y")
    args = parser.parse_args()
    cfg = require_market(args)
    import yfinance  # imported here so the rest of the repo works without it

    collector = PriceCollector(cfg, args.period)
    summary = collector.collect(yfinance)
    print(json.dumps(summary, indent=2))
    return 1 if summary[SUMMARY_FAILED] and len(summary[SUMMARY_FAILED]) == len(collector.targets) else 0
