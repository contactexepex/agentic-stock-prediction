"""Weekly review for one market (docs/DESIGN.md sections 6, 7 and 10 phase 4): what improved
coverage, what to drop.

From stored range outcomes, scored calls and calibration, for the review week, a rolling
window and since start (all by target date, never past the week's end):
- 50%/80% coverage vs target, interval score and width vs the naive baseline, by horizon,
  regime, sector and widening note;
- direction hit rate vs the always-up baseline, overall and by confidence band;
- ablation of each range input: (a) replay of the stored live scored ranges with one input
  changed (cue, AI drift, AI widening, earnings/event/regime widening, centre cap), and
  (b) walk-forward on stored prices (backtest.py) for the width parameters and the regime and
  event widening rebuilt from stored bars.
- signal-model check (model_skill.py): the walk-forward backtest of scripts/model_backtest.py rerun
  for the market, its headline numbers and a plain verdict on whether the model has shown skill
  (--no-model-backtest skips it).
Calls are summarised per scoring basis, never pooled (analytics/call_basis.py).
Thresholds and variants live in config/review.yaml. Small samples are flagged and get no
proposal. Proposed config/ranges.yaml changes are written to the report, never applied.
Appends a record to data/<market>/reviews/ and writes reports/<market>/review-YYYY-Www.md."""

from __future__ import annotations

import json
from datetime import date, timedelta

from marketbrief.analytics import call_basis
from marketbrief.analytics.features import load_bars
from marketbrief.constants.review import (
    DEFAULTS,
    MSG_HISTORY_ABLATION_SKIPPED,
    MSG_MODEL_CHECK_FAILED,
    MSG_MODEL_CHECK_SKIPPED,
    SKIP_HISTORY,
    SKIP_MODEL,
)
from marketbrief.core import paths
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_ranges_config
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.pipeline.review.aci_review import (
    aci_proposal,
    aci_state,
    latest_aci_replay,
)
from marketbrief.pipeline.review.helpers import (
    clean,
    load_review_config,
    previous_week,
    week_bounds,
)
from marketbrief.pipeline.review import model_skill
from marketbrief.pipeline.review.history_ablation import history_ablation
from marketbrief.pipeline.review.live_ablation import live_ablation
from marketbrief.pipeline.review.markdown import markdown
from marketbrief.pipeline.review.summaries import (
    breakdown,
    by_horizon,
    call_summary,
    confidence_bands,
    load_calls,
    load_ranges,
    per_basis,
    range_summary,
)
from marketbrief.pipeline.review.verdicts import (
    confidence_advice,
    judge,
    proper_scores,
    proposals,
)


def model_check(market: str, review_config: dict, enabled: bool, end: date | None = None) -> dict:
    """The signal-model check (model_skill.py) on the inputs stored by the week's end, or why it was not run; a
    failure never stops the review."""
    if not enabled:
        return {"skipped": MSG_MODEL_CHECK_SKIPPED}
    try:
        result, path = model_skill.rerun(market, end)
    except (Exception, SystemExit) as exc:  # e.g. no config/model.yaml or too little history for any fit
        return {"error": MSG_MODEL_CHECK_FAILED.format(error=str(exc)[:200])}
    return model_skill.headline(result, market, path, review_config)


