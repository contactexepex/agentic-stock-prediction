"""Splits and bonus issues of the prices collector (issue #31, both markets): Yahoo's frame is on today's basis,
a stored bar keeps the basis of its collection time; before a symbol's new bars are written the frame is compared
with our stored bars of the same dates.

1. Each `Stock Splits` row (ex-date E, ratio r, factor 1/r) not yet recorded: the stored bars in the frame before
   E (and on/after the previous split row) are compared with Yahoo's closes for the same dates, the stored ones
   on the basis the recorded adjustments give. All at Yahoo/stored = factor (within SPLIT_TOLERANCE; whether or
   not the session before E is stored) and Yahoo's own frame without a step of about the factor at E: recorded
   (source yahoo_splits). All at 1 (within BASIS_MATCH_TOLERANCE): collected after the split, nothing to adjust.
   No stored bar before E at all: nothing to adjust. Anything else: a warning, and hold.
2. Stored bars whose close differs from Yahoo's by more than BASIS_MATCH_TOLERANCE with no split row explaining
   it: when every stored date up to the newest mismatch is off by one ratio that is a simple fraction (a re-base),
   the NSE check (India watchlist stocks) may confirm it from NSE's bhavcopies (source nse_prev_close); else a
   warning, and hold. A mismatch that is no re-base (isolated, mixed, not a simple fraction) is a warning only.
   An overlap ratio alone is never recorded.
`hold` = True: the stored basis and Yahoo's disagree in a way no source confirms, so this run must not write the
symbol's new bars (they would sit on Yahoo's new basis next to old-basis bars; a later run writes them through
to_stored_basis once the split is recorded)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from marketbrief.analytics.price_adjustments import adjustment_record, as_date, factor_after, split_fraction
from marketbrief.collectors.price_frames import (frame_closes, has_stored_before, newest_stored_before, prices_file,
                                                 stored_bars, yahoo_split_ratios)
from marketbrief.collectors.price_rebase import RebaseClaim, step_matches
from marketbrief.collectors.price_run import PriceRun
from marketbrief.constants.columns import COL_CLOSE, COL_TICKER
from marketbrief.constants.price_adjustments import BASIS_MATCH_TOLERANCE, KEY_EX_DATE, SPLIT_TOLERANCE
from marketbrief.constants.prices import (MSG_CLOSE_MISMATCH, MSG_NO_STORED_IN_FRAME, MSG_NO_WINDOW_FOR_SPLIT,
                                          MSG_NOT_ONE_REBASE, MSG_NSE_CHECK_SUFFIX, MSG_REBASE_NOT_FRACTION,
                                          MSG_REBASE_UNCONFIRMED, MSG_SPLIT_NEITHER_ADJUSTED,
                                          MSG_SPLIT_NOT_REBASED, MSG_SPLIT_RATIOS_UNEXPLAINED, SOURCE_YAHOO_SPLITS)


@dataclass
class Detection:
    """The state of one symbol's check: Yahoo's closes, our stored closes, the adjustments known so far and the
    outcome (new records, warnings, hold)."""
    key: str
    yahoo_closes: dict[date, float]
    stored: dict[date, float]
    known: list[dict]
    seen: set
    records: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hold: bool = False

    def stored_view(self, day: date) -> float:
        """The stored close of `day` on the basis the known adjustments give."""
        return self.stored[day] * factor_after(self.known, self.key, day)

    def step_at(self, ex_date: date) -> float | None:
        """Yahoo's own close step at `ex_date` (close / previous close) when the frame has both, else None."""
        before = [d for d in self.yahoo_closes if d < ex_date]
        if ex_date in self.yahoo_closes and before:
            return self.yahoo_closes[ex_date] / self.yahoo_closes[max(before)]
        return None


