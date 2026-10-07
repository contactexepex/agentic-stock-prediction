"""The lab's derived outputs from stored data as of a time (served later by B4's read models): the scoreboard with
the paired comparisons and the heatmap data (F7, F2.8), the weekly news-impact rows (F3), the back-test (F2.3) and
the pick study. Nothing here writes to data/ except news_impact (an append-only kind)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from marketbrief.constants.kinds import KIND_NEWS_IMPACT
from marketbrief.lab import backtest, compare, heatmaps, news_impact, reads, registry, scoreboard
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.run import append_new
from marketbrief.model.history_cache import load_cache, merged_bars
from marketbrief.portfolio import reads as portfolio_reads

NEWS_IMPACT_LOOKBACK_DAYS = 400
MSG_BACKTEST_NO_EURUSD = ("no stored EURUSD bars to convert the BUX order fee; collect EURUSD=X first or pass "
                          "--eurusd RATE (an assumption, labelled in the output)")


def lab_summary(con, now: datetime) -> dict:
    """{scoreboard, comparisons, heatmaps} of the forward settled trades stored by `now`."""
    settled = reads.settlements(con, now)
    return {"as_of": now.isoformat(), "basis": "forward",
            "scoreboard": scoreboard.scoreboard(settled, "forward", now.isoformat()),
            "comparisons": compare.comparisons(settled, registry.strategies()),
            "heatmaps": heatmaps.heatmap_data(settled, "forward")}


def iso_week_of(now: datetime) -> str:
    """YYYY-Www of the run's date."""
    year, week, _ = now.date().isocalendar()
    return f"{year}-W{week:02d}"


def write_news_impact(con, cfg: dict, now: datetime) -> dict:
    """Compute and append the week's news_impact rows (ids of the week already stored are skipped)."""
    since = now - timedelta(days=NEWS_IMPACT_LOOKBACK_DAYS)
    events = [e for e in reads.news_items(con, now, since) if e["ticker"] in cfg["tickers"]
              and e.get("event_type") and e.get("materiality")]
    data = reads.market_data(con, cfg, now, sorted({e["ticker"] for e in events}), since.date())
    betas = reads.betas_asof(con, now)
    newest = {}
    for (ticker, day), beta in sorted(betas.items()):
        newest[ticker] = beta
    data.betas = newest
    rows = news_impact.impact_rows(data, events, registry.horizons(), iso_week_of(now), now)
    known = {r["id"] for r in reads.stored(con, KIND_NEWS_IMPACT, "computed_at", now)}
    return {"rows": len(rows), "written": append_new(cfg["market"], KIND_NEWS_IMPACT, rows, "computed_at", known),
            "enough": sum(bool(r["enough"]) for r in rows), "events": len(news_impact.first_per_event(events))}


def adjusted_bars(con, cfg: dict, now: datetime, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """{symbol: daily bars indexed by date} as stored by `now` (portfolio/reads.stored_bars: latest collection by
    `now`, sessions only), put on the newest split basis of the adjustments detected by `now`."""
    frame = portfolio_reads.stored_bars(con, cfg, now, sorted(set(symbols)))
    adjust = portfolio_reads.adjustments(con, now)
    out = {}
    for key, group in frame.groupby("ticker"):
        factors = [portfolio_reads.factor_after(adjust, key, day) for day in group["date"]]
        bars = group[["open", "high", "low", "close"]].astype(float).mul(factors, axis=0)
        out[key] = bars.set_index(pd.DatetimeIndex(pd.to_datetime(group["date"])))
    return out


def run_backtest(con, cfg: dict, now: datetime, history: bool, assumed_eurusd: float | None = None) -> dict:
    """F2.3 back-test rows of the no-news strategies on stored bars (plus the history cache with `history`). US:
    the BUX order fee is converted at the stored (or cached) EURUSD closes; without any, only at an explicitly
    given `assumed_eurusd` (labelled in the result), else the back-test refuses."""
    rate = lab_costs.rates(cfg["market"])
    fx_key = rate.get("eurusd_symbol")
    bars = adjusted_bars(con, cfg, now, [*cfg["tickers"], *([fx_key] if fx_key else [])])
    splice = None
    if history:
        cached, _ = load_cache(cfg["market"])
        keep = set(cfg["tickers"]) | {fx_key}
        bars, splice = merged_bars(bars, {k: v for k, v in cached.items() if k in keep})
    eurusd = bars.pop(fx_key)["close"] if fx_key and fx_key in bars else None
    fx_source = "stored EURUSD closes" if eurusd is not None else None
    if cfg["market"] == "us" and eurusd is None:
        if assumed_eurusd is None:
            return {"ok": False, "message": MSG_BACKTEST_NO_EURUSD}
        eurusd = pd.Series([assumed_eurusd], index=pd.DatetimeIndex(["1900-01-01"]))
        fx_source = f"ASSUMED constant {assumed_eurusd} (no stored EURUSD bars)"
    stocks = {k: v for k, v in bars.items() if k in cfg["tickers"] and v is not None}
    rows = backtest.run_backtest(cfg["market"], stocks, registry.rule_and_baselines(), registry.horizons(),
                                 {"rate": rate, "eurusd": eurusd, "probs": None})
    return {"market": cfg["market"], "basis": "backtest", "history": history, "splice": splice, "eurusd": fx_source,
            "note": "model-only needs B10's per-horizon walk-forward probabilities; not run",
            "first_date": min((str(v.index.min().date()) for v in stocks.values()), default=None),
            "last_date": max((str(v.index.max().date()) for v in stocks.values()), default=None), "rows": rows}


def study_inputs(con, cfg: dict, now: datetime) -> dict[str, pd.DataFrame]:
    """Adjusted bars of the watchlist stored by `now`, for the pick study."""
    return adjusted_bars(con, cfg, now, list(cfg["tickers"]))

