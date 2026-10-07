"""EUR/USD for the owner's portfolio (F1.11): the stored `EURUSD=X` closes (config/markets/us.yaml symbol EURUSD,
role fx) as of the clock, used to convert BUX's euro order fee and for the EUR view of US positions."""
from __future__ import annotations

from datetime import date

from marketbrief.portfolio import reads

MSG_NO_EURUSD = ("no stored EUR/USD close (symbol {symbol}) by {clock}: the BUX order fee and the EUR view need "
                 "one; run collect_prices for the us market first")


class EurUsd:
    """The stored EUR/USD closes (USD per EUR) by the clock."""

    def __init__(self, con, cfg: dict, clock, symbol: str | None):
        """Read the closes of `symbol` stored by the clock (none when symbol is None)."""
        self.symbol, self.clock = symbol, clock
        frame = reads.stored_bars(con, cfg, clock, [symbol]) if symbol else None
        self.closes = {} if frame is None else {row["date"]: float(row["close"]) for row in frame.to_dict("records")}

    def on(self, day: date) -> float | None:
        """The newest close dated on or before `day`; before the first stored close, the first one (known by the
        clock); None when none is stored."""
        before = [d for d in self.closes if d <= day]
        if before:
            return self.closes[max(before)]
        return self.closes[min(self.closes)] if self.closes else None

    def required(self, day: date) -> float:
        """on(day), exiting with a message when no close is stored at all."""
        rate = self.on(day)
        if rate is None:
            raise SystemExit(MSG_NO_EURUSD.format(symbol=self.symbol, clock=self.clock.isoformat()))
        return rate
