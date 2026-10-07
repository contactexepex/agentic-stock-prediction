"""Walk-forward backtest of the signal model, out-of-sample only (scripts/model_backtest.py).

For each market, horizon (1, 5) and label convention (open_to_close primary, close_to_close secondary):
walk_forward.py's monthly expanding-window fits, scored only on as-of dates after each fit's cutoff, with
labels the fit never saw. Reported: probability scores and reliability (metrics.py), hit rates and
coverage at the thresholds of config/model.yaml, the paper strategy after costs vs the baselines
(paper.py, open_to_close only: that is the trade), the coefficient table and group importance of the
latest fit, the features left out, and the gradient-boosted comparison (gbm_compare.py). Nothing here is
tuned: every setting comes from config/model.yaml as written before the run. Writes model-backtest-
<market|all>-<last date>.json and .html into --out (a scratch folder; never data/ or reports/)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from marketbrief.constants.model import (HORIZONS, LABEL_CONVENTIONS, LABEL_DESCRIPTIONS, LABEL_OPEN_TO_CLOSE,
                                         MSG_VERDICT_NO_POSITIONS, MSG_VERDICT_SCORES, MSG_VERDICT_VS,
                                         MIN_VERDICT_DATES, MSG_VERDICT_TOO_FEW, VERDICT_BEATS, VERDICT_SAME,
                                         VERDICT_WORSE)
from marketbrief.core.cli import market_arg
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.model.backtest_html import render_html
from marketbrief.model.explain import coefficient_table, group_importance
from marketbrief.model.gbm_compare import gbm_walk_forward
from marketbrief.model.labels import end_offset
from marketbrief.model.metrics import probability_scores, threshold_hits
from marketbrief.model.panel import build_panel
from marketbrief.model.panel_inputs import read_inputs
from marketbrief.model.paper import nan_free, paper_results
from marketbrief.model.settings import load_costs, load_model_config, round_trip_cost
from marketbrief.model.walk_forward import walk_forward

MARKETS = ("india", "us")


def with_trade_columns(oos: pd.DataFrame, panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Out-of-sample rows plus the entry open, 5-day return, RSI and the benchmark's return (paper.py)."""
    columns = {f"entry_open_{horizon}d": "entry_open", "ret_5d": "ret_5d", "rsi_14": "rsi_14",
               f"bench_ret_{LABEL_OPEN_TO_CLOSE}_{horizon}d": "bench_ret"}
    extra = panel[["date", "ticker", *columns]].rename(columns=columns)
    return oos.merge(extra, on=["date", "ticker"], how="left")


def model_summary(fits: list) -> dict:
    """The latest fit's formula summary and how the fits went over time."""
    last = fits[-1]
    return {"fits": len(fits), "first_cutoff": str(fits[0].cutoff.date()), "last_cutoff": str(last.cutoff.date()),
            "last_train_rows": last.train_rows, "last_base_rate": round(last.base_rate, 4),
            "last_intercept": round(last.model.intercept, 4),
            "last_platt": None if last.platt is None else [round(x, 4) for x in last.platt],
            "coefficients": coefficient_table(last.model), "group_importance": group_importance(last.model),
            "excluded": last.model.excluded}


def evaluate(panel: pd.DataFrame, spec: tuple[str, str, int], settings: dict, costs: dict) -> dict:
    """Every result of one market x convention x horizon."""
    market, convention, horizon = spec
    oos, fits = walk_forward(panel, spec, settings)
    if not fits:
        return {"skipped": "no fit: too little history"}
    done = with_trade_columns(oos[oos["up"].notna()], panel, horizon)
    block = end_offset(convention, horizon)
    out = {"label": LABEL_DESCRIPTIONS[convention], **probability_scores(done, settings, block)}
    cost = round_trip_cost(market, costs, done["entry_open"].fillna(100.0).to_numpy())
    out["thresholds"] = {f"{t:.2f}": threshold_hits(done, t, cost) for t in settings["backtest"]["thresholds"]}
    out["cost_aware_up_share"] = round(float((done["ret"] > cost).mean()), 4)
    if convention == LABEL_OPEN_TO_CLOSE:
        out["paper"] = paper_results(done, market, costs, settings, block)
    out["model"] = model_summary(fits)
    out["gbm_comparison"] = gbm_walk_forward(panel, spec, settings)
    return out


