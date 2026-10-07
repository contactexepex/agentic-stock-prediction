"""Historical replay of everything rule-based (no AI) for one market, walk-forward over stored bars.

For each trading day d in the window (as-of dates, default: from `warmup_bars` sessions after the
first benchmark bar to the last one), using only what ranges.py would know pre-open the next
session, i.e. bars up to d's close and events as known then:
1. Ranges: the 1d and 5d 50%/80% ranges built as ranges.py builds them (calibration quantiles from
   the recency-weighted pool of outcomes known at d as calibrate.py, EWMA volatility, earnings,
   regime and major-event widening, beta-split centre and ex-dividend shift where config/ranges.yaml
   switches them on), scored on the close h sessions later against the naive baseline: coverage
   overall and by regime, sector, ticker, month and earnings-in-horizon, interval score and width,
   and calibration (stated vs actual coverage, the published 50%/80% bands plus a curve of other
   levels from the same quantile pool).
2. Regime: the label per day (regime.py classify on the vol index and benchmark closes, and the
   major events of config/events.yaml), as features.py computes it.
3. Direction BASELINES (not the product's forecasts; the AI forecaster must beat them later):
   always-up, 1d and 5d momentum sign, and RSI(14) mean reversion (below 30 up, above 70 down;
   indicators.py has no direction signal of its own, so the rule is defined here). Each with a hit
   rate, a 95% interval clustered by date blocks, a two-sided binomial test vs 50%, and the
   difference vs always-up on the same rows.
Event dates: earnings via event_history.earnings_versions (SEC 2.02 filings judged only by the
10-Q/10-K reports accepted by the session date, as ranges.py), dividends via dividend_events.

Not replayable, so left out (listed in the output): the AI's drift and widening, overnight own-stock
cues (US pre-market gaps, India ADRs: no stored history; the next open would be look-ahead), the US
index cue (futures before the open), implied volatility, live scored ranges in the calibration pool,
quote-based vol index levels (closes are used), and the relationship/smart-money widening (off).
Also, past event dates are taken as known in advance (scheduled), since backfilled rows do not say
when each date was first announced.

Writes reports/<market>/replay-<end>.html (self-contained) and .json, and appends one row to
data/<market>/replays/ (schema `replays` in marketbrief/core/schemas.py). Prints a JSON summary."""

from __future__ import annotations

import json
import time
from datetime import date

from marketbrief.analytics import adaptive_conformal, range_switches
from marketbrief.constants.range_inputs import INPUTS
from marketbrief.constants.replay import (
    MSG_ACI_OPTIONS_NEED_ACI,
    MSG_NO_TRADING_DAYS_IN_THE_WINDOW,
)
from marketbrief.core import cli, database, paths, storage
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.market_config import benchmark_key, load_ranges_config
from marketbrief.replay.rule_replay.aci_compare import (
    aci_comparison,
    aci_ranges_config,
    aci_tag,
    held_out,
)
from marketbrief.replay.rule_replay.inputs import load_inputs
from marketbrief.replay.rule_replay.narrative import (
    headline,
    limitations,
    top_sentences,
)
from marketbrief.replay.rule_replay.range_rows import replay_rows
from marketbrief.replay.rule_replay.replay_statistics import summarize
from marketbrief.replay.rule_replay.rule_html import html_report


def run(cfg: dict, ranges_config: dict, con, start: date | None = None, end: date | None = None) -> tuple[dict, dict]:
    """Replay one market over the window and return the summary with its texts."""
    started_at = time.time()
    bars, extra = load_inputs(cfg, ranges_config, con)
    res, reg = replay_rows(cfg, ranges_config, bars, extra, start, end)
    summary = summarize(cfg, ranges_config, res, reg)
    bench = bars[benchmark_key(cfg)]
    days = reg.index.tolist()
    summary.update(
        {
            "market": cfg["market"],
            "name": cfg.get("name"),
            "start": str(days[0]) if days else None,
            "end": str(days[-1]) if days else None,
            "computed_at": utc_now(),
            "settings": {
                "inputs": {
                    str(horizon): {
                        key: range_switches.enabled(ranges_config, key, cfg["market"], horizon) for key in INPUTS
                    }
                    for horizon in ranges_config["horizons"]
                },
                "regime_factor": ranges_config["regime_factor"],
                "major_event_factor": ranges_config["major_event_factor"],
                "earnings_vol_multiple": ranges_config["earnings_vol_multiple"],
                "history_sessions": ranges_config["history_sessions"],
                "half_life_sessions": ranges_config["half_life_sessions"],
                "min_pool": ranges_config["min_pool"],
                "aci": {
                    **adaptive_conformal.settings(ranges_config),
                    "on": {
                        str(horizon): range_switches.enabled(ranges_config, "aci", cfg["market"], horizon)
                        for horizon in ranges_config["horizons"]
                    },
                },
            },
            "data": {
                "first_bar": str(bench.index[0].date()),
                "last_bar": str(bench.index[-1].date()),
                "tickers": sum(1 for ticker in cfg["tickers"] if ticker in bars),
                "earnings_events": sum(len(versions[-1][1]) for versions in extra["earnings"].values() if versions),
                "dividends": sum(map(len, extra["dividends"].values())),
            },
        }
    )
    summary["limitations"] = limitations(cfg, ranges_config, summary)
    summary["summary"] = headline(cfg, summary)
    summary["top"] = top_sentences(summary)
    summary["runtime_s"] = round(time.time() - started_at, 1)
    return summary, res


