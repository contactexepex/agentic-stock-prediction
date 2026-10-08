"""The weekly review's signal-model check (owner-approved change B): rerun the walk-forward, out-of-sample
backtest of the signal model for the market (marketbrief/model/backtest.py, as scripts/model_backtest.py does;
its JSON goes to work/model_backtest/, never data/ or reports/) and summarise its headline numbers: per horizon and
label, n, Brier vs the base-rate Brier, AUC with its 95% interval, and the paper long strategy vs each baseline
after costs (open_to_close only: that is the trade). It says plainly whether the model has shown skill, by the
thresholds under `model_skill` in config/review.yaml. Nothing here changes the model or its settings.
The backtest reads only the inputs dated, or first seen, by the reviewed week's end (issue #45.2), and runs with
its native thread pools capped at one thread when threadpoolctl is installed (it comes with scikit-learn), so
concurrent reviews do not oversubscribe the CPU (issue #45.1)."""

from __future__ import annotations

import contextlib
import json
from datetime import date

from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE, MIN_VERDICT_DATES
from marketbrief.constants.review import (
    MODEL_BACKTEST_DIR,
    MSG_MODEL_NO_SKILL,
    MSG_MODEL_SKILL,
    MSG_STRATEGY_BEATS,
    MSG_STRATEGY_NONE,
)
from marketbrief.core import paths
from marketbrief.model.backtest import run as run_backtest


def one_thread():
    """threadpoolctl's limit of the native thread pools (BLAS, OpenMP) to one thread, or no limit without it."""
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:  # optional: installed with scikit-learn (the gradient-boosted comparison)
        return contextlib.nullcontext()
    return threadpool_limits(1)


def rerun(market: str, end: date | None = None) -> tuple[dict, str]:
    """(backtest result, repo-relative JSON path) of a fresh backtest of one market on the inputs dated (or first
    seen) by the end of `end` (the reviewed week's last day; None: every stored input)."""
    with one_thread():
        result = run_backtest((market,), {"end": end})
    out = paths.ROOT / MODEL_BACKTEST_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"model-backtest-{market}-{result['data'][market]['last_panel_date']}.json"
    path.write_text(json.dumps(result, indent=1, default=str))
    return result, str(path.relative_to(paths.ROOT))


def has_skill(row: dict, rules: dict) -> bool:
    """Skill: enough rows, a Brier below the base rate's by the configured margin, and an AUC interval above 0.5."""
    low = (row.get("auc95") or [None])[0]
    return (row.get("n", 0) >= rules["min_n"] and row.get("brier_skill") is not None
            and row["brier_skill"] > rules["min_brier_skill"] and low is not None and low > rules["min_auc_low"])


def strategy_rows(key: str, res: dict) -> list[dict]:
    """The paper long vs each baseline after costs, per threshold (open_to_close results only)."""
    rows = []
    for threshold, paper in ((res.get("paper") or {}).get("thresholds") or {}).items():
        if not paper["long"]["positions"]:  # nothing reached the threshold: one row, no comparison
            rows.append({"key": key, "threshold": threshold, "positions": 0, "baseline": "–", "dates": 0,
                         "mean_pct": None, "ci95_pct": [None, None], "verdict": "no positions"})
            continue
        for name, diff in paper["vs"].items():
            low, high = diff.get("ci95_pct") or [None, None]
            enough = diff.get("dates", 0) >= MIN_VERDICT_DATES
            word = ("beats" if enough and low is not None and low > 0 else
                    "worse" if enough and high is not None and high < 0 else "not distinguishable" if enough
                    else f"fewer than {MIN_VERDICT_DATES} dates")
            rows.append({"key": key, "threshold": threshold, "positions": paper["long"]["positions"],
                         "baseline": name, "dates": diff.get("dates", 0), "mean_pct": diff.get("mean_pct"),
                         "ci95_pct": [low, high], "verdict": word})
    return rows


def headline(result: dict, market: str, path: str, review_config: dict) -> dict:
    """The review's summary of one market's backtest: score rows, strategy rows and the plain verdict."""
    rules = review_config["model_skill"]
    scores, strategy = [], []
    for key, res in sorted((result.get("results") or {}).get(market, {}).items()):
        if "brier" not in res:
            scores.append({"key": key, "skipped": res.get("skipped")})
            continue
        scores.append({"key": key, **{name: res.get(name) for name in
                                      ("n", "dates", "brier", "brier_base_rate", "brier_skill", "auc", "auc95")},
                       "skill": has_skill(res, rules)})
        if key.endswith(LABEL_OPEN_TO_CLOSE):
            strategy += strategy_rows(key, res)
    skilled = [row["key"] for row in scores if row.get("skill")]
    beats = sorted({f"{row['key']} p>={row['threshold']} vs {row['baseline']}" for row in strategy
                    if row["verdict"] == "beats"})
    verdict = (MSG_MODEL_SKILL.format(keys=", ".join(skilled)) if skilled else
               MSG_MODEL_NO_SKILL.format(n=rules["min_n"], margin=rules["min_brier_skill"], auc=rules["min_auc_low"]))
    verdict += " " + (MSG_STRATEGY_BEATS.format(which="; ".join(beats)) if beats else MSG_STRATEGY_NONE)
    return {"json": path, "computed_at": result.get("computed_at"), "data": (result.get("data") or {}).get(market),
            "scores": scores, "strategy": strategy, "skill": bool(skilled), "strategy_beats": bool(beats),
            "verdict": verdict}


def markdown_lines(model: dict) -> list[str]:
    """The review section: the plain verdict, the score table and the strategy table."""
    lines = ["## Signal model: does it show skill?", ""]
    if "scores" not in model:
        return lines + [f"_Not checked: {model.get('error') or model.get('skipped')}._", ""]
    data = model.get("data") or {}
    lines += [f"**{model['verdict']}**", "",
              f"Walk-forward, out-of-sample backtest rerun for this review (`scripts/model_backtest.py`; JSON "
              f"`{model['json']}`; panel {data.get('first_panel_date')} to {data.get('last_panel_date')}, "
              f"{data.get('tickers')} tickers). Brier: lower is better; skill = 1 - Brier / base-rate Brier. AUC 0.5 "
              "is no better than chance.", "",
              "| Horizon · label | n | Brier | Base-rate Brier | Skill | AUC | AUC 95% | Shows skill |",
              "|---|---|---|---|---|---|---|---|"]
    for row in model["scores"]:
        if "brier" not in row:
            lines.append(f"| {row['key']} | – | – | – | – | – | – | {row.get('skipped')} |")
            continue
        low, high = row.get("auc95") or [None, None]
        lines.append(
            f"| {row['key']} | {row['n']} | {row['brier']} | {row['brier_base_rate']} | {row['brier_skill']} | "
            f"{row['auc']} | {low} to {high} | {'yes' if row['skill'] else 'no'} |"
        )
    lines += ["", "Paper long strategy (open to close, after costs) minus each baseline, mean % per date with its "
              "95% interval:", "",
              "| Horizon | Threshold | Positions | Baseline | Dates | Mean % | 95% | Verdict |",
              "|---|---|---|---|---|---|---|---|"]
    show = lambda value: "–" if value is None else value  # noqa: E731
    lines += [f"| {row['key']} | p>={row['threshold']} | {row['positions']} | {row['baseline']} | {row['dates']} | "
              f"{show(row['mean_pct'])} | {show(row['ci95_pct'][0])} to {show(row['ci95_pct'][1])} | {row['verdict']} |"
              for row in model["strategy"]] or ["| – | – | 0 | – | 0 | – | – | no positions |"]
    return lines + [""]
