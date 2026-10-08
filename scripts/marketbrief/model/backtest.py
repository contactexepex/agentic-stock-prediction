"""Walk-forward backtest of the signal model, out-of-sample only (scripts/model_backtest.py).

For each market, horizon N+k of config/strategies.yaml (core/horizons.py) and label convention (open_to_close
primary, close_to_close secondary):
walk_forward.py's monthly expanding-window fits, scored only on as-of dates after each fit's cutoff, with
labels the fit never saw. Reported: probability scores and reliability (metrics.py), hit rates and
coverage at the thresholds of config/model.yaml, the paper strategy after costs vs the baselines
(paper.py, open_to_close only: that is the trade), the coefficient table and group importance of the
latest fit, the features left out, and the gradient-boosted comparison (gbm_compare.py). Nothing here is
tuned: every setting comes from config/model.yaml as written before the run. Writes model-backtest-
<market|all>-<last date>[-history][-ablate|-x-<groups>].json and .html into --out (a scratch folder; never
data/ or reports/). --history also reads the long-history cache (history_cache.py; data/'s bars win on
their dates); --cross-groups picks the cross-market groups of the reported variant and --ablate adds every
ablation variant on the same panel (backtest_variants.py; their headlines are in `headlines`)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from marketbrief.constants.model import (LABEL_CONVENTIONS, LABEL_DESCRIPTIONS, LABEL_OPEN_TO_CLOSE,
                                         MSG_VERDICT_NO_POSITIONS, MSG_VERDICT_SCORES, MSG_VERDICT_VS,
                                         MIN_VERDICT_DATES, MSG_VERDICT_TOO_FEW, VERDICT_BEATS, VERDICT_SAME,
                                         VERDICT_WORSE)
from marketbrief.core.cli import market_arg
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.horizons import horizons
from marketbrief.core.market_config import load_market
from marketbrief.model.backtest_html import render_html
from marketbrief.model.backtest_variants import CONFIG, headline, headline_lines, parse_groups, with_groups
from marketbrief.model.backtest_variants import ablation_variants as variants_for_ablation
from marketbrief.model.explain import coefficient_table, group_importance
from marketbrief.model.gbm_compare import gbm_walk_forward
from marketbrief.model.history_cache import load_cache, merged_bars
from marketbrief.model.labels import end_offset
from marketbrief.model.metrics import probability_scores, threshold_hits
from marketbrief.model.panel import build_panel
from marketbrief.model.panel_inputs import inputs_until, read_inputs
from marketbrief.model.paper import nan_free, paper_results
from marketbrief.model.settings import cross_groups, load_costs, load_model_config, round_trip_cost
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


def evaluate(panel: pd.DataFrame, spec: tuple[str, str, int], settings: dict, costs: dict, gbm: bool = True) -> dict:
    """Every result of one market x convention x horizon (the gradient-boosted comparison unless gbm is False)."""
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
    if gbm:
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


def market_inputs(market: str, history: bool) -> tuple[dict, dict | None]:
    """The stored inputs of a market, with the long-history cache's earlier bars when `history`."""
    inputs = read_inputs(connect(market), market)
    if not history:
        return inputs, None
    cached, manifest = load_cache(market)
    inputs["bars"], splice = merged_bars(inputs["bars"], cached)
    keep = ("fetched_at", "start", "rows", "bytes", "sha256", "basis")
    return inputs, {"manifest": {k: manifest.get(k) for k in keep}, "splice": splice}


def evaluate_market(panel: pd.DataFrame, market: str, settings: dict, gbm: bool) -> dict:
    """{"<h>d <convention>": evaluate()} of one market and settings."""
    return {f"{h}d {c}": evaluate(panel, (market, c, h), settings, load_costs(market), gbm)
            for h in horizons() for c in LABEL_CONVENTIONS}


