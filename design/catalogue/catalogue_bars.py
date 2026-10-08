"""Daily bars of the six example companies (EXAMPLES of real stored data): the last 60 sessions to the as-of date, read
from the `ohlc` view (split-adjusted on read) and compared with `ohlc_raw` to set `adjusted`."""
from __future__ import annotations

from marketbrief.core.database import connect

AS_OF = "2026-10-06"
SESSIONS = 60
TICKERS = {"india": ("RELIANCE", "HDFCBANK", "MARUTI"), "us": ("NVDA", "AAPL", "JPM")}
BARS_SQL = """
SELECT * FROM (
  SELECT o.ticker, o.date, o.open, o.high, o.low, o.close, o.volume,
         (o.open, o.high, o.low, o.close, o.volume)
           IS DISTINCT FROM (r.open, r.high, r.low, r.close, r.volume) AS adjusted,
         row_number() OVER (PARTITION BY o.ticker ORDER BY o.date DESC) AS back
  FROM ohlc o JOIN ohlc_raw r USING (ticker, date)
  WHERE o.ticker = ? AND o.date <= ?::DATE)
WHERE back <= ? ORDER BY date"""


def bar_rows() -> list[dict]:
    rows = []
    for market, tickers in TICKERS.items():
        con = connect(market)
        for ticker in tickers:
            for bar in con.execute(BARS_SQL, [ticker, AS_OF, SESSIONS]).df().itertuples():
                rows.append({"market": market, "ticker": ticker, "date": str(bar.date.date()), "open": float(bar.open),
                             "high": float(bar.high), "low": float(bar.low), "close": float(bar.close),
                             "volume": int(bar.volume), "adjusted": bool(bar.adjusted)})
    return rows
