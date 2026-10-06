"""Snapshot near-the-money implied volatility per watchlist ticker from yfinance option chains
into data/<market>/options/YYYY/MM/<today>.jsonl. Only for markets with `options: yfinance`
(the US); other markets are skipped cleanly (no free option chains for India).

Per ticker, the nearest expiries (1 to --max-days calendar days out, at most --expiries of them):
call and put implied vol interpolated to the spot price, their average (`atm_iv`, annualized)
and the at-the-money straddle (mid price, also as % of spot: roughly the implied move to that
expiry). Quotes with no bid or an implausible IV are ignored. Append-only: id
<date>-<ticker>-<expiry> is written once per UTC day. ranges.py blends `atm_iv` into the width
(docs/DESIGN.md section 4). A ticker that ends with no snapshot today (Yahoo returned no expiries,
none in the window, or no usable chain) is listed in `failed` with the reason."""
from __future__ import annotations

import json
import math
from datetime import date

import pandas as pd

from marketbrief.constants.columns import COL_ID, COL_TICKER
from marketbrief.constants.config_keys import CFG_MARKET, CFG_OPTIONS, CFG_TICKERS, META_YAHOO, OPTIONS_YFINANCE
from marketbrief.constants.kinds import KIND_OPTIONS
from marketbrief.constants.options import (COLLECTOR_OPTIONS, DEFAULT_EXPIRIES, DEFAULT_MAX_DAYS, ERROR_TEXT_LIMIT,
                                           MAX_IV, MIN_IV, MIN_QUOTED_STRIKES, MSG_NO_EXPIRIES, MSG_NO_EXPIRY_IN_WINDOW,
                                           MSG_NO_USABLE_CHAIN, MSG_SKIPPED_NO_CHAINS, OPTION_COLUMNS,
                                           SEEN_LOOKBACK_DAYS, SNAPSHOT_DECIMALS, SOURCE_YFINANCE)
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_FAILED, SUMMARY_MARKET, SUMMARY_SKIPPED
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.storage import append_jsonl, day_file, recent_ids


def usable_quotes(chain: pd.DataFrame) -> pd.DataFrame:
    """The quotes with a plausible implied vol, sorted by strike; only those with a bid and an ask when at
    least two have both."""
    if chain is None or chain.empty:
        return pd.DataFrame(columns=OPTION_COLUMNS)
    chain = chain[(chain["impliedVolatility"] > MIN_IV) & (chain["impliedVolatility"] < MAX_IV)].sort_values("strike")
    quoted = chain[(chain["bid"].fillna(0) > 0) & (chain["ask"].fillna(0) > 0)]
    return quoted if len(quoted) >= MIN_QUOTED_STRIKES else chain


def iv_at(chain: pd.DataFrame, spot: float) -> float | None:
    """Implied vol linearly interpolated in strike to the spot price."""
    chain = usable_quotes(chain)
    if chain.empty:
        return None
    below, above = chain[chain["strike"] <= spot].tail(1), chain[chain["strike"] >= spot].head(1)
    if below.empty or above.empty:
        return float((below if not below.empty else above)["impliedVolatility"].iloc[0])
    strike_low, strike_high = float(below["strike"].iloc[0]), float(above["strike"].iloc[0])
    vol_low, vol_high = float(below["impliedVolatility"].iloc[0]), float(above["impliedVolatility"].iloc[0])
    if strike_high == strike_low:
        return vol_low
    return vol_low + (vol_high - vol_low) * (spot - strike_low) / (strike_high - strike_low)


def option_price(row) -> float | None:
    """The mid of bid and ask, else the last price when positive."""
    bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    last = row.get("lastPrice")
    return float(last) if last is not None and last == last and last > 0 else None


