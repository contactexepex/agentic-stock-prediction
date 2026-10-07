"""The stored inputs the engine settles from, as one value (built as of a time by lab/reads.py, or by hand in
tests): raw bars per symbol, split/bonus records, EUR/USD closes, betas, verified news and cost rates."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class MarketData:
    """Everything settlement reads. bars: {symbol: {date: {open, high, low, close}}} raw (ohlc_raw) bars stored
    by `now`; adjustments: [{id, ticker, ex_date, factor}] active by `now` (factor = the price multiplier, 0.5 for
    a 2-for-1 split); eurusd: {date: EUR/USD close}; betas: {ticker: beta_1y as of the prediction};
    news: [{id, ticker, ts, status, sentiment}] (status as of `now`); rates: lab.costs.rates(market)."""
    market: str
    cfg: dict
    now: datetime
    rates: dict
    bars: dict[str, dict[date, dict]] = field(default_factory=dict)
    adjustments: list[dict] = field(default_factory=list)
    eurusd: dict[date, float] = field(default_factory=dict)
    betas: dict[str, float] = field(default_factory=dict)
    news: list[dict] = field(default_factory=list)

    def bar(self, symbol: str, day: date) -> dict | None:
        """The stored raw bar of a symbol on a day, or None."""
        return (self.bars.get(symbol) or {}).get(day)

    def split_factor(self, ticker: str, after: date, until: date) -> tuple[float, list[str]]:
        """(product of the factors, ids) of the ticker's adjustments with after < ex_date <= until."""
        factor, ids = 1.0, []
        for row in sorted(self.adjustments, key=lambda r: (str(r["ex_date"]), r["id"])):
            ex_date = row["ex_date"]
            ex_date = ex_date if isinstance(ex_date, date) else date.fromisoformat(str(ex_date)[:10])
            if row["ticker"] == ticker and after < ex_date <= until:
                factor *= float(row["factor"])
                ids.append(row["id"])
        return factor, ids

    def eurusd_on(self, day: date) -> float | None:
        """The newest stored EUR/USD close dated on or before `day`; else the oldest stored (known by now)."""
        before = [d for d in self.eurusd if d <= day]
        if before:
            return float(self.eurusd[max(before)])
        return float(self.eurusd[min(self.eurusd)]) if self.eurusd else None
