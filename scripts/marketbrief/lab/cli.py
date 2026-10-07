"""scripts/lab.py: the strategy lab's command line (research only; a paper trade is a record, never an order).

  lab.py --market us predict          pre-open: rule strategies and baselines (needs B10's per-horizon scores)
  lab.py --market us pick [--session YYYY-MM-DD]   pre-open, after every family predicted: head-to-head picks
  lab.py --market us settle           post-close: settle every due trade of both views (re-settle on a split fix)
  lab.py --market us news-impact      weekly: the news-impact rows of the ISO week (F3)
  lab.py --market us summary [--out FILE]          scoreboard, paired comparisons and heatmap data (forward)
  lab.py --market us backtest [--history] [--eurusd R] [--out FILE]   F2.3 back-test of the no-news strategies
  lab.py pick-study [--out FILE]      where "best expected gain" picks under the draft and the corrected formula

stdout is one JSON object (with --out: the full result goes to FILE and stdout gets a short summary). Every read is
as of the run's clock (MB_NOW-aware)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from marketbrief.contracts.watchlist import DEFAULT_AMOUNT
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import clock
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.lab import costs as lab_costs
from marketbrief.lab import pick_study, predict_inputs, registry, reports, run, settle_run
from marketbrief.lab.constants import MSG_NO_HORIZON_SCORES
from marketbrief.lab.strategies import company_rows
from marketbrief.model.settings import load_model_config

STUDY = {"days": 120, "window": 250, "threshold": 0.55, "eurusd_fallback": 1.17}
EXAMPLES = "design/catalogue/prediction.json"


def parser():
    """The argument parser with every subcommand."""
    root = market_arg(__doc__.splitlines()[0])
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("predict")
    pick = sub.add_parser("pick")
    pick.add_argument("--session", type=date.fromisoformat, help="D (default: the next session after the clock)")
    sub.add_parser("settle")
    sub.add_parser("news-impact")
    for name in ("summary", "backtest", "pick-study"):
        command = sub.add_parser(name)
        command.add_argument("--out", type=Path)
        if name == "backtest":
            command.add_argument("--history", action="store_true", help="add the long-history cache's earlier bars")
            command.add_argument("--eurusd", type=float, help="assumed EUR/USD when no EURUSD bars are stored (US)")
    return root


def predict(cfg: dict) -> dict:
    """The pre-open predictions of the rule strategies and baselines."""
    now, con = clock(), connect(cfg["market"])
    try:
        scores, ranges, cross_scores = predict_inputs.horizon_rows(cfg["market"], now)
    except NotImplementedError as error:
        return {"ok": False, "message": MSG_NO_HORIZON_SCORES.format(error=error)}
    news_cfg = load_model_config()["news"]
    preds, skipped = [], []
    for inputs in predict_inputs.build_inputs(con, cfg, now, scores, ranges, news_cfg, cross_scores):
        rows, abstentions = company_rows(registry.rule_and_baselines(), inputs, news_cfg)
        preds += rows
        skipped += abstentions
    return {"ok": True, **run.write_predictions(cfg, now, preds, skipped, con)}


def pick_study_result() -> dict:
    """The pick study on W1's examples and on each market's stored bars."""
    rates = {market: lab_costs.rates(market) for market in ("india", "us")}
    out = {"settings": STUDY, "example": pick_study.example_spread(paths.ROOT / EXAMPLES, rates,
                                                                   STUDY["eurusd_fallback"])}
    for market in ("india", "us"):
        cfg = load_market(market)
        con = connect(market)
        settings = {**STUDY, "amount": DEFAULT_AMOUNT[market], "eurusd": STUDY["eurusd_fallback"]}
        bars = reports.study_inputs(con, cfg, clock())
        out[market] = pick_study.history_spread(market, bars, registry.horizons(), rates, settings)
    return out


def dispatch(args) -> dict:
    """Run one subcommand."""
    if args.command == "pick-study":
        return pick_study_result()
    cfg = require_market(args)
    if args.command == "predict":
        return predict(cfg)
    now, con = clock(), connect(cfg["market"])
    commands = {
        "pick": lambda: run.pick_day(con, cfg, now, registry.strategies(),
                                     str(args.session or run.session_of(cfg, now))),
        "settle": lambda: settle_run.settle_due(con, cfg, now),
        "news-impact": lambda: reports.write_news_impact(con, cfg, now),
        "summary": lambda: reports.lab_summary(con, now),
        "backtest": lambda: reports.run_backtest(con, cfg, now, args.history, args.eurusd),
    }
    return commands[args.command]()


def main(argv=None) -> int:
    """Entry point."""
    args = parser().parse_args(argv)
    result = dispatch(args)
    text = json.dumps(result, indent=1, default=str, ensure_ascii=False)
    if getattr(args, "out", None):
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"written": str(args.out), "keys": sorted(result)}))
    else:
        print(text)
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    sys.exit(main())
