"""The dashboard's data: one JSON-ready dict per market, built only from stored data as of a cut-off
time (the run's clock, MB_NOW-aware). The as-of date is the newest indicator snapshot stored by the
cut-off; bars stop at it, and every other row (ranges, scores, reasoning, news, statuses, quotes,
reviews, scored outcomes) is one stored by the cut-off."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from marketbrief.constants.dashboard import (
    BAR_CALENDAR_DAYS,
    DEFAULT_SPAN,
    EARNINGS_TYPE,
    MSG_NO_DATA,
    MSG_NOT_AVAILABLE,
    MSG_RESEARCH_ONLY,
    NEWS_CANDIDATES,
    SPANS,
)
from marketbrief.constants.formatting import CURRENCY_SYMBOLS
from marketbrief.core import calendar
from marketbrief.core.market_config import market_names
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.pipeline.score_predictions import is_late
from marketbrief.presentation.dashboard import market, model_info, reads, stock, track
from view_data import NEWS_ID, safe_url


def session_plan(cfg: dict, as_of) -> dict:
    """D (the first session after the as-of date, the entry open) and the exit sessions: the close of D+1
    for the 1-day horizon and of D+4 for the 5-day horizon (model/labels.py)."""
    days = calendar.sessions_ahead(cfg, as_of + timedelta(days=1), 5)
    return {
        "entry": days[0].isoformat(),
        1: days[1].isoformat(),
        5: days[4].isoformat(),
        "sessions": [d.isoformat() for d in days],
    }


def cited_sources(con, cutoff: str, ids: set[str], ticker_of: dict, statuses: EvidenceStatuses) -> dict:
    """id -> headline, link and status (as of the cut-off) for the ids the reasoning cites."""
    if not ids:
        return {}
    rows = reads.news_by_id(con, cutoff)
    rows = rows[rows["id"].isin(ids)] if len(rows) else rows
    return {
        r.id: {
            "title": r.title,
            "url": safe_url(r.url),
            "source": r.source,
            "ts": stock.iso_time(r.ts),
            "status": statuses.of(r.id, ticker_of.get(r.id, ""), cutoff),
        }
        for r in rows.itertuples()
    }


def company(cfg: dict, ticker: str, sector: str, parts: dict) -> dict:
    """Everything the stock page shows for one ticker."""
    feats, statuses, cutoff = parts["features"], parts["statuses"], parts["cutoff"]
    f = feats.loc[ticker].to_dict() if ticker in feats.index else None
    rows = stock.bar_rows(parts["bars"][parts["bars"]["ticker"] == ticker])
    late_of = lambda as_of, made_at: is_late(cfg, as_of, made_at)  # noqa: E731
    ranges = (
        stock.range_rows(parts["ranges"][parts["ranges"]["ticker"] == ticker], late_of) if len(parts["ranges"]) else []
    )
    scores = parts["scores"][parts["scores"]["ticker"] == ticker] if len(parts["scores"]) else parts["scores"]
    news = parts["news"][parts["news"]["ticker"] == ticker] if len(parts["news"]) else parts["news"]
    reason = parts["reasoning"].get(ticker)
    earnings = parts["earnings"].get(ticker)
    preds = parts["predictions"]
    last = stock.last_session(rows)
    return {
        "ticker": ticker,
        "name": cfg["tickers"].get(ticker, {}).get("name", ticker),
        "sector": sector,
        "bars": rows,
        "last": last,
        "ranges": ranges,
        "model": [stock.model_row(s, parts["plan"]) for s in scores.sort_values("horizon_days").itertuples()],
        "reasoning": stock.reasoning_view(reason, parts["cited"], NEWS_ID),
        "calls": stock.call_rows(preds[preds["ticker"] == ticker]) if len(preds) else [],
        "news": stock.news_rows(news, lambda i: statuses.of(i, ticker, cutoff), safe_url),
        "earnings": earnings.isoformat() if earnings else None,
        "indicators": stock.indicator_values(f),
        "cost": model_info.cost_at(cfg["market"], last["close"] if last else None),
    }


def gather_dashboard(cfg: dict, con, cutoff_time) -> dict:
    """The full page data for one market as of `cutoff_time` (an aware datetime)."""
    cutoff = pd.Timestamp(cutoff_time).isoformat()
    as_of = reads.as_of_date(con, cutoff)
    head = {
        "market": cfg["market"],
        "name": cfg["name"],
        "currency": cfg.get("currency", ""),
        "symbol": CURRENCY_SYMBOLS.get(cfg.get("currency", ""), ""),
        "generated_at": cutoff,
        "disclaimer": MSG_RESEARCH_ONLY,
        "not_available": MSG_NOT_AVAILABLE,
        "markets": market_names(),
        "spans": [{"key": k, "label": label, "days": d} for k, label, d in SPANS],
        "default_span": DEFAULT_SPAN,
    }
    review = reads.review(con, cutoff)
    head["skill"] = model_info.skill_status(review)
    head["backtest"] = model_info.backtest_view(review, cfg["market"])
    head["track"] = track.track_record(con, cutoff, reads.replay(con, cutoff))
    if as_of is None:
        return {
            **head,
            "as_of": None,
            "empty": MSG_NO_DATA.format(market=cfg["name"]),
            "companies": [],
            "overview": None,
            "plan": None,
            "models": [],
        }
    feats = reads.features(con, as_of, cutoff)
    bars = reads.bars(con, as_of, as_of - timedelta(days=BAR_CALENDAR_DAYS))
    statuses = EvidenceStatuses(con)
    reasoning = reads.reasoning(con, as_of, cutoff)
    reasoning_rows = {r["ticker"]: r for r in reasoning.to_dict("records")}
    ids, ticker_of = set(), {}
    for t, row in reasoning_rows.items():
        for i in stock.reasoning_ids(row, NEWS_ID):
            ids.add(i)
            ticker_of.setdefault(i, t)
    scores = reads.scores(con, as_of, cutoff)
    plan = session_plan(cfg, as_of)
    parts = {
        "features": feats.set_index("ticker") if len(feats) else feats,
        "bars": bars,
        "ranges": reads.ranges(con, as_of, cutoff),
        "scores": scores,
        "plan": plan,
        "news": reads.news(con, cutoff, NEWS_CANDIDATES),
        "reasoning": reasoning_rows,
        "cited": cited_sources(con, cutoff, ids, ticker_of, statuses),
        "statuses": statuses,
        "cutoff": cutoff,
        "earnings": reads.earnings(con, EARNINGS_TYPE, as_of, cutoff),
        "predictions": reads.predictions(con, as_of, cutoff),
    }
    companies = [
        company(cfg, t, sector, parts)
        for sector, members in (cfg.get("sectors") or {"": list(cfg["tickers"])}).items()
        for t in members
    ]
    model_ids = set(scores["model_id"]) if len(scores) else set()
    return {
        **head,
        "as_of": as_of.isoformat(),
        "plan": {"entry": plan["entry"], "exit_1d": plan[1], "exit_5d": plan[5], "sessions": plan["sessions"]},
        "overview": market.overview(cfg, bars, reads.regime(con, as_of, cutoff), reads.quotes(con, cutoff), feats),
        "models": model_info.versions_used(reads.versions(con, cutoff), model_ids),
        "companies": companies,
    }