def run(markets: tuple[str, ...], options: dict | None = None) -> dict:
    """The backtest of the given markets. options: history (read the long-history cache too), cross
    ("config", "none", "all" or a comma list of groups: the reported variant), ablate (also every
    ablation variant, backtest_variants.py), gbm (the gradient-boosted comparison, default true), end (a date:
    read the stored inputs only as known by its end, panel_inputs.inputs_until)."""
    options = options or {}
    settings = load_model_config()
    out = {"computed_at": utc_now(), "settings": settings, "results": {}, "data": {}}
    for market in markets:
        cfg = load_market(market)
        inputs, history = market_inputs(market, options.get("history", False))
        if options.get("end") is not None:          # the weekly review: only what was known by its week end
            inputs = inputs_until(inputs, options["end"])
        configured = cross_groups(settings, market)
        variants = (variants_for_ablation(market) if options.get("ablate") else
                    [(options.get("cross", CONFIG), parse_groups(options.get("cross", CONFIG), market, configured))])
        union = tuple(sorted({g for _, groups in variants for g in groups}))
        panel = build_panel(cfg, inputs, settings["warmup_bars"], union)
        first_bar = min(frame.index[0] for frame in inputs["bars"].values())
        out["data"][market] = {"panel_rows": len(panel), "first_bar": str(first_bar.date()),
                               "first_panel_date": str(panel["date"].min().date()),
                               "last_panel_date": str(panel["date"].max().date()),
                               "tickers": int(panel["ticker"].nunique()),
                               "round_trip_cost_pct_at_100": round(round_trip_cost(market, load_costs(market)) * 100,
                                                                   4),
                               "cross_groups": list(variants[0][1]), "variant": variants[0][0]}
        if history:
            out.setdefault("history", {})[market] = history
        main_name, main_groups = variants[0]
        out["results"][market] = evaluate_market(panel, market, with_groups(settings, market, main_groups),
                                                 options.get("gbm", True))
        heads = out.setdefault("headlines", {}).setdefault(market, {})
        heads[main_name] = {key: headline(res) for key, res in out["results"][market].items()}
        for name, groups in variants[1:]:
            results = evaluate_market(panel, market, with_groups(settings, market, groups), False)
            heads[name] = {key: headline(res) for key, res in results.items()}
    out["verdicts"] = verdicts(out["results"])
    return nan_free(out)


def main() -> int:
    """Entry point of scripts/model_backtest.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--out", type=Path, required=True, help="folder for the JSON and HTML (a scratch folder)")
    parser.add_argument("--history", action="store_true",
                        help="also read the long-history cache of scripts/model_history.py (work/model_history/)")
    parser.add_argument("--cross-groups", default=CONFIG,
                        help="cross-market groups of the reported variant: config (default), none, all or a list")
    parser.add_argument("--ablate", action="store_true",
                        help="report all groups and also every ablation variant (none, only <g>, all minus <g>)")
    parser.add_argument("--no-gbm", action="store_true", help="skip the gradient-boosted comparison")
    args = parser.parse_args()
    markets = (args.market,) if args.market else MARKETS
    result = run(markets, {"history": args.history, "cross": args.cross_groups, "ablate": args.ablate,
                           "gbm": not args.no_gbm})
    args.out.mkdir(parents=True, exist_ok=True)
    last = max(d["last_panel_date"] for d in result["data"].values())
    tag = "".join(part for flag, part in ((args.history, "-history"), (args.ablate, "-ablate")) if flag)
    tag += "" if args.ablate or args.cross_groups == CONFIG else "-x-" + args.cross_groups.replace(",", "+")
    stem = args.out / f"model-backtest-{args.market or 'all'}-{last}{tag}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str))
    stem.with_suffix(".html").write_text(render_html(result))
    lines = [line for market, by_variant in result["headlines"].items() for variant, heads in by_variant.items()
             for line in headline_lines(market, variant, heads)]
    print(json.dumps({"json": str(stem.with_suffix(".json")), "html": str(stem.with_suffix(".html")),
                      "verdicts": result["verdicts"], "headlines": lines}, indent=1))
    return 0
