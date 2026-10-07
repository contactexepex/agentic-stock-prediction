"""The news term of the signal model (live only) and its planned re-estimation (docs/DESIGN.md section 15).

There is no historical news archive, so the news weights cannot be trained yet. They are fixed,
documented priors (config/model.yaml `news`):
    score(ticker) = clip(sum over its verified news items of sentiment x relevance x materiality weight
                         x verification weight x event-type weight, -score_cap, score_cap)
    news term (logit) = coefficient x score
Items: news whose primary ticker is the ticker, published in the `lookback_hours` before the scoring
time and enriched (news_enriched) by then; verification weights by each item's status as of the scoring
time (confirmed_primary 1.0, corroborated 0.7, single_source 0.3, rumour, promotional, unverified and
contradicted 0). The coefficient is small (0.10 logit per unit: at most +-0.2 logit, about +-5 points at
p = 0.5).

Re-estimation (posterior): once live scores have resolved labels, the coefficient is updated by a
Bayesian logistic fit with the model's own logit as a fixed offset, prior N(coefficient, prior_sd^2):
MAP by Newton's method, standard error from the curvature. samples_needed() says how many scored
stock-days give a standard error of at most target_se. A human applies a new value (as review.py's
proposals)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from marketbrief.constants.model import TEXT_NEWS
from marketbrief.model.logistic import sigmoid
from marketbrief.pipeline.evidence_status import EvidenceStatuses

ITEMS_SQL = """
WITH n AS (SELECT id, unnest(primary_tickers) AS ticker, coalesce(published_at, first_seen_at) AS ts FROM news),
e AS (SELECT DISTINCT ON (id) id, sentiment, relevance, materiality, event_type FROM news_enriched
      WHERE analyzed_at <= ?::TIMESTAMPTZ ORDER BY id, analyzed_at DESC)
SELECT n.ticker, n.id, n.ts, e.sentiment, e.relevance, e.materiality, e.event_type
FROM n JOIN e USING (id)
WHERE n.ts <= ?::TIMESTAMPTZ AND n.ts > ?::TIMESTAMPTZ
ORDER BY n.ticker, n.ts, n.id"""
ASSUMED_MEAN_SQUARED_SCORE = 0.1   # E[score^2] before live data: most stock-days carry no verified news
NEWTON_STEPS = 50


def item_weight(item, news_cfg: dict, status: str) -> float:
    """sentiment x relevance x materiality weight x verification weight x event-type weight of one item."""
    sentiment = float(item.sentiment) if pd.notna(item.sentiment) else 0.0
    relevance = float(item.relevance) if pd.notna(item.relevance) else 0.0
    materiality = news_cfg["materiality_weights"].get(item.materiality, 0.0)
    verification = news_cfg["status_weights"].get(status, 0.0)
    event_type = (news_cfg.get("event_type_weights") or {}).get(item.event_type, 1.0)
    return sentiment * relevance * materiality * verification * event_type


def news_terms(con, tickers: list[str], now: pd.Timestamp, news_cfg: dict) -> dict[str, dict]:
    """ticker -> {score, items, by_event_type, logit, ids, text} as of `now` (only what was public and
    enriched by then; statuses as of then)."""
    start = now - timedelta(hours=news_cfg["lookback_hours"])
    items = con.execute(ITEMS_SQL, [now.isoformat(), now.isoformat(), start.isoformat()]).df()
    statuses = EvidenceStatuses(con)
    out = {}
    for ticker in tickers:
        own = items[items["ticker"] == ticker] if len(items) else items
        by_type: dict[str, float] = {}
        ids = []
        for item in own.itertuples():
            weight = item_weight(item, news_cfg, statuses.of(item.id, ticker, now))
            if weight:
                by_type[str(item.event_type)] = by_type.get(str(item.event_type), 0.0) + weight
                ids.append(item.id)
        cap = news_cfg["score_cap"]
        score = float(np.clip(sum(by_type.values()), -cap, cap))
        out[ticker] = {"score": round(score, 4), "items": len(ids), "ids": ids,
                       "by_event_type": {k: round(v, 4) for k, v in sorted(by_type.items())},
                       "logit": news_cfg["coefficient"] * score,
                       "text": TEXT_NEWS.format(score=score, n=len(ids))}
    return out


def posterior(offsets, scores, outcomes, prior_mean: float, prior_sd: float) -> dict:
    """MAP and standard error of the news coefficient: y ~ Bernoulli(sigmoid(offset + beta * score)),
    beta ~ N(prior_mean, prior_sd^2)."""
    offsets, scores, outcomes = (np.asarray(v, dtype=float) for v in (offsets, scores, outcomes))
    beta = prior_mean
    precision = 1 / prior_sd ** 2
    curvature = precision
    for _ in range(NEWTON_STEPS):
        p = sigmoid(offsets + beta * scores)
        gradient = float(scores @ (outcomes - p)) - precision * (beta - prior_mean)
        curvature = float((p * (1 - p)) @ scores ** 2) + precision
        step = gradient / curvature
        beta += step
        if abs(step) < 1e-12:
            break
    return {"n": int(len(outcomes)), "coefficient": beta, "se": float(curvature ** -0.5),
            "prior_mean": prior_mean, "prior_sd": prior_sd}


def samples_needed(target_se: float, prior_sd: float, mean_squared_score: float, p: float = 0.5) -> int:
    """Scored stock-days for a posterior standard error <= target_se: the curvature grows by about
    p (1 - p) E[score^2] per row, so n = (1/target_se^2 - 1/prior_sd^2) / (p (1 - p) E[score^2])."""
    gap = 1 / target_se ** 2 - 1 / prior_sd ** 2
    if gap <= 0:
        return 0
    return int(np.ceil(gap / (p * (1 - p) * max(mean_squared_score, 1e-9))))


def update_plan(rows: pd.DataFrame, news_cfg: dict) -> dict:
    """The re-estimation report from live rows (offset = model logit without news, score, up)."""
    mean_sq = float((rows["score"] ** 2).mean()) if len(rows) else None
    need = samples_needed(news_cfg["target_se"], news_cfg["prior_sd"],
                          mean_sq if mean_sq else ASSUMED_MEAN_SQUARED_SCORE)
    result = {"rows": int(len(rows)), "mean_squared_score": mean_sq,
              "assumed_mean_squared_score": None if mean_sq else ASSUMED_MEAN_SQUARED_SCORE,
              "rows_needed": need, "ready": bool(len(rows) >= need and mean_sq)}
    if len(rows):
        result["posterior"] = posterior(rows["offset"], rows["score"], rows["up"], news_cfg["coefficient"],
                                        news_cfg["prior_sd"])
    return result