class AdjustmentDetector:
    """Detects the splits and bonus issues of one symbol at a time (see the module docstring); `nse_check` is
    the NseBasisCheck (or None) that may confirm a re-base from NSE's bhavcopies."""

    def __init__(self, run: PriceRun, adjustments: list[dict], nse_check=None):
        self.run, self.adjustments, self.nse_check = run, adjustments, nse_check

    def stored_closes(self, key: str, yahoo_closes: dict[date, float]) -> dict[date, float]:
        """Our stored closes for the dates of Yahoo's frame."""
        stored = {}
        for day in yahoo_closes:
            row = stored_bars(prices_file(self.run.cfg, day)).get(key)
            if row and row.get(COL_CLOSE) not in (None, "") and float(row[COL_CLOSE]) > 0:
                stored[day] = float(row[COL_CLOSE])
        return stored

    def detect(self, key: str, frame, seen: set | None = None) -> tuple[list[dict], list[str], bool]:
        """Splits and bonus issues of one symbol, from Yahoo's frame compared with our stored bars (run before this
        run's bars are written). Returns (new adjustments records, warnings, hold). `seen` = (ticker, ex_date)
        pairs already in data/<market>/adjustments/ (superseded ones too)."""
        yahoo_closes = frame_closes(frame, self.run.today)
        stored = self.stored_closes(key, yahoo_closes)
        known = [a for a in self.adjustments if a[COL_TICKER] == key]
        seen = set(seen or ()) | {(a[COL_TICKER], as_date(a[KEY_EX_DATE])) for a in known}
        state = Detection(key, yahoo_closes, stored, known, seen)
        if not stored and yahoo_closes and self.no_overlap(state):
            return state.records, state.warnings, True
        self.check_split_rows(state, yahoo_split_ratios(frame))
        if state.hold:
            return state.records, state.warnings, True
        return self.check_rebase(state)

    def no_overlap(self, state: Detection) -> bool:
        """True (with a warning) when the frame holds no stored bar and its first close is off our newest stored
        close: the price basis cannot be verified (fetch_overlap fetches back to the newest stored bar first)."""
        first = min(state.yahoo_closes)
        newest = newest_stored_before(self.run.cfg, state.key, first)
        if not newest:
            return False
        ratio = state.yahoo_closes[first] / (newest[1] * factor_after(state.known, state.key, newest[0]))
        if abs(ratio - 1) <= BASIS_MATCH_TOLERANCE:
            return False
        state.warnings.append(MSG_NO_STORED_IN_FRAME.format(key=state.key, first=first, ratio=ratio,
                                                            stored_day=newest[0]))
        return True

    def check_split_rows(self, state: Detection, ratios: dict[date, float]) -> None:
        """Handle each `Stock Splits` row, newest first."""
        bounds = sorted(ratios)
        for index in range(len(bounds) - 1, -1, -1):
            ex_date = bounds[index]
            if (state.key, ex_date) in state.seen:
                continue
            lower = bounds[index - 1] if index else date.min
            self.check_split_row(state, ex_date, ratios[ex_date], lower)

    def check_split_row(self, state: Detection, ex_date: date, ratio: float, lower: date) -> None:
        """One split row: record it, ignore it, or warn and hold (see the module docstring, case 1)."""
        factor = 1 / ratio
        window = [d for d in sorted(state.stored) if lower <= d < ex_date]
        if not window:
            if has_stored_before(self.run.cfg, state.key, ex_date):
                state.warnings.append(MSG_NO_WINDOW_FOR_SPLIT.format(key=state.key, day=ex_date, ratio=ratio))
                state.hold = True
            return
        got = {d: state.yahoo_closes[d] / state.stored_view(d) for d in window}
        step = state.step_at(ex_date)
        stepped = step is not None and step_matches(step, factor)
        if all(abs(x / factor - 1) <= SPLIT_TOLERANCE for x in got.values()):
            if stepped:
                state.warnings.append(MSG_SPLIT_NOT_REBASED.format(key=state.key, day=ex_date, ratio=ratio, step=step))
                state.hold = True
                return
            self.record_split(state, ex_date, ratio, factor, window[-1], got)
        elif all(abs(x - 1) <= BASIS_MATCH_TOLERANCE for x in got.values()):
            if stepped:
                state.warnings.append(MSG_SPLIT_NEITHER_ADJUSTED.format(key=state.key, day=ex_date, ratio=ratio,
                                                                        step=step))
                state.hold = True
        else:
            state.warnings.append(MSG_SPLIT_RATIOS_UNEXPLAINED.format(
                key=state.key, day=ex_date, ratio=ratio, low=min(got.values()), high=max(got.values()),
                factor=factor))
            state.hold = True

    def record_split(self, state: Detection, ex_date: date, ratio: float, factor: float, check_day: date,
                     got: dict[date, float]) -> None:
        """Record a split Yahoo's history is re-based for and our stored bars are not."""
        record = adjustment_record(state.key, ex_date, factor, SOURCE_YAHOO_SPLITS, self.run.now,
                                   yahoo_ratio=ratio, check_date=str(check_day),
                                   stored_close=state.stored[check_day], yahoo_close=state.yahoo_closes[check_day],
                                   measured_factor=round(got[check_day], 6))
        state.records.append(record)
        state.known.append({**record, KEY_EX_DATE: ex_date})
        state.seen.add((state.key, ex_date))

    def check_rebase(self, state: Detection) -> tuple[list[dict], list[str], bool]:
        """Stored closes that differ from Yahoo's with no split row explaining it (case 2)."""
        mismatches = {d: state.yahoo_closes[d] / state.stored_view(d) for d in sorted(state.stored)
                      if abs(state.yahoo_closes[d] / state.stored_view(d) - 1) > BASIS_MATCH_TOLERANCE}
        if not mismatches:
            return state.records, state.warnings, False
        first, last = min(mismatches), max(mismatches)
        values = list(mismatches.values())
        middle = sorted(values)[len(values) // 2]
        detail = MSG_CLOSE_MISMATCH.format(key=state.key, count=len(mismatches), first=first, last=last,
                                           low=min(values), high=max(values))
        is_rebase = (all(abs(x / middle - 1) <= SPLIT_TOLERANCE for x in values)
                     and all(d in mismatches for d in state.stored if d <= last))
        if not is_rebase:
            state.warnings.append(detail + MSG_NOT_ONE_REBASE)
            return state.records, state.warnings, False
        fraction = split_fraction(middle)
        if fraction is None:
            state.warnings.append(detail + MSG_REBASE_NOT_FRACTION)
            return state.records, state.warnings, True
        return self.confirm_rebase(state, detail, fraction, last)

    def confirm_rebase(self, state: Detection, detail: str, fraction, last: date) -> tuple[list[dict], list[str], bool]:
        """Ask the NSE check to confirm a re-base by `fraction`; hold when nothing does."""
        later = [d for d in sorted(state.yahoo_closes) if d > last]
        if self.nse_check and later:
            claim = RebaseClaim(state.key, last, state.stored[last], factor_after(state.known, state.key, last),
                                float(fraction), later, state.yahoo_closes)
            record, why = self.nse_check.confirm(claim)
            if record:
                state.records.append(record)
                return state.records, state.warnings, False
            detail += MSG_NSE_CHECK_SUFFIX.format(why=why)
        state.warnings.append(detail + MSG_REBASE_UNCONFIRMED.format(fraction=fraction))
        return state.records, state.warnings, True