def build(
    cfg: dict, ranges_config: dict, review_config: dict, con, week: str, skip: frozenset = frozenset()
) -> tuple[dict, dict]:
    """Build the review record and its data for one ISO week; `skip` may hold SKIP_HISTORY (no walk-forward on
    stored prices) and SKIP_MODEL (no signal-model backtest)."""
    start, end = week_bounds(week)
    roll_start = end - timedelta(days=review_config["rolling_days"] - 1)
    ranges, calls = load_ranges(con, cfg, end), load_calls(con, end)
    windows = {"week": start, "rolling": roll_start, "all": date.min}

    def rows_since(frame, start_date):
        """The rows of a frame whose target date is on or after the window start."""
        return frame[frame["target_date"] >= start_date] if not frame.empty else frame

    review_data = {
        "partial_week": end >= utc_today(),
        "ranges": {
            window: by_horizon(rows_since(ranges, start_date), range_summary, labels=True)
            for window, start_date in windows.items()
        },
        "calls": {  # per scoring basis, never pooled (call_basis.py)
            window: per_basis(rows_since(calls, start_date), lambda frame: by_horizon(frame, call_summary))
            for window, start_date in windows.items()
        },
        "breakdowns": {
            window: {
                "regime": breakdown(rows_since(ranges, start_date), "regime"),
                "sector": breakdown(rows_since(ranges, start_date), "sector"),
                "note": breakdown(rows_since(ranges, start_date), "tags"),
            }
            for window, start_date in windows.items()
        },
        "bands": {
            window: per_basis(
                rows_since(calls, start_date), lambda frame: confidence_bands(frame, review_config["confidence_bands"])
            )
            for window, start_date in windows.items()
        },
    }
    cal = con.execute(
        "SELECT DISTINCT ON (horizon_days) * FROM calibration WHERE as_of_date <= ? "
        "ORDER BY horizon_days, as_of_date DESC, computed_at DESC",
        [end],
    ).df()
    review_data["calibration"] = [
        {key: (str(value)[:10] if key == "as_of_date" else value) for key, value in row.items() if key != "computed_at"}
        for row in cal.to_dict("records")
    ]
    review_data["live_ablation"] = live_ablation(ranges, ranges_config, review_config)
    review_data["history_ablation"] = (
        history_ablation(cfg, ranges_config, review_config, load_bars(con), end)
        if SKIP_HISTORY not in skip
        else {"n": 0, "error": MSG_HISTORY_ABLATION_SKIPPED, "variants": []}
    )
    for ablation in (review_data["live_ablation"], review_data["history_ablation"]):
        judge(ablation, review_config)
    review_data["proposals"] = proposals(
        ranges_config, review_data["live_ablation"], review_data["history_ablation"], cfg["market"]
    )
    review_data["scores"] = {
        window: proper_scores(rows_since(ranges, start_date), rows_since(calls, start_date))
        for window, start_date in windows.items()
    }
    review_data["aci"] = aci_state(con, ranges_config, end)
    review_data["aci"]["replay"] = latest_aci_replay(con, end, ranges_config)
    proposal = aci_proposal(ranges_config, review_data["aci"]["replay"])
    if proposal:
        review_data["proposals"].append(proposal)
    review_data["model"] = model_check(cfg["market"], review_config, SKIP_MODEL not in skip, end)
    review_data["advice"] = confidence_advice(review_data["bands"]["all"], review_data["calls"]["all"], review_config)

    # the record's call columns are of the current basis (the newest scored call's), named in call_basis_all
    basis = call_basis.current(calls)
    range_all = review_data["ranges"]["all"]["all"]
    call_all = review_data["calls"]["all"].get(f"all · {call_basis.label(basis)}", {}) if basis else {}
    rec = {
        "id": week,
        "week": week,
        "week_start": str(start),
        "week_end": str(end),
        "computed_at": utc_now(),
        "report": f"reports/{cfg['market']}/review-{week}.md",
        "n_ranges_week": review_data["ranges"]["week"]["all"]["n"],
        "n_ranges_30d": review_data["ranges"]["rolling"]["all"]["n"],
        "n_ranges_all": range_all["n"],
        "n_calls_week": len(rows_since(calls, start)),
        "n_calls_all": len(calls),
        "call_basis_all": basis,
        "cover50_all": range_all.get("cover50"),
        "cover80_all": range_all.get("cover80"),
        "score80_all": range_all.get("score80_pct"),
        "naive_score80_all": range_all.get("naive_score80_pct"),
        "call_hit_all": call_all.get("hit_rate"),
        "always_up_all": call_all.get("always_up"),
        "low_sample": range_all["n"] < review_config["min_n_recommend"],
        "model_skill": review_data["model"].get("skill"),
        "n_proposals": len(review_data["proposals"]),
        "proposals": review_data["proposals"],
        "detail": {
            key: review_data[key]
            for key in ("ranges", "calls", "breakdowns", "bands", "calibration", "advice", "scores", "aci", "model")
        }
        | {
            "live_ablation": review_data["live_ablation"],
            "history_ablation": review_data["history_ablation"],
            "thresholds": {key: review_config[key] for key in DEFAULTS if not key.endswith("_variants")},
        },
    }
    return clean(rec), review_data


def main() -> int:
    """Write the weekly review (markdown and stored record) and print its summary."""
    parser = market_arg(__doc__)
    parser.add_argument("--week", help="ISO week to review, e.g. 2026-W40 (default: the previous ISO week)")
    parser.add_argument("--if-due", action="store_true", help="do nothing if this week's review is already stored")
    parser.add_argument("--no-history", action="store_true", help="skip the walk-forward on stored prices")
    parser.add_argument("--no-model-backtest", action="store_true", help="skip rerunning the signal-model backtest")
    args = parser.parse_args()
    cfg = require_market(args)
    week = args.week or previous_week(utc_today())
    week_bounds(week)
    con = connect(cfg["market"])
    if args.if_due and con.execute("SELECT count(*) FROM reviews WHERE id = ?", [week]).fetchone()[0]:
        print(
            json.dumps(
                {
                    "step": "review",
                    "market": cfg["market"],
                    "week": week,
                    "due": False,
                    "report": f"reports/{cfg['market']}/review-{week}.md",
                },
                indent=2,
            )
        )
        return 0
    review_config = load_review_config()
    rec, review_data = build(
        cfg,
        load_ranges_config(cfg["market"]),
        review_config,
        con,
        week,
        frozenset({SKIP_HISTORY} if args.no_history else set()) | ({SKIP_MODEL} if args.no_model_backtest else set()),
    )
    path = paths.ROOT / rec["report"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(cfg, review_config, rec, review_data))
    out = day_file(cfg["market"], "reviews", utc_today())
    append_jsonl(out, [rec])
    print(
        json.dumps(
            {
                "step": "review",
                "market": cfg["market"],
                "week": week,
                "due": True,
                "report": rec["report"],
                "record": str(out.relative_to(paths.ROOT)),
                "n_ranges_week": rec["n_ranges_week"],
                "n_ranges_all": rec["n_ranges_all"],
                "n_calls_all": rec["n_calls_all"],
                "low_sample": rec["low_sample"],
                "model_skill": rec["model_skill"],
                "proposals": [
                    {**change, "source": proposal["source"], "n": proposal["n"], "rel_score": proposal["rel_score"]}
                    for proposal in rec["proposals"]
                    for change in proposal["changes"]
                ],
            },
            indent=2,
            default=str,
        )
    )
    return 0