def record(summary: dict, report: str) -> dict:
    """The row appended to data/<market>/replays/ for a finished replay."""
    overall = {horizon: summary["horizons"].get(horizon, {}).get("overall", {}) for horizon in ("1", "5")}
    always_up = {horizon: (summary["baselines"].get(horizon) or {}).get("always_up", {}) for horizon in ("1", "5")}
    return {
        "id": f"{summary['start']}_{summary['end']}",
        "market": summary["market"],
        "start_date": summary["start"],
        "end_date": summary["end"],
        "computed_at": summary["computed_at"],
        "report": report,
        "n_days": len(summary["regime_timeline"]),
        "n_ranges": sum(overall_row.get("n", 0) for overall_row in overall.values()),
        "cover50_1d": overall["1"].get("cover50"),
        "cover80_1d": overall["1"].get("cover80"),
        "cover50_5d": overall["5"].get("cover50"),
        "cover80_5d": overall["5"].get("cover80"),
        "score80_1d": overall["1"].get("score80_same_rows"),
        "naive_score80_1d": overall["1"].get("naive_score80"),
        "score80_5d": overall["5"].get("score80_same_rows"),
        "naive_score80_5d": overall["5"].get("naive_score80"),
        "always_up_1d": always_up["1"].get("hit_rate"),
        "always_up_5d": always_up["5"].get("hit_rate"),
        "runtime_s": summary["runtime_s"],
        "settings": summary["settings"],
        "detail": {key: value for key, value in summary.items() if key not in ("settings", "regime_timeline")},
    }


def main() -> int:
    """Run the replay (optionally with ACI), write the HTML and JSON and print the summary."""
    parser = cli.market_arg(__doc__)
    parser.add_argument("--start", type=date.fromisoformat, help="first as-of date (default: after the warm-up bars)")
    parser.add_argument("--end", type=date.fromisoformat, help="last as-of date (default: the last benchmark bar)")
    parser.add_argument(
        "--aci",
        action="store_true",
        help="also replay with Adaptive Conformal Inference on (adaptive_conformal.py) and compare on the same rows; "
        "writes replay-<end>-aci.html|json",
    )
    parser.add_argument("--aci-gamma", type=float, help="with --aci: gamma instead of config/ranges.yaml aci.gamma")
    parser.add_argument(
        "--aci-by-regime", choices=("on", "off"), help="with --aci: one alpha per regime (on) or one overall"
    )
    parser.add_argument(
        "--aci-tune-end",
        type=date.fromisoformat,
        help="with --aci: held-out check; pick gamma/by_regime from a grid on as-of dates up to this date, "
        "report fixed vs ACI on the dates after it (out of sample)",
    )
    args = parser.parse_args()
    if (args.aci_gamma is not None or args.aci_by_regime or args.aci_tune_end) and not args.aci:
        raise SystemExit(MSG_ACI_OPTIONS_NEED_ACI)
    cfg = cli.require_market(args)
    ranges_config = load_ranges_config(cfg["market"])
    con = database.connect(cfg["market"])
    summary, _ = run(cfg, ranges_config, con, args.start, args.end)
    if not summary["end"]:
        raise SystemExit(MSG_NO_TRADING_DAYS_IN_THE_WINDOW)
    suffix = ""
    if args.aci:
        before = summary
        by_regime = None if args.aci_by_regime is None else args.aci_by_regime == "on"
        replay_ranges_config = aci_ranges_config(ranges_config, args.aci_gamma, by_regime)
        summary, _ = run(cfg, replay_ranges_config, con, args.start, args.end)
        summary["aci_comparison"] = aci_comparison(before, summary)
        if args.aci_tune_end:
            summary["aci_held_out"] = held_out(cfg, replay_ranges_config, con, args.aci_tune_end, args.start, args.end)
        suffix = aci_tag(replay_ranges_config["aci"], args.aci_tune_end)
    out = paths.ROOT / "reports" / cfg["market"]
    out.mkdir(parents=True, exist_ok=True)
    page, json_file = out / f"replay-{summary['end']}{suffix}.html", out / f"replay-{summary['end']}{suffix}.json"
    page.write_text(html_report(cfg, summary), encoding="utf-8")
    json_file.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    rel = str(page.relative_to(paths.ROOT))
    rec = record(summary, rel)
    # issue #27: a re-run of the same window is a new id (run time appended); issue #28: the file is the UTC run date
    rec["id"] += suffix + "@" + summary["computed_at"]
    storage.append_jsonl(storage.day_file(cfg["market"], "replays", utc_today()), [rec])
    print(
        json.dumps(
            {
                "step": "replay",
                "market": cfg["market"],
                "report": rel,
                "json": str(json_file.relative_to(paths.ROOT)),
                "start": summary["start"],
                "end": summary["end"],
                "runtime_s": summary["runtime_s"],
                "aci": summary["settings"]["aci"],
                "overall": {horizon: value["overall"] for horizon, value in summary["horizons"].items()},
                "aci_comparison": {
                    horizon: value["overall"] for horizon, value in summary.get("aci_comparison", {}).items()
                }
                or None,
                "aci_held_out": None
                if "aci_held_out" not in summary
                else {
                    **{
                        key: summary["aci_held_out"][key]
                        for key in ("tune_end", "selected", "config", "selected_is_config")
                    },
                    "test_selected": {
                        horizon: value["overall"] for horizon, value in summary["aci_held_out"]["test_selected"].items()
                    },
                    "test_config": {
                        horizon: value["overall"] for horizon, value in summary["aci_held_out"]["test_config"].items()
                    },
                },
                "always_up": {
                    horizon: (band or {}).get("always_up", {}).get("hit_rate")
                    for horizon, band in summary["baselines"].items()
                },
                "summary": summary["summary"],
            },
            indent=2,
            default=str,
        )
    )
    return 0
