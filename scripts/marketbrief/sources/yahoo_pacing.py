"""The one door to Yahoo (yfinance): every Yahoo call of a process is spaced and stops politely on a rate limit.

`paced_yfinance()` returns a stand-in for the yfinance module whose `Ticker(symbol)` wraps yfinance's Ticker:
each method call (history, option_chain, get_earnings_dates ...) and each property read that asks Yahoo
(calendar, dividends, options, info ...) first waits for the process's shared RequestPacer (config/settings.yaml
`yahoo.pause_seconds`, default 0.5 s between the starts of two calls). When a call raises yfinance's
YFRateLimitError (HTTP 429; yfinance 1.7.0 re-raises it from history and its data layer) or an error whose text
says 429 / Too Many Requests, the shared PoliteStop trips: every later Yahoo call of the run raises YahooStoppedError
without a request, so the collectors' existing per-symbol `except` lists the symbol in `failed` (no bar, quote,
event or chain is written for it; the gates see the gap as today) and `stop_report()` adds `yahoo_stopped` and
`yahoo_skipped` (symbols not asked) to the collector's summary. The stand-in exposes only `Ticker`, so a new kind
of Yahoo call cannot bypass the pacer (tests/test_request_pacing.py checks that nothing else imports yfinance).
Not paced: requests yfinance makes lazily after a call returned (e.g. a `fast_info[...]` lookup) and its
internal cookie/crumb requests, which belong to the paced call that triggers them."""

from __future__ import annotations

import inspect
import re

from marketbrief.constants.sources import (
    CFG_PAUSE_SECONDS,
    CFG_YAHOO,
    MSG_YAHOO_STOPPED,
    SUMMARY_YAHOO_SKIPPED,
    SUMMARY_YAHOO_STOPPED,
    YAHOO_PAUSE_SECONDS,
    YAHOO_RATE_LIMIT_CLASS,
    YAHOO_RATE_LIMIT_PATTERN,
    YAHOO_STOP_RATE_LIMITED,
)
from marketbrief.sources.pacing import PoliteStop, RequestPacer

RATE_LIMIT_TEXT = re.compile(YAHOO_RATE_LIMIT_PATTERN, re.IGNORECASE)


class YahooStoppedError(RuntimeError):
    """A Yahoo call not made: Yahoo rate-limited this run earlier."""


def is_rate_limit(exc: BaseException) -> bool:
    """True for yfinance's YFRateLimitError (by class name: yfinance stays an optional import) or an error whose
    text reports HTTP 429 / Too Many Requests."""
    if any(cls.__name__ == YAHOO_RATE_LIMIT_CLASS for cls in type(exc).__mro__):
        return True
    return bool(RATE_LIMIT_TEXT.search(str(exc)))


class YahooPacer:
    """The spacing and the polite stop shared by every Yahoo call of a process."""

    def __init__(self, pacer: RequestPacer):
        """A Yahoo pacer around a RequestPacer."""
        self.pacer, self.stop = pacer, PoliteStop()

    def call(self, symbol: str, request):
        """`request()` after the pacer's wait; YahooStoppedError without a request once the stop has tripped."""
        if self.stop.stopped:
            self.stop.skip(symbol)
            raise YahooStoppedError(MSG_YAHOO_STOPPED.format(symbol=symbol, reason=self.stop.reason))
        self.pacer.wait()
        try:
            return request()
        except Exception as exc:
            if is_rate_limit(exc):
                self.stop.trip(f"{YAHOO_STOP_RATE_LIMITED} at {symbol} ({type(exc).__name__})")
            raise

    def report(self) -> dict:
        """The summary keys of a stopped run ({} when Yahoo never rate-limited it)."""
        if not self.stop.stopped:
            return {}
        return {SUMMARY_YAHOO_STOPPED: self.stop.reason, SUMMARY_YAHOO_SKIPPED: list(self.stop.skipped)}


class PacedTicker:
    """yfinance's Ticker with every Yahoo request going through the YahooPacer."""

    def __init__(self, ticker, symbol: str, pacer: YahooPacer):
        """Wrap one yfinance Ticker."""
        self._ticker, self._symbol, self._pacer = ticker, symbol, pacer

    def __getattr__(self, name: str):
        """A method comes back wrapped (paced when called); a property (a Yahoo request) is read paced; a plain
        value comes back as it is. A missing attribute raises AttributeError, as on the Ticker itself."""
        found = inspect.getattr_static(self._ticker, name)
        if callable(found):
            method = getattr(self._ticker, name)
            return lambda *args, **kwargs: self._pacer.call(self._symbol, lambda: method(*args, **kwargs))
        if hasattr(type(found), "__get__"):
            value = self._pacer.call(self._symbol, lambda: getattr(self._ticker, name))
            if name in LAZY_PROPERTIES:
                return PacedLazy(value, self._symbol, self._pacer)
            return value
        return found


# Properties whose object asks Yahoo later, when a value is read from it (yfinance's fast_info).
LAZY_PROPERTIES = frozenset({"fast_info"})


class PacedLazy:
    """A lazy yfinance object (fast_info): each item or attribute read goes through the YahooPacer, so a rate limit
    raised by its deferred request still trips the stop and is paced."""

    def __init__(self, value, symbol: str, pacer: YahooPacer):
        """Wrap the lazy object."""
        self._value, self._symbol, self._pacer = value, symbol, pacer

    def __getitem__(self, key):
        """value[key], paced."""
        return self._pacer.call(self._symbol, lambda: self._value[key])

    def __getattr__(self, name: str):
        """value.name, paced."""
        return self._pacer.call(self._symbol, lambda: getattr(self._value, name))


class PacedYfinance:
    """The yfinance module as the scripts see it: only `Ticker`, paced."""

    def __init__(self, module, pacer: YahooPacer):
        """Wrap the yfinance module (or a test stand-in with a `Ticker`)."""
        self._module, self.pacer = module, pacer

    def Ticker(self, symbol: str) -> PacedTicker:  # noqa: N802 (the yfinance name)
        """yfinance.Ticker(symbol), paced (building a Ticker asks Yahoo nothing)."""
        return PacedTicker(self._module.Ticker(symbol), symbol, self.pacer)


_shared: YahooPacer | None = None


def configured_pause() -> float:
    """`yahoo.pause_seconds` of config/settings.yaml (YAHOO_PAUSE_SECONDS when the file or key is missing)."""
    from marketbrief.core.settings import load_settings

    try:
        settings = load_settings() or {}
    except OSError:
        settings = {}
    return float((settings.get(CFG_YAHOO) or {}).get(CFG_PAUSE_SECONDS, YAHOO_PAUSE_SECONDS))


def shared_pacer() -> YahooPacer:
    """The process's YahooPacer (built on first use)."""
    global _shared
    if _shared is None:
        _shared = YahooPacer(RequestPacer(configured_pause()))
    return _shared


def reset_shared(pacer: YahooPacer | None = None) -> None:
    """Replace (or drop) the process's YahooPacer: tests, and a process that starts a new run."""
    global _shared
    _shared = pacer


def paced_yfinance(module=None) -> PacedYfinance:
    """The yfinance module behind the shared pacer (imports yfinance unless a module is given)."""
    if module is None:
        import yfinance as module  # the only yfinance import of the scripts

    return PacedYfinance(module, shared_pacer())


def stop_report() -> dict:
    """`yahoo_stopped` and `yahoo_skipped` for a collector's summary when Yahoo rate-limited this run, else {}."""
    return _shared.report() if _shared is not None else {}
