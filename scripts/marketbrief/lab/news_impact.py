"""F3 news-impact study, weekly, as of the review time (only news first seen, enriched and with a status by then,
and only windows whose exit bar was final by then: no look-ahead). Per news category (event_type), verification
status and materiality, per horizon N+k: the mean abnormal move of the stock from the open of D (the first session
whose open is after the item's time) to the close of the k-th session after D,

    abnormal = stock move - beta x benchmark move - (sector index move - benchmark move)   (sector part when the
               company's sector index or ETF has bars, else 0; beta = beta_1y, 1 when missing),

with a 95% interval (mean +- 1.96 x sd / sqrt(n)) and the number of events. One event per company and same-event
cluster (the earliest item). Fewer than NEWS_IMPACT_MIN_EVENTS events: enough false and no mean ("not enough
events yet")."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime

from marketbrief.constants.kinds import KIND_NEWS_IMPACT
from marketbrief.core.market_config import benchmark_key
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab.constants import NEWS_IMPACT_MIN_EVENTS, NEWS_IMPACT_VERSION, PCT_DIGITS
from marketbrief.lab.market_data import MarketData
from marketbrief.lab.reasons import window_move
from marketbrief.lab.settle import is_due
from marketbrief.lab.timing import entry_session, exit_session
from marketbrief.utils.timefmt import as_utc_timestamp

Z95 = 1.959963984540054


def first_per_event(events: list[dict]) -> list[dict]:
    """The earliest item per (ticker, cluster or item id)."""
    chosen: dict[tuple, dict] = {}
    for event in sorted(events, key=lambda e: (str(e["ts"]), e["id"])):
        chosen.setdefault((event["ticker"], event.get("cluster_id") or event["id"]), event)
    return list(chosen.values())


def event_moves(data: MarketData, event: dict, horizon: int) -> dict | None:
    """{abnormal, benchmark, sector} in % of one event at one horizon, or None when not measurable yet."""
    entry = entry_session(data.cfg, as_utc_timestamp(event["ts"]).to_pydatetime())
    exit_ = exit_session(data.cfg, entry, horizon)
    if not is_due(data.cfg, exit_, data.now):
        return None
    stock = window_move(data, event["ticker"], entry, exit_)
    bench_key = benchmark_key(data.cfg)
    bench = window_move(data, bench_key, entry, exit_) if bench_key else None
    if stock is None or bench is None:
        return None
    index = (data.cfg["tickers"].get(event["ticker"]) or {}).get("sector_etf")
    sector = window_move(data, index, entry, exit_) if index else None
    beta = data.betas.get(event["ticker"])
    sector_part = (sector - bench) if sector is not None else 0.0
    abnormal = stock - (1.0 if beta is None else float(beta)) * bench - sector_part
    return {"abnormal": abnormal, "benchmark": bench, "sector": sector}


def summary(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """(mean, low, high) of the 95% interval; interval None below 2 values."""
    if not values:
        return None, None, None
    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean, None, None
    half = Z95 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - half, mean + half


def impact_rows(data: MarketData, events: list[dict], horizons: tuple[int, ...], iso_week: str,
                computed_at: datetime) -> list[dict]:
    """The news_impact rows of one market and week. events: [{id, ticker, ts, event_type, status, materiality,
    cluster_id}] as known at data.now."""
    groups: dict[tuple, list[tuple[dict, dict]]] = defaultdict(list)
    for event in first_per_event(events):
        for horizon in horizons:
            moves = event_moves(data, event, horizon)
            if moves is not None:
                groups[(event["event_type"], event["status"], event["materiality"], horizon)].append((event, moves))
    rows = []
    for (event_type, status, materiality, horizon), found in sorted(groups.items(), key=lambda kv: str(kv[0])):
        enough = len(found) >= NEWS_IMPACT_MIN_EVENTS
        mean, low, high = summary([m["abnormal"] for _, m in found])
        sectors = [m["sector"] for _, m in found if m["sector"] is not None]
        row = dict.fromkeys(SCHEMAS[KIND_NEWS_IMPACT][1])
        row.update(id=f"ni-{data.market}-{iso_week}-{event_type}-{status}-{materiality}-{horizon}", market=data.market,
                   iso_week=iso_week, as_of=as_utc_timestamp(data.now).isoformat(), event_type=event_type,
                   status=status, materiality=materiality, horizon_days=horizon, n_events=len(found), enough=enough,
                   news_ids=sorted(e["id"] for e, _ in found), method_version=NEWS_IMPACT_VERSION,
                   computed_at=as_utc_timestamp(computed_at).isoformat())
        if enough:
            row.update(mean_abnormal_pct=round(mean, PCT_DIGITS), ci_low_pct=round(low, PCT_DIGITS),
                       ci_high_pct=round(high, PCT_DIGITS),
                       mean_benchmark_pct=round(statistics.fmean(m["benchmark"] for _, m in found), PCT_DIGITS),
                       mean_sector_pct=round(statistics.fmean(sectors), PCT_DIGITS) if sectors else None)
        rows.append(row)
    return rows
