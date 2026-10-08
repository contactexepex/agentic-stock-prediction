"""The context pack's "Signal model" section: each ticker's model probability and its top drivers."""
from __future__ import annotations

import json

from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.constants.model import LABEL_DESCRIPTIONS, LABEL_OPEN_TO_CLOSE, MAX_AGENT_ADJUSTMENT

TITLE = "Signal model: P(up) per ticker (logistic, open-to-close; anchor for the forecaster's confidence)"
# N+k rows only (decision 37): a legacy_5d_d4 score (old D+4 exit) would read like an N+5 one (issue #95).
SQL = f"""
WITH scores AS (SELECT * FROM model_scores_latest WHERE horizon_label = '{LABEL_N_PLUS_K}')
SELECT id, ticker, horizon_days, prob_up, prob_model, calibrated, base_rate, news_score, trained_until, contributions
FROM scores WHERE as_of_date = (SELECT max(as_of_date) FROM scores)
ORDER BY ticker, horizon_days, id"""
NOTE = ("P(up) = probability that {label} returns more than 0; drivers in probability points vs the base rate "
        "(docs/DESIGN.md section 15). The forecaster's final probability = model P(up) + an adjustment of at most "
        "+-{cap:.2f} with a written reason; the direction is the side of 0.5 it is on.")


def drivers(items: list[dict]) -> str:
    """The drivers' plain-language lines joined, '–' when none."""
    return "; ".join(d["text"] for d in items) or "–"


def context_section(con) -> tuple[str, str]:
    """(title, Markdown body) of the latest as-of date's scores."""
    rows = con.execute(SQL).fetchall()
    note = NOTE.format(label=LABEL_DESCRIPTIONS[LABEL_OPEN_TO_CLOSE], cap=MAX_AGENT_ADJUSTMENT)
    if not rows:
        return TITLE, f"{note}\n\n_no model scores (run model_scores.py)_\n"
    lines = ["| id | P(up) | P(up) before news | calibrated | base rate | news score | model of | up drivers "
             "| down drivers |", "|---|---|---|---|---|---|---|---|---|"]
    for rid, _, _, prob, prob_model, calibrated, base, news, trained, contributions in rows:
        detail = contributions if isinstance(contributions, dict) else json.loads(contributions)
        lines.append(f"| {rid} | {prob:.4f} | {prob_model:.4f} | {'yes' if calibrated else 'no'} | {base:.4f} "
                     f"| {news:+.2f} | {trained} | {drivers(detail['up'])} | {drivers(detail['down'])} |")
    return TITLE, note + "\n\n" + "\n".join(lines) + "\n"
