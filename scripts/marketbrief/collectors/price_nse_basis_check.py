"""India watchlist stocks: confirm a re-base (ratio = factor) of our stored closes from NSE's bhavcopies and find
its ex-date.

NSE's PREV_CLOSE is the as-traded close of the session before; it is not adjusted on an ex-date (HDFCBANK's 1:1
bonus, ex 2025-08-26: PREV_CLOSE 1964.10 = its 25-Aug close). The frame's sessions e after the newest re-based
stored bar `last` are walked in order, up to NSE_SCAN:
- PREV_CLOSE(e) must equal the as-traded close of e's previous session within PREV_CLOSE_TOLERANCE: our stored
  close when that session is `last` (the first e must follow `last` directly: this ties our stored basis to the
  traded one), else Yahoo's re-based close / factor (e's previous session was still before the ex-date).
- Exact chain: with the next session n also in the frame, PREV_CLOSE(n) is e's traded close. If it equals
  Yahoo's close of e within CHAIN_TOLERANCE, e is on the new basis: e is the ex-date and the action is recorded.
  If it equals Yahoo's close / factor, e is still before the ex-date: next e. Anything else stops without a record.
- Step: for a factor below WEAK_FACTOR, a traded close(e) / PREV_CLOSE(e) that steps by about the factor
  (step_matches) also confirms e as the ex-date (no next session needed). For a factor of 0.9 or more (e.g. a
  1:10 bonus, 10/11) only the chain confirms, since an ordinary day's move can look like the step.
No confirmation (yet) returns (None, reason): the caller warns and holds the symbol."""

from __future__ import annotations

from datetime import date

from marketbrief.collectors.price_nse_fallback import bhavcopy_bars
from marketbrief.collectors.price_run import PriceRun
from marketbrief.collectors.price_rebase import RebaseClaim, step_matches
from marketbrief.constants.config_keys import CFG_TICKERS
from marketbrief.constants.prices import (
    BHAVCOPY_PATH,
    CHAIN_TOLERANCE,
    MSG_CHECK_BHAVCOPY_FAILED,
    MSG_CHECK_CHAIN_BROKEN,
    MSG_CHECK_NO_EX_DATE,
    MSG_CHECK_NO_ROW_WITH_PREV_CLOSE,
    MSG_CHECK_NO_STEP_PROOF,
    MSG_CHECK_NOT_WATCHLIST,
    MSG_CHECK_PREV_CLOSE_OFF,
    MSG_CHECK_PREVIOUS_UNKNOWN,
    NSE_ARCHIVES_FULL_URL,
    NSE_SCAN,
    PREV_CLOSE_TOLERANCE,
    SOURCE_NSE_PREV_CLOSE,
    WEAK_FACTOR,
)
from marketbrief.core.calendar import prev_session
from marketbrief.analytics.price_adjustments import adjustment_record
from marketbrief.sources.errors import FetchError
from marketbrief.sources.nse_parsing import nse_symbols


class NseBasisCheck:
    """Confirms re-bases from NSE bhavcopies; `nse_getter` gives the run's one NSE client."""

    def __init__(self, run: PriceRun, nse_getter):
        """The basis check's run and NSE getter, or a rebase claim and its cache."""
        self.run, self.nse_getter = run, nse_getter
        self.symbols = nse_symbols(run.cfg)

    def confirm(self, claim: RebaseClaim) -> tuple[dict | None, str | None]:
        """(adjustment record, None) when NSE's bhavcopies confirm the re-base and its ex-date, else (None, why)."""
        if claim.key not in self.run.cfg[CFG_TICKERS]:
            return None, MSG_CHECK_NOT_WATCHLIST
        return _BasisScan(self, claim).run()


