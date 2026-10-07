"""The news coefficient's re-estimation report (scripts/model_news_update.py; prints, never edits config).

Reads the live model_scores rows (their news score and the probability before the news term), joins each
with its realised open-to-close label once resolved, and runs news_score.update_plan: how many scored
stock-days exist, how many are needed for the target standard error, and the posterior of the coefficient.
A human applies a new coefficient to config/model.yaml (and bumps model_version), as with review.py."""
from __future__ import annotations

import json

import pandas as pd

from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.constants.model import HORIZONS, LABEL_OPEN_TO_CLOSE
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.database import connect
from marketbrief.model.labels import label_columns
from marketbrief.model.logistic import logit
from marketbrief.model.news_score import update_plan
from marketbrief.model.panel import build_panel
from marketbrief.model.panel_inputs import read_inputs
from marketbrief.model.settings import cross_groups, load_model_config

SCORES_SQL = """
SELECT as_of_date, ticker, horizon_days, prob_model, news_score FROM model_scores_latest
WHERE label_convention = ? ORDER BY as_of_date, ticker, horizon_days"""


def live_rows(con, panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Resolved live rows of one horizon: offset (model logit before news), score, up."""
    scores = con.execute(SCORES_SQL, [LABEL_OPEN_TO_CLOSE]).df()
    scores = scores[scores["horizon_days"] == horizon]
    if scores.empty:
        return pd.DataFrame(columns=["offset", "score", "up"])
    ret_col, _ = label_columns(LABEL_OPEN_TO_CLOSE, horizon)
    scores["date"] = pd.to_datetime(scores["as_of_date"])
    joined = scores.merge(panel[["date", "ticker", ret_col]], on=["date", "ticker"], how="inner")
    joined = joined[joined[ret_col].notna()]
    return pd.DataFrame({"offset": logit(joined["prob_model"].to_numpy()), "score": joined["news_score"].to_numpy(),
                         "up": (joined[ret_col] > 0).astype(float).to_numpy()})


def main() -> int:
    """Print the re-estimation report per horizon."""
    cfg = require_market(market_arg(__doc__).parse_args())
    settings = load_model_config()
    con = connect(cfg[CFG_MARKET])
    panel = build_panel(cfg, read_inputs(con, cfg[CFG_MARKET]), settings["warmup_bars"],
                        cross_groups(settings, cfg[CFG_MARKET]))
    report = {f"{h}d": update_plan(live_rows(con, panel, h), settings["news"]) for h in HORIZONS}
    print(json.dumps({"step": "model_news_update", "market": cfg[CFG_MARKET], "news_prior": settings["news"],
                      "horizons": report}, indent=2, default=str))
    return 0