def verdicts(results: dict) -> list[str]:
    """One plain line per market x horizon: Brier vs the base rate, and the paper long vs each baseline."""
    lines = []
    for market, by_spec in results.items():
        for key, res in sorted(by_spec.items()):
            if "brier" not in res:
                continue
            lines.append(MSG_VERDICT_SCORES.format(market=market, key=key, brier=res["brier"],
                                                   base=res["brier_base_rate"], skill=res["brier_skill"],
                                                   auc=res["auc"], auc95=res["auc95"]))
            for threshold, paper in (res.get("paper") or {}).get("thresholds", {}).items():
                lines += threshold_verdicts(threshold, paper)
    return lines


def threshold_verdicts(threshold: str, paper: dict) -> list[str]:
    """The model long at one threshold vs each baseline: beats (interval above 0), worse (below 0) or neither."""
    if not paper["long"]["positions"]:
        return [MSG_VERDICT_NO_POSITIONS.format(threshold=threshold)]
    lines = []
    for name, diff in paper["vs"].items():
        if diff["dates"] < MIN_VERDICT_DATES:
            lines.append(MSG_VERDICT_TOO_FEW.format(threshold=threshold, name=name, dates=diff["dates"],
                                                    need=MIN_VERDICT_DATES))
            continue
        low, high = diff["ci95_pct"]
        word = (VERDICT_BEATS if low is not None and low > 0 else
                VERDICT_WORSE if high is not None and high < 0 else VERDICT_SAME)
        lines.append(MSG_VERDICT_VS.format(threshold=threshold, positions=paper["long"]["positions"], word=word,
                                           name=name, mean=diff["mean_pct"], low=low, high=high))
    return lines


def run(markets: tuple[str, ...]) -> dict:
    """The backtest of the given markets."""
    settings = load_model_config()
    out = {"computed_at": utc_now(), "settings": settings, "results": {}, "data": {}}
    for market in markets:
        cfg = load_market(market)
        inputs = read_inputs(connect(market), market)
        panel = build_panel(cfg, inputs, settings["warmup_bars"])
        first_bar = min(frame.index[0] for frame in inputs["bars"].values())
        out["data"][market] = {"panel_rows": len(panel), "first_bar": str(first_bar.date()),
                               "first_panel_date": str(panel["date"].min().date()),
                               "last_panel_date": str(panel["date"].max().date()),
                               "tickers": int(panel["ticker"].nunique()),
                               "round_trip_cost_pct_at_100": round(round_trip_cost(market, load_costs(market)) * 100,
                                                                   4)}
        out["results"][market] = {f"{h}d {c}": evaluate(panel, (market, c, h), settings, load_costs(market))
                                  for h in HORIZONS for c in LABEL_CONVENTIONS}
    out["verdicts"] = verdicts(out["results"])
    return nan_free(out)


def main() -> int:
    """Entry point of scripts/model_backtest.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--out", type=Path, required=True, help="folder for the JSON and HTML (a scratch folder)")
    args = parser.parse_args()
    markets = (args.market,) if args.market else MARKETS
    result = run(markets)
    args.out.mkdir(parents=True, exist_ok=True)
    last = max(d["last_panel_date"] for d in result["data"].values())
    stem = args.out / f"model-backtest-{args.market or 'all'}-{last}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str))
    stem.with_suffix(".html").write_text(render_html(result))
    print(json.dumps({"json": str(stem.with_suffix(".json")), "html": str(stem.with_suffix(".html")),
                      "verdicts": result["verdicts"]}, indent=1))
    return 0