class _BasisScan:
    """One walk over the sessions after a re-based stored bar (bhavcopies cached for the walk)."""

    def __init__(self, check: NseBasisCheck, claim: RebaseClaim):
        """The basis check's run and NSE getter, or a rebase claim and its cache."""
        self.check, self.claim, self.cache = check, claim, {}

    def bar(self, day: date) -> tuple[dict | None, str | None, str]:
        """(bar with PREV_CLOSE, why not, url) of one session's bhavcopy for the claimed stock."""
        if day not in self.cache:
            url = BHAVCOPY_PATH.format(day=day)
            try:
                bars, problem = bhavcopy_bars(self.check.nse_getter().text(url), day, self.check.symbols)
            except FetchError as exc:
                self.cache[day] = (None, MSG_CHECK_BHAVCOPY_FAILED.format(day=day, error=exc.error[:120]), url)
            else:
                bar = bars.get(self.claim.key)
                why = problem or (
                    None
                    if bar and bar.get("prev_close")
                    else MSG_CHECK_NO_ROW_WITH_PREV_CLOSE.format(key=self.claim.key, day=day)
                )
                self.cache[day] = (None if why else bar, why, url)
        return self.cache[day]

    def found(self, day: date, bar: dict, url: str) -> tuple[dict, None]:
        """The adjustment record for ex-date `day`."""
        claim = self.claim
        measured = claim.yahoo_closes[claim.last] / (claim.stored_last * claim.known_factor)
        record = adjustment_record(
            claim.key,
            day,
            claim.factor,
            SOURCE_NSE_PREV_CLOSE,
            self.check.run.now,
            check_date=str(claim.last),
            stored_close=claim.stored_last,
            yahoo_close=claim.yahoo_closes[claim.last],
            measured_factor=round(measured, 6),
            nse_prev_close=bar["prev_close"],
            nse_ex_close=bar["close"],
            url=NSE_ARCHIVES_FULL_URL.format(path=url),
        )
        return record, None

    def expected_previous_close(self, previous: date) -> float | None:
        """The as-traded close of the session `previous`, or None when it is not known."""
        claim = self.claim
        if previous == claim.last:
            return claim.stored_last
        if previous in claim.yahoo_closes and previous > claim.last:
            return claim.yahoo_closes[previous] / (claim.factor * claim.known_factor)
        return None

    def step(self, index: int, day: date) -> tuple[dict | None, str | None] | None:
        """Examine one session: a result (record, why) ends the walk, None goes on to the next session."""
        claim, cfg = self.claim, self.check.run.cfg
        previous = prev_session(cfg, day, include=False)
        expected = self.expected_previous_close(previous)
        if expected is None:
            return None, MSG_CHECK_PREVIOUS_UNKNOWN.format(day=day, previous=previous, last=claim.last)
        bar, why, url = self.bar(day)
        if why:
            return None, why
        prev_close = bar["prev_close"]
        if abs(prev_close / expected - 1) > PREV_CLOSE_TOLERANCE:
            return None, MSG_CHECK_PREV_CLOSE_OFF.format(
                day=day, prev_close=prev_close, expected=expected, previous=previous
            )
        if claim.factor < WEAK_FACTOR and step_matches(bar["close"] / prev_close, claim.factor):
            return self.found(day, bar, url)
        return self.chain(index, day, bar, url)

    def chain(self, index: int, day: date, bar: dict, url: str) -> tuple[dict | None, str | None] | None:
        """The exact chain through the next session's PREV_CLOSE (see the module docstring)."""
        claim, cfg = self.claim, self.check.run.cfg
        following = claim.later[index + 1] if index + 1 < len(claim.later) else None
        if following is None or prev_session(cfg, following, include=False) != day:
            return None, MSG_CHECK_NO_STEP_PROOF.format(day=day)
        next_bar, why, _ = self.bar(following)
        if why:
            return None, why
        yahoo_close = claim.yahoo_closes[day]
        if abs(next_bar["prev_close"] / yahoo_close - 1) <= CHAIN_TOLERANCE:
            return self.found(day, bar, url)
        if abs(next_bar["prev_close"] * claim.factor * claim.known_factor / yahoo_close - 1) > CHAIN_TOLERANCE:
            return None, MSG_CHECK_CHAIN_BROKEN.format(
                day=following,
                prev_close=next_bar["prev_close"],
                previous_day=day,
                yahoo_close=yahoo_close,
                factor=claim.factor,
            )
        return None

    def run(self) -> tuple[dict | None, str | None]:
        """Walk the first NSE_SCAN sessions after the re-based bar."""
        scan = self.claim.later[:NSE_SCAN]
        for index, day in enumerate(scan):
            outcome = self.step(index, day)
            if outcome is not None:
                return outcome
        return None, MSG_CHECK_NO_EX_DATE.format(first=scan[0], last=scan[-1])