def straddle(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> tuple[float | None, float | None]:
    """(strike, call + put price) at the listed strike nearest the spot."""
    if calls is None or puts is None or calls.empty or puts.empty:
        return None, None
    common = sorted(set(calls["strike"]) & set(puts["strike"]), key=lambda strike: abs(strike - spot))
    if not common:
        return None, None
    strike = common[0]
    call_price = option_price(calls[calls["strike"] == strike].iloc[0])
    put_price = option_price(puts[puts["strike"] == strike].iloc[0])
    both = call_price is not None and put_price is not None
    return float(strike), (call_price + put_price if both else None)


def rounded(value, digits: int = SNAPSHOT_DECIMALS) -> float | None:
    """`value` rounded, or None for None and non-finite numbers."""
    return None if value is None or not math.isfinite(value) else round(value, digits)


def option_snapshot(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> dict | None:
    """The implied-vol snapshot of one expiry (spot, strike, call/put/at-the-money IV, straddle), or None."""
    call_iv, put_iv = iv_at(calls, spot), iv_at(puts, spot)
    ivs = [value for value in (call_iv, put_iv) if value is not None]
    if not ivs or not spot or spot <= 0:
        return None
    strike, straddle_price = straddle(calls, puts, spot)
    return {"spot": rounded(spot, 4), "strike": strike, "call_iv": rounded(call_iv), "put_iv": rounded(put_iv),
            "atm_iv": rounded(sum(ivs) / len(ivs)), "straddle": rounded(straddle_price, 4),
            "straddle_pct": rounded(straddle_price / spot) if straddle_price else None}


def no_chain_reason(listed: bool, expiries: list[str], max_days: int) -> str:
    """Why a ticker got no snapshot: Yahoo listed no expiries at all (an empty answer, e.g. a
    blocked or failed request), none falls in the window, or no chain had a usable implied vol."""
    if not listed:
        return MSG_NO_EXPIRIES
    if not expiries:
        return MSG_NO_EXPIRY_IN_WINDOW.format(max_days=max_days)
    return MSG_NO_USABLE_CHAIN


class OptionsCollector:
    """One run: a snapshot per near expiry of every watchlist ticker."""

    def __init__(self, cfg: dict, yf, expiries: int, max_days: int):
        self.cfg, self.yf, self.expiries, self.max_days = cfg, yf, expiries, max_days
        self.market, self.now, self.today = cfg[CFG_MARKET], utc_now(), utc_today()
        self.seen = recent_ids(self.market, KIND_OPTIONS, days=SEEN_LOOKBACK_DAYS)
        self.rows: list[dict] = []
        self.failed: list[dict] = []

    def snapshot_expiry(self, key: str, ticker, expiry: str) -> bool:
        """Snapshot one expiry; True when it is stored (now or earlier today)."""
        option_id = f"{self.today}-{key}-{expiry}"
        if option_id in self.seen:          # already snapshotted today
            return True
        chain = ticker.option_chain(expiry)
        underlying = getattr(chain, "underlying", None) or {}
        spot = underlying.get("regularMarketPrice") or ticker.fast_info["lastPrice"]
        snapshot = option_snapshot(chain.calls, chain.puts, float(spot))
        if snapshot is None:
            return False
        self.rows.append({COL_ID: option_id, COL_TICKER: key, "collected_at": self.now, "expiry": expiry,
                          "days_to_expiry": (date.fromisoformat(expiry) - self.today).days, **snapshot,
                          "source": SOURCE_YFINANCE})
        self.seen.add(option_id)
        return True

    def collect_ticker(self, key: str, meta: dict) -> None:
        """Snapshot the near expiries of one ticker; a ticker without any is a failure."""
        try:
            ticker = self.yf.Ticker(meta[META_YAHOO])
            expiries = [e for e in ticker.options if 1 <= (date.fromisoformat(e) - self.today).days <= self.max_days]
            listed = bool(ticker.options)   # () when Yahoo's answer has no option result
            stored = sum(self.snapshot_expiry(key, ticker, expiry) for expiry in expiries[:self.expiries])
            if not stored:
                self.failed.append({COL_TICKER: key, "error": no_chain_reason(listed, expiries, self.max_days)})
        except Exception as exc:
            self.failed.append({COL_TICKER: key, "error": str(exc)[:ERROR_TEXT_LIMIT]})

    def collect(self) -> int:
        """Run every ticker, store the rows and print the summary; returns the exit code."""
        for key, meta in self.cfg[CFG_TICKERS].items():
            self.collect_ticker(key, meta)
        written = append_jsonl(day_file(self.market, KIND_OPTIONS, self.today), self.rows)
        print(json.dumps({SUMMARY_COLLECTOR: COLLECTOR_OPTIONS, SUMMARY_MARKET: self.market, "written": written,
                          "tickers": len({row[COL_TICKER] for row in self.rows}), SUMMARY_FAILED: self.failed},
                         indent=2))
        return 1 if self.failed and len(self.failed) == len(self.cfg[CFG_TICKERS]) else 0


def main() -> int:
    """Entry point of scripts/collect_options.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--expiries", type=int, default=DEFAULT_EXPIRIES,
                        help=f"nearest expiries per ticker (default {DEFAULT_EXPIRIES})")
    parser.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS,
                        help=f"ignore expiries further out (default {DEFAULT_MAX_DAYS})")
    args = parser.parse_args()
    cfg = require_market(args)
    if cfg.get(CFG_OPTIONS) != OPTIONS_YFINANCE:
        print(json.dumps({SUMMARY_COLLECTOR: COLLECTOR_OPTIONS, SUMMARY_MARKET: cfg[CFG_MARKET],
                          SUMMARY_SKIPPED: MSG_SKIPPED_NO_CHAINS}))
        return 0
    import yfinance as yf

    return OptionsCollector(cfg, yf, args.expiries, args.max_days).collect()
