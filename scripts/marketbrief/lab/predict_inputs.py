"""The pre-open inputs of the rule strategies and baselines, as of the run's clock: the active companies (B1's
watchlist accessor, else the config's tickers), the per-horizon model scores and ranges (B10's
contracts/horizons.py), the latest stored closes, the feature row (quality, days to earnings), the regime and the
company's news as of the score time (the signal model's news window)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from marketbrief.contracts import horizons as horizons_contract
from marketbrief.contracts import watchlist as watchlist_contract
from marketbrief.contracts.watchlist import CURRENCY
from marketbrief.lab import reads
from marketbrief.lab.sizing import trade_amount
from marketbrief.lab.strategies import TickerInputs
from marketbrief.lab.timing import entry_session, exit_session
from marketbrief.portfolio import reads as portfolio_reads
from marketbrief.utils.timefmt import as_utc_timestamp

BARS_BACK_DAYS = 20


def active_tickers(cfg: dict, now: datetime) -> list[str]:
    """B1's active companies; until B1 has built the accessor, cfg active_tickers, else cfg tickers."""
    try:
        return sorted(company["ticker"] for company in watchlist_contract.watchlist(cfg["market"], now, "active"))
    except NotImplementedError:
        return sorted(cfg.get("active_tickers") or cfg["tickers"])


def horizon_rows(market: str, now: datetime) -> tuple[list[dict], list[dict]]:
    """(scores, ranges) of every horizon as of `now`; raises NotImplementedError until B10 has built them."""
    return horizons_contract.scores_asof(market, now), horizons_contract.ranges_asof(market, now)


def feature_rows(con, now: datetime) -> dict[str, dict]:
    """{ticker: newest feature row (quality, days_to_earnings, as_of_date)} computed by `now`."""
    frame = con.execute("SELECT DISTINCT ON (ticker) ticker, as_of_date, quality, days_to_earnings FROM features "
                        "WHERE computed_at <= ? ORDER BY ticker, as_of_date DESC, computed_at DESC", [now]).df()
    return {row["ticker"]: row for row in reads.records(frame)}


def regime_now(con, now: datetime) -> str | None:
    """The newest regime label computed by `now`."""
    rows = con.execute("SELECT regime FROM regime WHERE computed_at <= ? ORDER BY as_of_date DESC, computed_at DESC "
                       "LIMIT 1", [now]).fetchall()
    return rows[0][0] if rows else None


def previous_close(own, adjust, ticker: str) -> float | None:
    """The close before the as-of close, on the as-of close's split basis (momentum compares the two)."""
    if len(own) < 2:
        return None
    prev_day, last_day = own["date"].iloc[-2], own["date"].iloc[-1]
    ratio = portfolio_reads.factor_after(adjust, ticker, prev_day) / portfolio_reads.factor_after(adjust, ticker,
                                                                                                    last_day)
    return float(own["close"].iloc[-2]) * ratio


def same_day(row: dict, ticker: str, as_of: str) -> bool:
    """A score or range row of this ticker and as-of date."""
    return row["ticker"] == ticker and str(row["as_of_date"])[:10] == as_of


def build_inputs(con, cfg: dict, now: datetime, scores: list[dict], ranges: list[dict],
                 news_cfg: dict) -> list[TickerInputs]:
    """One TickerInputs per active company with a stored close."""
    market, tickers = cfg["market"], active_tickers(cfg, now)
    entry = entry_session(cfg, now)
    bars = portfolio_reads.stored_bars(con, cfg, now, tickers, entry - timedelta(days=BARS_BACK_DAYS))
    features, regime = feature_rows(con, now), regime_now(con, now)
    adjust = portfolio_reads.adjustments(con, now)
    out = []
    for ticker in tickers:
        own = bars[bars["ticker"] == ticker].sort_values("date")
        if own.empty:
            continue
        as_of = str(own["date"].iloc[-1])
        my_scores = {int(s["horizon_days"]): s for s in scores if same_day(s, ticker, as_of)}
        my_ranges = {int(r["horizon_days"]): r for r in ranges if same_day(r, ticker, as_of)}
        scored_at = max((as_utc_timestamp(s["computed_at"]) for s in my_scores.values()), default=pd.Timestamp(now))
        since = scored_at - timedelta(hours=news_cfg["lookback_hours"])
        news = [n for n in reads.news_items(con, scored_at.to_pydatetime(), since.to_pydatetime())
                if n["ticker"] == ticker]
        feature = features.get(ticker) or {}
        out.append(TickerInputs(
            market=market, ticker=ticker, as_of_date=as_of, session_date=str(entry),
            exit_dates={k: str(exit_session(cfg, entry, k)) for k in my_ranges}, made_at=now.isoformat(),
            base_close=float(own["close"].iloc[-1]),
            prev_close=previous_close(own, adjust, ticker), regime=regime,
            quality=feature.get("quality"), days_to_earnings=feature.get("days_to_earnings"),
            amount=trade_amount(market, ticker, now, cfg), currency=CURRENCY[market], scores=my_scores,
            ranges=my_ranges, news=news))
    return out
