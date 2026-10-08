"""Agreement records (catalogue entity "Agreement", docs/DATA_CATALOGUE.md): per horizon and active company, how many
strategies' predictions qualify as a trade (`buy`) of those that predicted it (`of`), split by family, with the
buyers' average P(up). The predictions are the newest batch made by the cut-off (the newest `session_date` among the
`strategy_predictions` rows with `made_at` at or before it; each id's first stored row). Rank: most buyers first,
then the higher average probability, then the ticker."""

from __future__ import annotations

import statistics
from datetime import datetime

import pandas as pd

from marketbrief.lab.registry import horizons as registry_horizons

FAMILIES = ("rule", "baseline", "ai")
PREDICTIONS_SQL = """
WITH p AS (SELECT DISTINCT ON (id) * FROM strategy_predictions WHERE made_at <= $cutoff::TIMESTAMPTZ
           ORDER BY id, made_at)
SELECT id, strategy_id, family, ticker, as_of_date, session_date, horizon_days, prob_up, qualifies FROM p
WHERE session_date = (SELECT max(session_date) FROM p) ORDER BY ticker, horizon_days, strategy_id"""


def latest_predictions(con, cutoff: datetime) -> list[dict]:
    """The newest batch of strategy predictions made by the cut-off (empty when none)."""
    return con.execute(PREDICTIONS_SQL, {"cutoff": cutoff.isoformat()}).df().to_dict("records")


def day(value) -> str | None:
    return None if value is None or pd.isna(value) else str(pd.Timestamp(value).date())


def counts(predictions: list[dict]) -> dict:
    """buy, of, by_family and avg_prob_up of one company's predictions at one horizon."""
    buys = [p for p in predictions if p["qualifies"] is True]
    probabilities = [p["prob_up"] for p in buys if p["prob_up"] is not None and not pd.isna(p["prob_up"])]
    return {
        "buy": len(buys),
        "of": len(predictions),
        "by_family": {family: {"buy": sum(p["family"] == family for p in buys),
                               "of": sum(p["family"] == family for p in predictions)} for family in FAMILIES},
        "avg_prob_up": round(statistics.mean(probabilities), 4) if probabilities else None,
    }


def agreement(predictions: list[dict], companies: list[dict], market: str) -> dict[str, list[dict]]:
    """horizon ("1".."5") -> the active companies' Agreement records, by rank."""
    as_of = day(predictions[0]["as_of_date"]) if predictions else None
    session = day(predictions[0]["session_date"]) if predictions else None
    out = {}
    for k in registry_horizons():
        rows = []
        for company in companies:
            mine = [p for p in predictions if p["ticker"] == company["ticker"] and p["horizon_days"] == k]
            tally = counts(mine)
            label = f"{company['name']}: {tally['buy']} of {tally['of']} strategies buy at N+{k}"
            rows.append({"market": market, "as_of_date": as_of, "session_date": session, "ticker": company["ticker"],
                         "name": company["name"], "horizon_days": k, **tally, "label": label, "paper": True})
        rows.sort(key=lambda r: (-r["buy"], -(r["avg_prob_up"] or 0), r["ticker"]))
        out[str(k)] = [{**row, "rank": rank} for rank, row in enumerate(rows, 1)]
    return out


def n1_counts(by_horizon: dict[str, list[dict]]) -> dict[str, dict]:
    """ticker -> its N+1 {buy, of} (the Company record's `agreement_n1`)."""
    return {row["ticker"]: {"buy": row["buy"], "of": row["of"]} for row in by_horizon.get("1", [])}
