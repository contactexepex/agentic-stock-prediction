"""As-of reads of the strategy lab: every query keeps only rows stored by `now` (MB_NOW-aware through the clock),
so a run never sees data written after it. Bars and split records reuse the paper portfolio's readers
(portfolio/reads.py: latest collection by `now` wins, sessions only)."""
from __future__ import annotations

import json
import math
from datetime import date, datetime

import pandas as pd

from marketbrief.constants.kinds import KIND_HEAD_TO_HEAD_PICKS, KIND_PAPER_TRADES_SETTLED, KIND_STRATEGY_PREDICTIONS
from marketbrief.core.market_config import benchmark_key
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.market_data import MarketData
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.portfolio import reads as portfolio_reads

JSON_COLUMNS = ("cost_lines", "reason_detail", "ranking", "candidates")
NEWS_SQL = """
WITH n AS (SELECT id, unnest(primary_tickers) AS ticker, coalesce(published_at, first_seen_at) AS ts, first_seen_at
           FROM news WHERE first_seen_at <= ?::TIMESTAMPTZ),
e AS (SELECT DISTINCT ON (id) id, sentiment, relevance, materiality, event_type FROM news_enriched
      WHERE analyzed_at <= ?::TIMESTAMPTZ ORDER BY id, analyzed_at DESC)
SELECT n.id, n.ticker, n.ts, e.sentiment, e.relevance, e.materiality, e.event_type
FROM n JOIN e USING (id) WHERE n.ts >= ?::TIMESTAMPTZ ORDER BY n.ts, n.id, n.ticker"""
CLUSTER_SQL = """SELECT news_id, ticker, cluster_id FROM news_status_ids_asof(?::TIMESTAMPTZ)"""


def clean(value):
    """A DuckDB/pandas value as plain Python (NaN/NaT -> None, timestamps -> ISO, JSON text -> object)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        return value.tolist()
    return value


def records(frame: pd.DataFrame, kind: str | None = None) -> list[dict]:
    """Rows as dicts of plain values, JSON columns parsed, dates as ISO text (a kind's DATE columns as
    YYYY-MM-DD)."""
    dates = {col for col, kind_type in SCHEMAS[kind][1].items() if kind_type == "DATE"} if kind else set()
    out = []
    for row in frame.to_dict("records"):
        row = {key: clean(value) for key, value in row.items()}
        for key in dates:
            if row.get(key) is not None:
                row[key] = str(row[key])[:10]
        for key in JSON_COLUMNS:
            if isinstance(row.get(key), str):
                row[key] = json.loads(row[key])
        for key, value in row.items():
            if isinstance(value, date) and not isinstance(value, datetime):
                row[key] = value.isoformat()
        out.append(row)
    return out


def stored(con, kind: str, time_column: str, now: datetime) -> list[dict]:
    """Every row of a lab kind stored by `now` (time_column <= now), in time then id order."""
    frame = con.execute(f"SELECT * FROM {kind} WHERE {time_column} <= ? ORDER BY {time_column}, id", [now]).df()
    return records(frame, kind)


def predictions(con, now: datetime) -> list[dict]:
    """strategy_predictions made by `now`, the first row of each id (an id is written once)."""
    seen, out = set(), []
    for row in stored(con, KIND_STRATEGY_PREDICTIONS, "made_at", now):
        if row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    return out


def picks(con, now: datetime) -> list[dict]:
    """head_to_head_picks made by `now` (first row of each id)."""
    seen, out = set(), []
    for row in stored(con, KIND_HEAD_TO_HEAD_PICKS, "made_at", now):
        if row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    return out


def settlements(con, now: datetime) -> list[dict]:
    """paper_trades_settled rows settled by `now`."""
    return stored(con, KIND_PAPER_TRADES_SETTLED, "settled_at", now)


def bars_by_symbol(con, cfg: dict, now: datetime, symbols: list[str], start: date | None) -> dict:
    """{symbol: {date: {open, high, low, close}}} of the raw bars stored by `now`."""
    frame = portfolio_reads.stored_bars(con, cfg, now, symbols, start)
    out: dict[str, dict] = {}
    for row in frame.to_dict("records"):
        out.setdefault(row["ticker"], {})[row["date"]] = {k: clean(row[k]) for k in ("open", "high", "low", "close")}
    return out


def betas_asof(con, now: datetime) -> dict[tuple[str, str], float]:
    """{(ticker, as_of_date): beta_1y} of the newest feature row per ticker and day computed by `now`."""
    frame = con.execute("SELECT DISTINCT ON (ticker, as_of_date) ticker, as_of_date, beta_1y FROM features "
                        "WHERE computed_at <= ? ORDER BY ticker, as_of_date, computed_at DESC", [now]).df()
    return {(row["ticker"], str(pd.Timestamp(row["as_of_date"]).date())): float(row["beta_1y"])
            for row in frame.to_dict("records") if clean(row["beta_1y"]) is not None}


def news_items(con, now: datetime, since: datetime) -> list[dict]:
    """[{id, ticker, ts, sentiment, relevance, materiality, event_type, status, cluster_id}]: enriched news on its
    primary tickers, first seen and enriched by `now`, timed from `since`; status as of `now`."""
    frame = con.execute(NEWS_SQL, [now.isoformat(), now.isoformat(), since.isoformat()]).df()
    statuses = EvidenceStatuses(con)
    clusters = {(r[0], r[1]): r[2] for r in con.execute(CLUSTER_SQL, [now.isoformat()]).fetchall()}
    out = records(frame)
    for item in out:
        item["status"] = statuses.of(item["id"], item["ticker"], now)
        item["cluster_id"] = clusters.get((item["id"], item["ticker"]))
    return out


def market_data(con, cfg: dict, now: datetime, tickers: list[str], start: date | None) -> MarketData:
    """The MarketData of a market as of `now` for these tickers (plus benchmark, sector indices, EUR/USD)."""
    market = cfg["market"]
    extra = [benchmark_key(cfg)] + [meta.get("sector_etf") for meta in cfg["tickers"].values()]
    peers = sorted(cfg["tickers"])
    rate = lab_costs.rates(market)
    fx_key = rate.get("eurusd_symbol")
    symbols = sorted({s for s in [*tickers, *peers, *extra, fx_key] if s})
    bars = bars_by_symbol(con, cfg, now, symbols, start)
    eurusd = {day: bar["close"] for day, bar in bars.pop(fx_key, {}).items() if bar["close"]} if fx_key else {}
    adjust = portfolio_reads.adjustments(con, now)
    since = pd.Timestamp(start or date(1900, 1, 1)).tz_localize("UTC").to_pydatetime()
    return MarketData(market=market, cfg=cfg, now=now, rates=rate, bars=bars, adjustments=records(adjust),
                      eurusd=eurusd, news=news_items(con, now, since))
